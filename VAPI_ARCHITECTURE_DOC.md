# Vapi Custom LLM Architecture: Division of Labor

This document outlines the system architecture for our AI Claims Support Assistant, specifically detailing the separation of concerns between Vapi's edge infrastructure and our custom FastAPI backend using the Custom LLM integration pattern.

## 1. System Overview

To maintain strict, deterministic control over the agent's state (Greeting, Authentication, Claim Status, Escalation) while delivering a natural conversational experience, we utilize a "Bring Your Own Brain" architecture. Vapi acts as the sensory edge (ears and mouth), while our FastAPI server acts as the central intelligence and state machine.

---

## 2. Vapi's Responsibilities (The "Edge")

Vapi's proprietary infrastructure handles all real-time audio processing and telephony complexities. We do not need to build or manage any of the following components on our server:

### A. Transport & Telephony Layer
* **Call Handling:** Vapi natively manages PSTN calls and SIP trunk integrations, automatically bridging standard phone networks to their servers.
* **Audio Formatting:** Handles the conversion and streaming of raw audio codecs (e.g., 8kHz Mu-Law for telephony).

### B. Speech-to-Text (STT) & Audio Processing
* **Real-time Transcription:** Converts the caller's spoken audio into text instantly.
* **Advanced Endpointing:** Uses a combination of silence detection and machine learning models to detect exactly when the user finishes speaking. 
* **Interruption Detection (Barge-in):** Distinguishes between actual interruptions and natural affirmations (like "uh-huh"). If the user interrupts, Vapi automatically halts the TTS output and clears the audio buffers without any backend intervention.
* **Noise Filtering:** Isolates the primary speaker and removes background noise or echoes.

### C. Text-to-Speech (TTS) & Conversational Fillers
* **Voice Synthesis:** Converts the text streamed from our backend into highly realistic audio.
* **Backchanneling & Fillers:** Vapi's orchestration layer injects natural speech patterns (like "um" or "yeah") to make the AI sound human.

---

## 3. FastAPI Backend Responsibilities (The "Brain")

Because we are overriding Vapi's default language model with our Custom LLM endpoint, our server assumes complete control over the conversation's logic, memory, and data integrations.

### A. Deterministic State Management
* **Call Tracking:** Intercepts the unique `call.id` provided in Vapi's payload to track the caller's progress across interaction turns.
* **Workflow Guardrails:** Enforces the strict sequence required by the assignment (Greeting $\rightarrow$ Authentication $\rightarrow$ Claim Handling). The backend dictates what the AI is allowed to say based on the current state.

### B. Context Engineering & Prompt Injection
* **Dynamic Instructions:** Modifies the system prompt in real-time. For example, if the state is `AUTHENTICATED`, the backend injects the caller's specific claim details into the prompt before sending it to the LLM. 
* **Hallucination Prevention:** Bypasses the LLM entirely for strict FAQ queries, returning hardcoded JSON responses to ensure absolute accuracy for business facts (like office hours).

### C. External Tool Execution (Airtable Integration)
* **Data Retrieval:** Executes local Python functions to query the Airtable `Customers` database based on phone numbers.
* **Logging:** Handles the post-call summary and writes it to the `Interactions` table.

### D. LLM Inference
* **Token Generation:** Interfaces directly with our chosen model (e.g., Gemini 1.5 Flash via API) to generate the conversational text based on our highly controlled, state-aware prompts.

---

## 4. The Communication Protocol: Server-Sent Events (SSE)

Vapi communicates with our backend by treating it as if it were the official OpenAI API.

1. **The Request:** When Vapi's endpointing model detects the user has finished speaking, it packages the conversation history and sends an HTTP POST request to our `/chat/completions` endpoint. This payload mimics the OpenAI format and includes `{stream: true}`.
2. **The Processing:** Our backend analyzes the payload, determines the state, retrieves Airtable data, and prompts our LLM.
3. **The Response Stream:** Instead of waiting for the full LLM response, our FastAPI server streams the generated tokens back to Vapi continuously using **Server-Sent Events (SSE)**.
4. **Playback:** As Vapi receives these SSE tokens, it immediately processes them through the TTS engine, ensuring ultra-low latency.