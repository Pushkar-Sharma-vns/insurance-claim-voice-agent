"""S2/S3/S4 substrate: ONE SQLite DB (stdlib sqlite3, no new dep) at data/conversations.db.
Serves calls+messages (S2), turns trace (S3), metrics-as-SQL (S4).

ponytail: single file, WAL, short-lived per-operation connection (same open/write/close
idiom as the per-call log handler). Single-worker ceiling; pooled conn / Postgres = V2.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/conversations.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    caller_phone_digits TEXT,
    caller_name TEXT,
    claim_id TEXT,
    identity_verified INTEGER,
    current_intent TEXT,
    final_phase TEXT,
    num_turns INTEGER,
    summary TEXT,
    sentiment TEXT,
    resolution_status TEXT,
    primary_topic TEXT,
    vapi_transcript TEXT,
    escalated INTEGER,
    airtable_synced INTEGER,
    duration_seconds REAL,
    started_at TEXT,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT,
    turn_index INTEGER,
    role TEXT,
    content TEXT,
    tool_name TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT,
    turn_index INTEGER,
    turn_latency_ms REAL,
    llm_latency_ms REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    tool_calls TEXT,
    phase_before TEXT,
    phase_after TEXT,
    current_intent TEXT,
    identity_verified INTEGER,
    error_type TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_calls_phone ON calls(caller_phone_digits);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    # Self-healing: ensure the schema on every connection. CREATE ... IF NOT EXISTS is a
    # near-noop on an existing DB, so a deleted/blank file can never cause "no such table".
    # ponytail: DDL-per-op is trivial at single-caller demo volume; move to startup-only if
    # write throughput ever matters.
    c.executescript(_SCHEMA)
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Explicit startup hook (called from main.py). _conn() also ensures the schema."""
    _conn().close()


def save_call(row: dict) -> None:
    row = {**row, "ended_at": _now()}
    cols = ", ".join(row)
    ph = ", ".join(f":{k}" for k in row)
    with _conn() as c:
        c.execute(f"INSERT OR REPLACE INTO calls ({cols}) VALUES ({ph})", row)


def save_messages(call_id: str, messages: list[dict]) -> None:
    """Persist the structured history the model processed (S2)."""
    now = _now()
    rows = [
        (call_id, i, m.get("role"), m.get("content"),
         (m.get("tool_calls") or [{}])[0].get("function", {}).get("name") if m.get("tool_calls") else m.get("name"),
         now)
        for i, m in enumerate(messages)
    ]
    with _conn() as c:
        c.executemany(
            "INSERT INTO messages (call_id, turn_index, role, content, tool_name, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )


def save_turn(row: dict) -> None:
    """S3 per-turn trace row (written after the SSE stream closes, off the latency path)."""
    row = {**row, "created_at": _now()}
    if isinstance(row.get("tool_calls"), (list, dict)):
        row["tool_calls"] = json.dumps(row["tool_calls"])
    cols = ", ".join(row)
    ph = ", ".join(f":{k}" for k in row)
    with _conn() as c:
        c.execute(f"INSERT INTO turns ({cols}) VALUES ({ph})", row)


def recent_calls_by_phone(digits: str, limit: int = 3) -> list[sqlite3.Row]:
    """S2 cross-call memory read: prior calls for this caller, newest first."""
    with _conn() as c:
        return c.execute(
            "SELECT caller_name, summary, ended_at FROM calls "
            "WHERE caller_phone_digits = ? AND summary IS NOT NULL "
            "ORDER BY ended_at DESC LIMIT ?",
            (digits, limit),
        ).fetchall()
