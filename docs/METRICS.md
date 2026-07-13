# Metrics & ROI — Observe Insurance Voice Agent

Companion to `app/metrics.py` (`python -m app.metrics`), which computes these from the
shared SQLite DB (`data/conversations.db`: `calls` + `turns`). Numbers fill in after live
calls; the framework below is the panel narrative.

## What we track and why it matters

| Metric | Source | ROI lever |
|---|---|---|
| **Containment rate** = 1 − escalated/total | `calls.escalated` (code-derived) | Every contained call is one an agent didn't take. Contained × fully-loaded agent-minutes = direct labor saved. |
| **Avg handle time** (s) | `calls.duration_seconds` | Shorter calls → more throughput per line and lower telephony cost. Trend it against prompt changes. |
| **Avg turns / call** | `calls.num_turns` | Proxy for friction. Rising turns on a topic = the flow or FAQ answer isn't landing. |
| **Sentiment distribution** | `calls.sentiment` (our post-processing) | CSAT proxy. Negative share is the queue for transcript review and tone fixes. |
| **Resolution distribution** | `calls.resolution_status` | Descriptive (model-derived) — read alongside the *code-derived* containment number, never instead of it. |
| **Total tokens + est. cost** | `turns.prompt/completion_tokens` × price | Per-call marginal cost. gemini-2.5-flash: **$0.30/1M in, $2.50/1M out** (verified 2026). Cost ÷ calls = margin per contained call. |
| **Tool success rate** | `turns.tool_calls` JSON | A failing tool (Airtable) silently tanks containment. Watch for drift. |
| **Avg turn / LLM latency** (ms) | `turns.turn_latency_ms`, `llm_latency_ms` | Voice UX. High latency → barge-in / talk-over. Drives the V2 streaming work. |

**Containment is deterministic on purpose (S4-D3).** `escalated` is set in code (final phase
`escalating`, or any error that hit the repeat/human-followup tier) — never from the LLM's
`resolution_status`. The headline ROI metric must not depend on the model grading its own work.

## Prompt-tuning feedback loop

The point of the trace tables is to close the loop from metric → change:

1. **`primary_topic` × `escalated`** → topics that escalate most → fix that FAQ answer or add
   prompt guidance for it. (e.g. if "submit documentation" escalates, the KB answer is unclear.)
2. **Per-tool latency** (`turns.tool_calls`) → a slow tool path → the S1.4 V2 work
   (stream-with-tool-interception) is where that latency goes to die.
3. **Negative-sentiment transcripts** → pull the `messages` rows for those calls → tone/prompt
   fixes, usually in the S1.6 repeat-tier wording.
4. **Tokens/turn trend** → context is bloating → trim the dynamic renderer / cap memory-block
   length in `prompts.py`.

## ROI headline (fill after live calls)

```
contained_calls   = total × containment_rate
labor_saved_hours  = contained_calls × avg_handle_time_s / 3600
cost_per_call      = est_cost_usd / total
net_margin_per_call = agent_cost_per_call − cost_per_call
```

> V2: date-range aggregation, latency percentiles, per-call cost tracking, dashboards,
> CSAT correlation.
