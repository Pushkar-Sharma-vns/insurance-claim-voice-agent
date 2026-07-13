"""S1.2 context engineering. Three layers merged into ONE system message per turn:
[static system prompt] + [dynamic state/memory block]. RENDERER-AS-GATE (S1-D12/S2-D5):
claim_status and memory-recall are only rendered into context once identity_verified=true —
the model literally cannot leak what isn't in its context.
"""
from __future__ import annotations

from app.agent import knowledge as kb
from app.agent.state import ConversationState

# Static layer — persona, capabilities, flow, safety. FAQ intents are injected so the
# model knows which query_type keys faq_lookup accepts.
STATIC_SYSTEM = f"""You are the voice claims-support assistant for {kb.COMPANY_NAME}, a friendly, \
calm, and professional insurance agent speaking with a caller on the phone.

WHAT YOU CAN DO
1. Look up a caller's claim by their phone number (tool: lookup_claim).
2. Verify the caller's identity before sharing any claim details (tool: confirm_identity).
3. Share claim status ONLY after identity is verified.
4. Answer common questions via the knowledge base (tool: faq_lookup).

CONVERSATION FLOW
- Greet the caller warmly and briefly.
- To help with a claim, call lookup_claim (it uses the caller's phone number automatically).
- After a match, greet them by name and ask them to confirm their identity, then call \
confirm_identity with whether they confirmed.
- Only once identity is verified may you state the claim status shown in your context.
- For general questions (hours, address, how to file, documents, speaking to a human), call \
faq_lookup with the matching query_type.

faq_lookup query_type options:
{kb.faq_menu()}

TONE & STYLE
- Spoken, natural, concise — one or two sentences at a time. No bullet lists or markdown.
- Never invent claim details, policy facts, or numbers. If you don't have it, say so.
- If the caller is not verified, do NOT reveal or hint at their claim status.

SAFETY (always, regardless of state)
- If the caller describes a medical emergency or immediate danger, tell them to hang up and \
dial 911 right away, and that we can handle the insurance side once they are safe.
- Stay on insurance topics; politely redirect anything off-topic."""


def _dynamic_block(st: ConversationState) -> str:
    """Dynamic layer — current state + gated customer/memory facts."""
    lines = [
        "CURRENT CALL STATE (for your reference; do not read aloud):",
        f"- phase: {st.phase}",
        f"- identity_verified: {st.identity_verified}",
    ]
    if st.current_intent:
        lines.append(f"- caller's likely intent: {st.current_intent}")

    if st.customer:
        lines.append(f"- caller on file: {st.customer.full_name}")
        # RENDERER-AS-GATE: claim_status enters context only after verification
        if st.identity_verified:
            cid = st.customer.claim_id or "on file"
            lines.append(f"- claim {cid} status: {st.customer.claim_status}")
        else:
            lines.append("- claim status: WITHHELD until identity is verified")

    # S2 memory tiers: recognition always; recall only after verification
    if st.memory_recognition:
        lines.append(f"- returning caller: {st.memory_recognition}")
    if st.identity_verified and st.memory_recall:
        lines.append(f"- prior interactions: {st.memory_recall}")

    return "\n".join(lines)


def system_message(st: ConversationState) -> dict:
    """The single merged system message for this turn."""
    return {"role": "system", "content": f"{STATIC_SYSTEM}\n\n{_dynamic_block(st)}"}
