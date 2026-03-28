# Twilio–Gemini Live Audio Bridge

**Date:** 2026-03-28
**Status:** Approved
**Scope:** Backend only — `backend/` directory

## Goal

Complete the stub at `POST /api/session/{id}/twilio/audio` with a real bidirectional audio pipeline connecting Twilio Programmable Voice (Media Streams) to the Dispatch Agent's Gemini 2.0 Flash Live session.

---

## Architecture

Four pieces are added or changed:

| Piece | Type | Change |
|-------|------|--------|
| `backend/audio_bridge.py` | New file | AudioBridge, AudioBridgeRegistry, audio conversion utilities |
| `backend/main.py` | Modified | 3 new endpoints; AudioBridgeRegistry in `app.state` |
| `backend/dispatch_agent.py` | Modified | Accepts `AudioBridge`; parallel sender/receiver tasks |
| `backend/orchestrator.py` | Modified | Accepts `AudioBridgeRegistry`; creates bridge before placing call |
| `backend/pyproject.toml` | Modified | Add `audioop-lts>=0.2.1` |

---

## Data Flow

```
Twilio WebSocket (inbound)
  │  JSON: {event:"media", media:{track:"inbound", payload:base64_mulaw_8k}}
  ▼
decode base64 → mulaw 8kHz
  │
  ▼ ulaw8k_to_pcm16k()
PCM 16kHz bytes
  │
  ▼ AudioBridge.inbound queue
Dispatch Agent sender task
  │
  ▼ session.send(audio/pcm;rate=16000)
Gemini 2.0 Flash Live
  │
  ▼ session.receive()
  ├─ audio (PCM 24kHz) ──► AudioBridge.outbound queue
  ├─ text ───────────────► broadcast(transcript)
  └─ tool_call ──────────► existing tool handlers
        │
AudioBridge.outbound queue
  │
  ▼ pcm24k_to_ulaw8k()
mulaw 8kHz → base64 encode
  │
  ▼
Twilio WebSocket (outbound)
  │  JSON: {event:"media", streamSid:..., media:{payload:base64_mulaw_8k}}

Status callback (POST /twilio/status):
  in-progress → update_call_status(CONNECTED)
  completed   → update_call_status(DROPPED)
  failed      → update_call_status(DROPPED)
  busy        → update_call_status(DROPPED)
  no-answer   → update_call_status(DROPPED)
```

---

## Audio Conversion

Python 3.13 removed `audioop`. Use `audioop-lts` (drop-in replacement, MIT license).

| Direction | Steps |
|-----------|-------|
| Twilio → Gemini | `audioop.ulaw2lin(data, 2)` → mulaw 8kHz to linear PCM 8kHz<br>`audioop.ratecv(data, 2, 1, 8000, 16000, None)` → upsample to 16kHz |
| Gemini → Twilio | `audioop.ratecv(data, 2, 1, 24000, 8000, None)` → downsample to 8kHz<br>`audioop.lin2ulaw(data, 2)` → linear PCM to mulaw |

---

## Components

### `AudioBridge` (audio_bridge.py)

Per-session audio pipeline object. Created by `_start_dispatch_agent` in the orchestrator before `run_dispatch_agent` is called, registered in `AudioBridgeRegistry` by `session_id`. Passed into `run_dispatch_agent` as a parameter — the function does not own the registry.

```python
class AudioBridge:
    inbound: asyncio.Queue[bytes]   # PCM 16kHz — Twilio → Gemini
    outbound: asyncio.Queue[bytes]  # PCM 24kHz — Gemini → Twilio
    stream_sid: str | None          # set when Twilio WebSocket connects
    _connected: asyncio.Event       # fires when Twilio WS connects

    async def wait_connected(timeout: float = 30.0) -> bool
    def on_twilio_connected(stream_sid: str) -> None
```

### `AudioBridgeRegistry` (audio_bridge.py)

Singleton stored in `app.state.bridge_registry`. Maps `session_id → AudioBridge`.

```python
class AudioBridgeRegistry:
    def create(session_id: str) -> AudioBridge
    def get(session_id: str) -> AudioBridge | None
    def remove(session_id: str) -> None
```

### Audio utilities (audio_bridge.py)

```python
def ulaw8k_to_pcm16k(data: bytes) -> bytes
def pcm24k_to_ulaw8k(data: bytes) -> bytes
```

---

## New Endpoints (main.py)

### `POST /api/session/{id}/twilio/twiml`

Called by Twilio when the outbound call connects. Returns TwiML XML instructing Twilio to open a Media Stream WebSocket.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://{backend_base_url}/api/session/{session_id}/twilio/stream"/>
    </Connect>
</Response>
```

Returns 404 if session not found.

### `POST /api/session/{id}/twilio/status`

Twilio status callback. Updates `call_status` in snapshot:

| Twilio `CallStatus` | Snapshot `call_status` |
|--------------------|----------------------|
| `in-progress` | `CONNECTED` |
| `completed` | `DROPPED` |
| `failed` | `DROPPED` |
| `busy` | `DROPPED` |
| `no-answer` | `DROPPED` |

Returns `{"ok": true}` always (Twilio ignores the body).

### `WSS /api/session/{id}/twilio/stream`

Twilio Media Streams WebSocket. Handles the following Twilio events:

| Event | Action |
|-------|--------|
| `connected` | No-op |
| `start` | Call `bridge.on_twilio_connected(stream_sid)` |
| `media` (track=inbound) | Decode base64, convert ulaw→PCM16k, put on `bridge.inbound` |
| `stop` | Close WebSocket cleanly |

Sends outbound audio by draining `bridge.outbound` in a background task, converting PCM24k→ulaw, base64-encoding, and sending `{"event":"media", "streamSid":..., "media":{"payload":...}}`.

Returns 404 (close with code 4004) if session not found or no bridge registered.

---

## Changes to `dispatch_agent.py`

`run_dispatch_agent` signature changes to:

```python
async def run_dispatch_agent(
    session_id: str,
    store: SnapshotStore,
    broadcast: BroadcastFn,
    bridge: AudioBridge,
) -> None
```

After Gemini Live connects, two concurrent asyncio tasks run inside the session context:

1. **Sender task** — drains `bridge.inbound`, converts PCM 16kHz to Gemini input format, sends via `session.send(LiveClientRealtimeInput(...))`. Runs until session ends or `bridge.inbound` signals done.

2. **Receiver task** — runs `session.receive()` loop:
   - Audio data → `bridge.outbound.put(data)`
   - Text → `broadcast(transcript)`
   - Tool calls → existing tool handler dispatch (unchanged)

The Twilio call is placed before connecting to Gemini Live (unchanged). The bridge is created externally and passed in — `run_dispatch_agent` does not own the registry.

---

## Changes to `orchestrator.py`

`SessionOrchestrator.__init__` gains:

```python
bridge_registry: AudioBridgeRegistry | None = None
```

`_start_dispatch_agent` becomes:

```python
async def _start_dispatch_agent(self) -> None:
    from dispatch_agent import run_dispatch_agent
    bridge = None
    if self.bridge_registry is not None:
        bridge = self.bridge_registry.create(self.session_id)
    self._dispatch_agent_task = asyncio.create_task(
        run_dispatch_agent(self.session_id, self.store, self.broadcast, bridge)
    )
```

`bridge_registry=None` is allowed so existing tests that pass `start_agents=False` continue to work without changes.

---

## Changes to `main.py` SOS endpoint

```python
orch = SessionOrchestrator(
    session_id=session_id,
    store=store,
    broadcast=registry.broadcast,
    bridge_registry=app.state.bridge_registry,  # new
)
```

`app.state.bridge_registry = AudioBridgeRegistry()` is set in `create_app`.

---

## Testing

| Test file | What it covers |
|-----------|---------------|
| `tests/test_audio_bridge.py` | AudioBridge queue flow; `ulaw8k_to_pcm16k` and `pcm24k_to_ulaw8k` round-trip; `wait_connected` timeout; registry create/get/remove |
| `tests/test_twilio_twiml.py` | TwiML endpoint returns 200 with `Content-Type: text/xml`; XML contains `<Stream url=...>`; returns 404 for unknown session |
| `tests/test_twilio_status.py` | `in-progress` → CONNECTED; `completed` → DROPPED; `failed` → DROPPED; unknown status ignored |

The existing `tests/test_twilio_endpoint.py` is removed (the polling stub it tested is replaced).

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Twilio WebSocket never connects (30s timeout) | `wait_connected` returns False; `run_dispatch_agent` sets status DROPPED and returns |
| Gemini Live session drops | Existing reconnect logic in orchestrator handles it; new bridge is created on each reconnect attempt |
| Audio conversion error | Log exception, skip chunk, continue — do not crash the session |
| `bridge_registry` is None (tests / `start_agents=False`) | `run_dispatch_agent` proceeds without audio bridge; Gemini session still connects and handles tool calls via text |
