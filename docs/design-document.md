> **Note:** This document uses the working title "Voice Bridge." The project's final name is **Medak**.

**VOICE BRIDGE**

Comprehensive Design Document

*AI Emergency Relay System for Deaf and Speech-Impaired Users*

| Field          | Value                 |
|----------------|-----------------------|
| Version        | 1.0 — Hackathon Build |
| Date           | March 2026            |
| Status         | In Development        |
| Authors        | Voice Bridge Team     |
| Classification | Internal / Technical  |

# 1. Executive Summary

Voice Bridge is a caller-side AI proxy that enables deaf and speech-impaired people to contact emergency services (112) independently. When a user presses the SOS button, the system gathers emergency details through an accessible conversational interface, then calls 112 on their behalf via VoIP, speaking fluently to the dispatcher while relaying responses back to the user in real time.

The system uses two Google Gemini Live agents coordinated by a deterministic orchestrator. It is designed for production deployment but is scoped here for a 48-hour hackathon demonstration using a simulated dispatch endpoint.

> **Problem statement**
>
> Deaf and speech-impaired people cannot call 112 in Serbia or most of Europe. There is no text-to-112 infrastructure. The EU mandates full accessibility compliance by 2027. This system bridges the gap on the caller side, requiring no changes to existing dispatch infrastructure.

## 1.1 Scope of this document

This document covers system architecture, agent design, data models, API contracts, infrastructure, security, and the demo implementation plan. It is intended as a complete implementation reference for the engineering team.

# 2. System Overview

## 2.1 High-level architecture

The system consists of four primary components: a React Native mobile app, a FastAPI backend, two Gemini Live agent sessions, and a Redis-backed shared state store. The mobile app triggers the session; the backend hosts the orchestrator and manages agent lifecycles; agents communicate exclusively through the shared state object, never directly with each other.

| Component | Technology | Role |
|----|----|----|
| Mobile app | React Native | SOS trigger, mic/GPS/sensor input, accessible UI |
| Backend | Python / FastAPI | HTTP API, WebSocket hub, orchestrator host, Twilio gateway |
| User Agent | Gemini 2.0 Flash Live | Passive triage via microphone and camera; surfaces optional yes/no questions; user may tap or type but is not required to |
| Dispatch Agent | Gemini 2.0 Flash Live | Voice call to 112 operator via Twilio VoIP |
| Shared state | Redis (versioned JSON) | Single source of truth for all agents and orchestrator |

## 2.2 Design principles

- **Sequential phases, not parallel agents.** The User Agent runs alone during triage. The Dispatch Agent spawns only when confidence reaches threshold or a 10-second timeout fires. The primary information sources are microphone audio and camera feed — the system never depends on user input. Optionally, the User Agent may surface a single contextual yes/no question on screen; the user can tap a preset or type freely, but silence is a valid response. This guarantees the first words spoken to 112 are accurate.

- **Snapshot is the protocol.** Agents do not message each other. They read and write a versioned JSON object in Redis. Cross-agent question-and-answer flows through named arrays in this object.

- **Orchestrator is not an agent.** No LLM is involved in phase transitions. The orchestrator is deterministic code. This eliminates a failure mode and reduces latency at the most critical moment.

- **Reconnection is first-class.** Every agent reconnects by fetching the current snapshot version and resuming. The session survives mobile network drops.

- **FAILED state has a defined escape hatch.** If all automated paths fail, an SMS is dispatched to 112 with raw GPS coordinates and emergency type. The user is instructed to seek help manually.

## 2.3 Session phases

| Phase | Description |
|----|----|
| INTAKE | SOS received. GPS and device data parsed. Snapshot initialised in Redis. Duration: \<2 seconds. |
| TRIAGE | User Agent active. Passively gathers information from microphone audio and camera feed. User may optionally tap a preset (YES/NO/HELP) or type a response to a surfaced question, but no input is required. Orchestrator polls confidence every second. Duration: up to 10 seconds. |
| LIVE_CALL | Both agents active. Dispatch Agent connected to 112. User Agent continues to field operator questions relayed through snapshot. Duration: variable. |
| RESOLVED | Dispatch confirmed. ETA written to snapshot. User notified. Both agents shut down gracefully. |
| FAILED | Unrecoverable error after all retries. SMS fallback fired. User instructed to seek manual help. |

# 3. Shared State Model

The EmergencySnapshot is the central data structure of the system. It is stored in Redis with a TTL of one hour and a monotonically incrementing version number. All writes go through a read-modify-write helper that increments the version and recomputes the confidence score atomically.

## 3.1 EmergencySnapshot schema

| Field | Type | Description |
|----|----|----|
| session_id | UUID | Unique per SOS event. Survives agent reconnects. Written by orchestrator on INTAKE. |
| phase | Enum | INTAKE \| TRIAGE \| LIVE_CALL \| RESOLVED \| FAILED. Written exclusively by orchestrator. |
| snapshot_version | int | Incremented on every write. Used by reconnecting agents to resume without restarting. |
| created_at | float (Unix) | Epoch timestamp of session creation. Used for 10-second triage timeout. |
| location.lat / lng | float | GPS coordinates from device on SOS trigger. Written by orchestrator from SOS payload. |
| location.address | string? | Reverse-geocoded address. |
| location.confirmed | bool | True only after User Agent tool call explicitly confirms address with user. |
| emergency_type | Enum | MEDICAL \| FIRE \| POLICE \| GAS \| OTHER. Written by User Agent. |
| victim_count | int? | Number of people needing help. Written by User Agent. Null until confirmed. |
| conscious | bool? | Victim consciousness. Null until confirmed. Dispatch Agent can request re-check. |
| breathing | bool? | Victim breathing. Same lifecycle as conscious. |
| free_text_details | string\[\] | Raw user utterances appended in order. Read by Dispatch Agent for context. |
| user_input | UserInput\[\]? | Optional. Each entry is { question, response_type: TAP\|TEXT, value }. Null if user did not interact. Small confidence boost (+0.05 per entry). Never depended on as a primary source. |
| input_conflicts | Conflict\[\]? | Populated when user input contradicts environment inference. Each entry is { field, env_value, user_value }. Passed to Dispatch Agent as a note; does not block triage progression. |
| confidence_score | float 0–1 | Computed by orchestrator from field completeness after every User Agent write. |
| dispatch_questions | string\[\] | Questions operator asked that Dispatch Agent could not answer from snapshot. |
| ua_answers | string\[\] | User Agent answers to dispatch questions. Format: 'question\|answer' per entry. |
| call_status | Enum | IDLE \| DIALING \| CONNECTED \| CONFIRMED \| DROPPED. Written by Dispatch Agent. |
| eta_minutes | int? | Set by Dispatch Agent when operator confirms dispatch. Pushed to mobile UI. |

## 3.2 Confidence scoring

The confidence score is computed deterministically from field completeness. It is not an LLM output. The orchestrator recalculates it after every User Agent write.

```python
score = 0.0
if location and location.confirmed: score += 0.35
elif location: score += 0.20  # GPS only, not verbally confirmed
if emergency_type: score += 0.25
if conscious is not None: score += 0.15
if breathing is not None: score += 0.15
if victim_count is not None: score += 0.10
if user_input: score += 0.05 * min(len(user_input), 2)  # cap at +0.10
# Dispatch Agent spawns when score >= 0.85 OR elapsed >= 10 seconds
# User input contributes at most +0.10 to score (capped at 2 responses x +0.05)
```

# 4. Orchestrator

The orchestrator is a backend process, not an AI agent. It contains no language model calls. It is responsible for session initialisation, phase transitions, agent lifecycle management, reconnection, and the failure fallback. One orchestrator instance exists per active session.

## 4.1 Responsibilities

- Receive the SOS payload from the HTTP handler and initialise the EmergencySnapshot in Redis

- Spawn the User Agent Gemini Live session and monitor confidence

- Trigger the Dispatch Agent when confidence threshold is met or triage timeout fires

- Monitor call_status for CONFIRMED or DROPPED

- Retry the Dispatch Agent up to three times with exponential backoff on failure

- Transition to RESOLVED on dispatch confirmation and notify the mobile UI

- Transition to FAILED after all retries are exhausted, fire the SMS fallback, and notify the mobile UI

## 4.2 Phase transition logic

Phase transitions are triggered by deterministic conditions, never by model output. The following table summarises each transition.

| From | To | Condition |
|----|----|----|
| — | INTAKE | SOS HTTP request received |
| INTAKE | TRIAGE | Snapshot initialised in Redis (immediate) |
| TRIAGE | LIVE_CALL | confidence_score \>= 0.85, OR 10 seconds elapsed since session start |
| LIVE_CALL | RESOLVED | call_status == CONFIRMED in snapshot |
| LIVE_CALL | FAILED | Dispatch Agent fails after 3 reconnect attempts |
| Any | FAILED | Unhandled exception in orchestrator run loop |

## 4.3 Reconnection strategy

When the Dispatch Agent session drops, the orchestrator retries with exponential backoff. On each reconnect attempt, the agent fetches the current snapshot_version and resumes the call context from the snapshot fields rather than restarting the conversation from scratch.

```
attempt 1: retry after 2 seconds
attempt 2: retry after 4 seconds
attempt 3: retry after 8 seconds
after 3 failures: transition to FAILED, fire SMS fallback
```

# 5. User Agent

The User Agent is a Gemini 2.0 Flash Live session that observes the user’s environment via microphone and camera. The primary information path is passive — the system never requires the user to respond. Optionally, the agent may surface one contextual yes/no question on screen at a time; the user can tap a preset (YES / NO / HELP) or type a free-text response. If no input arrives, the agent continues from environment data alone. Its sole job is to extract structured emergency information as quickly as possible and relay a coherent brief to the Dispatch Agent before the 10-second triage window closes.

## 5.1 Conversation strategy

The agent operates primarily in listen-and-observe mode. It extracts whatever the user articulates or whatever the camera feed reveals, and writes to the snapshot immediately as fields are inferred. In parallel, it may surface one contextual yes/no question at a time on the mobile UI — chosen based on what the environment data cannot yet resolve. User responses receive a small confidence boost (+0.05 per response, capped at +0.10 total). If a user response contradicts an environment inference, the conflict is written to input_conflicts and passed to the Dispatch Agent as an advisory note; triage is never paused waiting for resolution.

| Priority | Information target |
|----|----|
| 1 | Address confirmation — pre-filled from GPS |
| 2 | Emergency type — fire, medical, police, gas leak, other |
| 3 | Victim count — how many people need help |
| 4 | Consciousness — is the victim conscious |
| 5 | Breathing — is the victim breathing |
| Interrupt | Any question queued in dispatch_questions by the Dispatch Agent |

## 5.2 Tool set

The User Agent is given eight tools. Each tool maps directly to a write operation on the EmergencySnapshot. The model is instructed to call tools immediately when information is confirmed, not at the end of the conversation.

| Tool | Action |
|----|----|
| confirm_location(address) | Marks location.confirmed = True and updates address. Confidence +0.15 delta. |
| set_emergency_type(type) | Writes emergency_type enum. Triggers largest single confidence jump. |
| set_clinical_fields(conscious, breathing, victim_count) | Writes any combination of clinical fields. All parameters optional. |
| append_free_text(utterance) | Appends raw user utterance to free_text_details for Dispatch Agent context. |
| get_pending_dispatch_question() | Returns the next unanswered question from dispatch_questions, or NONE. |
| answer_dispatch_question(question, answer) | Appends question\|answer to ua_answers. Dispatch Agent polls this. |
| surface_user_question(question) | Pushes a yes/no question to the mobile UI. Renders as a prompt with YES / NO preset buttons and a free-text field. Only one question may be active at a time. If unanswered after 5 seconds, the UI dismisses it silently. |
| record_user_input(response_type, value) | Appends a UserInput entry to user_input in the snapshot. Applies +0.05 confidence boost. If value contradicts an existing environment-inferred field, writes a Conflict entry to input_conflicts instead of overwriting. |

## 5.3 System prompt summary

The system prompt instructs the agent to: operate in observation-first mode with no expectation of user response, infer emergency type and clinical state from ambient audio and camera context, extract any spoken utterances immediately, surface at most one contextual yes/no question at a time via surface_user_question when environment data is ambiguous, treat user input as supplementary and never block on it, and never speculate beyond what is directly observed or confirmed.

> **Key instruction**
>
> The agent is explicitly told: 'Never say I am an AI. Say I am your emergency relay assistant.' This reduces user friction and avoids confusion about who is speaking.

# 6. Dispatch Agent

The Dispatch Agent is a Gemini 2.0 Flash Live session connected to the 112 operator via Twilio VoIP. It speaks on behalf of the user. It identifies itself as an automated relay service on the first sentence, delivers a structured emergency brief, and handles operator questions using the snapshot as its knowledge base. When the operator asks something it cannot answer, it queues the question for the User Agent and waits. If the snapshot contains entries in input_conflicts, the Dispatch Agent notes these to the operator as unresolved discrepancies rather than asserting either value as fact.

## 6.1 Opening brief

On call connect, the agent delivers a fixed opening structure before the operator speaks. This is injected as initial context in the ADK session.

> "This is an automated emergency relay call on behalf of a person who cannot
> speak. I have their emergency details and will answer your questions."
>
> Then immediately:
> - Emergency type and severity
> - Location / address
> - Number of victims
> - Consciousness and breathing status
> - Any additional details from free_text_details

## 6.2 Tool set

| Tool | Action |
|----|----|
| get_emergency_brief() | Reads snapshot and returns structured brief. Called at session start and on reconnect. |
| queue_question_for_user(question) | Writes operator question to dispatch_questions. Called when snapshot cannot answer. |
| get_user_answer(question) | Polls ua_answers for a matching answer. Returns PENDING if not yet available. |
| update_call_status(status) | Writes call_status enum. Used to signal CONNECTED, DROPPED etc. to orchestrator. |
| confirm_dispatch(eta_minutes) | Writes CONFIRMED status and ETA. Triggers RESOLVED phase transition via orchestrator poll. |

## 6.3 Cross-agent Q&A flow

When the operator asks a question the Dispatch Agent cannot answer from the snapshot, the following sequence occurs:

1. Dispatch Agent says to operator: 'One moment, I am checking with the caller.'
2. Dispatch Agent calls queue_question_for_user(question).
3. User Agent's next get_pending_dispatch_question() call returns the question.
4. User Agent asks the user and calls answer_dispatch_question(question, answer).
5. Dispatch Agent polls get_user_answer(question) every 2 seconds.
6. Once answer is available, Dispatch Agent speaks it to the operator.

> **Latency target**
>
> The end-to-end round trip for this Q&A cycle should complete in under 5 seconds under normal network conditions. The 2-second poll interval is intentional — tight enough to feel responsive, loose enough not to saturate Redis.

# 7. Mobile Application

The mobile app is the user's only interface during an emergency. It is built in React Native to support both iOS and Android. The UI is designed for high-stress, low-dexterity use: large tap targets, high contrast, minimal text, and haptic feedback for all state transitions.

## 7.1 SOS trigger

The SOS button is displayed prominently on the home screen. A deliberate confirmation step (press and hold for 1.5 seconds, or press twice within 0.5 seconds) prevents accidental triggers. On trigger, the app immediately bundles a payload and POSTs to /api/sos.

```json
// SOS payload
{
  "lat": "float",       // from device GPS
  "lng": "float",
  "address": "string?", // reverse-geocoded if available within 2 seconds
  "user_id": "string",  // pre-registered user identifier
  "device_id": "string" // for session continuity
}
```

## 7.2 Session WebSocket

After receiving session_id from /sos, the app opens a WebSocket to /api/session/{id}/ws. This connection carries:

| Direction | Content |
|----|----|
| App → Backend | Base64-encoded PCM audio frames from microphone (16kHz, mono) |
| App → Backend | Ping messages for keepalive |
| Backend → App | JSON transcript events: { speaker, text, session_id } |
| Backend → App | JSON status events: { type: RESOLVED\|FAILED, eta_minutes, message } |

## 7.3 Accessible UI states

| Phase | UI presentation |
|----|----|
| INTAKE / connecting | Pulsing red SOS indicator. Large text: 'Connecting...' Haptic pulse every 1.5s. |
| TRIAGE | Full-screen transcript of User Agent observations. Large text, high contrast. Mic indicator active. Optional: a contextual yes/no prompt may appear at the bottom with YES / NO preset buttons and a free-text field. Dismisses automatically after 5 seconds if unanswered. |
| LIVE_CALL | Split view: call status top ('Talking to 112'), transcript bottom. Status badge: yellow 'Call in progress'. |
| RESOLVED | Green full-screen confirmation. Large text: 'Help is on the way — ETA X minutes.' Strong haptic burst. |
| FAILED | Red screen. Large text: 'Automatic call failed.' Instructions: 'Ask someone nearby to call 112.' Location displayed for reference. |

## 7.4 Sensor data collected on trigger

- GPS coordinates (primary location source)

- Reverse-geocoded address (if available within 2 seconds of trigger)

- Microphone audio stream (forwarded to User Agent)

- Camera — active during triage for scene context inference (victim state, environment type). Also reserved for future sign language recognition.

- Accelerometer data — reserved for automatic fall detection triggering

# 8. API Contracts

## 8.1 HTTP endpoints

### POST /api/sos

Trigger a new emergency session. Returns immediately with session_id. All further work is asynchronous.

```
Request body:
{ lat, lng, address?, user_id, device_id }

Response 200:
{ session_id: string, status: 'TRIAGE' }

Response 429:
{ error: 'Rate limit exceeded' }  // max 3 SOS per device per hour
```

### GET /api/session/{id}/status

Poll current session state. Useful for the mobile app when the WebSocket is unavailable.

```
Response 200:
{ session_id, phase, confidence, call_status, eta_minutes, snapshot_version }

Response 404:
{ error: 'Session not found' }
```

### POST /api/session/{id}/twilio/audio

Receive operator audio from Twilio and return queued agent audio. Simplified polling endpoint for the demo. Replaced by a full Twilio Media Streams WebSocket in production.

```
Request body:
{ audio: base64_encoded_pcm_string }

Response 200:
{ audio_chunks: string[] }  // base64 PCM chunks to pipe back to Twilio
```

### GET /api/health

```
Response 200:
{ status: 'ok', active_sessions: int }
```

## 8.2 WebSocket protocol

The WebSocket at /api/session/{id}/ws uses JSON messages in both directions.

| Direction | Message type | Fields |
|----|----|----|
| Client → Server | audio | { type: 'audio', data: base64_pcm } |
| Client → Server | ping | { type: 'ping' } |
| Server → Client | transcript | { type: 'transcript', speaker: 'assistant'\|'user', text: string } |
| Server → Client | status | { type: 'STATUS_UPDATE', phase: string, confidence: float } |
| Server → Client | pong | { type: 'pong' } |
| Server → Client | RESOLVED | { type: 'RESOLVED', eta_minutes: int, message: string } |
| Server → Client | FAILED | { type: 'FAILED', message: string } |

# 9. Infrastructure

## 9.1 Runtime dependencies

| Dependency | Purpose |
|----|----|
| Python 3.11+ | Backend runtime |
| FastAPI + uvicorn | ASGI HTTP server and WebSocket host |
| google-adk \>= 0.4 | Agent Development Kit for Gemini Live session management |
| google-genai | Gemini API client |
| redis\[asyncio\] | Async Redis client for shared state |
| Redis 7+ | Shared session state store |
| Twilio Programmable Voice | VoIP call to 112 (or simulated endpoint in demo) |
| React Native 0.73+ | Mobile application |

## 9.2 Environment variables

```bash
GOOGLE_API_KEY=              # Gemini API key
REDIS_URL=                   # redis://localhost:6379
TWILIO_ACCOUNT_SID=          # Twilio credentials (production)
TWILIO_AUTH_TOKEN=           # Twilio credentials (production)
TWILIO_FROM_NUMBER=          # VoIP caller ID
TRIAGE_TIMEOUT_SECONDS=10
CONFIDENCE_THRESHOLD=0.85
RECONNECT_MAX_ATTEMPTS=3
```

## 9.3 Deployment (hackathon)

For the hackathon, the backend runs locally or on a single cloud VM. Redis runs in Docker. The simulated dispatch endpoint is a second FastAPI process on the same machine that plays a scripted dispatcher role, receiving the Twilio call and responding with pre-recorded audio segments.

```bash
# Start Redis
docker run -p 6379:6379 redis:alpine

# Start backend
uvicorn main:app --reload --port 8000

# Start simulated dispatch (demo only)
uvicorn demo_dispatch:app --port 8001
```

# 10. Security and Compliance

## 10.1 Data handling

- All session data in Redis is encrypted at rest using Redis ACL and TLS in transit

- Audio streams are not persisted — they flow through memory only

- GPS coordinates and health information are classified as sensitive personal data under GDPR

- Audit logging and long-term data retention are deferred post-hackathon. Session data lives only in Redis with a 1-hour TTL.

## 10.2 Liability considerations

> **Critical risk**
>
> If the system misparses or hallucinates emergency details, harm could result. The system mitigates this through: (1) verbal confirmation of address before dialling, (2) explicit 'not yet confirmed' phrasing when fields are null, (3) full session audit log, (4) clear identification as an automated relay service on every call.

- The Dispatch Agent is explicitly instructed never to speculate on unconfirmed clinical fields

- All calls begin with a relay service disclosure to the operator

- Users must accept a liability disclaimer on first app launch

- The system is positioned as an assistive relay tool, not a replacement for direct emergency services

## 10.3 EU NG112 compliance path

The EU European Electronic Communications Code requires member states to provide accessible emergency communications by 2027. Voice Bridge operates as a caller-side proxy compatible with existing PSTN/VoIP infrastructure. A production compliance path would include: operator disclosure requirements, relay service registration with national regulatory authority, end-to-end encryption certification, and integration testing with actual 112 PSAP endpoints.

# 11. Demo Implementation Plan

## 11.1 Simulated dispatch endpoint

Since calling real 112 during a hackathon is not permitted, the demo uses a second agent process playing the dispatcher. This process receives the Twilio call, responds with scripted operator audio, and asks three questions in sequence: address confirmation, consciousness check, and dispatch confirmation with ETA.

```
Demo dispatch script:
[0:00] Call connects
[0:02] 'Emergency services, what is the nature of your emergency?'
[0:15] 'Is the patient conscious?'
[0:30] 'We are dispatching an ambulance. Estimated arrival 8 minutes.'
```

## 11.2 Demo scenario

The full demo runs in 10 minutes and is structured to show the three most important moments: the AI parsing panicked input, the live voice call, and the mid-call correction.

| Time | Demo beat |
|----|----|
| 0:00 – 1:00 | Intro. Show the accessible UI. 15-second video of the problem statement. |
| 1:00 – 3:00 | User types: 'father fall stairs not breathing blood head'. Show User Agent parsing in real time. Confidence meter climbing. One clarifying question: 'What is your address?' |
| 3:00 – 4:00 | Confidence hits 0.85. Triage complete. Dispatch Agent dials simulated 112. Audience sees the transition on screen. |
| 4:00 – 7:00 | Live call on speaker. Audience hears the AI speaking to dispatcher. Dispatcher asks 'Is he conscious?' — User Agent asks user — user types 'no eyes closed' — Dispatch Agent incorporates answer within 3 seconds. |
| 7:00 – 8:30 | Green screen. 'Help is on the way — ETA 8 minutes.' Haptic pulse shown on phone. Recap of what just happened technically. |
| 8:30 – 10:00 | Architecture overview. EU 2027 compliance path. Q&A. |

## 11.3 Risk mitigations for demo

- **Latency risk.** Do a full timing dry-run before the demo. If Twilio + Gemini round-trip exceeds 3 seconds, pre-record the dispatcher audio and play it from a local file to control timing.

- **Network risk.** Run backend locally, not on cloud, to eliminate remote network variability. Use USB tethering for the mobile demo device.

- **ASR accuracy risk.** Have a typed-input fallback ready — if the mic input is misrecognised, type the scenario text directly. The system is input-modality agnostic.

- **ADK version risk.** Pin google-adk to the exact version tested. Run 'pip show google-adk' and record the version in requirements.txt.

# 12. Known Risks and Open Questions

## 12.1 Technical risks

| Risk | Severity | Mitigation |
|----|----|----|
| Gemini Live session drops mid-call | High | Reconnect handler with exponential backoff. Session resume via snapshot_version. |
| STT misparses critical detail (e.g. 'blood' → 'flood') | High | User Agent confirms every critical field explicitly before writing to snapshot. Dispatch Agent states 'not confirmed' for null fields. |
| Triage timeout fires with insufficient data | Medium | Dispatch Agent reads free_text_details and presents all raw utterances. Operator can ask follow-up questions via Q&A loop. |
| Twilio VoIP call sounds robotic to dispatcher | Medium | ElevenLabs TTS as alternative to Gemini native voice. Test with simulated dispatcher in advance. |
| Confidence scorer too conservative — never reaches 0.85 | Medium | 10-second timeout is the safety valve. Dispatch Agent reads free_text_details and presents all raw utterances. Operator can ask follow-up questions via Q&A loop. |
| Redis connection lost during active session | Low | FastAPI middleware catches Redis errors and transitions session to FAILED with SMS fallback. |

## 12.2 Open questions

- What happens if the dispatcher puts the call on hold? The Dispatch Agent should detect silence \> 10 seconds and say 'Still here, please proceed.'

- Should the User Agent continue asking questions after the Dispatch Agent connects, or switch to a monitoring-only mode? Current design: continues asking, which risks confusing the user.

- How is the app distributed to users before an emergency? Pre-installation is required — this is a go-to-market problem, not a technical one.

- What language model is used for the confidence scorer in edge cases? Currently deterministic — consider a lightweight classifier for free_text_details analysis.

# 13. Repository Structure

```
voice_bridge/
├── backend/
│   ├── main.py               # FastAPI entry point — HTTP + WebSocket
│   ├── orchestrator.py       # Deterministic session manager
│   ├── user_agent.py         # Gemini Live session — user-facing
│   ├── dispatch_agent.py     # Gemini Live session — 112-facing
│   ├── snapshot.py           # EmergencySnapshot model + Redis helpers
│   └── demo_dispatch.py      # Simulated 112 dispatcher (demo only)
├── mobile/
│   ├── App.tsx               # React Native root
│   ├── screens/
│   │   ├── SOSScreen.tsx     # Main SOS button + status display
│   │   └── TranscriptView.tsx
│   └── services/
│       ├── websocket.ts      # WebSocket connection manager
│       └── audio.ts          # Mic capture + base64 PCM encoding
├── requirements.txt
├── README.md
└── docker-compose.yml        # Redis + backend for local dev
```

*Voice Bridge — Confidential — Hackathon Build*
