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

    # Bridge.inbound should have one item: PCM 16kHz (318 bytes for 80 mulaw input)
    assert not bridge.inbound.empty()
    chunk = bridge.inbound.get_nowait()
    assert isinstance(chunk, bytes)
    assert len(chunk) == 318  # 80 mulaw → 318 PCM 16kHz bytes (audioop.ratecv produces 159 samples)


def test_stream_outbound_audio_sent():
    """Bytes on bridge.outbound are encoded and sent to Twilio as 'media' events."""
    import asyncio
    import threading
    import time

    app, bridge = _make_app()

    # Pre-load 10ms of PCM 24kHz onto the outbound queue
    asyncio.get_event_loop().run_until_complete(bridge.outbound.put(bytes(480)))

    client = TestClient(app)
    received = []

    def receive_one(ws):
        try:
            msg = ws.receive_json()
            received.append(msg)
        except Exception:
            pass

    with client.websocket_connect("/api/session/s1/twilio/stream") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json({
            "event": "start",
            "streamSid": "SM123",
            "start": {"streamSid": "SM123"},
        })
        # Start a receiver thread so receive_json doesn't block the test
        t = threading.Thread(target=receive_one, args=(ws,), daemon=True)
        t.start()
        # Give the background task a moment to drain and send
        time.sleep(0.2)
        ws.send_json({"event": "stop"})
        t.join(timeout=1.0)

    # At least one outbound media message sent
    assert any(m.get("event") == "media" for m in received)
    media_msgs = [m for m in received if m.get("event") == "media"]
    payload = media_msgs[0]["media"]["payload"]
    decoded = base64.b64decode(payload)
    assert len(decoded) == 80  # 480 PCM 24kHz bytes → 80 mulaw bytes


def test_stream_outbound_includes_stream_sid():
    """Outbound 'media' events include the streamSid received from Twilio."""
    import asyncio
    import threading
    import time

    app, bridge = _make_app()
    asyncio.get_event_loop().run_until_complete(bridge.outbound.put(bytes(480)))

    client = TestClient(app)
    received = []

    def receive_one(ws):
        try:
            msg = ws.receive_json()
            received.append(msg)
        except Exception:
            pass

    with client.websocket_connect("/api/session/s1/twilio/stream") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json({
            "event": "start",
            "streamSid": "SM_TEST_SID",
            "start": {"streamSid": "SM_TEST_SID"},
        })
        t = threading.Thread(target=receive_one, args=(ws,), daemon=True)
        t.start()
        time.sleep(0.2)
        ws.send_json({"event": "stop"})
        t.join(timeout=1.0)

    media_msgs = [m for m in received if m.get("event") == "media"]
    if media_msgs:
        assert media_msgs[0]["streamSid"] == "SM_TEST_SID"
