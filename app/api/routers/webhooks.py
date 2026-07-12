"""Write-back: VAPI end-of-call-report -> Airtable Interactions. Reused by both phases."""
import logging

from fastapi import APIRouter, Depends

from app.api.dependencies import verify_vapi_secret
from app.logging_setup import call_id_var
from app.services import crm

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/vapi/end-of-call", dependencies=[Depends(verify_vapi_secret)])
def end_of_call(payload: dict):
    msg = payload.get("message", {})
    if msg.get("type") != "end-of-call-report":
        logger.info("end-of-call webhook: ignored type=%s", msg.get("type"))
        return {"status": "ignored"}

    call = msg.get("call") or {}
    call_id_var.set(call.get("id", "?"))
    analysis = msg.get("analysis") or {}
    structured = analysis.get("structuredData") or {}

    phone = (call.get("customer") or {}).get("number", "")
    cust = crm.lookup_by_phone(phone) if phone else None
    name = cust.full_name if cust else (structured.get("caller_name") or "Unknown")
    summary = analysis.get("summary") or ""
    # VAPI's structured-output sentiment; falls back to Neutral if not yet generated.
    sentiment = structured.get("sentiment") or "Neutral"

    logger.info("end-of-call report call=%s name=%s", call.get("id", "?"), name)
    crm.write_interaction(name=name, summary=summary, sentiment=sentiment)
    return {"status": "logged"}
