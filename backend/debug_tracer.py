# backend/debug_tracer.py
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from snapshot import EmergencySnapshot, SnapshotStore

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent / "debug_traces"


def _epoch_ms() -> int:
    return int(time.time_ns() // 1_000_000)


class DebugTracer:
    """Writes debug artifacts to disk for a single emergency session.

    Every public method is async and fire-and-forget safe — exceptions are
    caught and logged, never propagated to the emergency pipeline.
    """

    def __init__(self, session_id: str, base_dir: Path = BASE_DIR) -> None:
        self.session_id = session_id
        self._dir = base_dir / session_id
        self._timeline: list[dict] = []
        self._counts: dict[str, int] = {}
        self._started_at = time.time()

        # JSONL file locks
        self._ws_lock = asyncio.Lock()
        self._phase_lock = asyncio.Lock()

        # Create all subdirectories up-front (synchronous, one-time)
        for sub in ("frames", "audio", "snapshots", "gemini", "tools", "ws", "dispatch", "phases"):
            (self._dir / sub).mkdir(parents=True, exist_ok=True)

    def _record_event(self, event_type: str, detail: str = "") -> None:
        self._timeline.append({
            "ts": _epoch_ms(),
            "event": event_type,
            "detail": detail,
        })
        self._counts[event_type] = self._counts.get(event_type, 0) + 1

    async def _write_bytes(self, path: Path, data: bytes) -> None:
        await asyncio.to_thread(path.write_bytes, data)

    async def _write_text(self, path: Path, text: str) -> None:
        await asyncio.to_thread(path.write_text, text, "utf-8")

    async def _append_text(self, path: Path, line: str, lock: asyncio.Lock) -> None:
        async with lock:
            await asyncio.to_thread(_append_line, path, line)

    # --- Public API ---

    async def save_video_frame(self, jpeg_bytes: bytes) -> None:
        ts = _epoch_ms()
        self._record_event("video_frame", f"frame_{ts}.jpg")
        try:
            await self._write_bytes(self._dir / "frames" / f"frame_{ts}.jpg", jpeg_bytes)
        except Exception:
            logger.warning("DebugTracer: failed to save video frame", exc_info=True)

    async def save_audio_chunk(self, pcm_bytes: bytes) -> None:
        ts = _epoch_ms()
        self._record_event("audio_chunk", f"chunk_{ts}.pcm")
        try:
            await self._write_bytes(self._dir / "audio" / f"chunk_{ts}.pcm", pcm_bytes)
        except Exception:
            logger.warning("DebugTracer: failed to save audio chunk", exc_info=True)

    async def save_snapshot(self, snapshot: EmergencySnapshot) -> None:
        ver = snapshot.snapshot_version
        self._record_event("snapshot", f"v{ver}")
        try:
            data = snapshot.model_dump_json(indent=2)
            await self._write_text(
                self._dir / "snapshots" / f"snapshot_v{ver}.json", data
            )
        except Exception:
            logger.warning("DebugTracer: failed to save snapshot", exc_info=True)

    async def save_gemini_input(
        self,
        agent: str,
        payload: dict,
        image_bytes: bytes | None = None,
    ) -> None:
        ts = _epoch_ms()
        self._record_event("gemini_input", f"{agent}_input_{ts}")
        try:
            await self._write_text(
                self._dir / "gemini" / f"{agent}_input_{ts}.json",
                json.dumps(payload, indent=2, default=str),
            )
            if image_bytes is not None:
                await self._write_bytes(
                    self._dir / "gemini" / f"{agent}_input_{ts}_image.jpg",
                    image_bytes,
                )
        except Exception:
            logger.warning("DebugTracer: failed to save gemini input", exc_info=True)

    async def save_gemini_output(self, agent: str, payload: dict) -> None:
        ts = _epoch_ms()
        self._record_event("gemini_output", f"{agent}_output_{ts}")
        try:
            await self._write_text(
                self._dir / "gemini" / f"{agent}_output_{ts}.json",
                json.dumps(payload, indent=2, default=str),
            )
        except Exception:
            logger.warning("DebugTracer: failed to save gemini output", exc_info=True)

    async def save_tool_call(self, name: str, args: dict, result: str) -> None:
        ts = _epoch_ms()
        self._record_event("tool_call", name)
        try:
            await self._write_text(
                self._dir / "tools" / f"tool_{ts}_{name}.json",
                json.dumps({"name": name, "args": args, "result": result}, indent=2, default=str),
            )
        except Exception:
            logger.warning("DebugTracer: failed to save tool call", exc_info=True)

    async def log_ws_message(self, direction: str, msg: dict) -> None:
        self._record_event("ws_message", direction)
        try:
            line = json.dumps({"ts": _epoch_ms(), "dir": direction, "msg": msg}, default=str)
            await self._append_text(self._dir / "ws" / "ws_log.jsonl", line, self._ws_lock)
        except Exception:
            logger.warning("DebugTracer: failed to log ws message", exc_info=True)

    async def save_dispatch_brief(self, brief_text: str) -> None:
        self._record_event("dispatch_brief")
        try:
            await self._write_text(self._dir / "dispatch" / "brief.txt", brief_text)
        except Exception:
            logger.warning("DebugTracer: failed to save dispatch brief", exc_info=True)

    async def log_phase_transition(self, from_phase: str, to_phase: str) -> None:
        self._record_event("phase_transition", f"{from_phase} -> {to_phase}")
        try:
            line = json.dumps({"ts": _epoch_ms(), "from": from_phase, "to": to_phase})
            await self._append_text(
                self._dir / "phases" / "transitions.jsonl", line, self._phase_lock
            )
        except Exception:
            logger.warning("DebugTracer: failed to log phase transition", exc_info=True)

    async def write_summary(self) -> None:
        try:
            summary = {
                "session_id": self.session_id,
                "started_at": datetime.fromtimestamp(self._started_at, tz=timezone.utc).isoformat(),
                "ended_at": datetime.now(tz=timezone.utc).isoformat(),
                "duration_seconds": round(time.time() - self._started_at, 1),
                "counts": dict(self._counts),
                "timeline": self._timeline,
            }
            await self._write_text(
                self._dir / "summary.json",
                json.dumps(summary, indent=2, default=str),
            )
        except Exception:
            logger.warning("DebugTracer: failed to write summary", exc_info=True)


def _append_line(path: Path, line: str) -> None:
    """Synchronous line append — called via asyncio.to_thread."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# --- Registry ---

class TracerRegistry:
    """Maps session_id -> DebugTracer. Stored on app.state."""

    def __init__(self) -> None:
        self._tracers: dict[str, DebugTracer] = {}

    def register(self, session_id: str, tracer: DebugTracer) -> None:
        self._tracers[session_id] = tracer

    def get(self, session_id: str) -> DebugTracer | None:
        return self._tracers.get(session_id)

    def remove(self, session_id: str) -> None:
        self._tracers.pop(session_id, None)


# --- TracingSnapshotStore ---

from snapshot import SnapshotStore


class TracingSnapshotStore(SnapshotStore):
    """Wraps SnapshotStore to automatically trace every update."""

    def __init__(self, redis, tracer_registry: TracerRegistry) -> None:
        super().__init__(redis)
        self._tracer_registry = tracer_registry

    async def update(self, session_id, updater):
        snapshot = await super().update(session_id, updater)
        tracer = self._tracer_registry.get(session_id)
        if tracer:
            await tracer.save_snapshot(snapshot)
        return snapshot


# --- Factory ---

def create_tracer(session_id: str) -> DebugTracer | None:
    """Returns a DebugTracer if DEBUG_TRACE is enabled, else None."""
    from config import get_settings
    if get_settings().debug_trace:
        return DebugTracer(session_id)
    return None
