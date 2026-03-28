# Voice Bridge Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete Voice Bridge backend — a FastAPI service with two Gemini 2.0 Flash Live agents (User Agent for triage, Dispatch Agent for 112 calls) coordinated by a deterministic orchestrator, all sharing state through Redis.

**Architecture:** FastAPI handles HTTP + WebSocket. Redis stores versioned EmergencySnapshot JSON (1hr TTL). Orchestrator (pure Python, no LLM) manages phase transitions: INTAKE → TRIAGE → LIVE_CALL → RESOLVED/FAILED. User Agent passively gathers info from mic/camera via Gemini Live. Dispatch Agent calls 112 via Twilio VoIP and speaks to the operator.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, Redis, google-genai (Gemini 2.0 Flash Live), Twilio, pydantic-settings, pytest + fakeredis + httpx for testing.

---

## File Map

| File | Responsibility |
|------|---------------|
| `backend/pyproject.toml` | Dependencies and project config |
| `backend/config.py` | Pydantic settings, env loading, emergency number guard |
| `backend/snapshot.py` | Enums, Pydantic models, confidence scoring, Redis CRUD |
| `backend/main.py` | FastAPI app, HTTP endpoints, WebSocket handler, session registry |
| `backend/orchestrator.py` | Deterministic phase transitions, agent lifecycle, retry logic |
| `backend/user_agent.py` | Gemini Live session for triage — tools that write to snapshot |
| `backend/dispatch_agent.py` | Gemini Live session for 112 call — Twilio VoIP integration |
| `backend/demo_dispatch.py` | Simulated 112 dispatcher (separate FastAPI app, port 8001) |
| `backend/Dockerfile` | Container image for Cloud Run |
| `docker-compose.yml` | Redis + backend + demo-dispatch for local dev |

---

### Task 1: Project Setup and Config

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/config.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_config.py`

- [ ] **Step 1: Write pyproject.toml with all dependencies**

```toml
[project]
name = "voice-bridge-backend"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "pydantic>=2.0",
    "pydantic-settings>=2.6",
    "redis[hiredis]>=5.2",
    "google-genai>=1.10.0",
    "twilio>=9.3",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "httpx>=0.28",
    "fakeredis>=2.26",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: Install dependencies**

Run: `cd backend && uv sync --group dev`
Expected: Clean install, lock file generated.

- [ ] **Step 3: Write failing test for config**

```python
# backend/tests/__init__.py
# (empty)

# backend/tests/test_config.py
import pytest
from config import Settings


def test_settings_loads_defaults():
    s = Settings(
        google_api_key="test-key",
        emergency_number="+381601234567",
    )
    assert s.redis_url == "redis://localhost:6379"
    assert s.triage_timeout_seconds == 10
    assert s.confidence_threshold == 0.85
    assert s.reconnect_max_attempts == 3


def test_settings_rejects_112():
    with pytest.raises(ValueError, match="real emergency"):
        Settings(google_api_key="k", emergency_number="112")


def test_settings_rejects_194():
    with pytest.raises(ValueError, match="real emergency"):
        Settings(google_api_key="k", emergency_number="194")
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: FAIL — `config` module not found.

- [ ] **Step 5: Write config.py**

```python
# backend/config.py
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    google_api_key: str = ""
    redis_url: str = "redis://localhost:6379"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    emergency_number: str = ""
    triage_timeout_seconds: int = 10
    confidence_threshold: float = 0.85
    reconnect_max_attempts: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("emergency_number")
    @classmethod
    def reject_real_emergency_numbers(cls, v: str) -> str:
        if v.strip() in ("112", "194"):
            raise ValueError(
                "Cannot use real emergency numbers (112/194). "
                "Use a team member's phone for demo."
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/config.py backend/tests/
git commit -m "feat(backend): add project config with emergency number guard"
```

---

### Task 2: Domain Models and Confidence Scoring

**Files:**
- Create: `backend/snapshot.py`
- Create: `backend/tests/test_snapshot.py`

- [ ] **Step 1: Write failing tests for models and scoring**

```python
# backend/tests/test_snapshot.py
from snapshot import (
    CallStatus,
    EmergencySnapshot,
    EmergencyType,
    Location,
    SessionPhase,
    UserInput,
    compute_confidence,
)


def test_empty_snapshot_no_location():
    snap = EmergencySnapshot(session_id="s1")
    assert compute_confidence(snap) == 0.0


def test_gps_only():
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
    )
    assert compute_confidence(snap) == 0.20


def test_confirmed_location():
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4, address="Knez Mihailova 5", confirmed=True),
    )
    assert compute_confidence(snap) == 0.35


def test_full_snapshot():
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4, address="Addr", confirmed=True),
        emergency_type=EmergencyType.MEDICAL,
        conscious=False,
        breathing=True,
        victim_count=1,
        user_input=[
            UserInput(question="q1", response_type="TAP", value="DA"),
            UserInput(question="q2", response_type="TAP", value="NE"),
        ],
    )
    # 0.35 + 0.25 + 0.15 + 0.15 + 0.10 + 0.10 = 1.10 -> capped at 1.0
    assert compute_confidence(snap) == 1.0


def test_partial_clinical():
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
        emergency_type=EmergencyType.FIRE,
        conscious=True,
    )
    # 0.20 + 0.25 + 0.15 = 0.60
    assert compute_confidence(snap) == 0.60


def test_user_input_capped_at_two():
    snap = EmergencySnapshot(
        session_id="s1",
        user_input=[
            UserInput(question=f"q{i}", response_type="TAP", value="v") for i in range(5)
        ],
    )
    # 0.05 * min(5, 2) = 0.10
    assert compute_confidence(snap) == 0.10


def test_snapshot_defaults():
    snap = EmergencySnapshot(session_id="s1")
    assert snap.phase == SessionPhase.INTAKE
    assert snap.snapshot_version == 0
    assert snap.call_status == CallStatus.IDLE
    assert snap.confidence_score == 0.0
    assert snap.eta_minutes is None
    assert snap.dispatch_questions == []
    assert snap.ua_answers == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_snapshot.py -v`
Expected: FAIL — `snapshot` module not found.

- [ ] **Step 3: Write snapshot.py with models and scoring**

```python
# backend/snapshot.py
from __future__ import annotations

from enum import StrEnum
from time import time

from pydantic import BaseModel, Field


# --- Enums ---

class SessionPhase(StrEnum):
    INTAKE = "INTAKE"
    TRIAGE = "TRIAGE"
    LIVE_CALL = "LIVE_CALL"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class EmergencyType(StrEnum):
    MEDICAL = "MEDICAL"
    FIRE = "FIRE"
    POLICE = "POLICE"
    GAS = "GAS"
    OTHER = "OTHER"


class CallStatus(StrEnum):
    IDLE = "IDLE"
    DIALING = "DIALING"
    CONNECTED = "CONNECTED"
    CONFIRMED = "CONFIRMED"
    DROPPED = "DROPPED"


# --- Models ---

class Location(BaseModel):
    lat: float | None = None
    lng: float | None = None
    address: str | None = None
    confirmed: bool = False


class UserInput(BaseModel):
    question: str
    response_type: str  # "TAP" or "TEXT"
    value: str


class Conflict(BaseModel):
    field: str
    env_value: str | None = None
    user_value: str | None = None


class EmergencySnapshot(BaseModel):
    session_id: str
    phase: SessionPhase = SessionPhase.INTAKE
    snapshot_version: int = 0
    created_at: float = Field(default_factory=time)
    device_id: str | None = None
    location: Location = Field(default_factory=Location)
    emergency_type: EmergencyType | None = None
    victim_count: int | None = None
    conscious: bool | None = None
    breathing: bool | None = None
    free_text_details: list[str] = Field(default_factory=list)
    user_input: list[UserInput] = Field(default_factory=list)
    input_conflicts: list[Conflict] = Field(default_factory=list)
    confidence_score: float = 0.0
    dispatch_questions: list[str] = Field(default_factory=list)
    ua_answers: list[str] = Field(default_factory=list)
    call_status: CallStatus = CallStatus.IDLE
    eta_minutes: int | None = None


# --- Confidence Scoring ---

def compute_confidence(snapshot: EmergencySnapshot) -> float:
    score = 0.0
    loc = snapshot.location

    if loc.confirmed and loc.address:
        score += 0.35
    elif loc.lat is not None and loc.lng is not None:
        score += 0.20

    if snapshot.emergency_type is not None:
        score += 0.25
    if snapshot.conscious is not None:
        score += 0.15
    if snapshot.breathing is not None:
        score += 0.15
    if snapshot.victim_count is not None:
        score += 0.10

    user_input_bonus = 0.05 * min(len(snapshot.user_input), 2)
    score += user_input_bonus

    return round(min(score, 1.0), 2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_snapshot.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/snapshot.py backend/tests/test_snapshot.py
git commit -m "feat(backend): add EmergencySnapshot model and confidence scoring"
```

---

### Task 3: Redis Snapshot Store

**Files:**
- Modify: `backend/snapshot.py` (add Redis CRUD)
- Create: `backend/tests/test_store.py`

- [ ] **Step 1: Write failing tests for Redis store**

```python
# backend/tests/test_store.py
import pytest
import fakeredis.aioredis

from snapshot import (
    EmergencySnapshot,
    EmergencyType,
    Location,
    SnapshotStore,
)


@pytest.fixture
async def store():
    redis = fakeredis.aioredis.FakeRedis()
    s = SnapshotStore(redis)
    yield s
    await redis.aclose()


async def test_save_and_load(store: SnapshotStore):
    snap = EmergencySnapshot(session_id="s1")
    await store.save(snap)
    loaded = await store.load("s1")
    assert loaded is not None
    assert loaded.session_id == "s1"


async def test_load_missing_returns_none(store: SnapshotStore):
    result = await store.load("nonexistent")
    assert result is None


async def test_update_increments_version(store: SnapshotStore):
    snap = EmergencySnapshot(session_id="s1")
    await store.save(snap)

    def set_type(s: EmergencySnapshot) -> None:
        s.emergency_type = EmergencyType.MEDICAL

    updated = await store.update("s1", set_type)
    assert updated.snapshot_version == 1
    assert updated.emergency_type == EmergencyType.MEDICAL
    assert updated.confidence_score == 0.25  # recomputed


async def test_update_recomputes_confidence(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)

    def confirm_loc(s: EmergencySnapshot) -> None:
        s.location.confirmed = True
        s.location.address = "Test Address"

    updated = await store.update("s1", confirm_loc)
    assert updated.confidence_score == 0.35


async def test_ttl_is_set(store: SnapshotStore):
    snap = EmergencySnapshot(session_id="s1")
    await store.save(snap)
    ttl = await store._redis.ttl("session:s1")
    assert ttl > 0
    assert ttl <= 3600
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_store.py -v`
Expected: FAIL — `SnapshotStore` not found in `snapshot`.

- [ ] **Step 3: Add SnapshotStore to snapshot.py**

Append to `backend/snapshot.py`:

```python
from typing import Callable

import redis.asyncio as aioredis


SNAPSHOT_TTL = 3600  # 1 hour


class SnapshotStore:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}"

    async def save(self, snapshot: EmergencySnapshot) -> None:
        key = self._key(snapshot.session_id)
        await self._redis.set(key, snapshot.model_dump_json(), ex=SNAPSHOT_TTL)

    async def load(self, session_id: str) -> EmergencySnapshot | None:
        data = await self._redis.get(self._key(session_id))
        if data is None:
            return None
        return EmergencySnapshot.model_validate_json(data)

    async def update(
        self,
        session_id: str,
        updater: Callable[[EmergencySnapshot], None],
    ) -> EmergencySnapshot:
        snapshot = await self.load(session_id)
        if snapshot is None:
            raise KeyError(f"Session {session_id} not found")
        updater(snapshot)
        snapshot.confidence_score = compute_confidence(snapshot)
        snapshot.snapshot_version += 1
        await self.save(snapshot)
        return snapshot
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_store.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/snapshot.py backend/tests/test_store.py
git commit -m "feat(backend): add Redis snapshot store with versioned read-modify-write"
```

---

### Task 4: FastAPI App with Health + SOS + Status Endpoints

**Files:**
- Modify: `backend/main.py` (full rewrite)
- Create: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing tests for HTTP endpoints**

```python
# backend/tests/test_api.py
import pytest
from httpx import ASGITransport, AsyncClient
import fakeredis.aioredis

from main import create_app
from snapshot import SnapshotStore


@pytest.fixture
async def client():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    app = create_app(store=store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await redis.aclose()


async def test_health(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "active_sessions" in data


async def test_sos_creates_session(client: AsyncClient):
    resp = await client.post("/api/sos", json={
        "lat": 44.8176,
        "lng": 20.4633,
        "user_id": "u1",
        "device_id": "d1",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["status"] == "TRIAGE"


async def test_sos_with_address(client: AsyncClient):
    resp = await client.post("/api/sos", json={
        "lat": 44.8176,
        "lng": 20.4633,
        "address": "Knez Mihailova 5",
        "user_id": "u1",
        "device_id": "d1",
    })
    assert resp.status_code == 200


async def test_session_status(client: AsyncClient):
    # Create session first
    resp = await client.post("/api/sos", json={
        "lat": 44.8, "lng": 20.4, "user_id": "u1", "device_id": "d1",
    })
    sid = resp.json()["session_id"]

    # Poll status
    resp = await client.get(f"/api/session/{sid}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == sid
    assert data["phase"] in ("INTAKE", "TRIAGE")
    assert "confidence" in data
    assert "call_status" in data


async def test_session_status_not_found(client: AsyncClient):
    resp = await client.get("/api/session/nonexistent/status")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: FAIL — `create_app` signature mismatch or module errors.

- [ ] **Step 3: Rewrite main.py**

```python
# backend/main.py
from __future__ import annotations

import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import get_settings
from snapshot import (
    EmergencySnapshot,
    Location,
    SessionPhase,
    SnapshotStore,
)


# --- Request/Response models ---

class SOSRequest(BaseModel):
    lat: float
    lng: float
    address: str | None = None
    user_id: str
    device_id: str


class SOSResponse(BaseModel):
    session_id: str
    status: str


class SessionStatusResponse(BaseModel):
    session_id: str
    phase: str
    confidence: float
    call_status: str
    eta_minutes: int | None
    snapshot_version: int


# --- Session registry for WebSocket broadcast ---

class SessionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def add(self, session_id: str, ws: WebSocket) -> None:
        self._connections.setdefault(session_id, []).append(ws)

    async def remove(self, session_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(session_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._connections.pop(session_id, None)

    async def broadcast(self, session_id: str, message: dict) -> None:
        import json
        raw = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in self._connections.get(session_id, []):
            try:
                await ws.send_text(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.remove(session_id, ws)

    def active_count(self) -> int:
        return len(self._connections)


# --- App factory ---

def create_app(
    store: SnapshotStore | None = None,
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

    # --- Routes ---

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "active_sessions": registry.active_count()}

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
        snapshot.confidence_score = 0.20  # GPS gives base confidence
        await store.save(snapshot)

        # TODO: launch orchestrator as background task (Task 7)

        return SOSResponse(session_id=session_id, status="TRIAGE")

    @app.get("/api/session/{session_id}/status")
    async def session_status(session_id: str) -> SessionStatusResponse:
        snapshot = await store.load(session_id)
        if snapshot is None:
            return JSONResponse(
                status_code=404,
                content={"error": "Session not found"},
            )
        return SessionStatusResponse(
            session_id=snapshot.session_id,
            phase=snapshot.phase,
            confidence=snapshot.confidence_score,
            call_status=snapshot.call_status,
            eta_minutes=snapshot.eta_minutes,
            snapshot_version=snapshot.snapshot_version,
        )

    @app.websocket("/api/session/{session_id}/ws")
    async def session_websocket(ws: WebSocket, session_id: str) -> None:
        snapshot = await store.load(session_id)
        if snapshot is None:
            await ws.close(code=4004, reason="Session not found")
            return

        await ws.accept()
        await registry.add(session_id, ws)

        try:
            while True:
                raw = await ws.receive_text()
                import json
                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))

                elif msg_type == "audio":
                    # TODO: forward to User Agent (Task 8)
                    pass

                elif msg_type == "video_frame":
                    # TODO: forward to User Agent (Task 8)
                    pass

                elif msg_type == "user_response":
                    from snapshot import UserInput
                    await store.update(session_id, lambda s: s.user_input.append(
                        UserInput(
                            question="user_initiated",
                            response_type=msg.get("response_type", "TEXT"),
                            value=msg.get("value", ""),
                        )
                    ))

        except WebSocketDisconnect:
            pass
        finally:
            await registry.remove(session_id, ws)

    return app


app = create_app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: 5 passed.

- [ ] **Step 5: Manual smoke test**

Run: `cd backend && uv run uvicorn main:app --port 8080 --reload`
Then in another terminal: `curl http://localhost:8080/api/health`
Expected: `{"status":"ok","active_sessions":0}` (requires Redis running; skip if no Redis available locally)

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat(backend): add FastAPI app with SOS, status, and WebSocket endpoints"
```

---

### Task 5: Orchestrator

**Files:**
- Create: `backend/orchestrator.py`
- Create: `backend/tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for orchestrator**

```python
# backend/tests/test_orchestrator.py
import asyncio

import pytest
import fakeredis.aioredis

from orchestrator import SessionOrchestrator
from snapshot import (
    CallStatus,
    EmergencySnapshot,
    EmergencyType,
    Location,
    SessionPhase,
    SnapshotStore,
)


@pytest.fixture
async def store():
    redis = fakeredis.aioredis.FakeRedis()
    s = SnapshotStore(redis)
    yield s
    await redis.aclose()


class FakeBroadcaster:
    def __init__(self):
        self.messages: list[dict] = []

    async def __call__(self, session_id: str, message: dict) -> None:
        self.messages.append(message)


async def test_intake_to_triage(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    broadcaster = FakeBroadcaster()

    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=broadcaster,
        start_agents=False,
    )
    # Run just the intake->triage transition
    await orch._transition_to_triage()

    updated = await store.load("s1")
    assert updated.phase == SessionPhase.TRIAGE
    assert any(m.get("type") == "STATUS_UPDATE" for m in broadcaster.messages)


async def test_triage_timeout_triggers_live_call(store: SnapshotStore):
    import time
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
        created_at=time.time() - 15,  # 15 seconds ago
    )
    await store.save(snap)
    broadcaster = FakeBroadcaster()

    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=broadcaster,
        start_agents=False,
        triage_timeout=10,
    )
    should_transition = await orch._check_triage_complete()
    assert should_transition is True


async def test_confidence_threshold_triggers_live_call(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4, address="Addr", confirmed=True),
        emergency_type=EmergencyType.MEDICAL,
        conscious=False,
        breathing=True,
        confidence_score=0.90,
    )
    await store.save(snap)
    broadcaster = FakeBroadcaster()

    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=broadcaster,
        start_agents=False,
    )
    should_transition = await orch._check_triage_complete()
    assert should_transition is True


async def test_confirmed_call_resolves(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.LIVE_CALL,
        call_status=CallStatus.CONFIRMED,
        eta_minutes=8,
    )
    await store.save(snap)
    broadcaster = FakeBroadcaster()

    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=broadcaster,
        start_agents=False,
    )
    result = await orch._check_call_status()
    assert result == "RESOLVED"
    resolved_msgs = [m for m in broadcaster.messages if m.get("type") == "RESOLVED"]
    assert len(resolved_msgs) == 1
    assert resolved_msgs[0]["eta_minutes"] == 8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_orchestrator.py -v`
Expected: FAIL — `orchestrator` module not found.

- [ ] **Step 3: Write orchestrator.py**

```python
# backend/orchestrator.py
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Awaitable

from config import get_settings
from snapshot import (
    CallStatus,
    EmergencySnapshot,
    SessionPhase,
    SnapshotStore,
)

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, dict], Awaitable[None]]


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
    ) -> None:
        self.session_id = session_id
        self.store = store
        self.broadcast = broadcast
        self.start_agents = start_agents

        settings = get_settings()
        self.triage_timeout = triage_timeout or settings.triage_timeout_seconds
        self.confidence_threshold = confidence_threshold or settings.confidence_threshold
        self.max_reconnects = max_reconnects or settings.reconnect_max_attempts

        self._user_agent_task: asyncio.Task | None = None
        self._dispatch_agent_task: asyncio.Task | None = None

    async def run(self) -> None:
        try:
            await self._transition_to_triage()
            await self._run_triage_loop()
            await self._transition_to_live_call()
            await self._run_live_call_loop()
        except Exception:
            logger.exception("Orchestrator error for session %s", self.session_id)
            await self._transition_to_failed("Internal error")

    async def _transition_to_triage(self) -> None:
        await self.store.update(self.session_id, lambda s: setattr(s, "phase", SessionPhase.TRIAGE))
        snap = await self.store.load(self.session_id)
        await self.broadcast(self.session_id, {
            "type": "STATUS_UPDATE",
            "phase": "TRIAGE",
            "confidence": snap.confidence_score,
        })
        logger.info("Session %s: INTAKE -> TRIAGE", self.session_id)

        if self.start_agents:
            await self._start_user_agent()

    async def _run_triage_loop(self) -> None:
        while True:
            if await self._check_triage_complete():
                break
            snap = await self.store.load(self.session_id)
            await self.broadcast(self.session_id, {
                "type": "STATUS_UPDATE",
                "phase": "TRIAGE",
                "confidence": snap.confidence_score,
            })
            await asyncio.sleep(1)

    async def _check_triage_complete(self) -> bool:
        snap = await self.store.load(self.session_id)
        if snap is None:
            return True

        if snap.confidence_score >= self.confidence_threshold:
            logger.info(
                "Session %s: confidence %.2f >= threshold",
                self.session_id, snap.confidence_score,
            )
            return True

        elapsed = time.time() - snap.created_at
        if elapsed >= self.triage_timeout:
            logger.info(
                "Session %s: triage timeout (%.1fs elapsed)",
                self.session_id, elapsed,
            )
            return True

        return False

    async def _transition_to_live_call(self) -> None:
        snap = await self.store.update(
            self.session_id,
            lambda s: setattr(s, "phase", SessionPhase.LIVE_CALL),
        )
        await self.broadcast(self.session_id, {
            "type": "STATUS_UPDATE",
            "phase": "LIVE_CALL",
            "confidence": snap.confidence_score,
        })
        logger.info("Session %s: TRIAGE -> LIVE_CALL", self.session_id)

        if self.start_agents:
            await self._start_dispatch_agent()

    async def _run_live_call_loop(self) -> None:
        reconnect_count = 0
        while True:
            result = await self._check_call_status()
            if result == "RESOLVED":
                return
            if result == "DROPPED":
                reconnect_count += 1
                if reconnect_count > self.max_reconnects:
                    await self._transition_to_failed(
                        "Call failed after all retry attempts"
                    )
                    return
                delay = 2 ** reconnect_count
                logger.warning(
                    "Session %s: call dropped, retry %d in %ds",
                    self.session_id, reconnect_count, delay,
                )
                await asyncio.sleep(delay)
                if self.start_agents:
                    await self._start_dispatch_agent()
            await asyncio.sleep(2)

    async def _check_call_status(self) -> str | None:
        snap = await self.store.load(self.session_id)
        if snap is None:
            return "RESOLVED"

        if snap.call_status == CallStatus.CONFIRMED:
            await self.store.update(
                self.session_id,
                lambda s: setattr(s, "phase", SessionPhase.RESOLVED),
            )
            await self.broadcast(self.session_id, {
                "type": "RESOLVED",
                "eta_minutes": snap.eta_minutes or 0,
                "message": "Pomoć je na putu!",
            })
            logger.info("Session %s: LIVE_CALL -> RESOLVED", self.session_id)
            return "RESOLVED"

        if snap.call_status == CallStatus.DROPPED:
            return "DROPPED"

        return None

    async def _transition_to_failed(self, reason: str) -> None:
        await self.store.update(self.session_id, lambda s: (
            setattr(s, "phase", SessionPhase.FAILED),
        ))
        await self.broadcast(self.session_id, {
            "type": "FAILED",
            "message": reason,
        })
        logger.error("Session %s: -> FAILED: %s", self.session_id, reason)

    async def _start_user_agent(self) -> None:
        from user_agent import run_user_agent
        self._user_agent_task = asyncio.create_task(
            run_user_agent(self.session_id, self.store, self.broadcast)
        )

    async def _start_dispatch_agent(self) -> None:
        from dispatch_agent import run_dispatch_agent
        self._dispatch_agent_task = asyncio.create_task(
            run_dispatch_agent(self.session_id, self.store, self.broadcast)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_orchestrator.py -v`
Expected: 4 passed.

- [ ] **Step 5: Wire orchestrator into main.py SOS endpoint**

In `backend/main.py`, update the `/api/sos` handler to launch the orchestrator:

Replace the `# TODO: launch orchestrator as background task (Task 7)` comment with:

```python
        from orchestrator import SessionOrchestrator
        orch = SessionOrchestrator(
            session_id=session_id,
            store=store,
            broadcast=registry.broadcast,
        )
        import asyncio
        asyncio.create_task(orch.run())
```

- [ ] **Step 6: Run all tests**

Run: `cd backend && uv run pytest -v`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/orchestrator.py backend/tests/test_orchestrator.py backend/main.py
git commit -m "feat(backend): add deterministic orchestrator with phase transitions"
```

---

### Task 6: User Agent (Gemini Live)

**Files:**
- Create: `backend/user_agent.py`
- Create: `backend/tests/test_user_agent.py`

- [ ] **Step 1: Write failing tests for User Agent tool functions**

```python
# backend/tests/test_user_agent.py
import pytest
import fakeredis.aioredis

from snapshot import (
    EmergencySnapshot,
    EmergencyType,
    Location,
    SnapshotStore,
)
from user_agent import UserAgentTools


@pytest.fixture
async def setup():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    messages = []

    async def broadcast(sid, msg):
        messages.append(msg)

    tools = UserAgentTools("s1", store, broadcast)
    yield tools, store, messages
    await redis.aclose()


async def test_confirm_location(setup):
    tools, store, _ = setup
    result = await tools.confirm_location("Knez Mihailova 5, Beograd")
    assert "confirmed" in result.lower()
    snap = await store.load("s1")
    assert snap.location.confirmed is True
    assert snap.location.address == "Knez Mihailova 5, Beograd"


async def test_set_emergency_type(setup):
    tools, store, _ = setup
    result = await tools.set_emergency_type("MEDICAL")
    snap = await store.load("s1")
    assert snap.emergency_type == EmergencyType.MEDICAL


async def test_set_clinical_fields(setup):
    tools, store, _ = setup
    await tools.set_clinical_fields(conscious=False, breathing=True, victim_count=2)
    snap = await store.load("s1")
    assert snap.conscious is False
    assert snap.breathing is True
    assert snap.victim_count == 2


async def test_append_free_text(setup):
    tools, store, _ = setup
    await tools.append_free_text("otac pao niz stepenice")
    snap = await store.load("s1")
    assert "otac pao niz stepenice" in snap.free_text_details


async def test_dispatch_question_flow(setup):
    tools, store, _ = setup
    # Initially no questions
    result = await tools.get_pending_dispatch_question()
    assert result == "NONE"

    # Simulate dispatch agent queuing a question
    await store.update("s1", lambda s: s.dispatch_questions.append("Da li je pri svesti?"))

    # Now there should be a pending question
    result = await tools.get_pending_dispatch_question()
    assert result == "Da li je pri svesti?"

    # Answer it
    await tools.answer_dispatch_question("Da li je pri svesti?", "Ne, nije pri svesti")
    snap = await store.load("s1")
    assert "Da li je pri svesti?|Ne, nije pri svesti" in snap.ua_answers


async def test_surface_user_question(setup):
    tools, _, messages = setup
    await tools.surface_user_question("Da li je pacijent pri svesti?")
    question_msgs = [m for m in messages if m.get("type") == "user_question"]
    assert len(question_msgs) == 1
    assert question_msgs[0]["question"] == "Da li je pacijent pri svesti?"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_user_agent.py -v`
Expected: FAIL — `user_agent` module not found.

- [ ] **Step 3: Write user_agent.py**

```python
# backend/user_agent.py
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from google import genai
from google.genai import types as genai_types

from config import get_settings
from snapshot import (
    EmergencyType,
    SnapshotStore,
    UserInput,
)

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, dict], Awaitable[None]]


class UserAgentTools:
    """Tool implementations that modify the EmergencySnapshot."""

    def __init__(
        self,
        session_id: str,
        store: SnapshotStore,
        broadcast: BroadcastFn,
    ) -> None:
        self.session_id = session_id
        self.store = store
        self.broadcast = broadcast

    async def confirm_location(self, address: str) -> str:
        await self.store.update(self.session_id, lambda s: (
            setattr(s.location, "confirmed", True),
            setattr(s.location, "address", address),
        ))
        return f"Location confirmed: {address}"

    async def set_emergency_type(self, emergency_type: str) -> str:
        et = EmergencyType(emergency_type)
        await self.store.update(self.session_id, lambda s: setattr(s, "emergency_type", et))
        return f"Emergency type set: {et}"

    async def set_clinical_fields(
        self,
        conscious: bool | None = None,
        breathing: bool | None = None,
        victim_count: int | None = None,
    ) -> str:
        def updater(s):
            if conscious is not None:
                s.conscious = conscious
            if breathing is not None:
                s.breathing = breathing
            if victim_count is not None:
                s.victim_count = victim_count

        await self.store.update(self.session_id, updater)
        return "Clinical fields updated"

    async def append_free_text(self, utterance: str) -> str:
        await self.store.update(
            self.session_id,
            lambda s: s.free_text_details.append(utterance),
        )
        return "Text appended"

    async def get_pending_dispatch_question(self) -> str:
        snap = await self.store.load(self.session_id)
        if snap is None:
            return "NONE"
        answered = {a.split("|")[0] for a in snap.ua_answers}
        for q in snap.dispatch_questions:
            if q not in answered:
                return q
        return "NONE"

    async def answer_dispatch_question(self, question: str, answer: str) -> str:
        await self.store.update(
            self.session_id,
            lambda s: s.ua_answers.append(f"{question}|{answer}"),
        )
        return "Answer recorded"

    async def surface_user_question(self, question: str) -> str:
        await self.broadcast(self.session_id, {
            "type": "user_question",
            "question": question,
        })
        return "Question sent to user"

    async def record_user_input(self, response_type: str, value: str) -> str:
        inp = UserInput(question="agent_prompted", response_type=response_type, value=value)
        await self.store.update(
            self.session_id,
            lambda s: s.user_input.append(inp),
        )
        return "User input recorded"


# --- Tool declarations for Gemini ---

TOOL_DECLARATIONS = genai_types.Tool(
    function_declarations=[
        genai_types.FunctionDeclaration(
            name="confirm_location",
            description="Confirm the user's location address. Call when address is verbally confirmed.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"address": genai_types.Schema(type="STRING", description="Confirmed address")},
                required=["address"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="set_emergency_type",
            description="Set the type of emergency: MEDICAL, FIRE, POLICE, GAS, or OTHER.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"emergency_type": genai_types.Schema(type="STRING", enum=["MEDICAL", "FIRE", "POLICE", "GAS", "OTHER"])},
                required=["emergency_type"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="set_clinical_fields",
            description="Set clinical assessment fields. All parameters are optional — set only what is confirmed.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "conscious": genai_types.Schema(type="BOOLEAN", description="Is the victim conscious?"),
                    "breathing": genai_types.Schema(type="BOOLEAN", description="Is the victim breathing?"),
                    "victim_count": genai_types.Schema(type="INTEGER", description="Number of victims"),
                },
            ),
        ),
        genai_types.FunctionDeclaration(
            name="append_free_text",
            description="Append a raw user utterance for context. Call for every meaningful thing the user says.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"utterance": genai_types.Schema(type="STRING")},
                required=["utterance"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="get_pending_dispatch_question",
            description="Check if the 112 operator asked a question the AI cannot answer. Returns the question or 'NONE'.",
            parameters=genai_types.Schema(type="OBJECT", properties={}),
        ),
        genai_types.FunctionDeclaration(
            name="answer_dispatch_question",
            description="Answer a question relayed from the 112 operator.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "question": genai_types.Schema(type="STRING"),
                    "answer": genai_types.Schema(type="STRING"),
                },
                required=["question", "answer"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="surface_user_question",
            description="Show a yes/no question on the user's screen. Use sparingly — max one at a time.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"question": genai_types.Schema(type="STRING")},
                required=["question"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="record_user_input",
            description="Record a user's response (tap or text) to a question.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "response_type": genai_types.Schema(type="STRING", enum=["TAP", "TEXT"]),
                    "value": genai_types.Schema(type="STRING"),
                },
                required=["response_type", "value"],
            ),
        ),
    ]
)

USER_AGENT_SYSTEM_PROMPT = """Ti si hitni asistent za prenos poziva. Posmatra okruzenje korisnika putem mikrofona i kamere da prikupis informacije o hitnom slucaju.

PRAVILA:
- Radi u rezimu posmatranja. Nikada ne zahtevaj odgovor korisnika.
- Odmah pozovi alat kad se informacija potvrdi iz audio/video konteksta.
- Postavi najvise jedno da/ne pitanje istovremeno koristeci surface_user_question.
- Nikada ne spekulisi izvan onoga sto je direktno uoceno ili potvrdjeno.
- Nikada ne reci "Ja sam vestacka inteligencija". Reci "Ja sam vas hitni asistent za prenos poziva."
- Govori srpski.

PRIORITET INFORMACIJA:
1. Potvrda adrese (unapred popunjena sa GPS-a)
2. Tip hitnog slucaja (medicinski, pozar, policija, gas, ostalo)
3. Broj zrtava
4. Stanje svesti
5. Disanje

Ako se pojavi pitanje u dispatch_questions, odmah ga obradi."""


async def run_user_agent(
    session_id: str,
    store: SnapshotStore,
    broadcast: BroadcastFn,
) -> None:
    settings = get_settings()
    tools = UserAgentTools(session_id, store, broadcast)
    client = genai.Client(api_key=settings.google_api_key)

    tool_handlers = {
        "confirm_location": lambda args: tools.confirm_location(args["address"]),
        "set_emergency_type": lambda args: tools.set_emergency_type(args["emergency_type"]),
        "set_clinical_fields": lambda args: tools.set_clinical_fields(
            conscious=args.get("conscious"),
            breathing=args.get("breathing"),
            victim_count=args.get("victim_count"),
        ),
        "append_free_text": lambda args: tools.append_free_text(args["utterance"]),
        "get_pending_dispatch_question": lambda _: tools.get_pending_dispatch_question(),
        "answer_dispatch_question": lambda args: tools.answer_dispatch_question(args["question"], args["answer"]),
        "surface_user_question": lambda args: tools.surface_user_question(args["question"]),
        "record_user_input": lambda args: tools.record_user_input(args["response_type"], args["value"]),
    }

    config = genai_types.LiveConnectConfig(
        response_modalities=["TEXT"],
        system_instruction=genai_types.Content(
            parts=[genai_types.Part(text=USER_AGENT_SYSTEM_PROMPT)]
        ),
        tools=[TOOL_DECLARATIONS],
    )

    try:
        async with client.aio.live.connect(
            model="gemini-2.0-flash-live-001",
            config=config,
        ) as session:
            logger.info("User Agent connected for session %s", session_id)

            # Send initial context from snapshot
            snap = await store.load(session_id)
            if snap:
                initial_context = (
                    f"Hitni slucaj prijavljen. GPS lokacija: {snap.location.lat}, {snap.location.lng}. "
                    f"Adresa: {snap.location.address or 'nepoznata'}. "
                    f"Pocni sa posmatranjem i prikupljanjem informacija."
                )
                await session.send(input=initial_context, end_of_turn=True)

            async for response in session.receive():
                # Handle tool calls
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

                # Handle text responses — broadcast as transcript
                if response.text:
                    await broadcast(session_id, {
                        "type": "transcript",
                        "speaker": "assistant",
                        "text": response.text,
                    })

    except Exception:
        logger.exception("User Agent error for session %s", session_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_user_agent.py -v`
Expected: 7 passed. (Tests only exercise `UserAgentTools`, not the Gemini session.)

- [ ] **Step 5: Commit**

```bash
git add backend/user_agent.py backend/tests/test_user_agent.py
git commit -m "feat(backend): add User Agent with Gemini Live tools and triage logic"
```

---

### Task 7: Dispatch Agent (Gemini Live + Twilio)

**Files:**
- Create: `backend/dispatch_agent.py`
- Create: `backend/tests/test_dispatch_agent.py`

- [ ] **Step 1: Write failing tests for Dispatch Agent tools**

```python
# backend/tests/test_dispatch_agent.py
import pytest
import fakeredis.aioredis

from snapshot import (
    CallStatus,
    EmergencySnapshot,
    EmergencyType,
    Location,
    SessionPhase,
    SnapshotStore,
)
from dispatch_agent import DispatchAgentTools


@pytest.fixture
async def setup():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8, lng=20.4, address="Knez Mihailova 5", confirmed=True),
        emergency_type=EmergencyType.MEDICAL,
        conscious=False,
        breathing=True,
        victim_count=1,
        free_text_details=["otac pao niz stepenice", "krv na glavi"],
    )
    await store.save(snap)
    messages = []

    async def broadcast(sid, msg):
        messages.append(msg)

    tools = DispatchAgentTools("s1", store, broadcast)
    yield tools, store, messages
    await redis.aclose()


async def test_get_emergency_brief(setup):
    tools, _, _ = setup
    brief = await tools.get_emergency_brief()
    assert "MEDICAL" in brief
    assert "Knez Mihailova 5" in brief
    assert "1" in brief  # victim count


async def test_queue_question_for_user(setup):
    tools, store, _ = setup
    await tools.queue_question_for_user("Da li je pri svesti?")
    snap = await store.load("s1")
    assert "Da li je pri svesti?" in snap.dispatch_questions


async def test_get_user_answer_pending(setup):
    tools, _, _ = setup
    result = await tools.get_user_answer("Da li je pri svesti?")
    assert result == "PENDING"


async def test_get_user_answer_found(setup):
    tools, store, _ = setup
    await store.update("s1", lambda s: s.ua_answers.append("Da li je pri svesti?|Ne"))
    result = await tools.get_user_answer("Da li je pri svesti?")
    assert result == "Ne"


async def test_update_call_status(setup):
    tools, store, _ = setup
    await tools.update_call_status("CONNECTED")
    snap = await store.load("s1")
    assert snap.call_status == CallStatus.CONNECTED


async def test_confirm_dispatch(setup):
    tools, store, messages = setup
    await tools.confirm_dispatch(8)
    snap = await store.load("s1")
    assert snap.call_status == CallStatus.CONFIRMED
    assert snap.eta_minutes == 8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_dispatch_agent.py -v`
Expected: FAIL — `dispatch_agent` module not found.

- [ ] **Step 3: Write dispatch_agent.py**

```python
# backend/dispatch_agent.py
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from google import genai
from google.genai import types as genai_types
from twilio.rest import Client as TwilioClient

from config import get_settings
from snapshot import (
    CallStatus,
    EmergencySnapshot,
    SnapshotStore,
)

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, dict], Awaitable[None]]


class DispatchAgentTools:
    """Tool implementations for the Dispatch Agent."""

    def __init__(
        self,
        session_id: str,
        store: SnapshotStore,
        broadcast: BroadcastFn,
    ) -> None:
        self.session_id = session_id
        self.store = store
        self.broadcast = broadcast

    async def get_emergency_brief(self) -> str:
        snap = await self.store.load(self.session_id)
        if snap is None:
            return "No session data available."

        loc = snap.location
        if loc.confirmed and loc.address:
            addr = loc.address
        elif loc.address:
            addr = f"{loc.address} (nepotvrdjeno)"
        else:
            addr = f"GPS: {loc.lat}, {loc.lng}"

        parts = [
            f"Tip: {snap.emergency_type or 'nepoznat'}",
            f"Adresa: {addr}",
            f"Broj zrtava: {snap.victim_count if snap.victim_count is not None else 'nepoznat'}",
            f"Svest: {'da' if snap.conscious else 'ne' if snap.conscious is not None else 'nepoznato'}",
            f"Disanje: {'da' if snap.breathing else 'ne' if snap.breathing is not None else 'nepoznato'}",
        ]
        if snap.free_text_details:
            parts.append(f"Detalji: {'; '.join(snap.free_text_details)}")
        if snap.input_conflicts:
            conflicts = [f"{c.field}: korisnik kaze '{c.user_value}', okruzenje pokazuje '{c.env_value}'" for c in snap.input_conflicts]
            parts.append(f"Neslaganja: {'; '.join(conflicts)}")

        return " | ".join(parts)

    async def queue_question_for_user(self, question: str) -> str:
        await self.store.update(
            self.session_id,
            lambda s: s.dispatch_questions.append(question),
        )
        return "Question queued for user agent"

    async def get_user_answer(self, question: str) -> str:
        snap = await self.store.load(self.session_id)
        if snap is None:
            return "PENDING"
        for entry in snap.ua_answers:
            if "|" in entry:
                q, a = entry.split("|", 1)
                if q == question:
                    return a
        return "PENDING"

    async def update_call_status(self, status: str) -> str:
        cs = CallStatus(status)
        await self.store.update(self.session_id, lambda s: setattr(s, "call_status", cs))
        return f"Call status: {cs}"

    async def confirm_dispatch(self, eta_minutes: int) -> str:
        def updater(s: EmergencySnapshot) -> None:
            s.call_status = CallStatus.CONFIRMED
            s.eta_minutes = eta_minutes

        await self.store.update(self.session_id, updater)
        return f"Dispatch confirmed, ETA {eta_minutes} minutes"


# --- Tool declarations for Gemini ---

DISPATCH_TOOL_DECLARATIONS = genai_types.Tool(
    function_declarations=[
        genai_types.FunctionDeclaration(
            name="get_emergency_brief",
            description="Get the full emergency briefing from user data. Call at start and on reconnect.",
            parameters=genai_types.Schema(type="OBJECT", properties={}),
        ),
        genai_types.FunctionDeclaration(
            name="queue_question_for_user",
            description="Ask the user a question through the relay. Use when operator asks something not in the brief.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"question": genai_types.Schema(type="STRING")},
                required=["question"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="get_user_answer",
            description="Check if the user answered a previously queued question. Returns answer or 'PENDING'.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"question": genai_types.Schema(type="STRING")},
                required=["question"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="update_call_status",
            description="Update the call status: DIALING, CONNECTED, DROPPED.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"status": genai_types.Schema(type="STRING", enum=["DIALING", "CONNECTED", "DROPPED"])},
                required=["status"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="confirm_dispatch",
            description="Confirm that emergency services are dispatched with ETA.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"eta_minutes": genai_types.Schema(type="INTEGER")},
                required=["eta_minutes"],
            ),
        ),
    ]
)

DISPATCH_AGENT_SYSTEM_PROMPT = """Ti si automatizovani servis za prenos hitnih poziva. Zoves 112 u ime osobe koja ne moze da govori.

PRAVILA:
- Prva recenica: "Ovo je automatizovani poziv hitne sluzbe u ime osobe koja ne moze da govori. Imam detalje o hitnom slucaju i odgovoricu na vasa pitanja."
- Odmah zatim izgovori ceo brifing koristeci get_emergency_brief().
- Odgovaraj na pitanja operatera koristeci podatke iz brifinga.
- Ako ne znas odgovor, reci "Jedan momenat, proveravam sa pozivaocem" i koristi queue_question_for_user().
- Zatim periodcno proveravaj get_user_answer() dok ne dobijes odgovor.
- Nikada ne spekulisi o nepotvdrjenim poljima. Reci "to jos nije potvrdjeno".
- Ako postoje neslaganja (input_conflicts), prijavi ih operateru kao nerazresene.
- Kada operator potvrdi slanje ekipe, pozovi confirm_dispatch(eta_minutes).
- Govori srpski, jasno i koncizno."""


async def run_dispatch_agent(
    session_id: str,
    store: SnapshotStore,
    broadcast: BroadcastFn,
) -> None:
    settings = get_settings()
    tools = DispatchAgentTools(session_id, store, broadcast)
    client = genai.Client(api_key=settings.google_api_key)

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
                url=f"https://your-backend-url/api/session/{session_id}/twilio/twiml",
                status_callback=f"https://your-backend-url/api/session/{session_id}/twilio/status",
            )
            call_sid = call.sid
            await tools.update_call_status("DIALING")
            logger.info("Twilio call initiated: %s", call_sid)
        except Exception:
            logger.exception("Failed to initiate Twilio call for session %s", session_id)
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

            # Instruct agent to begin
            await session.send(
                input="Poziv je uspostavljen. Pocni sa brifingom.",
                end_of_turn=True,
            )

            async for response in session.receive():
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

                if response.text:
                    await broadcast(session_id, {
                        "type": "transcript",
                        "speaker": "assistant",
                        "text": response.text,
                    })

    except Exception:
        logger.exception("Dispatch Agent error for session %s", session_id)
        await tools.update_call_status("DROPPED")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_dispatch_agent.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/dispatch_agent.py backend/tests/test_dispatch_agent.py
git commit -m "feat(backend): add Dispatch Agent with Gemini Live and Twilio integration"
```

---

### Task 8: Twilio Audio Exchange Endpoint

**Files:**
- Modify: `backend/main.py` (add Twilio endpoints)
- Create: `backend/tests/test_twilio_endpoint.py`

- [ ] **Step 1: Write failing tests for Twilio audio endpoint**

```python
# backend/tests/test_twilio_endpoint.py
import pytest
from httpx import ASGITransport, AsyncClient
import fakeredis.aioredis

from main import create_app
from snapshot import EmergencySnapshot, Location, SessionPhase, SnapshotStore


@pytest.fixture
async def client():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    app = create_app(store=store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await redis.aclose()


async def test_twilio_audio_endpoint(client: AsyncClient):
    resp = await client.post("/api/session/s1/twilio/audio", json={
        "audio": "base64encodedaudio",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "audio_chunks" in data


async def test_twilio_audio_not_found(client: AsyncClient):
    resp = await client.post("/api/session/nonexistent/twilio/audio", json={
        "audio": "base64encodedaudio",
    })
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_twilio_endpoint.py -v`
Expected: FAIL — endpoint not found.

- [ ] **Step 3: Add Twilio audio endpoint to main.py**

Add to the `create_app` function in `main.py`, after the existing routes:

```python
    class TwilioAudioRequest(BaseModel):
        audio: str

    @app.post("/api/session/{session_id}/twilio/audio")
    async def twilio_audio(session_id: str, req: TwilioAudioRequest) -> dict:
        snapshot = await store.load(session_id)
        if snapshot is None:
            return JSONResponse(
                status_code=404,
                content={"error": "Session not found"},
            )
        # In a full implementation, this would:
        # 1. Feed req.audio into the Dispatch Agent's Gemini session
        # 2. Return any queued audio from the Dispatch Agent
        # For now, return empty chunks (agent integration happens in Task 7)
        return {"audio_chunks": []}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_twilio_endpoint.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run all tests**

Run: `cd backend && uv run pytest -v`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_twilio_endpoint.py
git commit -m "feat(backend): add Twilio audio exchange endpoint"
```

---

### Task 9: Demo Dispatch Simulator

**Files:**
- Create: `backend/demo_dispatch.py`

- [ ] **Step 1: Write demo_dispatch.py**

```python
# backend/demo_dispatch.py
"""
Simulated 112 dispatcher for demo.
Run: uvicorn demo_dispatch:app --port 8001

This is a standalone FastAPI app that simulates an emergency dispatcher.
It receives audio from the Dispatch Agent and responds with scripted lines.
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import StrEnum

from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="Demo Dispatch Simulator", version="0.1.0")


class DispatchState(StrEnum):
    GREETING = "GREETING"
    LISTENING = "LISTENING"
    ASKING_CONSCIOUS = "ASKING_CONSCIOUS"
    CONFIRMING = "CONFIRMING"
    DONE = "DONE"


# Per-session state
sessions: dict[str, dict] = {}

SCRIPT = {
    DispatchState.GREETING: "Hitna sluzba, sta se desilo?",
    DispatchState.ASKING_CONSCIOUS: "Da li je pacijent pri svesti?",
    DispatchState.CONFIRMING: "Saljemo ekipu. Procenjeno vreme dolaska je 8 minuta. Ostanite na liniji.",
}

# Delays between script steps (seconds from call start)
SCRIPT_TIMING = {
    DispatchState.GREETING: 2,
    DispatchState.ASKING_CONSCIOUS: 15,
    DispatchState.CONFIRMING: 30,
}


class AudioRequest(BaseModel):
    audio: str
    session_id: str = "demo"


@app.post("/dispatch/audio")
async def dispatch_audio(req: AudioRequest) -> dict:
    sid = req.session_id

    if sid not in sessions:
        sessions[sid] = {
            "state": DispatchState.GREETING,
            "start_time": time.time(),
            "lines_sent": set(),
        }

    sess = sessions[sid]
    elapsed = time.time() - sess["start_time"]
    response_lines: list[str] = []

    # Check which scripted lines should fire based on elapsed time
    for state, timing in SCRIPT_TIMING.items():
        if elapsed >= timing and state not in sess["lines_sent"]:
            response_lines.append(SCRIPT[state])
            sess["lines_sent"].add(state)
            sess["state"] = state

    if DispatchState.CONFIRMING in sess["lines_sent"]:
        sess["state"] = DispatchState.DONE

    return {
        "responses": response_lines,
        "state": sess["state"],
        "elapsed_seconds": round(elapsed, 1),
    }


@app.get("/dispatch/health")
async def health() -> dict:
    return {"status": "ok", "active_sessions": len(sessions)}


@app.post("/dispatch/reset")
async def reset() -> dict:
    sessions.clear()
    return {"status": "reset"}
```

- [ ] **Step 2: Commit**

```bash
git add backend/demo_dispatch.py
git commit -m "feat(backend): add simulated 112 dispatcher for demo"
```

---

### Task 10: Docker Setup

**Files:**
- Create: `backend/Dockerfile`
- Create: `docker-compose.yml` (repo root)
- Create: `.env.example` (repo root)

- [ ] **Step 1: Write Dockerfile**

```dockerfile
# backend/Dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

COPY . .

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 2: Write docker-compose.yml**

```yaml
# docker-compose.yml (repo root)
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  backend:
    build: ./backend
    ports:
      - "8080:8080"
    env_file: .env
    depends_on:
      - redis
    environment:
      - REDIS_URL=redis://redis:6379

  demo-dispatch:
    build: ./backend
    command: uv run uvicorn demo_dispatch:app --host 0.0.0.0 --port 8001
    ports:
      - "8001:8001"
```

- [ ] **Step 3: Write .env.example**

```bash
# .env.example
GOOGLE_API_KEY=your-gemini-api-key
REDIS_URL=redis://localhost:6379
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
EMERGENCY_NUMBER=+381601234567
TRIAGE_TIMEOUT_SECONDS=10
CONFIDENCE_THRESHOLD=0.85
RECONNECT_MAX_ATTEMPTS=3
```

- [ ] **Step 4: Add Docker-related entries to .gitignore**

Append to `.gitignore`:
```
.env
```

- [ ] **Step 5: Commit**

```bash
git add backend/Dockerfile docker-compose.yml .env.example .gitignore
git commit -m "feat: add Docker setup with Redis and demo dispatch"
```

---

## Verification

After all tasks are complete, verify the full system:

1. **Unit tests pass:**
   ```bash
   cd backend && uv run pytest -v
   ```
   Expected: All tests green.

2. **Backend starts locally (requires Redis):**
   ```bash
   docker compose up redis -d
   cd backend && uv run uvicorn main:app --port 8080 --reload
   ```

3. **Health check works:**
   ```bash
   curl http://localhost:8080/api/health
   # {"status":"ok","active_sessions":0}
   ```

4. **SOS flow works:**
   ```bash
   curl -X POST http://localhost:8080/api/sos \
     -H "Content-Type: application/json" \
     -d '{"lat":44.8176,"lng":20.4633,"user_id":"test","device_id":"test"}'
   # {"session_id":"<uuid>","status":"TRIAGE"}
   ```

5. **WebSocket connects:**
   ```bash
   websocat ws://localhost:8080/api/session/<session_id>/ws
   # Send: {"type":"ping"}
   # Receive: {"type":"pong"}
   ```

6. **Docker compose builds and runs:**
   ```bash
   docker compose up --build
   ```

7. **Frontend connects to backend:**
   Start the Expo dev server, open the app, and verify the SOS button triggers a session and WebSocket connects.
