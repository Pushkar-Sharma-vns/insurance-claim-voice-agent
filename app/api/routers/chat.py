"""Phase 2 adapter: OpenAI-compatible POST /chat/completions that VAPI calls each turn.
VAPI owns telephony/STT/TTS/barge-in; we own the brain (orchestration in app.agent.loop).
"""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agent import loop, state
from app.api.dependencies import verify_vapi_secret
from app.logging_setup import call_id_var
from app.services import crm

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat/completions", dependencies=[Depends(verify_vapi_secret)])
async def chat_completions(payload: dict):
    call = payload.get("call") or {}
    call_id = call.get("id") or "no-call-id"
    phone = (call.get("customer") or {}).get("number", "")
    messages = payload.get("messages") or []

    call_id_var.set(call_id)

    existing = state.get(call_id)
    st = state.get_or_create(call_id, caller_phone=phone)
    if existing is None:
        loop.load_memory(st)
        logger.info("new call=%s phone=%s returning=%s",
                    call_id, crm.mask_phone(phone), bool(st.memory_recognition))

    return StreamingResponse(
        loop.stream_turn(st, messages), media_type="text/event-stream"
    )
