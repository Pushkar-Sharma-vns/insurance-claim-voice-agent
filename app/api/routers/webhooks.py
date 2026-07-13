"""Write-back: VAPI end-of-call-report -> Airtable (CRM source of truth) + SQLite (durable
local copy / fallback).

Error philosophy (user decision): NO blind retries. The Airtable write is attempted
synchronously so we KNOW its outcome, but a failure is NOT bounced back to VAPI as a 5xx
(the call is over — there's no customer to re-prompt, and a blind VAPI retry tells no one
anything). Instead we log it, keep the record in SQLite flagged `airtable_synced=0` for a
V2 reconciliation job, and still ack 200. Mid-call CRM errors are handled differently — in
the /chat/completions loop, where a mapped fallback IS spoken and re-tried on the caller's
next turn (see app/agent/loop.py + docs/fallbacks.json).

S4-D5 branch: in-memory ConversationState for call.id -> Phase 2 (our post-processing +
SQLite persist); else -> Phase 1 (VAPI-analysis fields, Airtable only — no SQLite substrate).
"""
import logging

from fastapi import APIRouter, Depends

from app.agent import state as agent_state
from app.agent.state import ESCALATING
from app.api.dependencies import verify_vapi_secret
from app.logging_setup import call_id_var
from app.services import crm, postprocess, store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/vapi/end-of-call", dependencies=[Depends(verify_vapi_secret)])
def end_of_call(payload: dict):
    """Only end-of-call-report is processed; other event types are ignored with 200 so VAPI
    doesn't retry. On a report: post-process -> Airtable write (sync, no retry) -> SQLite
    persist (durable fallback). Always acks 200.
    """
    msg = payload.get("message", {})
    if msg.get("type") != "end-of-call-report":
        logger.info("end-of-call webhook: ignored type=%s", msg.get("type"))
        return {"status": "ignored"}

    call_id = (msg.get("call") or {}).get("id", "?")
    call_id_var.set(call_id)
    st = agent_state.get(call_id)

    # Post-processing (phase 2) has its own internal fallback and never raises, so only the
    # Airtable WRITE below can fail.
    record = _phase2_record(st) if st is not None else _phase1_record(msg)

    # CRM source of truth — attempt synchronously so we know the outcome. No retry on failure.
    synced = 1
    try:
        crm.write_interaction(name=record["name"], summary=record["summary"],
                              sentiment=record["sentiment"])
    except Exception:
        synced = 0
        logger.exception(
            "Airtable write FAILED call=%s — no retry; kept in SQLite (unsynced) for "
            "reconciliation", call_id)

    # Durable local copy / fallback. Phase 2 only (Phase 1 has no in-memory state to persist).
    if st is not None:
        _persist_sqlite(call_id, msg, st, record, synced)
        agent_state.drop(call_id)

    logger.info("end-of-call logged call=%s phase=%s name=%s airtable_synced=%s",
                call_id, record["phase"], record["name"], synced)
    return {"status": "logged", "phase": record["phase"], "airtable_synced": bool(synced)}


def _phase2_record(st) -> dict:
    """Phase 2: our own post-processing (P2-D3). Self-falling-back; never raises."""
    post = postprocess.summarize_call(st.transcript_messages)
    name = st.customer.full_name if st.customer else "Unknown"
    # containment is CODE-derived (S4-D3): escalated phase OR any error hit the repeat tier
    escalated = int(st.phase == ESCALATING or any(v >= 2 for v in st.error_counts.values()))
    return {"phase": 2, "name": name, "summary": post["summary"],
            "sentiment": post["sentiment"], "post": post, "escalated": escalated}


def _phase1_record(msg: dict) -> dict:
    """Phase 1 (VAPI-native): name from CRM lookup (guarded), summary/sentiment from VAPI."""
    call = msg.get("call") or {}
    analysis = msg.get("analysis") or {}
    structured = analysis.get("structuredData") or {}
    phone = (call.get("customer") or {}).get("number", "")
    try:
        cust = crm.lookup_by_phone(phone) if phone else None
    except Exception:
        logger.exception("phase1 CRM lookup failed — falling back to structured name")
        cust = None
    name = cust.full_name if cust else (structured.get("caller_name") or "Unknown")
    return {"phase": 1, "name": name, "summary": analysis.get("summary") or "",
            "sentiment": structured.get("sentiment") or "Neutral"}


def _persist_sqlite(call_id: str, msg: dict, st, record: dict, synced: int) -> None:
    """Durable local copy. On Airtable failure (synced=0) this IS the record of record until
    reconciliation. Failure here is tolerable and never surfaced ('sqlite is fine')."""
    call_id_var.set(call_id)
    post = record["post"]
    try:
        store.save_call({
            "call_id": call_id,
            "caller_phone_digits": crm._digits(st.caller_phone),
            "caller_name": record["name"],
            "claim_id": st.customer.claim_id if st.customer else "",
            "identity_verified": int(st.identity_verified),
            "current_intent": st.current_intent,
            "final_phase": st.phase,
            "num_turns": st.turn_count,
            "summary": post["summary"],
            "sentiment": post["sentiment"],
            "resolution_status": post["resolution_status"],
            "primary_topic": post["primary_topic"],
            "vapi_transcript": msg.get("transcript") or (msg.get("artifact") or {}).get("transcript") or "",
            "escalated": record["escalated"],
            "airtable_synced": synced,
            "duration_seconds": msg.get("durationSeconds"),
            "started_at": msg.get("startedAt"),
        })
        store.save_messages(call_id, st.transcript_messages)
        logger.info("sqlite persist ok call=%s airtable_synced=%s", call_id, synced)
    except Exception:
        logger.exception("sqlite persist failed call=%s (tolerable)", call_id)
