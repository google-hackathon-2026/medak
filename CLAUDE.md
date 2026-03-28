# Medak

## Project Overview
Google Hackathon project. Emergency accessibility app for deaf/mute people in Serbia to contact emergency services (112) via AI agents. The system uses two Gemini 2.0 Flash Live agents coordinated by a deterministic orchestrator. The user selects an emergency type (Ambulance, Police, Fire), the system gathers details via mic + camera, then calls a demo number on their behalf via Twilio VoIP — speaking to the dispatcher while relaying responses back in real time.

## User Flow

### Primary flow (manual)
1. User opens app → sees 3 large emergency type buttons (Hitna pomoć, Policija, Vatrogasci)
2. Taps one → GPS captured, emergency type + location sent to backend
3. **INTAKE**: Session initialised, snapshot created in Redis (<2s)
4. **TRIAGE**: User Agent passively observes via mic + camera. Optional yes/no prompts on screen. Up to 10 seconds.
5. Confidence threshold (0.85) reached OR 10s timeout → transition to LIVE_CALL
6. **LIVE_CALL**: Dispatch Agent calls emergency services via Twilio VoIP, speaks on behalf of user
7. User sees live transcript via WebSocket. If operator asks something the AI can't answer, User Agent prompts the user.
8. **RESOLVED**: Dispatch confirmed, ETA displayed. OR **FAILED**: Red screen with manual instructions + SMS fallback.

### Secondary flow (danger detection)
1. User has fall detection or shake-to-SOS enabled in settings (off by default)
2. Phone detects a fall (freefall → impact via accelerometer) or sustained shaking
3. Alarm screen appears with **15-second countdown** and heavy haptic feedback
4. If user does NOT cancel within 15s → auto-triggers SOS (same as tapping an emergency button)
5. If user cancels → returns to previous screen, no call made

## Team
- **Branko** — Frontend (`frontend/`)
- **Filip** — Frontend (`frontend/`)
- **Milan Doslic** — TBD
- **Milan Jovanovic** — Backend (`backend/`)
- **Boris Antonijev** — TBD

## Collaboration Rules
- Frontend devs (Branko, Filip) work only on frontend. Do not write backend or other service code for them.
- If frontend needs something from backend/other services, generate a ready-to-send prompt to forward to the relevant teammate.

## Architecture
- **Two Gemini 2.0 Flash Live agents**: User Agent (passive triage via mic/camera) + Dispatch Agent (voice call to 112 via Twilio VoIP)
- **Deterministic orchestrator** (not an LLM) manages phase transitions based on confidence score
- **Redis** for shared state (EmergencySnapshot — versioned JSON, 1-hour TTL)
- **No PostgreSQL.** Audit logging is deferred post-hackathon.
- **Google-first:** Gemini Live for voice + vision (not separate Cloud TTS/STT)
- **Twilio** for telephony (VoIP outbound calls) — Google has no equivalent product

## Session Phases

| Phase | Description |
|-------|-------------|
| INTAKE | SOS received. GPS and device data parsed. Snapshot initialised in Redis. <2 seconds. |
| TRIAGE | User Agent active. Passively gathers info from mic audio and camera feed. Optional yes/no prompts. Up to 10 seconds. |
| LIVE_CALL | Both agents active. Dispatch Agent connected to 112. User Agent fields operator questions relayed through snapshot. |
| RESOLVED | Dispatch confirmed. ETA written to snapshot. User notified. |
| FAILED | Unrecoverable error after all retries. SMS fallback fired. User instructed to seek manual help. |

## Structure
- `frontend/` — React Native (Expo SDK 54), TypeScript, Expo Router
- `backend/` — Python / FastAPI (Dockerized), deployed on Cloud Run

## API Contract

### Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/sos` | Trigger emergency session |
| `GET` | `/api/session/{id}/status` | Poll session state (WebSocket fallback) |
| `WSS` | `/api/session/{id}/ws` | WebSocket for real-time audio/video/transcript |
| `GET` | `/api/health` | Health check |

### POST /api/sos — Request
```json
{
  "emergency_type": "AMBULANCE | POLICE | FIRE",
  "lat": 44.8176,
  "lng": 20.4633,
  "address": "Knez Mihailova 5, Beograd",
  "user_id": "uuid",
  "device_id": "uuid"
}
```

### POST /api/sos — Response
```json
{ "session_id": "uuid", "status": "TRIAGE" }
```

### GET /api/session/{id}/status — Response
```json
{
  "session_id": "uuid",
  "phase": "TRIAGE",
  "confidence": 0.65,
  "call_status": "IDLE",
  "eta_minutes": null,
  "snapshot_version": 4
}
```

### WebSocket Protocol (WSS /api/session/{id}/ws)

**Client -> Server:**
| Message type | Fields |
|-------------|--------|
| audio | `{ type: 'audio', data: base64_pcm }` — 16kHz mono PCM |
| video_frame | `{ type: 'video_frame', data: base64_jpeg }` — ~1-2fps, 640x480 |
| ping | `{ type: 'ping' }` |
| user_response | `{ type: 'user_response', response_type: 'TAP'\|'TEXT', value: string }` |

**Server -> Client:**
| Message type | Fields |
|-------------|--------|
| transcript | `{ type: 'transcript', speaker: 'assistant'\|'user', text: string }` |
| STATUS_UPDATE | `{ type: 'STATUS_UPDATE', phase: string, confidence: float }` |
| user_question | `{ type: 'user_question', question: string }` — surfaced by User Agent |
| pong | `{ type: 'pong' }` |
| RESOLVED | `{ type: 'RESOLVED', eta_minutes: int, message: string }` |
| FAILED | `{ type: 'FAILED', message: string }` |

## AI Agents (Backend)

### User Agent
Gemini 2.0 Flash Live session. Observes mic audio + camera feed passively. Emergency type is already known (user selected it). Extracts location confirmation, victim count, consciousness, breathing. Writes to EmergencySnapshot via tool calls. May surface one yes/no question at a time on the mobile UI. Never blocks on user input.

### Dispatch Agent
Gemini 2.0 Flash Live session connected to 112 operator via Twilio VoIP. Delivers structured emergency brief on connect. Handles operator questions using snapshot data. Queues unanswerable questions for User Agent via cross-agent Q&A flow.

### Orchestrator
Deterministic Python code (no LLM). Manages phase transitions based on confidence score and timeouts. Handles agent lifecycle, reconnection with exponential backoff (3 attempts), and SMS fallback on total failure.

### Backend Environment Variables
```
GOOGLE_API_KEY
REDIS_URL
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM_NUMBER
EMERGENCY_NUMBER              # Team member's phone for demo, NEVER real 112/194
TRIAGE_TIMEOUT_SECONDS=10
CONFIDENCE_THRESHOLD=0.85
RECONNECT_MAX_ATTEMPTS=3
```

## GCP / Deployment
- **GCP project:** `medak-hackathon`
- **Region:** `us-central1`
- **Backend:** Cloud Run (min-instances=0, max-instances=1, 256Mi, CPU throttling — cheapest settings)
- **Frontend:** React Native app — runs via Expo Go on phones (not deployed to Cloud Run)
- **CI/CD:** GitHub Actions (not Cloud Build)
- **Important:** Backend deploy workflow must be named exactly `Deploy Backend`.
- GitHub secret `GCP_SA_KEY` contains the service account key for deployment.

## Demo Strategy
- **NEVER call real emergency number 112/194.** Use a team member's phone as the "operator."
- Code must reject "112" and "194" as `EMERGENCY_NUMBER` unless explicitly overridden.
- **All 3 emergency types call the same demo number** — in the hackathon there is only one fake operator.
- Simulated dispatch endpoint: a second FastAPI process playing the dispatcher role with scripted responses.
- If Twilio isn't ready: mock call mode with scripted exchange using Gemini + TTS.

## Frontend Notes
- React Native (Expo SDK 54) with TypeScript and Expo Router
- React Native Paper (Material Design 3) dark theme
- Key libs: `expo-location`, `expo-haptics`, `expo-av` (mic), `expo-camera` (camera frames), `expo-crypto` (UUID generation), `expo-sensors` (accelerometer for danger detection)
- WebSocket (native RN API) for real-time session communication
- AsyncStorage for user info + danger detection settings persistence
- Danger detection: fall detection (freefall → impact) and shake-to-SOS via accelerometer, with 15s alarm countdown
- Accessibility: 48x48px min touch targets, high contrast, large fonts, visual+haptic feedback only, Serbian language
