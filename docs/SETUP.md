# Phase 1 Setup — VAPI-native path

## 1. Airtable

Create a base with two tables.

**Customers**
| Field | Type | Example |
|---|---|---|
| First Name | Single line text | Jane |
| Last Name | Single line text | Doe |
| Phone | Phone / text (E.164) | +14155550100 |
| Claim Status | Single select: Approved / Pending / Requires Documentation | Pending |
| Claim ID | Single line text | CLM-1042 |

Seed ~3 rows. Use **your own phone number** in one row so you can test the live call.

**Interactions**
| Field | Type |
|---|---|
| Caller Name | Single line text |
| Summary | Long text |
| Sentiment | Single select: Positive / Neutral / Negative |
| Timestamp | Single line text (ISO) or Date |

Create a **Personal Access Token** (scopes: `data.records:read`, `data.records:write`; grant the base). Put token + base id in `.env`.

## 2. Backend

```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in values
uvicorn app.main:app --reload --port 8000
```

Expose it publicly (VAPI needs an HTTPS webhook URL). One-time ngrok setup:

```bash
brew install ngrok                       # if not installed
ngrok config add-authtoken 3GPFGC6p3YzuhJSBkf8a5lFAUcX_6KbFhrgeoAyi9RhNYW555  # free token from dashboard.ngrok.com
```

```bash
ngrok http 8000           # note the https URL -> BASE
```

Endpoints:
- `POST {BASE}/tools/lookup-claim` — VAPI tool webhook
- `POST {BASE}/webhooks/vapi/end-of-call` — write-back
- `GET  {BASE}/health`

## 3. VAPI assistant

Layers: **STT** Deepgram Nova-2 · **TTS** ElevenLabs (or 11labs Turbo for latency) · **LLM** GPT-4o-mini or Gemini Flash.

**Tool** (function with server URL):
```json
{
  "type": "function",
  "function": {
    "name": "lookup_claim",
    "description": "Look up a caller's insurance account and claim status by phone number.",
    "parameters": {
      "type": "object",
      "properties": {
        "phone_number": { "type": "string", "description": "Caller's phone number, digits only or E.164" }
      },
      "required": ["phone_number"]
    }
  },
  "server": { "url": "{BASE}/tools/lookup-claim", "secret": "{VAPI_SECRET}" }
}
```

**Server** (end-of-call write-back) on the assistant:
```json
{ "server": { "url": "{BASE}/webhooks/vapi/end-of-call", "secret": "{VAPI_SECRET}" } }
```

**Analysis plan** (VAPI generates summary + sentiment for the write-back):
```json
{
  "analysisPlan": {
    "summaryPrompt": "Summarize the call in 2 sentences: caller intent and outcome.",
    "structuredDataPrompt": "Extract the caller's sentiment and name.",
    "structuredDataSchema": {
      "type": "object",
      "properties": {
        "sentiment": { "type": "string", "enum": ["Positive", "Neutral", "Negative"] },
        "caller_name": { "type": "string" }
      }
    }
  }
}
```
Note: structured data is generated a few seconds after the call ends. If the
write-back shows `Neutral`/`Unknown`, VAPI hadn't finished analysis when the
webhook fired — fallback is intentional; production would poll `GET /call/{id}`.

## 4. System prompt

```
You are Sam, a calm, supportive claims assistant for Observe Insurance.
Keep replies short and natural — this is a phone call.

FLOW:
1. Greet, then ask for the caller's phone number.
2. Call lookup_claim with that number. Then confirm identity:
   "Am I speaking with {first name} {last name}?"
3. On confirmation, share the claim status:
   - Approved: reassure, state it's approved.
   - Pending: it's under review, no action needed yet.
   - Requires Documentation: explain they must submit documents via the portal
     or email support@observeinsurance.com.
4. If no record is found or identity is denied: try alternative verification
   (full name + claim ID), else offer a human callback.

FAQ (answer directly, do not invent):
- Office hours: Mon–Fri, 9am–6pm ET.
- Mailing address: 100 Market St, San Francisco, CA 94105.
- Start a new claim: at observeinsurance.com/claims or by calling this line.

SAFETY:
- Emergency / 911: tell the caller to hang up and dial 911 immediately.
- Human request: confirm a callback will be scheduled.
- Off-topic: politely say you can only help with claims, and steer back.

Never reveal account details before identity is confirmed.
```

First message: "Thanks for calling Observe Insurance, this is Sam. Can I get the phone number on your account to pull up your claim?"

## 5. Test

Assign a VAPI phone number to the assistant, call it, walk the flow, hang up.
Check the Interactions table for a new row.

---

## Phase 2 — Custom LLM (bring-your-own-brain)

Phase 2 swaps only the brain: our server implements the OpenAI-compatible SSE
endpoint VAPI calls each turn. VAPI still owns telephony/STT/TTS. Phase 1 stays
as the fallback demo, untouched.

1. **Env:** set `GEMINI_API_KEY` in `.env` (Gemini 2.5 Flash via LiteLLM).
   Reuses the same `VAPI_SECRET` + Airtable creds as Phase 1.
2. **Install:** `pip install -r requirements.txt` (adds `litellm`).
3. **VAPI dashboard:** Assistant → **Model → Custom LLM**.
   - URL (**auth via query param**): `{BASE}/vapi/chat/completions?secret=<VAPI_SECRET>`
     (e.g. `https://<ngrok>.ngrok.app/vapi/chat/completions?secret=observe_agent_secret_080101`)
   - **Why the query param:** VAPI does NOT forward your secret to a Custom LLM — its
     `Authorization: Bearer` for a custom LLM is a fixed placeholder (`no-custom-llm-key-…`)
     you can't set. So we pass the secret in the URL. `verify_vapi_secret` accepts the shared
     `VAPI_SECRET` from the `?secret=` query param, an `Authorization` header, or `X-Vapi-Secret`.
     (Tradeoff: a URL secret can appear in access/proxy logs — fine for this demo.)
   - The dashboard system-prompt field is **ignored** — our server strips VAPI's
     system message and injects its own static+dynamic prompt.
   - Keep the same **end-of-call webhook** (`{BASE}/webhooks/vapi/end-of-call`, auth via
     `X-Vapi-Secret` = `server.secret`, which VAPI DOES send for server messages); it branches
     to Phase-2 post-processing automatically when it recognizes the call.
4. **Verify before a live call:**
   - `python harness.py` — deterministic safety checks (identity gate, escalation, fallbacks).
   - `python harness.py --live` — real-Gemini E2E happy path (needs `GEMINI_API_KEY`).
5. **After calls:** `python -m app.metrics` for the ROI report (see `METRICS.md`).

State lives in one SQLite DB (`data/conversations.db`) created on startup: `calls`
+ `messages` (transcript/memory) + `turns` (per-turn trace). Single-worker demo
scale — run one uvicorn worker.
