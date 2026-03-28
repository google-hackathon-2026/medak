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

        # TODO: launch orchestrator as background task (Task 5)

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
                    # TODO: forward to User Agent (Task 6)
                    pass

                elif msg_type == "video_frame":
                    # TODO: forward to User Agent (Task 6)
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
