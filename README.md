# Medak

Emergency accessibility app for deaf/mute people in Serbia to contact emergency services (112) via AI agents. Built for the Google Hackathon.

See [CLAUDE.md](CLAUDE.md) for full architecture, API contract, and agent details.

## Local Development

### Prerequisites

- Docker
- Node.js 18+ and npm
- [ngrok](https://ngrok.com/) with an auth token configured (`ngrok config add-authtoken <token>`)
- GCP Application Default Credentials (`gcloud auth application-default login`)
- [Expo Go](https://expo.dev/go) installed on your phone

### Setup

1. Copy `.env.example` to `.env` and fill in your credentials:
   ```bash
   cp .env.example .env
   # Edit .env — set GOOGLE_API_KEY, Twilio creds, EMERGENCY_NUMBER, BACKEND_BASE_URL
   ```

2. Start backend services (Terminal 1):
   ```bash
   docker compose up --build
   ```
   This starts Redis (6379), Backend (8080), and Demo Dispatch (8001).

3. Start ngrok tunnel (Terminal 2):
   ```bash
   ngrok http 8080 --domain=<your-ngrok-domain>
   ```
   The ngrok URL must match `BACKEND_BASE_URL` in your `.env` so Twilio callbacks reach the backend.

4. Start the frontend (Terminal 3):
   ```bash
   cd frontend
   npm install
   EXPO_PUBLIC_API_URL=https://<your-ngrok-domain> npx expo start
   ```
   `EXPO_PUBLIC_API_URL` tells the phone app where the backend is. Without it, it falls back to a hardcoded LAN IP in `frontend/lib/config.ts`.

5. Open **Expo Go** on your phone, scan the QR code. Phone and laptop must be on the same WiFi. If it won't connect, try `npx expo start --tunnel`.

### Verify

```bash
curl https://<your-ngrok-domain>/api/health
# {"status":"ok","active_sessions":0}
```

### E2E Test Flow

1. Tap an emergency type (Ambulance / Police / Fire)
2. Point the camera at a scene (e.g. a picture of a car crash)
3. The phone set as `EMERGENCY_NUMBER` rings via Twilio
4. Answer — you'll hear the Dispatch Agent speaking on behalf of the user

### Debug Trace Mode

To record every step of the pipeline to disk for post-mortem debugging:

1. Set `DEBUG_TRACE=true` in `.env`
2. Restart the backend (`docker compose up --build`)
3. Run the E2E test flow above
4. After the session ends, inspect the trace:
   ```bash
   ls backend/debug_traces/                              # Find session ID
   open backend/debug_traces/<id>/frames/                # View camera frames
   open backend/debug_traces/<id>/gemini/ua_input_*_image.jpg  # What Gemini saw
   cat backend/debug_traces/<id>/gemini/ua_output_*.json       # Gemini's responses
   cat backend/debug_traces/<id>/dispatch/brief.txt            # Brief sent to operator
   cat backend/debug_traces/<id>/summary.json                  # Full event timeline
   ```

Trace output per session:
| Directory | Contents |
|-----------|----------|
| `frames/` | Every JPEG camera frame received from the phone |
| `audio/` | Every PCM audio chunk from the phone mic |
| `snapshots/` | Snapshot JSON after every mutation (v0, v1, v2...) |
| `gemini/` | All Gemini inputs (text, images) and outputs (tool calls, text) for both agents |
| `tools/` | Each tool call with args and result |
| `ws/` | Full WebSocket message log (JSONL) |
| `dispatch/` | Emergency brief delivered to the dispatch agent |
| `phases/` | Phase transition log |
| `summary.json` | Timeline of all events with counts |

The `debug_traces/` directory is gitignored. Set `DEBUG_TRACE=false` (or remove it) to disable.
