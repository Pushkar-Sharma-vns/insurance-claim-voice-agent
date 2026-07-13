"""S1.1 ConversationState + in-memory store keyed by call.id.

Ownership (S1.1): identity_verified + phase + customer are CODE-owned (deterministic,
zero-lag, protect the identity gate). current_intent is EXTRACTOR-owned (lag-tolerant).
Single-worker ceiling — a dict, not Redis (ponytail; Redis/SQLite state = V2).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.internal import Customer

# phases (code-derived): greeting -> authenticating -> handling -> escalating -> ending
GREETING = "greeting"
AUTHENTICATING = "authenticating"
HANDLING = "handling"
ESCALATING = "escalating"
ENDING = "ending"


class ConversationState(BaseModel):
    call_id: str
    caller_phone: str = ""
    phase: str = GREETING
    identity_verified: bool = False
    customer: Customer | None = None
    turn_count: int = 0
    error_counts: dict[str, int] = Field(default_factory=dict)
    current_intent: str = ""  # extractor-owned (V1: minimal)

    # S2 memory tiers, computed once at call start (recall tier gated on identity_verified)
    memory_recognition: str = ""
    memory_recall: str = ""

    # latest structured history the model processed (for S2 messages + S4 post-processing)
    transcript_messages: list[dict] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    def bump_error(self, key: str) -> str:
        """Increment an error counter; return the tier to serve: 'first' then 'repeat'."""
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
        return "first" if self.error_counts[key] == 1 else "repeat"


# in-memory store (single-worker ceiling — ponytail: dict; Redis if multi-worker, V2)
_STORE: dict[str, ConversationState] = {}


def get_or_create(call_id: str, caller_phone: str = "") -> ConversationState:
    st = _STORE.get(call_id)
    if st is None:
        st = ConversationState(call_id=call_id, caller_phone=caller_phone)
        _STORE[call_id] = st
    return st


def get(call_id: str) -> ConversationState | None:
    return _STORE.get(call_id)


def drop(call_id: str) -> None:
    _STORE.pop(call_id, None)
