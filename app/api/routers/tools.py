"""Phase 1 adapter: VAPI native server tool for claim lookup."""
import logging

from fastapi import APIRouter, Depends

from app.api.dependencies import verify_vapi_secret
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
    caller = ((msg.get("call") or {}).get("customer") or {}).get("number", "")

    results = []
    for tc in tool_calls:
        args = tc.get("arguments") or (tc.get("function") or {}).get("arguments") or {}
        phone = args.get("phone_number") or caller
        cust = crm.lookup_by_phone(phone)
        logger.info(
            "lookup_claim call=%s phone=%s found=%s", call_id, crm.mask_phone(phone), bool(cust)
        )
        results.append({"toolCallId": tc.get("id"), "result": _format(cust)})
    return {"results": results}
