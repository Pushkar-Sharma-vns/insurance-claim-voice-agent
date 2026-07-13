"""S4 post-processing: OUR synchronous LiteLLM Gemini pass at call end (replaces VAPI
analysisPlan, P2-D3). ONE flat structured-output call -> {summary, sentiment,
resolution_status, primary_topic}. Flat schema dodges the nested-Pydantic 400 on Gemini.
resolution_status is descriptive only — containment is code-derived elsewhere (S4-D3).
"""
from __future__ import annotations

import json
import logging

import litellm

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "gemini/gemini-2.5-flash"

_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "sentiment": {"type": "string", "enum": ["Positive", "Neutral", "Negative"]},
        "resolution_status": {"type": "string", "enum": ["resolved", "escalated", "unresolved"]},
        "primary_topic": {"type": "string"},
    },
    "required": ["summary", "sentiment", "resolution_status", "primary_topic"],
}

_PROMPT = (
    "You analyze a completed insurance claims support call. Given the transcript, return a "
    "concise 1-2 sentence summary, the caller's overall sentiment, whether their need was "
    "resolved, and the primary topic. Base everything only on the transcript."
)


def _render(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def summarize_call(messages: list[dict]) -> dict:
    transcript = _render(messages)
    try:
        resp = litellm.completion(
            model=MODEL, temperature=0, api_key=settings.gemini_api_key,
            messages=[{"role": "system", "content": _PROMPT},
                      {"role": "user", "content": transcript}],
            response_format={"type": "json_object", "response_schema": _SCHEMA},
        )
        data = json.loads(resp.choices[0].message.content)
        logger.info("postprocess ok sentiment=%s resolution=%s",
                    data.get("sentiment"), data.get("resolution_status"))
        return data
    except Exception:
        # S1.6 llm_error tier: never crash the webhook; degrade gracefully
        logger.exception("postprocess failed; using fallback summary")
        tail = transcript[-300:] if transcript else "No transcript available."
        return {"summary": tail, "sentiment": "Neutral",
                "resolution_status": "unresolved", "primary_topic": "unknown"}
