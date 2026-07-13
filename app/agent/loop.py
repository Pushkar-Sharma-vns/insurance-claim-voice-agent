"""S1.4 orchestration. Per turn: build messages (our system prompt + VAPI turns) ->
responder tool loop (resolve-then-stream) -> stream final answer as OpenAI SSE chunks ->
after the stream closes, write the S3 turn trace. A parallel extractor task updates
current_intent for the NEXT turn (lag-by-one).

ponytail: resolve-then-stream = resolve tool calls with non-streamed calls, then chunk the
final string out as SSE. Real token-streaming with tool interception is V2 (user's #1 V2).
Blocking requests/sqlite in this async handler is accepted at single-caller demo scale.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from time import perf_counter

import litellm

from app.agent import knowledge as kb
from app.agent import prompts
from app.agent import state as st_mod
from app.agent import tools
from app.agent.state import ConversationState
from app.agent.tools import ToolError
from app.config import settings
from app.services import crm, store

logger = logging.getLogger(__name__)
litellm.drop_params = True

MODEL = "gemini/gemini-2.5-flash"
MAX_TOOL_ROUNDS = 4
EXTRACT_PROMPT = (
    "You label a phone caller's current intent for an insurance claims line. "
    "In 2-5 words, give only the label (e.g. 'check claim status', 'office hours', "
    "'wants a human'). Reply with the label and nothing else."
)

_TASKS: set = set()  # keep extractor task refs alive (fire-and-forget)


def load_memory(st: ConversationState) -> None:
    """S2 cross-call memory read: fill recognition (always) + recall (gated) tiers."""
    digits = crm._digits(st.caller_phone)
    if not digits:
        return
    rows = store.recent_calls_by_phone(digits)
    if not rows:
        return
    name = rows[0]["caller_name"] or "a returning caller"
    st.memory_recognition = f"{name}; {len(rows)} prior call(s), most recent {rows[0]['ended_at'][:10]}"
    st.memory_recall = " | ".join(r["summary"] for r in rows if r["summary"])


def build_messages(st: ConversationState, vapi_messages: list[dict]) -> list[dict]:
    """Strip VAPI's system message, prepend ours (static + dynamic-gated block)."""
    turns = [m for m in vapi_messages if m.get("role") != "system"]
    return [prompts.system_message(st)] + turns


async def stream_turn(st: ConversationState, vapi_messages: list[dict]):
    """Async generator yielding SSE strings for one turn."""
    st.turn_count += 1
    phase_before = st.phase
    turn_t0 = perf_counter()
    messages = build_messages(st, vapi_messages)

    tool_events: list[dict] = []
    error_type: str | None = None
    llm_ms = 0.0
    prompt_tokens = 0

    try:
        final_text, llm_ms, prompt_tokens = await _resolve(st, messages, tool_events)
    except ToolError as e:
        error_type = e.fallback_key
        tier = st.bump_error(e.fallback_key)
        if tier == "repeat":
            st.phase = st_mod.ESCALATING
        final_text = kb.fallback(e.fallback_key, tier)["response"]
        logger.info("fallback call=%s key=%s tier=%s", st.call_id, e.fallback_key, tier)
    except Exception:
        logger.exception("llm_error call=%s", st.call_id)
        error_type = "llm_error"
        tier = st.bump_error("llm_error")
        if tier == "repeat":
            st.phase = st_mod.ESCALATING
        final_text = kb.fallback("llm_error", tier)["response"]

    # record what the model processed this turn + the final answer (S2/S4 transcript)
    st.transcript_messages = [m for m in messages if m.get("role") != "system"] + [
        {"role": "assistant", "content": final_text}
    ]

    _fire_extractor(st, list(messages))

    # stream the resolved answer as OpenAI SSE chunks
    first = True
    for piece in _chunks(final_text):
        yield _sse(_chunk(st, piece, role=first))
        first = False
    yield _sse(_chunk(st, None, finish="stop"))
    yield "data: [DONE]\n\n"

    # OFF the latency path: S3 turn trace
    completion_tokens = litellm.token_counter(
        model=MODEL, messages=[{"role": "assistant", "content": final_text}]
    )
    store.save_turn({
        "call_id": st.call_id,
        "turn_index": st.turn_count,
        "turn_latency_ms": (perf_counter() - turn_t0) * 1000,
        "llm_latency_ms": llm_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "tool_calls": tool_events,
        "phase_before": phase_before,
        "phase_after": st.phase,
        "current_intent": st.current_intent,
        "identity_verified": int(st.identity_verified),
        "error_type": error_type,
    })


async def _resolve(st: ConversationState, messages: list[dict], tool_events: list[dict]):
    """Non-streamed tool loop. Returns (final_text, total_llm_ms, prompt_tokens)."""
    total_llm_ms = 0.0
    for _ in range(MAX_TOOL_ROUNDS):
        t0 = perf_counter()
        resp = await litellm.acompletion(
            model=MODEL, messages=messages, tools=tools.TOOL_SCHEMAS,
            temperature=0.3, api_key=settings.gemini_api_key,
        )
        total_llm_ms += (perf_counter() - t0) * 1000
        msg = resp.choices[0].message

        if not msg.tool_calls:
            prompt_tokens = getattr(resp.usage, "prompt_tokens", 0) or litellm.token_counter(
                model=MODEL, messages=messages
            )
            return (msg.content or "", total_llm_ms, prompt_tokens)

        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            te0 = perf_counter()
            try:
                result = tools.execute(name, args, st)
            except ToolError:
                tool_events.append({"name": name, "status": "error",
                                    "latency_ms": (perf_counter() - te0) * 1000})
                raise
            tool_events.append({"name": name, "status": "ok",
                                "latency_ms": (perf_counter() - te0) * 1000})
            logger.info("tool=%s call=%s status=ok", name, st.call_id)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    raise ToolError("llm_error")  # tool loop didn't converge


def _fire_extractor(st: ConversationState, messages: list[dict]) -> None:
    if not settings.gemini_api_key:
        return
    task = asyncio.create_task(_extract(st, messages))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def _extract(st: ConversationState, messages: list[dict]) -> None:
    last_user = next(
        (m.get("content") for m in reversed(messages)
         if m.get("role") == "user" and m.get("content")), None
    )
    if not last_user:
        return
    try:
        resp = await litellm.acompletion(
            model=MODEL, temperature=0, max_tokens=20, api_key=settings.gemini_api_key,
            messages=[{"role": "system", "content": EXTRACT_PROMPT},
                      {"role": "user", "content": last_user}],
        )
        st.current_intent = (resp.choices[0].message.content or "").strip()[:60]
        logger.info("extractor call=%s current_intent=%s", st.call_id, st.current_intent)
    except Exception:
        logger.exception("extractor failed call=%s", st.call_id)


def _chunks(text: str):
    """Split into sentence-ish pieces so TTS can start early. One blob if no split."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip()) if text else []
    return [p for p in parts if p] or [text or ""]


def _sse(payload) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _chunk(st: ConversationState, content: str | None, role: bool = False, finish=None) -> dict:
    delta: dict = {}
    if role:
        delta["role"] = "assistant"
    if content is not None:
        delta["content"] = (content + " ") if finish is None else content
    return {
        "id": f"chatcmpl-{st.call_id}-{st.turn_count}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
