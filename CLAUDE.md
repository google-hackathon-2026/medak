# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Medak** — Google Hackathon emergency accessibility app for deaf/mute people in Serbia. Two Gemini 2.0 Flash Live agents (User Agent for triage, Dispatch Agent for 112 calls) coordinated by a deterministic Python orchestrator. React Native frontend, FastAPI backend, Redis for session state.

Full architecture reference: `docs/design-document.md`

## Common Commands

### Backend (from `backend/`)

```bash
uv sync                                   # Install dependencies (Python 3.13, uv package manager)
uv run uvicorn main:app --host 0.0.0.0 --port 8080   # Run server
uv run pytest                             # Run all tests
uv run pytest tests/test_api.py           # Run single test file
uv run pytest tests/test_orchestrator.py::test_triage_timeout_triggers_live_call  # Run single test
uv run pytest -v                          # Verbose output
```

### Frontend (from `frontend/`)

```bash
npm install                               # Install dependencies
npm start                                 # Start Expo dev server
npm run android                           # Android emulator
npm run ios                               # iOS simulator
```

### Docker (from repo root)

```bash
docker-compose up                         # Start redis + backend + demo-dispatch
docker-compose up -d                      # Detached mode
```

Services: `redis` (port 6379), `backend` (port 8080), `demo-dispatch` (port 8001).

### Environment

Copy `.env.example` to `.env` and fill in values. Backend uses `GOOGLE_API_KEY`, `GOOGLE_CLOUD_PROJECT=proud-quasar-310818`, `REDIS_URL`, Twilio creds, and `EMERGENCY_NUMBER`. Frontend uses `EXPO_PUBLIC_API_URL` (defaults to `http://localhost:8080`).

## Architecture

### Session Flow (Phases)

`INTAKE` → `TRIAGE` → `LIVE_CALL` → `RESOLVED` or `FAILED`

The **orchestrator** (`backend/orchestrator.py`) is deterministic Python (no LLM). It manages phase transitions based on confidence score (threshold 0.85) and timeouts (10s triage). It spawns both agents as async tasks and handles reconnection with exponential backoff (3 attempts).

### Backend Structure

- `main.py` — FastAPI app factory (`create_app()`). App state holds `SnapshotStore` (Redis) and `SessionRegistry` (WebSocket broadcast hub). CORS allows all origins.
- `orchestrator.py` — `SessionOrchestrator` runs the INTAKE→TRIAGE→LIVE_CALL→RESOLVED flow. Spawned as background task on each `/api/sos` call.
- `snapshot.py` — `EmergencySnapshot` (Pydantic model) + `SnapshotStore` (async Redis). Confidence scoring is weighted: location confirmation (+0.35), GPS-only (+0.20), emergency type (+0.25), consciousness (+0.15), breathing (+0.15), victim count (+0.10), user responses (+0.05×min(count,2)).
- `user_agent.py` — Gemini Live session. Passively observes mic/camera. Updates snapshot via tool calls (`confirm_location`, `set_emergency_type`, `set_clinical_fields`).
- `dispatch_agent.py` — Gemini Live session + Twilio VoIP. Delivers emergency brief to 112 operator. Tools: `get_emergency_brief`, `confirm_dispatch`, `set_eta`.
- `demo_dispatch.py` — Separate FastAPI app simulating the 112 dispatcher for demos.
- `config.py` — Pydantic Settings, reads `.env` automatically. Validates that `EMERGENCY_NUMBER` is not real 112/194.

### Frontend Structure

- Expo SDK 54, React 19, TypeScript (strict mode), Expo Router (file-based routing)
- `app/_layout.tsx` — Root layout: PaperProvider (MD3 dark theme) + DangerDetectionProvider
- `app/index.tsx` — Home screen with SOS button (press-and-hold 1.5s)
- `app/session.tsx` — Active session: manages mic/camera streaming, WebSocket, transcript display, phase-based UI
- `app/alarm.tsx` — Full-screen alert modal
- `app/settings.tsx` — User configuration
- `lib/sosFlow.ts` — SOS initiation: captures GPS, calls POST `/api/sos`, returns session ID
- `lib/websocket.ts` — `SessionWebSocket` class with auto-reconnect (exponential backoff, max 3 attempts) and ping/pong keep-alive (15s)
- `lib/theme.ts` — Extended MD3DarkTheme with custom emergency colors (SOS red, triage navy, resolved green, failed red)
- `lib/types.ts` — All shared TypeScript types (phases, WS message unions, API contracts)
- `lib/config.ts` — `API_BASE` from `EXPO_PUBLIC_API_URL` env var

### Testing

Backend uses **pytest** + **pytest-asyncio** (auto mode). Tests use `fakeredis` for Redis mocking and `httpx.ASGITransport` + `AsyncClient` for endpoint testing (no real HTTP). All tests are async.

### API Contract

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/sos` | Trigger emergency session → `{ session_id, status }` |
| `GET` | `/api/session/{id}/status` | Poll session state |
| `WSS` | `/api/session/{id}/ws` | Real-time audio/video/transcript |
| `GET` | `/api/health` | Health check |

### WebSocket Protocol

**Client → Server:** `audio` (base64 PCM 16kHz mono), `video_frame` (base64 JPEG ~1-2fps), `user_response` (TAP/TEXT), `ping`

**Server → Client:** `transcript` (speaker + text), `STATUS_UPDATE` (phase + confidence), `user_question`, `RESOLVED` (eta_minutes), `FAILED`, `pong`

## Team & Collaboration Rules

- **Branko & Filip** — Frontend only (`frontend/`). Do not write backend code for them; generate ready-to-send prompts instead.
- **Milan Jovanovic** — Backend (`backend/`)
- **Milan Doslic, Boris Antonijev** — TBD

## Deployment

- **GCP project:** `medak-hackathon`, region `us-central1`
- **Backend:** Cloud Run (min=0, max=1, 256Mi, CPU throttling)
- **Frontend:** Expo Go on phones (dev), Cloud Run for web export
- **CI/CD:** GitHub Actions. Backend deploy workflow must be named exactly `Deploy Backend`. Secret: `GCP_SA_KEY`.

## Critical Safety Rules

- **NEVER call real 112 or 194.** `EMERGENCY_NUMBER` must be a team member's phone for demos.
- Backend config rejects "112" and "194" as `EMERGENCY_NUMBER` unless explicitly overridden.
- If Twilio isn't ready: use mock call mode with `demo_dispatch.py`.
