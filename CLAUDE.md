# Medak

## Project Overview
Google Hackathon project. Emergency accessibility app for deaf/mute people in Serbia to contact emergency services ("hitna pomoć") via AI agents. The user describes their emergency through a simple mobile UI, and an AI agent calls emergency services on their behalf — speaking and listening via Google Cloud TTS/STT, with Gemini orchestrating the conversation.

## User Flow
1. User opens app → sees large emergency type buttons (Ambulance, Police, Fire)
2. Selects type → GPS location captured automatically
3. Describes emergency → quick-select chips in Serbian + free text + optional photo
4. Taps "POZOVI" (CALL) → backend receives data + GPS
5. AI calls emergency services → Gemini composes briefing → Twilio places call → Cloud TTS speaks → Cloud STT transcribes operator → Gemini responds → loop
6. User sees live transcript on phone via SSE
7. If AI needs more info → app prompts user to type, AI relays it
8. Call ends → summary displayed

## Team
- **Branko** — Frontend (`frontend/`)
- **Filip** — Frontend (`frontend/`)
- **Milan Doslic** — TBD
- **Milan Jovanovic** — Backend (language TBD)
- **Boris Antonijev** — TBD

## Collaboration Rules
- Frontend devs (Branko, Filip) work only on frontend. Do not write backend or other service code for them.
- If frontend needs something from backend/other services, generate a ready-to-send prompt to forward to the relevant teammate.

## Architecture
- **No database.** All persistence is via AsyncStorage (React Native). Never suggest DB solutions.
- Backend should be stateless or use in-memory/file-based approaches if needed.
- **Google-first:** Use Google Cloud services where possible (Gemini, Cloud TTS, Cloud STT).
- **Twilio** for telephony (outbound voice calls) — Google has no equivalent product.

## Structure
- `frontend/` — React Native (Expo), TypeScript, Expo Router
- `backend/` — Language TBD (Dockerized), deployed on Cloud Run

## API Contract

### Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/calls` | Initiate emergency call |
| `GET` | `/api/calls/{id}/stream` | SSE stream for live call status |
| `POST` | `/api/calls/{id}/input` | User provides additional info during call |
| `GET` | `/api/health` | Cloud Run health check |

### POST /api/calls — Request
```json
{
  "emergencyType": "AMBULANCE | POLICE | FIRE",
  "description": "Free text in Serbian",
  "quickTags": ["TRAFFIC_ACCIDENT", "MULTIPLE_VICTIMS"],
  "location": { "latitude": 44.8176, "longitude": 20.4633, "accuracy": 15.0 },
  "userInfo": { "name": "...", "phone": "+381...", "medicalNotes": "...", "disability": "DEAF" },
  "photoBase64": "optional"
}
```

### POST /api/calls — Response
```json
{ "callId": "uuid", "status": "INITIATING", "streamUrl": "/api/calls/{uuid}/stream" }
```

### SSE Stream Events
```
event: status     → {"status": "CALLING|CONNECTED|COMPLETED", "message": "..."}
event: transcript → {"speaker": "AI|OPERATOR", "text": "..."}
event: needInput  → {"question": "Operator pita da li je pacijent pri svesti?"}
```

### POST /api/calls/{id}/input — Request
```json
{ "text": "Da, pri svesti je" }
```

## AI Agent — Core Call Loop (Backend)
1. **Gemini API** composes initial emergency briefing in Serbian from user data
2. **Twilio Programmable Voice** places outbound call to emergency number
3. **Google Cloud TTS** (voice `sr-RS`) converts AI text → speech, streamed into call
4. **Google Cloud STT** (language `sr-RS`, telephony model) transcribes operator → text
5. **Gemini** processes operator's question, generates response (or asks user via SSE `needInput`)
6. Steps 3-5 loop until call ends

### Backend Environment Variables
```
GEMINI_API_KEY
GOOGLE_APPLICATION_CREDENTIALS
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_PHONE_NUMBER
EMERGENCY_NUMBER          ← Team member's phone for demo, NEVER real 194
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
- **NEVER call real emergency number 194.** Use a team member's phone as the "operator."
- Code must reject "194" as `EMERGENCY_NUMBER` unless explicitly overridden.
- If Twilio isn't ready: mock call mode with scripted exchange using Gemini + TTS + STT.

## Frontend Notes
- React Native (Expo) with TypeScript and Expo Router
- Key libs: `expo-location`, `expo-haptics`, `expo-image-picker`
- AsyncStorage for user info and call history
- SSE (EventSource) for live call transcript
- Accessibility: 48x48px min touch targets, high contrast, large fonts, visual+haptic feedback only, Serbian language
