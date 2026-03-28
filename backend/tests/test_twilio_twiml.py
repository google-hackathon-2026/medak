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


async def test_twiml_stream_url_uses_wss_scheme(client_with_session):
    resp = await client_with_session.post("/api/session/s1/twilio/twiml")
    assert 'url="wss://' in resp.text
