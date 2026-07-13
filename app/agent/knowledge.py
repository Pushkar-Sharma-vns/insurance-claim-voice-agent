"""Static knowledge loaded once at import: FAQ KB + fallback map (S1.5, S1.6)."""
from __future__ import annotations

import json
from pathlib import Path

_DOCS = Path(__file__).resolve().parents[2] / "docs"

_KB = json.loads((_DOCS / "faqs.json").read_text())["knowledge_base"]
FALLBACKS: dict = json.loads((_DOCS / "fallbacks.json").read_text())

COMPANY_NAME: str = _KB["company_name"]
SUPPORT_EMAIL: str = _KB["support_email"]

# intent -> answer, and intent -> example phrasings (for the system prompt)
_FAQS: list[dict] = _KB["faqs"]
FAQ_ANSWERS: dict[str, str] = {f["intent"]: f["answer"] for f in _FAQS}
FAQ_INTENTS: list[str] = list(FAQ_ANSWERS)


def faq_answer(query_type: str) -> str:
    """S1.5 faq_lookup: intent enum -> answer; unknown -> out_of_scope."""
    return FAQ_ANSWERS.get(query_type, FAQ_ANSWERS["out_of_scope"])


def fallback(key: str, tier: str) -> dict:
    """S1.6: fallback[key][tier] -> {response, action}. tier in {first, repeat}."""
    return FALLBACKS[key][tier]


def faq_menu() -> str:
    """Human-readable list of intents + example phrasings for the system prompt."""
    lines = []
    for f in _FAQS:
        ex = "; ".join(f["questions"][:2])
        lines.append(f'  - {f["intent"]}: e.g. "{ex}"')
    return "\n".join(lines)
