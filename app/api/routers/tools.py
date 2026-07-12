"""Phase 1 adapter: VAPI native server tool for claim lookup."""
import logging

from fastapi import APIRouter, Depends

from app.api.dependencies import verify_vapi_secret
from app.logging_setup import call_id_var
from app.services import crm

logger = logging.getLogger(__name__)

router = APIRouter()


def _format(cust) -> str:
    if not cust:
        return ("No account was found for that phone number. Offer alternative "
                "verification (full name + claim ID) or escalate to a human agent.")
    return (f"Account found. Name: {cust.full_name}. "
            f"Claim {cust.claim_id or 'on file'} status: {cust.claim_status}.")


@router.post("/lookup-claim", dependencies=[Depends(verify_vapi_secret)])
def lookup_claim(payload: dict):
    """VAPI POSTs {message:{toolCallList:[{id,name,arguments}], call:{customer:{number}}}}.
    We return {results:[{toolCallId, result}]}."""
    msg = payload.get("message", {})
    tool_calls = msg.get("toolCallList") or msg.get("toolCalls") or []
    call_id = (msg.get("call") or {}).get("id", "?")
    call_id_var.set(call_id)
    caller = ((msg.get("call") or {}).get("customer") or {}).get("number", "")

    if not tool_calls:
        logger.warning("lookup_claim call=%s: no tool calls in payload", call_id)

    results = []
    for tc in tool_calls:
        name = tc.get("name") or (tc.get("function") or {}).get("name") or "?"
        args = tc.get("arguments") or (tc.get("function") or {}).get("arguments") or {}
        arg_phone = args.get("phone_number")
        phone = arg_phone or caller
        source = "tool-arg" if arg_phone else ("caller-id" if caller else "none")
        logger.info(
            "tool=%s call=%s phone=%s source=%s", name, call_id, crm.mask_phone(phone), source
        )
        try:
            cust = crm.lookup_by_phone(phone)
        except Exception:
            logger.exception("lookup_claim call=%s: Airtable lookup errored", call_id)
            results.append({"toolCallId": tc.get("id"),
                            "result": "Lookup is temporarily unavailable. Offer a human callback."})
            continue
        logger.info("lookup_claim call=%s found=%s", call_id, bool(cust))
        results.append({"toolCallId": tc.get("id"), "result": _format(cust)})
    return {"results": results}
