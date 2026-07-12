# Observe.AI – Take-Home Assessment: AI Agent Demo Architect

## 🎯 Objective
Demonstrate the ability to design, integrate, and optimize a VoiceAI agent from a technical and analytical standpoint. The goal is to build a voice-enabled assistant that simulates a real inbound customer support call, evaluating practical skills in conversational design, workflow logic, data integration, and product reasoning.

---

## 🏢 Scenario: “AI Claims Support Assistant for Observe Insurance”
Build a VoiceAI Agent that handles inbound calls from customers checking on their insurance claim status. 

### Core Capabilities

* **1. Greeting & Authentication:** * Greet the caller and request their phone number.
    * Look up the caller in an external data source (e.g., Airtable, Google Sheets) to find First Name, Last Name, Phone Number, and Claim Status.
    * **Success Path:** Confirm identity ("Am I speaking with {first name} {last name}?").
    * **Fallback Path:** If the record is missing or identity is denied, gracefully attempt alternative verification or escalate to a human.
* **2. Claim Status Handling:** * Retrieve and communicate the claim status (Approved, Pending, or Requires Documentation).
    * If documentation is required, provide clear submission instructions (e.g., portal upload or email to support@observeinsurance.com).
* **3. FAQ Support:** * Answer common questions (office hours, mailing address, how to start a new claim, general process) using a simple internal knowledge base.
* **4. Escalation & Safety Behavior:** * **Human Request:** Politely confirm a callback/transfer will be scheduled.
    * **Emergency (911):** Instruct the caller to hang up and dial 911 immediately.
    * **Off-topic:** Clarify the assistant's scope and guide the conversation back to the task.
* **5. Call Completion & Summary Logging:** * Write a post-call record to an external "Interactions" table.
    * Include: Caller Name (if authenticated), Conversation Summary, Call Sentiment (Positive/Neutral/Negative), and Timestamp.

### 🎭 Persona & Tone
Maintain a calm, supportive, and conversational tone. Accurately interpret questions and respond in a clear, reassuring, human-like manner.

---

## 📦 Deliverables for Panel Presentation

### 1. VoiceAI Agent Build / Demonstration
Build the agent using a preferred framework (Retell, VAPI, LiveKit, etc.) and integration platform. The demo must showcase two specific integrations:
* **Data Retrieval:** Fetch caller information and claim status from an external system using a phone number.
* **Data Write-back:** Log a post-call interaction record (name, summary, sentiment, timestamp) to an external table.

### 2. Solution Architecture Diagram
Provide a brief write-up detailing the conversation flow and system architecture:
* **Voice Flow Steps:** Greeting $\rightarrow$ Authentication $\rightarrow$ API Call $\rightarrow$ Response Handling $\rightarrow$ Fallback.
* **Integration Points:** APIs, data storage, telephony routing, and TTS/STT/LLM layers.
* **Monitoring/Logging:** Identify where errors or metrics are captured.

### 3. Technical Presentation
Prepare to discuss the following topics:
* **Tools & Architecture:** Explain choices for STT, TTS, and LLM, why they were selected, and how the system scales for production.
* **Problem Solving:** Describe one technical challenge encountered and solved, plus one future optimization.
* **Metrics & Evaluation:** Explain how to measure performance and improve ROI (metrics to track, using data for prompt tuning, and fixing drops in containment or increased handle times).