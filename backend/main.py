# backend/main.py
from __future__ import annotations

import json
import logging
import uuid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from fastapi import FastAPI, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from audio_bridge import AudioBridgeRegistry
from config import get_settings
from snapshot import (
    EmergencySnapshot,
    Location,
    SessionPhase,
    SnapshotStore,
    UserInput,
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
    app.state.bridge_registry = bridge_registry  # used by Twilio Media Streams WebSocket

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

        from orchestrator import SessionOrchestrator
        import asyncio
        orch = SessionOrchestrator(
            session_id=session_id,
            store=store,
            broadcast=registry.broadcast,
            bridge_registry=app.state.bridge_registry,
        )
        asyncio.create_task(orch.run())

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
        await ws.accept()
        snapshot = await store.load(session_id)
        if snapshot is None:
            await ws.close(code=4004, reason="Session not found")
            return

        await registry.add(session_id, ws)

        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))

                elif msg_type == "audio":
                    # TODO: forward to User Agent (Task 6)
                    pass

                elif msg_type == "video_frame":
                    # TODO: forward to User Agent (Task 6)
                    pass

                elif msg_type == "user_response":
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

    @app.post("/api/session/{session_id}/twilio/twiml")
    async def twilio_twiml(session_id: str) -> Response:
        snapshot = await store.load(session_id)
        if snapshot is None:
            return JSONResponse(status_code=404, content={"error": "Session not found"})
        base = settings.backend_base_url.removeprefix("https://").removeprefix("http://")
        stream_url = f"wss://{base}/api/session/{session_id}/twilio/stream"
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            "<Connect>"
            f'<Stream url="{stream_url}"/>'
            "</Connect>"
            "</Response>"
        )
        return Response(content=twiml, media_type="text/xml")

    @app.post("/api/session/{session_id}/twilio/status")
    async def twilio_status(
        session_id: str,
        CallStatus: str = Form(""),  # must match Twilio's exact field name casing
    ) -> dict:
        from snapshot import CallStatus as CS
        # "queued" and "ringing" are intentionally omitted — they don't map to
        # a meaningful internal state change; treated as no-ops.
        STATUS_MAP = {
            "in-progress": "CONNECTED",
            "completed": "DROPPED",
            "failed": "DROPPED",
            "busy": "DROPPED",
            "no-answer": "DROPPED",
        }
        new_status = STATUS_MAP.get(CallStatus)
        if new_status is not None:
            cs = CS(new_status)
            try:
                await store.update(session_id, lambda s: setattr(s, "call_status", cs))
            except KeyError:
                # Session doesn't exist; no-op
                pass
        return {"ok": True}

    @app.websocket("/api/session/{session_id}/twilio/stream")
    async def twilio_stream(ws: WebSocket, session_id: str) -> None:
        from audio_bridge import ulaw8k_to_pcm16k, pcm24k_to_ulaw8k
        import base64
        import asyncio

        bridge = app.state.bridge_registry.get(session_id)
        if bridge is None:
            await ws.accept()
            await ws.close(code=4004, reason="No bridge for session")
            return

        await ws.accept()

        async def send_outbound() -> None:
            """Drain bridge.outbound and forward encoded audio to Twilio."""
            # Wait until the 'start' event has been received and stream_sid is set
            try:
                await asyncio.wait_for(bridge._connected.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                return
            except asyncio.CancelledError:
                return
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

    return app


app = create_app()
