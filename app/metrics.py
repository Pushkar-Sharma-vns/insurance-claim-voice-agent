"""S4 metrics compute: pure SQL aggregates over data/conversations.db (no pandas).
Containment is code-derived (calls.escalated), never the LLM. Run: python -m app.metrics
"""
from __future__ import annotations

import json

from app.services.store import _conn

# gemini-2.5-flash pricing (web-verified 2026): $0.30 / 1M input, $2.50 / 1M output.
PRICE_IN = 0.30 / 1_000_000
PRICE_OUT = 2.50 / 1_000_000


def compute() -> dict:
    with _conn() as c:
        calls = c.execute("SELECT * FROM calls").fetchall()
        turns = c.execute("SELECT * FROM turns").fetchall()

    total = len(calls)
    if total == 0:
        return {"total_calls": 0}

    escalated = sum(r["escalated"] or 0 for r in calls)
    sentiments: dict = {}
    resolutions: dict = {}
    for r in calls:
        sentiments[r["sentiment"]] = sentiments.get(r["sentiment"], 0) + 1
        resolutions[r["resolution_status"]] = resolutions.get(r["resolution_status"], 0) + 1

    durations = [r["duration_seconds"] for r in calls if r["duration_seconds"]]
    turn_counts = [r["num_turns"] for r in calls if r["num_turns"]]

    prompt_tok = sum(t["prompt_tokens"] or 0 for t in turns)
    completion_tok = sum(t["completion_tokens"] or 0 for t in turns)
    turn_lat = [t["turn_latency_ms"] for t in turns if t["turn_latency_ms"]]
    llm_lat = [t["llm_latency_ms"] for t in turns if t["llm_latency_ms"]]

    tool_ok = tool_total = 0
    for t in turns:
        for ev in json.loads(t["tool_calls"] or "[]"):
            tool_total += 1
            tool_ok += ev.get("status") == "ok"

    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    return {
        "total_calls": total,
        "containment_rate": round(1 - escalated / total, 3),
        "escalated_calls": escalated,
        "avg_handle_time_s": avg(durations),
        "avg_turns": avg(turn_counts),
        "sentiment_distribution": sentiments,
        "resolution_distribution": resolutions,
        "total_tokens": prompt_tok + completion_tok,
        "est_cost_usd": round(prompt_tok * PRICE_IN + completion_tok * PRICE_OUT, 4),
        "tool_success_rate": round(tool_ok / tool_total, 3) if tool_total else None,
        "avg_turn_latency_ms": avg(turn_lat),
        "avg_llm_latency_ms": avg(llm_lat),
    }


if __name__ == "__main__":
    report = compute()
    print("=== Observe Insurance — Voice Agent Metrics ===")
    for k, v in report.items():
        print(f"{k:24} {v}")
