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
