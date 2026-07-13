"""S1.7 acceptance harness. Two layers:
(1) Deterministic no-LLM checks on safety-critical logic (ALWAYS run) — the renderer gate,
    confirm_identity flip, error_counts 2nd-hit escalation, no-record/faq/crm-error paths.
(2) Live Gemini E2E happy path (python harness.py --live) — simulates VAPI multi-turn POSTs
    through the real /chat/completions loop with crm stubbed, asserting the identity gate.

Run: python harness.py         (deterministic checks)
     python harness.py --live   (also the real-Gemini E2E; needs GEMINI_API_KEY)
"""
from __future__ import annotations

import asyncio
import json
import sys

import requests

from app.agent import knowledge as kb
from app.agent import loop, prompts, state, tools
from app.agent.state import ESCALATING, HANDLING, ConversationState
from app.agent.tools import ToolError
from app.config import settings
from app.schemas.internal import Customer
from app.services import crm, store

CUST = Customer(first_name="Jane", last_name="Doe", phone="+14155550100",
                claim_status="Requires Documentation", claim_id="CLM-42")


def check_renderer_gate():
    st = ConversationState(call_id="t-gate")
    st.customer = CUST
    before = prompts.system_message(st)["content"]
    assert "Jane Doe" in before, "name should always be visible"
    assert "Requires Documentation" not in before, "LEAK: claim_status before verification"
    assert "WITHHELD" in before
    st.identity_verified = True
    after = prompts.system_message(st)["content"]
    assert "Requires Documentation" in after, "claim_status not exposed after verification"
    print("ok  renderer-as-gate withholds claim_status until verified")


def check_confirm_flip():
    st = ConversationState(call_id="t-confirm")
    tools.execute("confirm_identity", {"confirmed": True}, st)
    assert st.identity_verified and st.phase == HANDLING
    print("ok  confirm_identity(true) flips identity_verified + phase=handling")


def check_denied_escalation():
    st = ConversationState(call_id="t-deny")
    tools.execute("confirm_identity", {"confirmed": False}, st)
    assert st.error_counts["identity_denied"] == 1 and st.phase != ESCALATING
    r2 = tools.execute("confirm_identity", {"confirmed": False}, st)
    assert st.error_counts["identity_denied"] == 2 and st.phase == ESCALATING
    assert r2 == kb.fallback("identity_denied", "repeat")["response"]
    print("ok  2nd identity denial escalates (repeat tier)")


def check_no_record():
    st = ConversationState(call_id="t-norec")
    orig = crm.lookup_by_phone
    crm.lookup_by_phone = lambda _p: None
    try:
        r = tools.execute("lookup_claim", {"phone_number": "+10000000000"}, st)
    finally:
        crm.lookup_by_phone = orig
    assert st.error_counts["no_record"] == 1 and "No account" in r
    print("ok  lookup_claim no-record bumps no_record + conversational fallback")


def check_crm_error():
    st = ConversationState(call_id="t-crm")
    orig = crm.lookup_by_phone

    def boom(p):
        raise requests.ConnectionError("down")

    crm.lookup_by_phone = boom
    try:
        tools.execute("lookup_claim", {}, st)
        assert False, "should have raised ToolError"
    except ToolError as e:
        assert e.fallback_key == "crm_lookup_error"
    finally:
        crm.lookup_by_phone = orig
    print("ok  crm failure raises ToolError(crm_lookup_error)")


def check_faq():
    st = ConversationState(call_id="t-faq")
    assert "Monday" in tools.execute("faq_lookup", {"query_type": "office_hours"}, st)
    assert "AI assistant" in tools.execute("faq_lookup", {"query_type": "bogus"}, st)
    print("ok  faq_lookup returns KB answer + out_of_scope fallback")


def check_sse_shape():
    st = ConversationState(call_id="t-sse")
    st.turn_count = 1
    chunk = loop._chunk(st, "Hello.", role=True)
    assert chunk["object"] == "chat.completion.chunk"
    assert chunk["choices"][0]["delta"]["role"] == "assistant"
    final = loop._chunk(st, None, finish="stop")
    assert final["choices"][0]["finish_reason"] == "stop"
    line = loop._sse(chunk)
    assert line.startswith("data: ") and line.endswith("\n\n")
    json.loads(line[len("data: "):].strip())
    print("ok  SSE chunk shape is OpenAI-compatible")


def deterministic():
    check_renderer_gate()
    check_confirm_flip()
    check_denied_escalation()
    check_no_record()
    check_crm_error()
    check_faq()
    check_sse_shape()
    print("\nDETERMINISTIC CHECKS PASSED")


async def _collect(st, messages) -> str:
    text = ""
    async for line in loop.stream_turn(st, messages):
        if not line.startswith("data: "):
            continue
        body = line[len("data: "):].strip()
        if body == "[DONE]":
            continue
        delta = json.loads(body)["choices"][0]["delta"]
        text += delta.get("content", "")
    return text.strip()


async def live_e2e():
    print("\n--- LIVE Gemini E2E (crm stubbed, real model) ---")
    store.init_db()
    crm.lookup_by_phone = lambda _p: CUST
    st = state.get_or_create("live-e2e", caller_phone="+14155550100")

    msgs = [{"role": "user", "content": "Hi, I'd like to check the status of my claim."}]
    a1 = await _collect(st, msgs)
    print(f"turn1 assistant: {a1}")
    assert "Requires Documentation" not in a1, "LEAK before verification"

    msgs += [{"role": "assistant", "content": a1},
             {"role": "user", "content": "Yes, this is Jane Doe. You can confirm that's me."}]
    a2 = await _collect(st, msgs)
    print(f"turn2 assistant: {a2}")
    assert st.identity_verified, "model did not verify identity via confirm_identity"

    msgs += [{"role": "assistant", "content": a2},
             {"role": "user", "content": "Great, so what's my claim status?"}]
    a3 = await _collect(st, msgs)
    print(f"turn3 assistant: {a3}")
    assert any(w in a3.lower() for w in ("document", "requires")), \
        "claim status (requires documentation) not conveyed after verification"

    print("\nLIVE E2E PASSED — greet -> lookup -> verify -> gated status reveal")


if __name__ == "__main__":
    deterministic()
    if "--live" in sys.argv:
        if not settings.gemini_api_key:
            print("\nSKIP live E2E: GEMINI_API_KEY not set")
        else:
            asyncio.run(live_e2e())
