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
