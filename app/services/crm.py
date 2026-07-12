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
    for rec in resp.json().get("records", []):
        f = rec["fields"]
        if _digits(f.get("Phone", "")) == target:
            return Customer(
                first_name=f.get("First Name", ""),
                last_name=f.get("Last Name", ""),
                phone=f.get("Phone", ""),
                claim_status=f.get("Claim Status", ""),
                claim_id=f.get("Claim ID", ""),
            )
    return None


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
