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
