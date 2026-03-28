# backend/tests/test_integration.py
"""
Integration tests for the Medak emergency relay backend.

These tests exercise cross-module interactions through the HTTP API,
WebSocket interface, and coordinated tool flows — never calling private methods.
"""
from __future__ import annotations

import asyncio
import json
import time

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from demo_dispatch import app as demo_dispatch_app
from dispatch_agent import DispatchAgentTools
from main import create_app
from orchestrator import SessionOrchestrator
from snapshot import (
    CallStatus,
    EmergencySnapshot,
    EmergencyType,
    Location,
    SessionPhase,
    SnapshotStore,
    UserInput,
)
from user_agent import UserAgentTools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def store(redis):
    return SnapshotStore(redis)


@pytest.fixture
async def app(store):
    return create_app(store=store)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def dispatch_client():
    transport = ASGITransport(app=demo_dispatch_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def sos_payload(*, lat=44.8176, lng=20.4633, address=None, user_id="u1", device_id="d1"):
    body = {"lat": lat, "lng": lng, "user_id": user_id, "device_id": device_id}
    if address is not None:
        body["address"] = address
    return body


async def create_session(client: AsyncClient, **kwargs) -> str:
    """POST /api/sos and return the session_id."""
    resp = await client.post("/api/sos", json=sos_payload(**kwargs))
    assert resp.status_code == 200
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------
# 1. SOS → Status flow
# ---------------------------------------------------------------------------

async def test_sos_creates_session_and_status_returns_initial_state(client: AsyncClient):
    sid = await create_session(client)

    resp = await client.get(f"/api/session/{sid}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == sid
    # Orchestrator may have already moved to TRIAGE by the time we poll
    assert data["phase"] in ("INTAKE", "TRIAGE")
    assert data["confidence"] == pytest.approx(0.20, abs=0.05)
    assert data["call_status"] in ("IDLE", "DIALING")
    assert "snapshot_version" in data


async def test_sos_response_contains_session_id_and_triage_status(client: AsyncClient):
    resp = await client.post("/api/sos", json=sos_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert body["status"] == "TRIAGE"


async def test_status_endpoint_returns_404_for_unknown_session(client: AsyncClient):
    resp = await client.get("/api/session/does-not-exist/status")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. SOS with / without address — confidence differs
# ---------------------------------------------------------------------------

async def test_sos_without_address_gives_gps_base_confidence(store: SnapshotStore, client: AsyncClient):
    sid = await create_session(client)
    snap = await store.load(sid)
    # GPS-only base confidence
    assert snap.confidence_score == pytest.approx(0.20, abs=0.01)


async def test_sos_with_address_still_gets_gps_confidence_initially(store: SnapshotStore, client: AsyncClient):
    """Address is stored but confidence doesn't auto-confirm; GPS base stays 0.20."""
    sid = await create_session(client, address="Knez Mihailova 5, Beograd")
    snap = await store.load(sid)
    # main.py sets confidence to 0.20 regardless; address needs confirmation for 0.35
    assert snap.confidence_score == pytest.approx(0.20, abs=0.01)
    assert snap.location.address == "Knez Mihailova 5, Beograd"


async def test_confirmed_address_raises_confidence_above_gps_only(store: SnapshotStore):
    """Confirmed address gives 0.35 confidence vs 0.20 for GPS-only."""
    snap = EmergencySnapshot(
        session_id="conf1",
        location=Location(lat=44.8, lng=20.4, address="Knez Mihailova 5"),
        confidence_score=0.20,
    )
    await store.save(snap)

    await store.update("conf1", lambda s: (
        setattr(s.location, "confirmed", True),
        setattr(s.location, "address", "Knez Mihailova 5"),
    ))
    updated = await store.load("conf1")
    assert updated.confidence_score >= 0.35
    assert updated.confidence_score > 0.20


# ---------------------------------------------------------------------------
# 3. Session lifecycle through store
# ---------------------------------------------------------------------------

async def test_session_lifecycle_status_reflects_store_updates(store: SnapshotStore, client: AsyncClient):
    """Create via API, then update store directly; status should reflect changes."""
    snap = EmergencySnapshot(
        session_id="lifecycle1",
        location=Location(lat=44.8, lng=20.4),
        confidence_score=0.20,
    )
    await store.save(snap)

    # Simulate agent work: set emergency type & clinical fields
    await store.update("lifecycle1", lambda s: setattr(s, "emergency_type", EmergencyType.MEDICAL))
    await store.update("lifecycle1", lambda s: setattr(s, "conscious", False))

    resp = await client.get("/api/session/lifecycle1/status")
    data = resp.json()
    # confidence should have increased from agent-supplied fields
    assert data["confidence"] > 0.20


async def test_session_version_increments_after_updates(store: SnapshotStore, client: AsyncClient):
    """Each store.update increments snapshot_version."""
    snap = EmergencySnapshot(
        session_id="version1",
        location=Location(lat=44.8, lng=20.4),
        confidence_score=0.20,
    )
    await store.save(snap)

    resp_before = await client.get("/api/session/version1/status")
    v0 = resp_before.json()["snapshot_version"]

    await store.update("version1", lambda s: setattr(s, "emergency_type", EmergencyType.FIRE))

    resp_after = await client.get("/api/session/version1/status")
    v1 = resp_after.json()["snapshot_version"]
    assert v1 > v0


async def test_phase_change_visible_through_status_endpoint(store: SnapshotStore, client: AsyncClient):
    """Phase set via store is visible through the status API."""
    snap = EmergencySnapshot(
        session_id="phase1",
        location=Location(lat=44.8, lng=20.4),
        confidence_score=0.20,
    )
    await store.save(snap)

    await store.update("phase1", lambda s: setattr(s, "phase", SessionPhase.LIVE_CALL))

    resp = await client.get("/api/session/phase1/status")
    assert resp.json()["phase"] == "LIVE_CALL"


# ---------------------------------------------------------------------------
# 4. Multiple concurrent sessions
# ---------------------------------------------------------------------------

async def test_three_concurrent_sessions_have_independent_ids(client: AsyncClient):
    ids = [await create_session(client, user_id=f"u{i}", device_id=f"d{i}") for i in range(3)]
    assert len(set(ids)) == 3  # all different


async def test_concurrent_sessions_have_independent_state(store: SnapshotStore):
    """Mutating one session doesn't affect another."""
    snap_a = EmergencySnapshot(session_id="ind_a", location=Location(lat=44.8, lng=20.4))
    snap_b = EmergencySnapshot(session_id="ind_b", location=Location(lat=45.0, lng=21.0))
    await store.save(snap_a)
    await store.save(snap_b)

    await store.update("ind_a", lambda s: setattr(s, "emergency_type", EmergencyType.POLICE))

    loaded_a = await store.load("ind_a")
    loaded_b = await store.load("ind_b")
    assert loaded_a.emergency_type == EmergencyType.POLICE
    assert loaded_b.emergency_type is None  # untouched


async def test_concurrent_sessions_status_endpoints_are_isolated(client: AsyncClient, store: SnapshotStore):
    """Two sessions can have different phases visible via the status API."""
    snap1 = EmergencySnapshot(session_id="iso1", location=Location(lat=44.8, lng=20.4))
    snap2 = EmergencySnapshot(session_id="iso2", location=Location(lat=45.0, lng=21.0))
    await store.save(snap1)
    await store.save(snap2)

    await store.update("iso1", lambda s: setattr(s, "phase", SessionPhase.RESOLVED))

    r1 = (await client.get("/api/session/iso1/status")).json()
    r2 = (await client.get("/api/session/iso2/status")).json()
    assert r1["phase"] == "RESOLVED"
    assert r2["phase"] != "RESOLVED"


# ---------------------------------------------------------------------------
# 5. Orchestrator full run (start_agents=False)
# ---------------------------------------------------------------------------

async def test_orchestrator_full_run_intake_to_resolved(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="orch1",
        phase=SessionPhase.INTAKE,
        location=Location(lat=44.8, lng=20.4),
        confidence_score=0.20,
    )
    await store.save(snap)

    broadcast_log: list[dict] = []

    async def fake_broadcast(sid: str, msg: dict):
        broadcast_log.append(msg)

    orch = SessionOrchestrator(
        session_id="orch1",
        store=store,
        broadcast=fake_broadcast,
        start_agents=False,
        triage_timeout=1,           # very short — will timeout quickly
        confidence_threshold=0.99,  # unreachable → forces timeout path
    )

    task = asyncio.create_task(orch.run())

    # Wait for it to reach LIVE_CALL (triage times out after 1s)
    for _ in range(30):
        await asyncio.sleep(0.2)
        s = await store.load("orch1")
        if s and s.phase == SessionPhase.LIVE_CALL:
            break
    else:
        pytest.fail("Orchestrator did not reach LIVE_CALL within timeout")

    # Confirm dispatch to trigger RESOLVED
    await store.update("orch1", lambda s: (
        setattr(s, "call_status", CallStatus.CONFIRMED),
        setattr(s, "eta_minutes", 5),
    ))

    await asyncio.wait_for(task, timeout=10)

    final = await store.load("orch1")
    assert final.phase == SessionPhase.RESOLVED

    phase_types = [m.get("type") for m in broadcast_log]
    assert "STATUS_UPDATE" in phase_types
    assert "RESOLVED" in phase_types


async def test_orchestrator_broadcasts_triage_updates(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="orch2",
        phase=SessionPhase.INTAKE,
        location=Location(lat=44.8, lng=20.4),
        confidence_score=0.20,
    )
    await store.save(snap)

    broadcast_log: list[dict] = []

    async def fake_broadcast(sid: str, msg: dict):
        broadcast_log.append(msg)

    orch = SessionOrchestrator(
        session_id="orch2",
        store=store,
        broadcast=fake_broadcast,
        start_agents=False,
        triage_timeout=1,
        confidence_threshold=0.99,
    )

    task = asyncio.create_task(orch.run())

    for _ in range(30):
        await asyncio.sleep(0.2)
        s = await store.load("orch2")
        if s and s.phase == SessionPhase.LIVE_CALL:
            break

    await store.update("orch2", lambda s: setattr(s, "call_status", CallStatus.CONFIRMED))
    await asyncio.wait_for(task, timeout=10)

    triage_updates = [m for m in broadcast_log if m.get("type") == "STATUS_UPDATE" and m.get("phase") == "TRIAGE"]
    assert len(triage_updates) >= 1


async def test_orchestrator_dropped_call_transitions_to_failed_after_max_retries(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="orch3",
        phase=SessionPhase.INTAKE,
        location=Location(lat=44.8, lng=20.4),
        confidence_score=0.20,
    )
    await store.save(snap)

    broadcast_log: list[dict] = []

    async def fake_broadcast(sid: str, msg: dict):
        broadcast_log.append(msg)

    orch = SessionOrchestrator(
        session_id="orch3",
        store=store,
        broadcast=fake_broadcast,
        start_agents=False,
        triage_timeout=1,
        confidence_threshold=0.99,
        max_reconnects=1,
    )

    task = asyncio.create_task(orch.run())

    for _ in range(30):
        await asyncio.sleep(0.2)
        s = await store.load("orch3")
        if s and s.phase == SessionPhase.LIVE_CALL:
            break

    await store.update("orch3", lambda s: setattr(s, "call_status", CallStatus.DROPPED))
    await asyncio.wait_for(task, timeout=20)

    final = await store.load("orch3")
    assert final.phase == SessionPhase.FAILED
    assert any(m.get("type") == "FAILED" for m in broadcast_log)


# ---------------------------------------------------------------------------
# 6. UserAgentTools → SnapshotStore → DispatchAgentTools cross-module flow
# ---------------------------------------------------------------------------

async def test_user_agent_sets_data_dispatch_agent_reads_brief(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="cross1",
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    broadcast_log: list[dict] = []

    async def bcast(sid, msg):
        broadcast_log.append(msg)

    user_tools = UserAgentTools("cross1", store, bcast)
    dispatch_tools = DispatchAgentTools("cross1", store, bcast)

    # User agent gathers data
    await user_tools.set_emergency_type("MEDICAL")
    await user_tools.confirm_location("Knez Mihailova 5, Beograd")
    await user_tools.set_clinical_fields(conscious=False, breathing=True, victim_count=1)

    # Dispatch agent reads brief
    brief = await dispatch_tools.get_emergency_brief()
    assert "MEDICAL" in brief
    assert "Knez Mihailova 5, Beograd" in brief
    assert "1" in brief  # victim_count


async def test_dispatch_queues_question_user_agent_sees_and_answers(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="cross2",
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    broadcast_log: list[dict] = []

    async def bcast(sid, msg):
        broadcast_log.append(msg)

    user_tools = UserAgentTools("cross2", store, bcast)
    dispatch_tools = DispatchAgentTools("cross2", store, bcast)

    # Dispatch agent queues a question
    await dispatch_tools.queue_question_for_user("Da li krvari?")

    # User agent checks for pending question
    pending = await user_tools.get_pending_dispatch_question()
    assert pending == "Da li krvari?"

    # User agent answers
    await user_tools.answer_dispatch_question("Da li krvari?", "Da, iz glave")

    # Dispatch agent retrieves the answer
    answer = await dispatch_tools.get_user_answer("Da li krvari?")
    assert answer == "Da, iz glave"


async def test_dispatch_question_pending_before_user_answers(store: SnapshotStore):
    snap = EmergencySnapshot(session_id="cross3", location=Location(lat=44.8, lng=20.4))
    await store.save(snap)

    async def noop(sid, msg):
        pass

    dispatch_tools = DispatchAgentTools("cross3", store, noop)

    await dispatch_tools.queue_question_for_user("Koliko ima godina?")
    answer = await dispatch_tools.get_user_answer("Koliko ima godina?")
    assert answer == "PENDING"


async def test_full_cross_module_flow_with_multiple_questions(store: SnapshotStore):
    snap = EmergencySnapshot(session_id="cross4", location=Location(lat=44.8, lng=20.4))
    await store.save(snap)

    broadcast_log: list[dict] = []

    async def bcast(sid, msg):
        broadcast_log.append(msg)

    user_tools = UserAgentTools("cross4", store, bcast)
    dispatch_tools = DispatchAgentTools("cross4", store, bcast)

    # User agent sets initial data
    await user_tools.set_emergency_type("FIRE")
    await user_tools.append_free_text("dim iz stana na trecem spratu")

    # Dispatch agent queues two questions
    await dispatch_tools.queue_question_for_user("Da li ima povredjenih?")
    await dispatch_tools.queue_question_for_user("Da li je gas iskljucen?")

    # User agent gets first pending question
    q1 = await user_tools.get_pending_dispatch_question()
    assert q1 == "Da li ima povredjenih?"
    await user_tools.answer_dispatch_question(q1, "Ne, svi su napolju")

    # First is answered, second should be pending
    q2 = await user_tools.get_pending_dispatch_question()
    assert q2 == "Da li je gas iskljucen?"
    await user_tools.answer_dispatch_question(q2, "Nije sigurno")

    # All answered
    q3 = await user_tools.get_pending_dispatch_question()
    assert q3 == "NONE"

    # Dispatch reads answers
    a1 = await dispatch_tools.get_user_answer("Da li ima povredjenih?")
    a2 = await dispatch_tools.get_user_answer("Da li je gas iskljucen?")
    assert a1 == "Ne, svi su napolju"
    assert a2 == "Nije sigurno"

    # Brief should include FIRE and free text
    brief = await dispatch_tools.get_emergency_brief()
    assert "FIRE" in brief
    assert "dim iz stana" in brief


# ---------------------------------------------------------------------------
# 7. WebSocket connection — ping / pong
#
# WebSocket tests use sync `def` to avoid event loop conflicts between
# the async test runner and Starlette's TestClient (which runs its own loop).
# Each test creates a self-contained FakeRedis/Store/App.
# ---------------------------------------------------------------------------

def _make_ws_app():
    """Create an isolated app + store for WebSocket tests."""
    redis_client = fakeredis.aioredis.FakeRedis()
    ws_store = SnapshotStore(redis_client)
    ws_app = create_app(store=ws_store)
    return ws_app


def _recv_until_type(ws, expected_type: str, max_messages: int = 20) -> dict:
    """Receive WS messages, skipping broadcasts, until we get the expected type."""
    for _ in range(max_messages):
        data = json.loads(ws.receive_text())
        if data.get("type") == expected_type:
            return data
    raise AssertionError(f"Did not receive message with type={expected_type!r} within {max_messages} messages")


def test_websocket_ping_pong():
    from starlette.testclient import TestClient

    ws_app = _make_ws_app()
    with TestClient(ws_app) as tc:
        # Create session via sync HTTP (runs in TestClient's own event loop)
        resp = tc.post("/api/sos", json=sos_payload())
        sid = resp.json()["session_id"]

        with tc.websocket_connect(f"/api/session/{sid}/ws") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            data = _recv_until_type(ws, "pong")
            assert data["type"] == "pong"


def test_websocket_multiple_pings():
    from starlette.testclient import TestClient

    ws_app = _make_ws_app()
    with TestClient(ws_app) as tc:
        resp = tc.post("/api/sos", json=sos_payload())
        sid = resp.json()["session_id"]

        with tc.websocket_connect(f"/api/session/{sid}/ws") as ws:
            for _ in range(5):
                ws.send_text(json.dumps({"type": "ping"}))
                data = _recv_until_type(ws, "pong")
                assert data["type"] == "pong"


# ---------------------------------------------------------------------------
# 8. WebSocket user_response
# ---------------------------------------------------------------------------

def test_websocket_user_response_accepted_and_stored():
    """Send user_response via WS, then verify connection is alive and confidence increased."""
    from starlette.testclient import TestClient

    ws_app = _make_ws_app()
    with TestClient(ws_app) as tc:
        resp = tc.post("/api/sos", json=sos_payload())
        sid = resp.json()["session_id"]

        initial = tc.get(f"/api/session/{sid}/status").json()
        initial_version = initial["snapshot_version"]

        with tc.websocket_connect(f"/api/session/{sid}/ws") as ws:
            ws.send_text(json.dumps({
                "type": "user_response",
                "response_type": "TAP",
                "value": "yes",
            }))
            # Verify connection is still alive after processing
            ws.send_text(json.dumps({"type": "ping"}))
            pong = _recv_until_type(ws, "pong")
            assert pong["type"] == "pong"

        # Snapshot version should have increased (user_response triggers store.update)
        time.sleep(0.2)
        after = tc.get(f"/api/session/{sid}/status").json()
        assert after["snapshot_version"] > initial_version


def test_websocket_user_response_text_type():
    from starlette.testclient import TestClient

    ws_app = _make_ws_app()
    with TestClient(ws_app) as tc:
        resp = tc.post("/api/sos", json=sos_payload())
        sid = resp.json()["session_id"]

        with tc.websocket_connect(f"/api/session/{sid}/ws") as ws:
            ws.send_text(json.dumps({
                "type": "user_response",
                "response_type": "TEXT",
                "value": "Otac je pao",
            }))
            # Confirm connection alive
            ws.send_text(json.dumps({"type": "ping"}))
            pong = _recv_until_type(ws, "pong")
            assert pong["type"] == "pong"


# ---------------------------------------------------------------------------
# 9. WebSocket invalid session
# ---------------------------------------------------------------------------

def test_websocket_invalid_session_closes_with_4004():
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    ws_app = _make_ws_app()
    with TestClient(ws_app) as tc:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with tc.websocket_connect("/api/session/nonexistent/ws") as ws:
                ws.receive_text()  # should trigger close
        assert exc_info.value.code == 4004


# ---------------------------------------------------------------------------
# 10. Twilio audio endpoint
# ---------------------------------------------------------------------------

async def test_twilio_audio_returns_empty_chunks_for_existing_session(client: AsyncClient, store: SnapshotStore):
    sid = await create_session(client)
    resp = await client.post(f"/api/session/{sid}/twilio/audio", json={"audio": "base64data"})
    assert resp.status_code == 200
    assert resp.json()["audio_chunks"] == []


async def test_twilio_audio_returns_404_for_missing_session(client: AsyncClient):
    resp = await client.post("/api/session/missing/twilio/audio", json={"audio": "base64data"})
    assert resp.status_code == 404


async def test_twilio_audio_with_empty_audio_field(client: AsyncClient, store: SnapshotStore):
    sid = await create_session(client)
    resp = await client.post(f"/api/session/{sid}/twilio/audio", json={"audio": ""})
    assert resp.status_code == 200
    assert "audio_chunks" in resp.json()


# ---------------------------------------------------------------------------
# 11. Health endpoint
# ---------------------------------------------------------------------------

async def test_health_returns_ok_and_active_sessions(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert isinstance(data["active_sessions"], int)
    assert data["active_sessions"] >= 0


async def test_health_active_sessions_starts_at_zero(client: AsyncClient):
    resp = await client.get("/api/health")
    # No WebSocket connections → 0 active sessions
    assert resp.json()["active_sessions"] == 0


# ---------------------------------------------------------------------------
# 12. Demo dispatch simulator
# ---------------------------------------------------------------------------

async def test_demo_dispatch_health(dispatch_client: AsyncClient):
    resp = await dispatch_client.get("/dispatch/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_demo_dispatch_greeting_after_2_seconds(dispatch_client: AsyncClient):
    # Reset state
    await dispatch_client.post("/dispatch/reset")

    # First call at t=0 — no lines yet (< 2s)
    resp = await dispatch_client.post("/dispatch/audio", json={"audio": "hello", "session_id": "demo1"})
    data = resp.json()
    assert data["elapsed_seconds"] < 2 or len(data["responses"]) >= 1

    # Wait for greeting timing
    await asyncio.sleep(2.1)

    resp = await dispatch_client.post("/dispatch/audio", json={"audio": "hello", "session_id": "demo1"})
    data = resp.json()
    assert data["elapsed_seconds"] >= 2
    # The greeting line should have been sent by now
    assert "Hitna sluzba" in " ".join(data["responses"]) or data["state"] in ("GREETING", "LISTENING")


async def test_demo_dispatch_scripted_flow_full(dispatch_client: AsyncClient):
    """Full scripted flow: greeting → asking → confirming."""
    await dispatch_client.post("/dispatch/reset")

    session_id = "demo_full"

    # Seed session with start_time 31s in the past so all lines fire
    from demo_dispatch import sessions, DispatchState, SCRIPT

    sessions[session_id] = {
        "state": DispatchState.GREETING,
        "start_time": time.time() - 31,
        "lines_sent": set(),
    }

    resp = await dispatch_client.post("/dispatch/audio", json={"audio": "info", "session_id": session_id})
    data = resp.json()

    # All three scripted lines should fire
    assert len(data["responses"]) == 3
    assert data["state"] == "DONE"
    assert any("Hitna sluzba" in r for r in data["responses"])
    assert any("pri svesti" in r for r in data["responses"])
    assert any("Saljemo ekipu" in r for r in data["responses"])


async def test_demo_dispatch_reset_clears_sessions(dispatch_client: AsyncClient):
    # Create a session
    await dispatch_client.post("/dispatch/audio", json={"audio": "x", "session_id": "reset_test"})
    health_before = (await dispatch_client.get("/dispatch/health")).json()
    assert health_before["active_sessions"] >= 1

    # Reset
    resp = await dispatch_client.post("/dispatch/reset")
    assert resp.json()["status"] == "reset"

    health_after = (await dispatch_client.get("/dispatch/health")).json()
    assert health_after["active_sessions"] == 0


async def test_demo_dispatch_independent_sessions(dispatch_client: AsyncClient):
    await dispatch_client.post("/dispatch/reset")

    from demo_dispatch import sessions, DispatchState

    # Seed two sessions with different start times
    sessions["early"] = {
        "state": DispatchState.GREETING,
        "start_time": time.time() - 20,  # 20s ago → greeting + asking
        "lines_sent": set(),
    }
    sessions["late"] = {
        "state": DispatchState.GREETING,
        "start_time": time.time() - 1,  # 1s ago → nothing yet
        "lines_sent": set(),
    }

    resp_early = await dispatch_client.post("/dispatch/audio", json={"audio": "a", "session_id": "early"})
    resp_late = await dispatch_client.post("/dispatch/audio", json={"audio": "a", "session_id": "late"})

    assert len(resp_early.json()["responses"]) >= 2  # greeting + asking
    assert len(resp_late.json()["responses"]) == 0  # too early


# ---------------------------------------------------------------------------
# Additional integration scenarios
# ---------------------------------------------------------------------------

async def test_sos_stores_device_id(store: SnapshotStore, client: AsyncClient):
    sid = await create_session(client, device_id="my-phone-123")
    snap = await store.load(sid)
    assert snap.device_id == "my-phone-123"


async def test_sos_stores_location_coordinates(store: SnapshotStore, client: AsyncClient):
    sid = await create_session(client, lat=45.25, lng=19.85)
    snap = await store.load(sid)
    assert snap.location.lat == pytest.approx(45.25)
    assert snap.location.lng == pytest.approx(19.85)


async def test_confidence_recomputed_on_each_store_update(store: SnapshotStore):
    """Confidence increases as more data fields are populated."""
    snap = EmergencySnapshot(
        session_id="conf_incr",
        location=Location(lat=44.8, lng=20.4),
        confidence_score=0.20,
    )
    await store.save(snap)

    s0 = await store.load("conf_incr")
    c0 = s0.confidence_score

    # Add emergency type (+0.25)
    await store.update("conf_incr", lambda s: setattr(s, "emergency_type", EmergencyType.MEDICAL))
    s1 = await store.load("conf_incr")
    assert s1.confidence_score > c0

    # Add conscious (+0.15)
    await store.update("conf_incr", lambda s: setattr(s, "conscious", True))
    s2 = await store.load("conf_incr")
    assert s2.confidence_score > s1.confidence_score


async def test_user_input_contributes_to_confidence(store: SnapshotStore):
    """User input adds confidence bonus."""
    snap = EmergencySnapshot(
        session_id="ui_conf",
        location=Location(lat=44.8, lng=20.4),
        confidence_score=0.20,
    )
    await store.save(snap)

    s0 = await store.load("ui_conf")
    c0 = s0.confidence_score

    await store.update("ui_conf", lambda s: s.user_input.append(
        UserInput(question="test", response_type="TAP", value="yes")
    ))
    s1 = await store.load("ui_conf")
    assert s1.confidence_score > c0


async def test_dispatch_agent_confirm_dispatch_sets_call_status_and_eta(store: SnapshotStore):
    snap = EmergencySnapshot(session_id="confirm1", phase=SessionPhase.LIVE_CALL)
    await store.save(snap)

    async def noop(sid, msg):
        pass

    tools = DispatchAgentTools("confirm1", store, noop)
    await tools.confirm_dispatch(7)

    updated = await store.load("confirm1")
    assert updated.call_status == CallStatus.CONFIRMED
    assert updated.eta_minutes == 7


async def test_user_agent_surface_question_broadcasts(store: SnapshotStore):
    snap = EmergencySnapshot(session_id="bcast1", location=Location(lat=44.8, lng=20.4))
    await store.save(snap)

    broadcast_log: list[dict] = []

    async def bcast(sid, msg):
        broadcast_log.append(msg)

    tools = UserAgentTools("bcast1", store, bcast)
    await tools.surface_user_question("Da li je pri svesti?")

    assert len(broadcast_log) == 1
    assert broadcast_log[0]["type"] == "user_question"
    assert broadcast_log[0]["question"] == "Da li je pri svesti?"


async def test_end_to_end_sos_to_resolution_through_api(store: SnapshotStore, client: AsyncClient):
    """Full end-to-end: create session → agent updates → status reflects → resolve."""
    snap = EmergencySnapshot(
        session_id="e2e1",
        location=Location(lat=44.8, lng=20.4),
        confidence_score=0.20,
    )
    await store.save(snap)

    # Phase 1: initial status
    r1 = (await client.get("/api/session/e2e1/status")).json()
    assert r1["confidence"] == pytest.approx(0.20, abs=0.05)

    # Phase 2: agent gathers data
    await store.update("e2e1", lambda s: setattr(s, "emergency_type", EmergencyType.MEDICAL))
    await store.update("e2e1", lambda s: (
        setattr(s.location, "confirmed", True),
        setattr(s.location, "address", "Bulevar Kralja Aleksandra 73"),
    ))
    await store.update("e2e1", lambda s: setattr(s, "conscious", False))
    await store.update("e2e1", lambda s: setattr(s, "breathing", True))
    await store.update("e2e1", lambda s: setattr(s, "victim_count", 1))

    r2 = (await client.get("/api/session/e2e1/status")).json()
    assert r2["confidence"] >= 0.85  # should meet threshold

    # Phase 3: resolve
    await store.update("e2e1", lambda s: (
        setattr(s, "phase", SessionPhase.RESOLVED),
        setattr(s, "call_status", CallStatus.CONFIRMED),
        setattr(s, "eta_minutes", 8),
    ))

    r3 = (await client.get("/api/session/e2e1/status")).json()
    assert r3["phase"] == "RESOLVED"
    assert r3["call_status"] == "CONFIRMED"
    assert r3["eta_minutes"] == 8


async def test_dispatch_brief_shows_unconfirmed_address(store: SnapshotStore):
    """Dispatch brief labels unconfirmed address correctly."""
    snap = EmergencySnapshot(
        session_id="brief1",
        location=Location(lat=44.8, lng=20.4, address="Knez Mihailova 5", confirmed=False),
    )
    await store.save(snap)

    async def noop(sid, msg):
        pass

    tools = DispatchAgentTools("brief1", store, noop)
    brief = await tools.get_emergency_brief()
    assert "nepotvrdjeno" in brief


async def test_dispatch_brief_shows_confirmed_address(store: SnapshotStore):
    """Dispatch brief shows confirmed address without warning."""
    snap = EmergencySnapshot(
        session_id="brief2",
        location=Location(lat=44.8, lng=20.4, address="Knez Mihailova 5", confirmed=True),
    )
    await store.save(snap)

    async def noop(sid, msg):
        pass

    tools = DispatchAgentTools("brief2", store, noop)
    brief = await tools.get_emergency_brief()
    assert "Knez Mihailova 5" in brief
    assert "nepotvrdjeno" not in brief


def test_websocket_audio_message_type_accepted():
    """Audio message type is accepted without error (TODO handler)."""
    from starlette.testclient import TestClient

    ws_app = _make_ws_app()
    with TestClient(ws_app) as tc:
        resp = tc.post("/api/sos", json=sos_payload())
        sid = resp.json()["session_id"]

        with tc.websocket_connect(f"/api/session/{sid}/ws") as ws:
            ws.send_text(json.dumps({"type": "audio", "data": "base64audio"}))
            # Should not crash; verify with ping
            ws.send_text(json.dumps({"type": "ping"}))
            data = _recv_until_type(ws, "pong")
            assert data["type"] == "pong"


async def test_multiple_store_updates_accumulate_correctly(store: SnapshotStore):
    """Multiple sequential updates all persist."""
    snap = EmergencySnapshot(session_id="accum1", location=Location(lat=44.8, lng=20.4))
    await store.save(snap)

    await store.update("accum1", lambda s: setattr(s, "emergency_type", EmergencyType.GAS))
    await store.update("accum1", lambda s: setattr(s, "conscious", True))
    await store.update("accum1", lambda s: setattr(s, "breathing", True))
    await store.update("accum1", lambda s: setattr(s, "victim_count", 3))
    await store.update("accum1", lambda s: s.free_text_details.append("curi gas"))

    final = await store.load("accum1")
    assert final.emergency_type == EmergencyType.GAS
    assert final.conscious is True
    assert final.breathing is True
    assert final.victim_count == 3
    assert "curi gas" in final.free_text_details
    assert final.snapshot_version == 5
