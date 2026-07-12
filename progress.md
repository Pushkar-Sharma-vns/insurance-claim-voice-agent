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

Env note: Python 3.9.6 locally → used `from __future__ import annotations`.
`requirements.txt` carries speculative deps (mcp/anthropic/websockets); Phase 1
only needs fastapi/uvicorn/pydantic-settings/requests.

## Logging / monitoring touchpoints (graded deliverable)

stdlib `logging`, configured in `main.py`. Touchpoints:
- `dependencies.py` — WARNING on rejected (bad-secret) requests
- `tools.py` — INFO per lookup: call id, **masked** phone (`***last4`), found/not-found
- `webhooks.py` — INFO on end-of-call received + ignored non-report events
- `crm.py` — INFO on interaction written; `logger.exception` on Airtable failures

Phone numbers are masked to last-4 in logs (PII). Verified output live.

## VAPI credentials — which is which

- **Webhook auth (VAPI→us):** our own `VAPI_SECRET`, set as `server.secret` in VAPI,
  received as `X-Vapi-Secret`. Not any of the VAPI keys.
- **Private key:** server→VAPI API (Phase 2 polling `GET /call/{id}`). In `.env`.
- **Public key:** client SDK only — unused here.
- **Assistant id / phone number:** configured in the VAPI dashboard, not in `.env`.
