# Observe Insurance – Voice AI Claims Agent · Progress & Decisions

Living doc. Summary + decisions + tradeoffs only. Updated every turn.
Companion: `progress.json` (machine-readable state).

---

## Strategy

Build **two** VAPI integration paths, sharing one backend:

- **Phase 1 – VAPI-native** → reliable end-to-end demo. VAPI owns the LLM; our
  server exposes tool webhooks + a write-back webhook.
- **Phase 2 – Custom LLM** → "bring your own brain". Our server *is* the LLM
  (`/chat/completions` SSE). Showcases engineering depth for the panel.

Native first so there's always a working demo. Phase 2 reuses Phase 1's
Airtable integration verbatim — the only thing that changes is the transport
adapter (ports & adapters).

## Architecture (shared core, swappable adapter)

```
                 ┌─────────────── SHARED CORE (build once) ───────────────┐
                 │  services/crm.py   lookup_by_phone() / write_interaction() │
                 │  core/prompts.py   persona + flow + FAQ facts             │
                 │  schemas/internal  Customer, Interaction                  │
                 └────────────────────────────────────────────────────────┘
   Phase 1 adapter                              Phase 2 adapter
   POST /tools/lookup-claim  (VAPI server tool) POST /vapi/chat/completions (SSE)
   POST /webhooks/vapi/end-of-call (write-back) (write-back webhook reused)
```

One FastAPI server hosts all adapters.

## Voice flow (both phases)

Greeting → ask phone # → `lookup_by_phone` → confirm identity
→ claim status (Approved / Pending / Requires-Docs → submission instructions)
→ FAQ / escalation (transferCall) / 911-safety / off-topic redirect
→ end → write interaction (name, summary, sentiment, timestamp).

## Decisions (why)

- **D1/D2 – Both paths, native first.** Reliable fallback demo + depth showcase.
- **D3 – Shared core, adapter-only difference.** No wasted work; strong panel story.
- **D4 – VAPI end-of-call-report + structured outputs for summary/sentiment.**
  Don't rebuild a summarizer/sentiment classifier VAPI already provides.
- **D5 – FAQ facts in the system prompt**, not an LLM-bypass. Simpler, low
  hallucination risk on ~12 static facts.
- **D6 – Corrected VAPI schemas.** `call.customer.number` is nested (not flat);
  `Message.content` is Optional (tool turns have null content). Verified vs
  official docs + VapiAI Flask reference server.

## Key tradeoffs to remember

- **State (Phase 2):** derive from the message history VAPI resends each turn.
  Avoid in-memory store — it breaks across multiple workers. Redis only if needed.
- **Structured outputs timing:** not synchronous in the end-of-call webhook;
  poll `GET /call/{id}` a few seconds later, or accept summary-only in the webhook.
- **Latency (Phase 2):** custom LLM adds a network hop. Cache the customer record
  after first lookup; keep Airtable reads off the token-streaming path.

## Verified VAPI facts (sources)

- Payload: OpenAI-shaped `{model, messages, temperature, stream, tools?}` + injected `call` object.
- Customer phone: `call.customer.number` (E.164, nested).
- SSE: `data: {chat.completion.chunk}\n\n`; `[DONE]` optional (reference server omits it).
- Both streaming and non-streaming responses accepted.
- Tools: passed in request; `tool_calls` detected in stream; backend executes + feeds result back.

## Current status

**Phase 1 backend: code-complete and verified.** Built the shared core +
native adapter:

```
app/
  config.py                 env settings
  schemas/internal.py       Customer model
  services/crm.py           Airtable: lookup_by_phone(), write_interaction()
  api/dependencies.py       X-Vapi-Secret auth
  api/routers/tools.py      POST /tools/lookup-claim
  api/routers/webhooks.py   POST /webhooks/vapi/end-of-call
  main.py                   app + /health
test_crm.py                 phone-normalization check
SETUP.md                    Airtable schema + VAPI config + system prompt
```

Verified (no live telephony needed yet): unit test passes, app imports,
TestClient confirms 401 on bad secret, correct `results` shape on tool call,
type-gating on end-of-call. Locked stack: Gemini 2.5 Flash (Phase 2), ngrok dev.

**Next (user actions):** create/seed Airtable, fill `.env`, run uvicorn + ngrok,
configure the VAPI assistant per `SETUP.md`, place a live test call. Then Phase 2.

Env note: upgraded to **Python 3.12.13** (Homebrew `python3.12`); venv recreated,
`requirements.txt` now installs clean (incl. mcp/anthropic/websockets). `SETUP.md`
pins `python3.12 -m venv`. Phase 1 runtime still only needs
fastapi/uvicorn/pydantic-settings/requests; rest are Phase 2 / speculative.

## Logging / monitoring touchpoints (graded deliverable)

stdlib `logging`, configured in `main.py`. Touchpoints:
- `dependencies.py` — WARNING on rejected (bad-secret) requests
- `tools.py` — INFO per lookup: call id, **masked** phone (`***last4`), found/not-found
- `webhooks.py` — INFO on end-of-call received + ignored non-report events
- `crm.py` — INFO on interaction written; `logger.exception` on Airtable failures

Phone numbers are masked to last-4 in logs (PII). Verified output live.

**Per-call log files** (`app/logging_setup.py`): a contextvar holds the current
`call.id` (set at the top of each endpoint); `PerCallFileHandler` routes every
module's log line for that request into `log/<callId>.log` — so one file per
call holds its tool lookup + write-back + Airtable logs. Console output kept for
dev. Call id is filename-sanitized (external input). Verified: two calls → two
separate, correctly-grouped files.

**Call tracing (values + errors):** `tools.py` logs the tool name, the phone
VAPI sent, and its source (`tool-arg` vs `caller-id`), then the found result;
`crm.py` logs the matched name, or on a miss the `target` vs every scanned
`candidate` (all masked `***last4`) so mismatches are obvious. Airtable errors
are caught in `tools.py` and returned to VAPI as a graceful "unavailable"
result instead of a 500. Lookup is fully server-side — VAPI POSTs the tool
webhook, our server queries Airtable and returns the result string; VAPI never
touches Airtable.

## Phase 2 · S2 (CRM/Memory) + S3 (Logging/Tracing) — deep-planned

`progress-phase2.json` is the source of truth; this is the narrative. S1, S2, S3
are now deep-planned and ready to build V1 (they hook into the S1 orchestration
loop, which is built first). S4 still has only V1/V2 scope.

**One SQLite DB does S2 + S3 + S4** (`data/conversations.db`, stdlib `sqlite3`,
no new dep, WAL, per-op connection — the same open/write/close idiom as the
per-call log handler). Chosen over JSONL/Airtable for queryability: cross-call
memory reads, and S4 metrics become SQL instead of a log-parser.

- **Store division.** Airtable *Interactions* stays the CRM-visible business
  record (name, summary, sentiment, timestamp), reused verbatim. SQLite is the
  engineering substrate: transcript + per-turn trace + memory. Both written at
  call end; `turns` written per turn during the call.
- **Three tables.** `calls` (one row/call: identity, claim_id, summary+sentiment
  from S4, `vapi_transcript`, timing, `escalated`), `messages` (structured
  history — what the model processed, incl. tool calls), `turns` (S3 trace).
- **Transcript, belt-and-suspenders.** `vapi_transcript` string (authoritative
  spoken record from the end-of-call-report) *and* structured `messages` rows.

**S2 — cross-call memory is V1** (headline demo pulled forward). At call start,
`recent_calls_by_phone(digits)` builds a memory block injected into the S1.2
dynamic context. It's **two-tier and gated**, mirroring the identity gate:
recognition (name + prior-call count + last-call date) pre-verification; recall
(prior summaries) only after `identity_verified=true`; **claim_status never**
enters memory. Same renderer-as-gate that withholds claim data — a phone-spoofed
caller can't hear prior claim details. Persist path extends the reused
`/webhooks/vapi/end-of-call`.

**S3 — two channels.** Human-readable INFO lines to the reused
`log/<callId>.log` (Phase 1 `PerCallFileHandler` + `call_id_var` + masked
phones, unchanged); machine-readable per-turn trace to the SQLite `turns` table.
Trace row is written *after* the SSE stream closes, so it's off the
user-perceived latency path.

- **Metrics locked (V1).** Per turn: turn/LLM latency, prompt/completion/total
  tokens, tool calls `[{name,status,latency}]`, phase before→after,
  current_intent, identity_verified, error_type. Per call (derivable):
  num_turns, total tokens, duration, `escalated` (containment), final_phase,
  sentiment.
- **Tokens.** LiteLLM `usage`. resolve-then-stream gives tool-resolution usage
  for free; the final stream uses `stream_options={"include_usage":True}`;
  `litellm.token_counter` is the fallback. *Build-verify* Gemini actually
  returns usage on the final chunk. ([LiteLLM usage](https://docs.litellm.ai/docs/completion/usage))
- **No tracing library** in V1 — stdlib `time.perf_counter` + a small span
  helper. OpenTelemetry/dashboards/cost/percentiles are V2.

Still to build-verify (unchanged from handoff): VAPI end-of-call transcript
field path; that in-memory state is still resident (same worker) at webhook time.

## Phase 2 · S4 (Post-processing + Metrics/ROI) — deep-planned

**Post-processing is ours, synchronous, in the webhook** (P2-D3). Instead of
VAPI's `analysisPlan`, the extended `/webhooks/vapi/end-of-call` makes one
LiteLLM Gemini call and gets `{summary, sentiment, resolution_status,
primary_topic}` back on a **flat** structured-output schema (`response_format`
json_schema + `enable_json_schema_validation`; flat because nested Pydantic can
400 on Gemini; prompt-and-parse fallback → S1.6 `llm_error` tier). This also
*removes* the Phase 1 async-analysis timing problem — we own the call, so no
`GET /call/{id}` polling. `summary`+`sentiment` → Airtable `write_interaction`
(reused); all four → SQLite `calls` row.

- **Same webhook, two phases.** Branch on whether in-memory state exists for
  `call.id`: present → Phase 2 → our post-processing; absent → Phase 1 → keep the
  existing VAPI-analysis path. Fallback demo stays untouched.
- **Containment is code-derived, not the LLM.** `escalated` on the calls row
  (final_phase `escalating` or an S1.6 repeat-tier hit) drives containment. The
  LLM's `resolution_status` is descriptive only — never trust the model for the
  headline metric.

**Metrics compute pulled into V1** (P2-D7). `app/metrics.py` = pure `sqlite3`
SQL aggregates over the shared DB, no pandas: containment rate, avg handle time,
avg turns, total tokens + est. cost, sentiment/resolution distributions, tool
success rate, avg turn/LLM latency. Prints a report; `python -m app.metrics`.
Cheap because S2/S3 already populate `calls` + `turns`.

**ROI writeup** = `METRICS.md` for the panel: metric→ROI mapping (containment →
deflected calls → agent-hours saved; token cost → per-call margin; latency →
throughput) plus the **prompt-tuning feedback loop** — `primary_topic`×escalated
finds topics to fix in the FAQ/prompt; slow tool latency → S1.4 V2 streaming
work; negative-sentiment transcripts → tone fixes. Skeleton now, numbers after
live calls.

Build-verify at build: gemini-2.5-flash json_schema returns valid output (flat
schema); current gemini-2.5-flash token price for the cost metric (don't
hardcode from memory).

> **Phase 2 planning is complete — all four sections (S1–S4) are deep-planned
> and ready to build V1.** Build order: S1 orchestration loop → S2 SQLite store
> → S3 turn trace → S4 post-processing + metrics. No Phase 2 code written yet.

## Phase 2 · V1 — BUILT (turn 25)

All four sections are code-complete. The brain lives in `app/agent/`
(`state.py`, `prompts.py`, `tools.py`, `loop.py`, `knowledge.py`) behind
`POST /vapi/chat/completions` (`app/api/routers/chat.py`). One SQLite DB
(`app/services/store.py`) carries S2/S3/S4; post-processing is
`app/services/postprocess.py`; metrics `app/metrics.py`; ROI writeup `METRICS.md`;
acceptance harness `harness.py`.

**Verified.** `python harness.py` — the deterministic safety checks pass
(renderer-as-gate withholds claim_status until `identity_verified`, confirm_identity
flip, 2nd-denial escalation, no-record/CRM-error/FAQ fallbacks, SSE shape). A full
offline plumbing run (HTTP→SSE tool loop, S2/S3 SQLite writes, S4 post-processing +
metrics, with LiteLLM and Airtable stubbed) passes end-to-end.

**Build-time facts (web-verified per CLAUDE.md).** litellm 1.92.0; model id
`gemini/gemini-2.5-flash`; tool-calling is standard OpenAI shape; S4 structured
output via `response_format={"type":"json_object","response_schema":<flat>}`; price
$0.30/1M in, $2.50/1M out.

**One deliberate change from the plan.** The final answer is streamed by *chunking
the resolved string* (one generation per turn), **not** `stream_options.include_usage`
— Gemini has a known `content:None` bug with that flag. Completion tokens come from
`litellm.token_counter` (the plan's fallback, now primary). Real token-streaming with
tool interception remains the #1 V2 item. Post-processing runs synchronously
(`litellm.completion`) because the end-of-call webhook is a sync handler.

**Live-Gemini E2E — PASSED.** `python harness.py --live` runs 3 real Gemini turns
(greet → `lookup_claim` → `confirm_identity` → gated status reveal) with Airtable
stubbed. The renderer-as-gate held: no claim_status before verification. The live run
caught two real bugs, now fixed:
- litellm's `acompletion` lazily imports its MCP handler, which needs **`orjson`**
  (not auto-installed) — would have broken *every* server turn. Added to requirements.
- the harness live path didn't call `store.init_db()` — fixed.

`confirm_identity(confirmed=True)` now returns the claim_status *in its tool result*
(only reachable when confirmed, same gate) so the agent reveals it on the same turn as
verification instead of the next — the per-turn context is built pre-flip. The
renderer-as-gate still governs every subsequent turn.

**Repo reorg.** Docs + data JSON moved to `docs/` (TASK, VAPI_ARCHITECTURE_DOC, SETUP,
METRICS, progress*, handoffs, faqs.json, fallbacks.json); `knowledge.py` loads the FAQ/
fallback JSON from `docs/`. Kept at root: `CLAUDE.md` (project-instructions convention)
and `skills-lock.json` (tooling lockfile).

**Only pending:** a real VAPI dashboard telephony call (Model → Custom LLM → URL
`{BASE}/vapi/chat/completions`, header `X-Vapi-Secret`; see the Phase 2 section of
`docs/SETUP.md`). The VAPI end-of-call transcript field path is read defensively
(`msg.transcript || msg.artifact.transcript`) — confirm on a real report.

## VAPI credentials — which is which

- **Webhook auth (VAPI→us):** our own `VAPI_SECRET`, set as `server.secret` in VAPI,
  received as `X-Vapi-Secret`. Not any of the VAPI keys.
- **Private key:** server→VAPI API (Phase 2 polling `GET /call/{id}`). In `.env`.
- **Public key:** client SDK only — unused here.
- **Assistant id / phone number:** configured in the VAPI dashboard, not in `.env`.
