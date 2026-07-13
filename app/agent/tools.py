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
            "description": "Look up the caller's account and claim by the phone number they give "
                           "you. Returns the name on file only. Call this only after the caller "
                           "has spoken a phone number. If it reports multiple or no matches, "
                           "ask the caller for their full name and call it again with full_name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "The phone number the caller gave, digits only.",
                    },
                    "full_name": {
                        "type": "string",
                        "description": "The caller's full name (first and last). Provide this to "
                                       "disambiguate multiple matches or as alternative "
                                       "verification when the number does not match.",
                    },
                },
                "required": ["phone_number"],
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
    name = args.get("full_name") or ""
    logger.info("tool=lookup_claim call=%s phone=%s name=%s",
                st.call_id, crm.mask_phone(phone), bool(name))
    try:
        cands = crm.match(crm.all_customers(), phone=phone, name=name)
    except requests.RequestException:
        raise ToolError("crm_lookup_error")

    if len(cands) == 1:
        cust = cands[0]
        st.customer = cust
        st.phase = st_mod.AUTHENTICATING
        # NAME ONLY — claim_status is never returned here (S1-D12); it reaches the model
        # only through the renderer once identity_verified=true.
        return (f"Account found. Name on file: {cust.full_name}. Confirm identity by asking "
                f"exactly 'Am I speaking with {cust.full_name}?', then call confirm_identity. "
                "Do NOT share claim status yet.")

    if len(cands) > 1:
        return ("Multiple accounts are close to that number — the number may have been misheard. "
                "Ask the caller for their full name (first and last), then call lookup_claim "
                "again with both phone_number and full_name.")

    # zero matches: alternative verification by name before giving up (S1 fallback)
    if not name and not st.name_attempted:
        st.name_attempted = True
        return ("No account matches that number; it may have been misheard. Ask the caller for "
                "their full name (first and last) to try another way, then call lookup_claim "
                "again with phone_number and full_name.")
    tier = st.bump_error("no_record")
    fb = kb.fallback("no_record", tier)
    return f"Still no match after alternative verification. Tell the caller, warmly: {fb['response']}"


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
