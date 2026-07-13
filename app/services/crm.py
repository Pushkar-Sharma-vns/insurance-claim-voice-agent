"""Airtable integration — shared by both the native and custom-LLM paths."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from app.config import settings
from app.schemas.internal import Customer

logger = logging.getLogger(__name__)

_BASE = "https://api.airtable.com/v0"
_HEADERS = {"Authorization": f"Bearer {settings.airtable_token}"}


def _digits(phone: str) -> str:
    """Last 10 digits — normalizes '+1 (415) 555-0100' and '4155550100' to match."""
    return "".join(c for c in phone if c.isdigit())[-10:]


def mask_phone(phone: str) -> str:
    """PII-safe: log only the last 4 digits."""
    d = _digits(phone)
    return f"***{d[-4:]}" if d else "(none)"


def lookup_by_phone(phone: str) -> Customer | None:
    # ponytail: full-table scan + normalize both sides. Robust to phone formatting,
    # fine for a demo table. Swap to filterByFormula / an index if Customers grows.
    target = _digits(phone)
    if not target:
        return None
    url = f"{_BASE}/{settings.airtable_base_id}/{settings.customers_table}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        resp.raise_for_status()
    except requests.RequestException:
        logger.exception("Airtable lookup failed phone=%s", mask_phone(phone))
        raise
    records = resp.json().get("records", [])
    for rec in records:
        f = rec["fields"]
        if _digits(f.get("Phone", "")) == target:
            logger.info("lookup matched target=%s name=%s %s",
                        mask_phone(phone), f.get("First Name", ""), f.get("Last Name", ""))
            return Customer(
                first_name=f.get("First Name", ""),
                last_name=f.get("Last Name", ""),
                phone=f.get("Phone", ""),
                claim_status=f.get("Claim Status", ""),
                claim_id=f.get("Claim ID", ""),
            )
    # no match: log target vs the candidates we scanned (masked) so mismatches are debuggable
    candidates = [mask_phone(r["fields"].get("Phone", "")) for r in records]
    logger.info("lookup no match target=%s scanned=%d candidates=%s",
                mask_phone(phone), len(records), candidates)
    return None


def _lev(a: str, b: str) -> int:
    """Levenshtein edit distance (stdlib, iterative DP)."""
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _name_tokens(s: str) -> list[str]:
    """Lowercase alpha tokens of a name, e.g. 'Púshkar Sharma!' -> ['pshkar', 'sharma']."""
    return "".join(c if c.isalpha() else " " for c in s.lower()).split()


def _name_match(c: Customer, provided: list[str]) -> bool:
    """Every provided name token fuzzy-matches (edit distance <=1) some token on file."""
    on_file = _name_tokens(f"{c.first_name} {c.last_name}")
    return bool(provided) and all(any(_lev(p, o) <= 1 for o in on_file) for p in provided)


def all_customers() -> list[Customer]:
    """One Airtable scan -> parsed Customer list (matching happens in-memory)."""
    url = f"{_BASE}/{settings.airtable_base_id}/{settings.customers_table}"
    resp = requests.get(url, headers=_HEADERS, timeout=8)
    resp.raise_for_status()
    out = []
    for rec in resp.json().get("records", []):
        f = rec["fields"]
        out.append(Customer(
            first_name=f.get("First Name", ""), last_name=f.get("Last Name", ""),
            phone=f.get("Phone", ""), claim_status=f.get("Claim Status", ""),
            claim_id=f.get("Claim ID", ""),
        ))
    return out


def match(customers: list[Customer], phone: str = "", name: str = "") -> list[Customer]:
    """Resolve candidates by phone then name. Phone: exact (last-10 digits), else fuzzy
    (Levenshtein <=2, covers a mis-heard/dropped/extra digit). Name filters/searches by
    fuzzy token match. Needs at least one of phone/name."""
    pd = _digits(phone)
    if not pd and not name:
        return []
    cands = customers
    if pd:
        exact = [c for c in customers if _digits(c.phone) == pd]
        cands = exact if exact else [c for c in customers if _lev(_digits(c.phone), pd) <= 2]
    if name:
        tokens = _name_tokens(name)
        cands = [c for c in cands if _name_match(c, tokens)]
    return cands


def write_interaction(name: str, summary: str, sentiment: str) -> None:
    url = f"{_BASE}/{settings.airtable_base_id}/{settings.interactions_table}"
    body = {"fields": {
        "Caller Name": name,
        "Summary": summary,
        "Sentiment": sentiment,
        "Timestamp": datetime.now(timezone.utc).isoformat(),
    }}
    try:
        resp = requests.post(
            url, headers={**_HEADERS, "Content-Type": "application/json"}, json=body, timeout=8
        )
        resp.raise_for_status()
    except requests.RequestException:
        logger.exception("Airtable write failed name=%s", name)
        raise
    logger.info("Interaction logged name=%s sentiment=%s", name, sentiment)
