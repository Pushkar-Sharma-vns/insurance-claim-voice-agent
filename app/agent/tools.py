"""S1.5 tool registry + executor. Three V1 tools: lookup_claim (reuse crm, NAME ONLY),
confirm_identity (deterministic gate flip), faq_lookup (KB answer by intent enum).

The executor mutates ConversationState and returns a result string fed back to the model.
Infra failures raise ToolError(key) so the loop serves the S1.6 scripted fallback.
"""
from __future__ import annotations

import logging

import requests

from app.agent import knowledge as kb
from app.agent import state as st_mod
from app.agent.state import ConversationState
from app.services import crm

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """Infra failure during a tool call; carries an S1.6 fallback key."""

    def __init__(self, fallback_key: str):
        super().__init__(fallback_key)
        self.fallback_key = fallback_key


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_claim",
            "description": "Look up the caller's account and claim by phone number. Uses the "
                           "caller's own number automatically. Returns the name on file only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "Optional. Only if the caller gives a different number "
                                       "than the one they're calling from.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_identity",
            "description": "Record whether the caller confirmed they are the person on file. "
                           "Must be called before any claim status is shared.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmed": {
                        "type": "boolean",
                        "description": "True if the caller confirmed their identity, else False.",
                    }
                },
                "required": ["confirmed"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "faq_lookup",
            "description": "Get the approved answer to a common question from the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": kb.FAQ_INTENTS,
                        "description": "The category of the caller's question.",
                    }
                },
                "required": ["query_type"],
            },
        },
    },
]


def execute(name: str, args: dict, st: ConversationState) -> str:
    if name == "lookup_claim":
        return _lookup_claim(args, st)
    if name == "confirm_identity":
        return _confirm_identity(args, st)
    if name == "faq_lookup":
        return kb.faq_answer(args.get("query_type", "out_of_scope"))
    logger.warning("unknown tool name=%s", name)
    raise ToolError("malformed_request")


def _lookup_claim(args: dict, st: ConversationState) -> str:
    phone = args.get("phone_number") or st.caller_phone
    logger.info("tool=lookup_claim call=%s phone=%s", st.call_id, crm.mask_phone(phone))
    try:
        cust = crm.lookup_by_phone(phone)
    except requests.RequestException:
        raise ToolError("crm_lookup_error")

    if cust is None:
        tier = st.bump_error("no_record")
        fb = kb.fallback("no_record", tier)
        return f"No account found for that number. Tell the caller, warmly: {fb['response']}"

    st.customer = cust
    st.phase = st_mod.AUTHENTICATING
    # NAME ONLY — claim_status is never returned here (S1-D12); it reaches the model
    # only through the renderer once identity_verified=true.
    return (f"Account found. Name on file: {cust.full_name}. Greet them by name, ask them to "
            "confirm their identity, then call confirm_identity. Do NOT share claim status yet.")


def _confirm_identity(args: dict, st: ConversationState) -> str:
    if args.get("confirmed"):
        st.identity_verified = True
        st.phase = st_mod.HANDLING
        # Safe to include claim_status here: only reached when confirmed=True (same gate as
        # the renderer). Returning it lets the model reveal it THIS turn — the per-turn context
        # was built pre-flip, so without this the reveal would slip to the next turn.
        if st.customer:
            cid = st.customer.claim_id or "on file"
            return (f"Identity confirmed. Claim {cid} status is '{st.customer.claim_status}'. "
                    "Share it now; if it requires documentation, explain how to submit it.")
        return "Identity confirmed. You may now help the caller with their request."
    tier = st.bump_error("identity_denied")
    st.phase = st_mod.ESCALATING if tier == "repeat" else st.phase
    return kb.fallback("identity_denied", tier)["response"]
