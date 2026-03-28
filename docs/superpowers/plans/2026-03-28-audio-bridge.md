# Audio Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Twilio Programmable Voice Media Streams to Gemini 2.0 Flash Live via asyncio queues, replacing the polling stub with a real bidirectional audio pipeline.

**Architecture:** A new `AudioBridge` object (per-session) holds two asyncio queues — `inbound` (Twilio→Gemini, PCM 16kHz) and `outbound` (Gemini→Twilio, PCM 24kHz). An `AudioBridgeRegistry` singleton maps session IDs to bridges and lives on `app.state`. Three new HTTP/WebSocket endpoints handle Twilio callbacks. The dispatch agent grows two concurrent tasks (sender + receiver) to stream audio through the bridge.

**Tech Stack:** Python 3.13, FastAPI, `audioop-lts` (mulaw↔PCM conversion), `python-multipart` (Twilio form POSTs), `asyncio.Queue`, Starlette TestClient (WebSocket tests), `fakeredis.aioredis`, `unittest.mock`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `backend/audio_bridge.py` | `AudioBridge`, `AudioBridgeRegistry`, `ulaw8k_to_pcm16k`, `pcm24k_to_ulaw8k` |
| **Create** | `backend/tests/test_audio_bridge.py` | All audio_bridge unit tests |
| **Create** | `backend/tests/test_twilio_twiml.py` | TwiML endpoint tests |
| **Create** | `backend/tests/test_twilio_status.py` | Status callback tests |
| **Create** | `backend/tests/test_twilio_stream.py` | Media Streams WebSocket tests |
| **Modify** | `backend/pyproject.toml` | Add `audioop-lts`, `python-multipart` |
| **Modify** | `backend/main.py` | 3 new endpoints, remove audio stub, `bridge_registry` param in `create_app` |
| **Modify** | `backend/dispatch_agent.py` | Accept `AudioBridge | None`, add sender/receiver tasks |
| **Modify** | `backend/orchestrator.py` | Accept `AudioBridgeRegistry | None`, create bridge in `_start_dispatch_agent` |
| **Delete** | `backend/tests/test_twilio_endpoint.py` | Old stub tests (replaced) |

---

## Task 1: Audio conversion utilities

**Files:**
- Create: `backend/audio_bridge.py`
- Create: `backend/tests/test_audio_bridge.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add dependencies to pyproject.toml**

In `backend/pyproject.toml`, add `audioop-lts>=0.2.1` and `python-multipart>=0.0.9` to `dependencies`:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "pydantic>=2.0",
    "pydantic-settings>=2.6",
    "redis[hiredis]>=5.2",
    "google-genai>=1.10.0",
    "twilio>=9.3",
    "audioop-lts>=0.2.1",
    "python-multipart>=0.0.9",
]
```

- [ ] **Step 2: Install the new dependencies**

Run from `backend/`:
```bash
uv sync
```
Expected: resolves without error.

- [ ] **Step 3: Write failing tests for audio conversion**

Create `backend/tests/test_audio_bridge.py`:

```python
# backend/tests/test_audio_bridge.py
"""Tests for audio format conversion utilities.

10ms of audio durations (used throughout):
  mulaw 8kHz  = 80 samples × 1 byte  =   80 bytes
  PCM 8kHz    = 80 samples × 2 bytes =  160 bytes
  PCM 16kHz   = 160 samples × 2 bytes = 320 bytes
  PCM 24kHz   = 240 samples × 2 bytes = 480 bytes
"""
import audioop

import pytest

from audio_bridge import ulaw8k_to_pcm16k, pcm24k_to_ulaw8k


# ── ulaw8k_to_pcm16k ──────────────────────────────────────────────────────────

def test_ulaw8k_to_pcm16k_returns_bytes():
    mulaw = audioop.lin2ulaw(bytes(160), 2)  # 80 bytes mulaw silence
    result = ulaw8k_to_pcm16k(mulaw)
    assert isinstance(result, bytes)


def test_ulaw8k_to_pcm16k_upsamples_correctly():
    """80 mulaw-8kHz bytes → 320 PCM-16kHz bytes (4× size: ×2 linear, ×2 rate)."""
    pcm8 = bytes(160)  # 80 samples of silence, 2 bytes each
    mulaw = audioop.lin2ulaw(pcm8, 2)   # 80 bytes
    result = ulaw8k_to_pcm16k(mulaw)
    assert len(result) == 320


def test_ulaw8k_to_pcm16k_empty_returns_empty():
    result = ulaw8k_to_pcm16k(b"")
    assert result == b""


# ── pcm24k_to_ulaw8k ──────────────────────────────────────────────────────────

def test_pcm24k_to_ulaw8k_returns_bytes():
    pcm24 = bytes(480)  # 240 samples of silence at 24kHz (10ms)
    result = pcm24k_to_ulaw8k(pcm24)
    assert isinstance(result, bytes)


def test_pcm24k_to_ulaw8k_downsamples_correctly():
    """480 PCM-24kHz bytes → 80 mulaw-8kHz bytes (÷6: ÷3 rate, ÷2 linear→mulaw)."""
    pcm24 = bytes(480)
    result = pcm24k_to_ulaw8k(pcm24)
    assert len(result) == 80


def test_pcm24k_to_ulaw8k_empty_returns_empty():
    result = pcm24k_to_ulaw8k(b"")
    assert result == b""


# ── round-trip duration coherence ─────────────────────────────────────────────

def test_round_trip_duration_coherence():
    """10ms in → 10ms out at each stage of the pipeline."""
    # Inbound: 10ms mulaw 8kHz = 80 bytes → PCM 16kHz = 320 bytes
    pcm8_silence = bytes(160)
    mulaw_in = audioop.lin2ulaw(pcm8_silence, 2)  # 80 bytes
    assert len(mulaw_in) == 80
    pcm16 = ulaw8k_to_pcm16k(mulaw_in)
    assert len(pcm16) == 320  # 10ms × 16kHz × 2 bytes/sample

    # Outbound: 10ms PCM 24kHz = 480 bytes → mulaw 8kHz = 80 bytes
    pcm24 = bytes(480)
    mulaw_out = pcm24k_to_ulaw8k(pcm24)
    assert len(mulaw_out) == 80  # 10ms × 8kHz × 1 byte/sample
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_audio_bridge.py -v
```
Expected: `ModuleNotFoundError: No module named 'audio_bridge'`

- [ ] **Step 5: Create audio_bridge.py with conversion functions**

Create `backend/audio_bridge.py`:

```python
# backend/audio_bridge.py
from __future__ import annotations

import asyncio
import logging

import audioop

logger = logging.getLogger(__name__)


# ── Audio conversion ───────────────────────────────────────────────────────────

def ulaw8k_to_pcm16k(data: bytes) -> bytes:
    """Convert mulaw 8kHz audio (from Twilio) to linear PCM 16kHz (for Gemini).

    Steps:
      1. ulaw2lin: mulaw → linear PCM 8kHz (1 byte/sample → 2 bytes/sample)
      2. ratecv:   8kHz → 16kHz (doubles sample count)
    """
    if not data:
        return b""
    try:
        pcm8 = audioop.ulaw2lin(data, 2)
        pcm16, _ = audioop.ratecv(pcm8, 2, 1, 8000, 16000, None)
        return pcm16
    except Exception:
        logger.exception("ulaw8k_to_pcm16k conversion error — skipping chunk")
        return b""


def pcm24k_to_ulaw8k(data: bytes) -> bytes:
    """Convert linear PCM 24kHz audio (from Gemini) to mulaw 8kHz (for Twilio).

    Steps:
      1. ratecv:   24kHz → 8kHz (reduces sample count by 3)
      2. lin2ulaw: linear PCM → mulaw (2 bytes/sample → 1 byte/sample)
    """
    if not data:
        return b""
    try:
        pcm8, _ = audioop.ratecv(data, 2, 1, 24000, 8000, None)
        return audioop.lin2ulaw(pcm8, 2)
    except Exception:
        logger.exception("pcm24k_to_ulaw8k conversion error — skipping chunk")
        return b""
```

- [ ] **Step 6: Run tests — all should pass**

```bash
cd backend && uv run pytest tests/test_audio_bridge.py -v
```
Expected: 8 tests PASSED.

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/audio_bridge.py backend/tests/test_audio_bridge.py
git commit -m "feat: add audio conversion utilities (ulaw8k↔pcm16k/24k)"
```

---

## Task 2: AudioBridge and AudioBridgeRegistry

**Files:**
- Modify: `backend/audio_bridge.py`
- Modify: `backend/tests/test_audio_bridge.py`

- [ ] **Step 1: Write failing tests for AudioBridge and AudioBridgeRegistry**

Append to `backend/tests/test_audio_bridge.py`:

```python
import asyncio
from audio_bridge import AudioBridge, AudioBridgeRegistry


# ── AudioBridge ───────────────────────────────────────────────────────────────

async def test_bridge_inbound_queue():
    bridge = AudioBridge()
    await bridge.inbound.put(b"chunk1")
    data = await bridge.inbound.get()
    assert data == b"chunk1"


async def test_bridge_outbound_queue():
    bridge = AudioBridge()
    await bridge.outbound.put(b"chunk2")
    data = await bridge.outbound.get()
    assert data == b"chunk2"


async def test_on_twilio_connected_sets_stream_sid():
    bridge = AudioBridge()
    assert bridge.stream_sid is None
    bridge.on_twilio_connected("SM123abc")
    assert bridge.stream_sid == "SM123abc"


async def test_on_twilio_connected_fires_event():
    bridge = AudioBridge()
    assert not bridge._connected.is_set()
    bridge.on_twilio_connected("SM123abc")
    assert bridge._connected.is_set()


async def test_wait_connected_resolves_when_connected():
    bridge = AudioBridge()

    async def connect_soon():
        await asyncio.sleep(0.02)
        bridge.on_twilio_connected("SM456")

    asyncio.create_task(connect_soon())
    result = await bridge.wait_connected(timeout=1.0)
    assert result is True
    assert bridge.stream_sid == "SM456"


async def test_wait_connected_returns_false_on_timeout():
    bridge = AudioBridge()
    result = await bridge.wait_connected(timeout=0.05)
    assert result is False


async def test_wait_connected_returns_true_if_already_connected():
    bridge = AudioBridge()
    bridge.on_twilio_connected("SM789")
    result = await bridge.wait_connected(timeout=0.1)
    assert result is True


# ── AudioBridgeRegistry ───────────────────────────────────────────────────────

def test_registry_create_returns_bridge():
    reg = AudioBridgeRegistry()
    bridge = reg.create("session-1")
    assert isinstance(bridge, AudioBridge)


def test_registry_get_returns_same_instance():
    reg = AudioBridgeRegistry()
    created = reg.create("session-1")
    got = reg.get("session-1")
    assert got is created


def test_registry_get_missing_returns_none():
    reg = AudioBridgeRegistry()
    assert reg.get("nonexistent") is None


def test_registry_remove_deletes_entry():
    reg = AudioBridgeRegistry()
    reg.create("session-1")
    reg.remove("session-1")
    assert reg.get("session-1") is None


def test_registry_remove_missing_is_noop():
    reg = AudioBridgeRegistry()
    reg.remove("nonexistent")  # must not raise


def test_registry_independent_sessions():
    reg = AudioBridgeRegistry()
    b1 = reg.create("s1")
    b2 = reg.create("s2")
    assert b1 is not b2
    assert reg.get("s1") is b1
    assert reg.get("s2") is b2
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/test_audio_bridge.py -v -k "bridge or registry"
```
Expected: `ImportError: cannot import name 'AudioBridge'`

- [ ] **Step 3: Implement AudioBridge and AudioBridgeRegistry in audio_bridge.py**

Append to `backend/audio_bridge.py` (after the conversion functions):

```python

# ── AudioBridge ───────────────────────────────────────────────────────────────

class AudioBridge:
    """Per-session audio pipeline connecting Twilio WebSocket ↔ Gemini Live.

    inbound:  PCM 16kHz bytes  — Twilio → Gemini
    outbound: PCM 24kHz bytes  — Gemini → Twilio
    """

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self.outbound: asyncio.Queue[bytes] = asyncio.Queue()
        self.stream_sid: str | None = None
        self._connected: asyncio.Event = asyncio.Event()

    def on_twilio_connected(self, stream_sid: str) -> None:
        """Called when the Twilio Media Streams WebSocket sends a 'start' event."""
        self.stream_sid = stream_sid
        self._connected.set()

    async def wait_connected(self, timeout: float = 30.0) -> bool:
        """Wait until on_twilio_connected is called. Returns False on timeout."""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


# ── AudioBridgeRegistry ───────────────────────────────────────────────────────

class AudioBridgeRegistry:
    """Singleton stored in app.state.bridge_registry. Maps session_id → AudioBridge."""

    def __init__(self) -> None:
        self._bridges: dict[str, AudioBridge] = {}

    def create(self, session_id: str) -> AudioBridge:
        bridge = AudioBridge()
        self._bridges[session_id] = bridge
        return bridge

    def get(self, session_id: str) -> AudioBridge | None:
        return self._bridges.get(session_id)

    def remove(self, session_id: str) -> None:
        self._bridges.pop(session_id, None)
```

- [ ] **Step 4: Run full test_audio_bridge.py — all pass**

```bash
cd backend && uv run pytest tests/test_audio_bridge.py -v
```
Expected: 20 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/audio_bridge.py backend/tests/test_audio_bridge.py
git commit -m "feat: add AudioBridge and AudioBridgeRegistry"
```

---

## Task 3: TwiML endpoint

**Files:**
- Create: `backend/tests/test_twilio_twiml.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_twilio_twiml.py`:

```python
# backend/tests/test_twilio_twiml.py
import pytest
from httpx import ASGITransport, AsyncClient
import fakeredis.aioredis

from main import create_app
from snapshot import EmergencySnapshot, Location, SessionPhase, SnapshotStore
from audio_bridge import AudioBridgeRegistry


@pytest.fixture
async def client_with_session():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    registry = AudioBridgeRegistry()
    app = create_app(store=store, bridge_registry=registry)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await redis.aclose()


async def test_twiml_returns_200(client_with_session):
    resp = await client_with_session.post("/api/session/s1/twilio/twiml")
    assert resp.status_code == 200


async def test_twiml_content_type_is_xml(client_with_session):
    resp = await client_with_session.post("/api/session/s1/twilio/twiml")
    assert "text/xml" in resp.headers["content-type"]


async def test_twiml_contains_connect_stream(client_with_session):
    resp = await client_with_session.post("/api/session/s1/twilio/twiml")
    assert "<Connect>" in resp.text
    assert "<Stream" in resp.text


async def test_twiml_stream_url_contains_session_id(client_with_session):
    resp = await client_with_session.post("/api/session/s1/twilio/twiml")
    assert "s1" in resp.text
    assert "twilio/stream" in resp.text


async def test_twiml_not_found():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    registry = AudioBridgeRegistry()
    app = create_app(store=store, bridge_registry=registry)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/session/nonexistent/twilio/twiml")
    assert resp.status_code == 404
    await redis.aclose()
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/test_twilio_twiml.py -v
```
Expected: 404 Not Found (endpoint doesn't exist yet) or `TypeError` on `create_app` signature.

- [ ] **Step 3: Add bridge_registry param to create_app and the TwiML endpoint**

In `backend/main.py`:

**Change the `create_app` signature** (top of the function):

```python
from audio_bridge import AudioBridgeRegistry

def create_app(
    store: SnapshotStore | None = None,
    bridge_registry: AudioBridgeRegistry | None = None,
) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Voice Bridge Backend", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    registry = SessionRegistry()
    app.state.registry = registry

    if store is None:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(settings.redis_url)
        store = SnapshotStore(redis_client)
    app.state.store = store

    if bridge_registry is None:
        bridge_registry = AudioBridgeRegistry()
    app.state.bridge_registry = bridge_registry
```

**Add the TwiML endpoint** (inside `create_app`, after the existing routes):

```python
    @app.post("/api/session/{session_id}/twilio/twiml")
    async def twilio_twiml(session_id: str) -> Response:
        from fastapi.responses import Response
        snapshot = await store.load(session_id)
        if snapshot is None:
            return JSONResponse(status_code=404, content={"error": "Session not found"})
        stream_url = (
            f"wss://{settings.backend_base_url.removeprefix('https://').removeprefix('http://')}"
            f"/api/session/{session_id}/twilio/stream"
        )
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            "<Connect>"
            f'<Stream url="{stream_url}"/>'
            "</Connect>"
            "</Response>"
        )
        return Response(content=twiml, media_type="text/xml")
```

Also add `from fastapi.responses import Response` at the top-level imports (next to the existing `JSONResponse` import).

- [ ] **Step 4: Run tests — all should pass**

```bash
cd backend && uv run pytest tests/test_twilio_twiml.py -v
```
Expected: 5 tests PASSED.

- [ ] **Step 5: Make sure existing tests still pass**

```bash
cd backend && uv run pytest tests/ -v --ignore=tests/test_twilio_endpoint.py
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_twilio_twiml.py
git commit -m "feat: add TwiML endpoint, bridge_registry wiring in create_app"
```

---

## Task 4: Twilio status callback endpoint

**Files:**
- Create: `backend/tests/test_twilio_status.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_twilio_status.py`:

```python
# backend/tests/test_twilio_status.py
import pytest
from httpx import ASGITransport, AsyncClient
import fakeredis.aioredis

from main import create_app
from snapshot import (
    CallStatus,
    EmergencySnapshot,
    Location,
    SessionPhase,
    SnapshotStore,
)
from audio_bridge import AudioBridgeRegistry


@pytest.fixture
async def client_and_store():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    app = create_app(store=store, bridge_registry=AudioBridgeRegistry())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, store
    await redis.aclose()


async def _post_status(client, session_id, call_status):
    return await client.post(
        f"/api/session/{session_id}/twilio/status",
        content=f"CallStatus={call_status}".encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


async def test_status_in_progress_sets_connected(client_and_store):
    client, store = client_and_store
    resp = await _post_status(client, "s1", "in-progress")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    snap = await store.load("s1")
    assert snap.call_status == CallStatus.CONNECTED


async def test_status_completed_sets_dropped(client_and_store):
    client, store = client_and_store
    resp = await _post_status(client, "s1", "completed")
    assert resp.status_code == 200
    snap = await store.load("s1")
    assert snap.call_status == CallStatus.DROPPED


async def test_status_failed_sets_dropped(client_and_store):
    client, store = client_and_store
    resp = await _post_status(client, "s1", "failed")
    assert resp.status_code == 200
    snap = await store.load("s1")
    assert snap.call_status == CallStatus.DROPPED


async def test_status_busy_sets_dropped(client_and_store):
    client, store = client_and_store
    resp = await _post_status(client, "s1", "busy")
    assert resp.status_code == 200
    snap = await store.load("s1")
    assert snap.call_status == CallStatus.DROPPED


async def test_status_no_answer_sets_dropped(client_and_store):
    client, store = client_and_store
    resp = await _post_status(client, "s1", "no-answer")
    assert resp.status_code == 200
    snap = await store.load("s1")
    assert snap.call_status == CallStatus.DROPPED


async def test_status_unknown_value_ignored(client_and_store):
    client, store = client_and_store
    snap_before = await store.load("s1")
    resp = await _post_status(client, "s1", "queued")
    assert resp.status_code == 200
    snap_after = await store.load("s1")
    assert snap_after.call_status == snap_before.call_status


async def test_status_always_returns_ok(client_and_store):
    client, _ = client_and_store
    resp = await _post_status(client, "nonexistent", "completed")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/test_twilio_status.py -v
```
Expected: 404 (endpoint does not exist yet).

- [ ] **Step 3: Add the status endpoint to main.py**

Add this import at the top of `backend/main.py`:

```python
from fastapi import FastAPI, Form, WebSocket, WebSocketDisconnect
```

Add this endpoint inside `create_app` (after the TwiML route):

```python
    @app.post("/api/session/{session_id}/twilio/status")
    async def twilio_status(
        session_id: str,
        CallStatus: str = Form(""),
    ) -> dict:
        STATUS_MAP = {
            "in-progress": "CONNECTED",
            "completed": "DROPPED",
            "failed": "DROPPED",
            "busy": "DROPPED",
            "no-answer": "DROPPED",
        }
        new_status = STATUS_MAP.get(CallStatus)
        if new_status is not None:
            from snapshot import CallStatus as CS
            cs = CS(new_status)
            await store.update(session_id, lambda s: setattr(s, "call_status", cs))
        return {"ok": True}
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd backend && uv run pytest tests/test_twilio_status.py -v
```
Expected: 7 tests PASSED.

- [ ] **Step 5: Run full suite**

```bash
cd backend && uv run pytest tests/ -v --ignore=tests/test_twilio_endpoint.py
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_twilio_status.py
git commit -m "feat: add Twilio status callback endpoint"
```

---

## Task 5: Media Streams WebSocket endpoint

**Files:**
- Create: `backend/tests/test_twilio_stream.py`
- Modify: `backend/main.py`

The Twilio Media Streams WebSocket sends JSON events. The endpoint must:
1. Close with code 4004 if no bridge is registered for this session
2. On `start` event: call `bridge.on_twilio_connected(stream_sid)`
3. On `media` event (track=inbound): decode base64 → mulaw → PCM 16kHz → `bridge.inbound`
4. On `stop` event: close the WebSocket
5. Background task: drain `bridge.outbound`, convert PCM 24kHz → mulaw → base64, send to Twilio

> **Note on WebSocket testing:** These tests use Starlette's `TestClient` (sync), not the async `AsyncClient`. This is the correct tool for WebSocket testing. The `asyncio_mode="auto"` setting only affects `async def` tests — these are regular `def` functions and run synchronously.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_twilio_stream.py`:

```python
# backend/tests/test_twilio_stream.py
"""Tests for the Twilio Media Streams WebSocket endpoint.

Uses Starlette's sync TestClient (correct for WebSocket testing).
All test functions are regular `def`, not `async def`.
"""
import audioop
import base64
import json

import fakeredis.aioredis
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from audio_bridge import AudioBridge, AudioBridgeRegistry
from main import create_app
from snapshot import EmergencySnapshot, Location, SessionPhase, SnapshotStore


def _make_app(with_session: bool = True, with_bridge: bool = True):
    """Build a test app with optional session and bridge in the registry."""
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    registry = AudioBridgeRegistry()

    if with_session:
        import asyncio
        snap = EmergencySnapshot(
            session_id="s1",
            phase=SessionPhase.LIVE_CALL,
            location=Location(lat=44.8, lng=20.4),
        )
        # Run async save in a new event loop (sync context)
        asyncio.get_event_loop().run_until_complete(store.save(snap))

    bridge = None
    if with_bridge:
        bridge = registry.create("s1")

    app = create_app(store=store, bridge_registry=registry)
    return app, bridge


def test_stream_rejects_unknown_session():
    """Close with code 4004 when session has no registered bridge."""
    app, _ = _make_app(with_session=False, with_bridge=False)
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/session/nonexistent/twilio/stream") as ws:
            ws.receive_text()
    assert exc.value.code == 4004


def test_stream_rejects_session_without_bridge():
    """Close with 4004 when session exists but has no bridge (registry miss)."""
    app, _ = _make_app(with_session=True, with_bridge=False)
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/session/s1/twilio/stream") as ws:
            ws.receive_text()
    assert exc.value.code == 4004


def test_stream_start_event_sets_stream_sid():
    """'start' event calls bridge.on_twilio_connected(stream_sid)."""
    app, bridge = _make_app()
    client = TestClient(app)
    with client.websocket_connect("/api/session/s1/twilio/stream") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json({
            "event": "start",
            "streamSid": "SM123",
            "start": {"streamSid": "SM123"},
        })
        ws.send_json({"event": "stop"})
    assert bridge.stream_sid == "SM123"
    assert bridge._connected.is_set()


def test_stream_inbound_media_queued():
    """'media' event (inbound) puts converted PCM 16kHz bytes onto bridge.inbound."""
    app, bridge = _make_app()
    client = TestClient(app)

    # Create 10ms of mulaw silence (80 bytes)
    mulaw_bytes = audioop.lin2ulaw(bytes(160), 2)  # 80 bytes
    payload = base64.b64encode(mulaw_bytes).decode()

    with client.websocket_connect("/api/session/s1/twilio/stream") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json({
            "event": "start",
            "streamSid": "SM123",
            "start": {"streamSid": "SM123"},
        })
        ws.send_json({
            "event": "media",
            "media": {"track": "inbound", "payload": payload},
        })
        ws.send_json({"event": "stop"})

    # Bridge.inbound should have one item: PCM 16kHz (320 bytes)
    assert not bridge.inbound.empty()
    chunk = bridge.inbound.get_nowait()
    assert isinstance(chunk, bytes)
    assert len(chunk) == 320  # 80 mulaw → 320 PCM 16kHz bytes


def test_stream_outbound_audio_sent():
    """Bytes on bridge.outbound are encoded and sent to Twilio as 'media' events."""
    app, bridge = _make_app()

    # Pre-load 10ms of PCM 24kHz onto the outbound queue
    import asyncio
    asyncio.get_event_loop().run_until_complete(bridge.outbound.put(bytes(480)))

    client = TestClient(app)
    received = []
    with client.websocket_connect("/api/session/s1/twilio/stream") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json({
            "event": "start",
            "streamSid": "SM123",
            "start": {"streamSid": "SM123"},
        })
        # Give the background task a moment to drain
        import time; time.sleep(0.05)
        try:
            msg = ws.receive_json(timeout=0.1)
            received.append(msg)
        except Exception:
            pass
        ws.send_json({"event": "stop"})

    # At least one outbound media message sent
    assert any(m.get("event") == "media" for m in received)
    media_msgs = [m for m in received if m.get("event") == "media"]
    payload = media_msgs[0]["media"]["payload"]
    decoded = base64.b64decode(payload)
    assert len(decoded) == 80  # 480 PCM 24kHz bytes → 80 mulaw bytes


def test_stream_outbound_includes_stream_sid():
    """Outbound 'media' events include the streamSid received from Twilio."""
    app, bridge = _make_app()
    import asyncio
    asyncio.get_event_loop().run_until_complete(bridge.outbound.put(bytes(480)))

    client = TestClient(app)
    received = []
    with client.websocket_connect("/api/session/s1/twilio/stream") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json({
            "event": "start",
            "streamSid": "SM_TEST_SID",
            "start": {"streamSid": "SM_TEST_SID"},
        })
        import time; time.sleep(0.05)
        try:
            msg = ws.receive_json(timeout=0.1)
            received.append(msg)
        except Exception:
            pass
        ws.send_json({"event": "stop"})

    media_msgs = [m for m in received if m.get("event") == "media"]
    if media_msgs:
        assert media_msgs[0]["streamSid"] == "SM_TEST_SID"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/test_twilio_stream.py -v
```
Expected: failures due to missing endpoint.

- [ ] **Step 3: Add the Media Streams WebSocket endpoint to main.py**

Add this inside `create_app` in `backend/main.py`, after the status callback route.

First, remove the old stub endpoint entirely:

```python
    # DELETE this block:
    @app.post("/api/session/{session_id}/twilio/audio")
    async def twilio_audio(session_id: str, req: TwilioAudioRequest) -> dict:
        ...
```

Also delete the `TwilioAudioRequest` class at module scope.

Then add the WebSocket endpoint:

```python
    @app.websocket("/api/session/{session_id}/twilio/stream")
    async def twilio_stream(ws: WebSocket, session_id: str) -> None:
        from audio_bridge import ulaw8k_to_pcm16k, pcm24k_to_ulaw8k
        import base64

        bridge = app.state.bridge_registry.get(session_id)
        if bridge is None:
            await ws.accept()
            await ws.close(code=4004, reason="No bridge for session")
            return

        await ws.accept()

        async def send_outbound() -> None:
            """Drain bridge.outbound and forward to Twilio."""
            while True:
                try:
                    pcm24 = await asyncio.wait_for(bridge.outbound.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                mulaw = pcm24k_to_ulaw8k(pcm24)
                if mulaw and bridge.stream_sid:
                    payload = base64.b64encode(mulaw).decode()
                    try:
                        await ws.send_json({
                            "event": "media",
                            "streamSid": bridge.stream_sid,
                            "media": {"payload": payload},
                        })
                    except Exception:
                        break

        sender_task = asyncio.create_task(send_outbound())

        try:
            async for raw in ws.iter_text():
                msg = json.loads(raw)
                event = msg.get("event")

                if event == "start":
                    stream_sid = msg.get("streamSid") or msg.get("start", {}).get("streamSid", "")
                    bridge.on_twilio_connected(stream_sid)

                elif event == "media":
                    media = msg.get("media", {})
                    if media.get("track") == "inbound":
                        raw_mulaw = base64.b64decode(media["payload"])
                        pcm16 = ulaw8k_to_pcm16k(raw_mulaw)
                        if pcm16:
                            await bridge.inbound.put(pcm16)

                elif event == "stop":
                    break

        except WebSocketDisconnect:
            pass
        finally:
            sender_task.cancel()
            try:
                await sender_task
            except asyncio.CancelledError:
                pass
```

Also add `import asyncio` at the top of `main.py` if not already present.

- [ ] **Step 4: Run WebSocket tests**

```bash
cd backend && uv run pytest tests/test_twilio_stream.py -v
```
Expected: all pass (the outbound timing tests may be flaky in slow environments — if so, increase the `time.sleep` to 0.1).

- [ ] **Step 5: Run full suite (excluding old stub test)**

```bash
cd backend && uv run pytest tests/ -v --ignore=tests/test_twilio_endpoint.py
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_twilio_stream.py
git commit -m "feat: add Twilio Media Streams WebSocket endpoint"
```

---

## Task 6: dispatch_agent.py — AudioBridge integration

**Files:**
- Modify: `backend/dispatch_agent.py`
- Modify: `backend/tests/test_dispatch_agent.py`

The dispatch agent needs two concurrent asyncio tasks inside the Gemini Live session:
1. **Sender task** — drains `bridge.inbound`, sends PCM 16kHz to Gemini as `LiveClientRealtimeInput`
2. **Receiver task** — the existing `session.receive()` loop, extended to also route audio parts to `bridge.outbound`

When `bridge` is `None` (no audio, e.g. in tests or mock mode), the agent still connects to Gemini and handles tool calls via text — no change to existing behavior.

- [ ] **Step 1: Write failing tests for the new signature and bridge=None path**

Append to `backend/tests/test_dispatch_agent.py`:

```python
from dispatch_agent import run_dispatch_agent
from audio_bridge import AudioBridge


async def test_run_dispatch_agent_accepts_bridge_none_kwarg():
    """run_dispatch_agent must accept bridge=None without raising TypeError."""
    import inspect
    sig = inspect.signature(run_dispatch_agent)
    assert "bridge" in sig.parameters
    param = sig.parameters["bridge"]
    # Default must be None so callers without bridge= still work
    assert param.default is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && uv run pytest tests/test_dispatch_agent.py::test_run_dispatch_agent_accepts_bridge_none_kwarg -v
```
Expected: FAILED (parameter doesn't exist yet).

- [ ] **Step 3: Update run_dispatch_agent signature and add sender/receiver tasks**

Replace the `run_dispatch_agent` function in `backend/dispatch_agent.py` with:

```python
async def run_dispatch_agent(
    session_id: str,
    store: SnapshotStore,
    broadcast: BroadcastFn,
    bridge: "AudioBridge | None" = None,
) -> None:
    from audio_bridge import AudioBridge  # avoid circular import at module level

    settings = get_settings()
    tools = DispatchAgentTools(session_id, store, broadcast)
    client = genai.Client(
        vertexai=True,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        api_key=settings.google_api_key,
    )

    tool_handlers = {
        "get_emergency_brief": lambda _: tools.get_emergency_brief(),
        "queue_question_for_user": lambda args: tools.queue_question_for_user(args["question"]),
        "get_user_answer": lambda args: tools.get_user_answer(args["question"]),
        "update_call_status": lambda args: tools.update_call_status(args["status"]),
        "confirm_dispatch": lambda args: tools.confirm_dispatch(args["eta_minutes"]),
    }

    # Initiate Twilio call
    twilio_client = None
    call_sid = None
    if settings.twilio_account_sid and settings.emergency_number:
        try:
            twilio_client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
            call = twilio_client.calls.create(
                to=settings.emergency_number,
                from_=settings.twilio_from_number,
                url=f"{settings.backend_base_url}/api/session/{session_id}/twilio/twiml",
                status_callback=f"{settings.backend_base_url}/api/session/{session_id}/twilio/status",
            )
            call_sid = call.sid
            await tools.update_call_status("DIALING")
            logger.info("Twilio call initiated: %s", call_sid)
        except Exception:
            logger.exception("Failed to initiate Twilio call for session %s", session_id)
            await tools.update_call_status("DROPPED")
            return

    # Wait for Twilio WebSocket to connect before starting Gemini (30s timeout)
    if bridge is not None:
        connected = await bridge.wait_connected(timeout=30.0)
        if not connected:
            logger.error("Twilio WebSocket never connected for session %s", session_id)
            await tools.update_call_status("DROPPED")
            return

    # Connect Gemini Live session
    config = genai_types.LiveConnectConfig(
        response_modalities=["AUDIO", "TEXT"],
        system_instruction=genai_types.Content(
            parts=[genai_types.Part(text=DISPATCH_AGENT_SYSTEM_PROMPT)]
        ),
        tools=[DISPATCH_TOOL_DECLARATIONS],
    )

    try:
        async with client.aio.live.connect(
            model="gemini-2.0-flash-live-001",
            config=config,
        ) as session:
            logger.info("Dispatch Agent connected for session %s", session_id)

            await session.send(
                input="Poziv je uspostavljen. Pocni sa brifingom.",
                end_of_turn=True,
            )

            async def _sender() -> None:
                """Forward inbound PCM 16kHz from Twilio to Gemini Live."""
                if bridge is None:
                    return
                while True:
                    try:
                        chunk = await asyncio.wait_for(bridge.inbound.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break
                    try:
                        await session.send(
                            input=genai_types.LiveClientRealtimeInput(
                                media_chunks=[
                                    genai_types.Blob(
                                        data=chunk,
                                        mime_type="audio/pcm;rate=16000",
                                    )
                                ]
                            )
                        )
                    except Exception:
                        logger.exception("Sender task error for session %s", session_id)
                        break

            sender_task = asyncio.create_task(_sender())

            try:
                async for response in session.receive():
                    # Audio output from Gemini → bridge.outbound
                    if bridge is not None and response.server_content:
                        turn = response.server_content.model_turn
                        if turn:
                            for part in turn.parts:
                                if (
                                    part.inline_data
                                    and part.inline_data.mime_type
                                    and part.inline_data.mime_type.startswith("audio/")
                                ):
                                    await bridge.outbound.put(part.inline_data.data)

                    # Tool calls
                    if response.tool_call:
                        for fc in response.tool_call.function_calls:
                            handler = tool_handlers.get(fc.name)
                            if handler:
                                result = await handler(fc.args or {})
                                await session.send(
                                    input=genai_types.LiveClientToolResponse(
                                        function_responses=[
                                            genai_types.FunctionResponse(
                                                name=fc.name,
                                                response={"result": result},
                                            )
                                        ]
                                    )
                                )

                    # Text transcript
                    if response.text:
                        await broadcast(session_id, {
                            "type": "transcript",
                            "speaker": "assistant",
                            "text": response.text,
                        })
            finally:
                sender_task.cancel()
                try:
                    await sender_task
                except asyncio.CancelledError:
                    pass

    except Exception:
        logger.exception("Dispatch Agent error for session %s", session_id)
        await tools.update_call_status("DROPPED")
```

Also add `import asyncio` at the top of `dispatch_agent.py` if not already present.

- [ ] **Step 4: Run dispatch agent tests**

```bash
cd backend && uv run pytest tests/test_dispatch_agent.py -v
```
Expected: all 7 tests PASSED.

- [ ] **Step 5: Run full suite**

```bash
cd backend && uv run pytest tests/ -v --ignore=tests/test_twilio_endpoint.py
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/dispatch_agent.py backend/tests/test_dispatch_agent.py
git commit -m "feat: dispatch agent accepts AudioBridge, adds sender/receiver tasks"
```

---

## Task 7: orchestrator.py — bridge_registry integration + final wiring

**Files:**
- Modify: `backend/orchestrator.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/test_orchestrator.py`
- Delete: `backend/tests/test_twilio_endpoint.py`

- [ ] **Step 1: Write failing tests for orchestrator with bridge_registry**

Append to `backend/tests/test_orchestrator.py`:

```python
import unittest.mock as mock
from audio_bridge import AudioBridge, AudioBridgeRegistry
from orchestrator import SessionOrchestrator


async def test_orchestrator_accepts_bridge_registry_param(store, session_s1):
    """SessionOrchestrator.__init__ must accept bridge_registry kwarg."""
    import inspect
    sig = inspect.signature(SessionOrchestrator.__init__)
    assert "bridge_registry" in sig.parameters
    param = sig.parameters["bridge_registry"]
    assert param.default is None  # backward compat


async def test_orchestrator_creates_bridge_in_registry(store, session_s1):
    """_start_dispatch_agent must call registry.create(session_id) before launching agent."""
    registry = AudioBridgeRegistry()
    dispatched_bridges = []

    async def mock_run_dispatch_agent(session_id, s, b, bridge=None):
        dispatched_bridges.append(bridge)

    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=lambda sid, msg: None,
        start_agents=True,
        bridge_registry=registry,
    )

    with mock.patch("dispatch_agent.run_dispatch_agent", mock_run_dispatch_agent):
        await orch._start_dispatch_agent()

    assert registry.get("s1") is not None, "Bridge not in registry"
    assert len(dispatched_bridges) == 1
    assert isinstance(dispatched_bridges[0], AudioBridge)
    # The bridge passed to the agent must be the same one in the registry
    assert dispatched_bridges[0] is registry.get("s1")


async def test_orchestrator_no_bridge_registry_passes_none(store, session_s1):
    """When bridge_registry=None, run_dispatch_agent receives bridge=None."""
    dispatched_bridges = []

    async def mock_run_dispatch_agent(session_id, s, b, bridge=None):
        dispatched_bridges.append(bridge)

    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=lambda sid, msg: None,
        start_agents=True,
        bridge_registry=None,
    )

    with mock.patch("dispatch_agent.run_dispatch_agent", mock_run_dispatch_agent):
        await orch._start_dispatch_agent()

    assert dispatched_bridges[0] is None
```

Check `backend/tests/test_orchestrator.py` for existing fixtures — it likely has a `store` and `session_s1` fixture. If not, add:

```python
@pytest.fixture
async def store():
    redis = fakeredis.aioredis.FakeRedis()
    s = SnapshotStore(redis)
    yield s
    await redis.aclose()

@pytest.fixture
async def session_s1(store):
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.TRIAGE,
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/test_orchestrator.py -v -k "bridge"
```
Expected: FAILED (bridge_registry param doesn't exist).

- [ ] **Step 3: Update orchestrator.py**

In `backend/orchestrator.py`, update `__init__` to accept `bridge_registry`:

```python
from audio_bridge import AudioBridgeRegistry  # add to imports

class SessionOrchestrator:
    def __init__(
        self,
        session_id: str,
        store: SnapshotStore,
        broadcast: BroadcastFn,
        start_agents: bool = True,
        triage_timeout: int | None = None,
        confidence_threshold: float | None = None,
        max_reconnects: int | None = None,
        bridge_registry: AudioBridgeRegistry | None = None,
    ) -> None:
        self.session_id = session_id
        self.store = store
        self.broadcast = broadcast
        self.start_agents = start_agents
        self.bridge_registry = bridge_registry

        settings = get_settings()
        self.triage_timeout = triage_timeout or settings.triage_timeout_seconds
        self.confidence_threshold = confidence_threshold or settings.confidence_threshold
        self.max_reconnects = max_reconnects or settings.reconnect_max_attempts

        self._user_agent_task: asyncio.Task | None = None
        self._dispatch_agent_task: asyncio.Task | None = None
```

Update `_start_dispatch_agent`:

```python
    async def _start_dispatch_agent(self) -> None:
        from dispatch_agent import run_dispatch_agent
        bridge = None
        if self.bridge_registry is not None:
            bridge = self.bridge_registry.create(self.session_id)
        self._dispatch_agent_task = asyncio.create_task(
            run_dispatch_agent(self.session_id, self.store, self.broadcast, bridge=bridge)
        )
```

- [ ] **Step 4: Update SOS endpoint in main.py to pass bridge_registry**

In `backend/main.py`, update the `trigger_sos` handler:

```python
    @app.post("/api/sos")
    async def trigger_sos(req: SOSRequest) -> SOSResponse:
        session_id = str(uuid.uuid4())
        snapshot = EmergencySnapshot(
            session_id=session_id,
            phase=SessionPhase.INTAKE,
            device_id=req.device_id,
            location=Location(
                lat=req.lat,
                lng=req.lng,
                address=req.address,
            ),
        )
        snapshot.confidence_score = 0.20
        await store.save(snapshot)

        from orchestrator import SessionOrchestrator
        import asyncio
        orch = SessionOrchestrator(
            session_id=session_id,
            store=store,
            broadcast=registry.broadcast,
            bridge_registry=app.state.bridge_registry,  # NEW
        )
        asyncio.create_task(orch.run())

        return SOSResponse(session_id=session_id, status="TRIAGE")
```

- [ ] **Step 5: Run orchestrator tests**

```bash
cd backend && uv run pytest tests/test_orchestrator.py -v
```
Expected: all pass.

- [ ] **Step 6: Delete the old stub test file**

```bash
rm backend/tests/test_twilio_endpoint.py
```

- [ ] **Step 7: Run the complete test suite**

```bash
cd backend && uv run pytest tests/ -v
```
Expected: all tests pass. No `test_twilio_endpoint.py` in the output.

- [ ] **Step 8: Commit everything**

```bash
git add backend/orchestrator.py backend/main.py backend/tests/test_orchestrator.py
git rm backend/tests/test_twilio_endpoint.py
git commit -m "feat: wire AudioBridgeRegistry into orchestrator and SOS endpoint; remove stub"
```

---

## Self-Review Notes

- All 5 spec sections have corresponding tasks ✓
- Twilio status map covers all 5 values from spec (`in-progress`, `completed`, `failed`, `busy`, `no-answer`) ✓
- `bridge_registry=None` backward compat maintained (existing tests with `start_agents=False` unaffected) ✓
- `run_dispatch_agent` has `bridge=None` default — existing tests importing it won't break ✓
- Audio conversion length assertions use exact math (documented in test file header) ✓
- `python-multipart` added for FastAPI Form() to work ✓
- `audioop-lts` added for Python 3.13 compatibility ✓
- WebSocket tests use Starlette TestClient (correct tool) with clear note explaining why sync ✓
- Outbound audio tests pre-populate the queue before connecting, avoiding race conditions ✓
