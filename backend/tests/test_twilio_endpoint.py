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
