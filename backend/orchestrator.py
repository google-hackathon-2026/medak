# backend/orchestrator.py
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Awaitable

from audio_bridge import AudioBridgeRegistry
from config import get_settings
from user_agent import UserMediaRegistry
from snapshot import (
    CallStatus,
    EmergencySnapshot,
    SessionPhase,
    SnapshotStore,
)

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, dict], Awaitable[None]]


class SessionOrchestrator:
    def __init__(
        self,
        session_id: str,
        store: SnapshotStore,
        broadcast: BroadcastFn,
        start_agents: bool = True,
        triage_timeout: int | None = None,
        confidence_threshold: float | None = None,
        max_reconnects: int | None = None,
        bridge_registry: AudioBridgeRegistry | None = None,
        user_media_registry: UserMediaRegistry | None = None,
        tracer: "DebugTracer | None" = None,
    ) -> None:
        self.session_id = session_id
        self.store = store
        self.broadcast = broadcast
        self.start_agents = start_agents
        self.bridge_registry = bridge_registry
        self.user_media_registry = user_media_registry
        self.tracer = tracer

        settings = get_settings()
        self.triage_timeout = triage_timeout if triage_timeout is not None else settings.triage_timeout_seconds
        self.confidence_threshold = confidence_threshold if confidence_threshold is not None else settings.confidence_threshold
        self.max_reconnects = max_reconnects if max_reconnects is not None else settings.reconnect_max_attempts

        self._user_agent_task: asyncio.Task | None = None
        self._dispatch_agent_task: asyncio.Task | None = None

    async def _is_ended(self) -> bool:
        snap = await self.store.load(self.session_id)
        return snap is None or snap.phase in (SessionPhase.FAILED, SessionPhase.RESOLVED)

    async def run(self) -> None:
        try:
            await self._transition_to_triage()
            await self._run_triage_loop()
            if await self._is_ended():
                return
            await self._transition_to_live_call()
            await self._run_live_call_loop()
        except Exception:
            logger.exception("Orchestrator error for session %s", self.session_id)
            await self._transition_to_failed("Internal error")
        finally:
            # FIX: Cancel any running agent tasks to prevent ghost coroutines
            for task in (self._user_agent_task, self._dispatch_agent_task):
                if task is not None and not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
            # Clean up registries
            if self.bridge_registry is not None:
                self.bridge_registry.remove(self.session_id)
            if self.user_media_registry is not None:
                self.user_media_registry.remove(self.session_id)
            if self.tracer:
                await self.tracer.write_summary()

    async def _transition_to_triage(self) -> None:
        await self.store.update(self.session_id, lambda s: setattr(s, "phase", SessionPhase.TRIAGE))
        snap = await self.store.load(self.session_id)
        await self.broadcast(self.session_id, {
            "type": "STATUS_UPDATE",
            "phase": "TRIAGE",
            "confidence": snap.confidence_score,
        })
        logger.info("Session %s: INTAKE -> TRIAGE", self.session_id)
        if self.tracer:
            await self.tracer.log_phase_transition("INTAKE", "TRIAGE")

        if self.start_agents:
            await self._start_user_agent()

    async def _run_triage_loop(self) -> None:
        last_confidence = None
        while True:
            if await self._check_triage_complete():
                break
            snap = await self.store.load(self.session_id)
            if snap.confidence_score != last_confidence:
                await self.broadcast(self.session_id, {
                    "type": "STATUS_UPDATE",
                    "phase": "TRIAGE",
                    "confidence": snap.confidence_score,
                })
                last_confidence = snap.confidence_score
            await asyncio.sleep(1)

    async def _check_triage_complete(self) -> bool:
        snap = await self.store.load(self.session_id)
        if snap is None:
            return True

        if snap.phase == SessionPhase.FAILED:
            logger.info("Session %s: ended by user during triage", self.session_id)
            return True

        if snap.confidence_score >= self.confidence_threshold:
            logger.info(
                "Session %s: confidence %.2f >= threshold",
                self.session_id, snap.confidence_score,
            )
            return True

        elapsed = time.time() - snap.created_at
        if elapsed >= self.triage_timeout:
            logger.info(
                "Session %s: triage timeout (%.1fs elapsed)",
                self.session_id, elapsed,
            )
            return True

        return False

    async def _transition_to_live_call(self) -> None:
        snap = await self.store.update(
            self.session_id,
            lambda s: setattr(s, "phase", SessionPhase.LIVE_CALL),
        )
        await self.broadcast(self.session_id, {
            "type": "STATUS_UPDATE",
            "phase": "LIVE_CALL",
            "confidence": snap.confidence_score,
        })
        logger.info("Session %s: TRIAGE -> LIVE_CALL", self.session_id)
        if self.tracer:
            await self.tracer.log_phase_transition("TRIAGE", "LIVE_CALL")

        if self.start_agents:
            await self._start_dispatch_agent()

    async def _run_live_call_loop(self) -> None:
        reconnect_count = 0
        while True:
            if await self._is_ended():
                return
            result = await self._check_call_status()
            if result == "RESOLVED":
                return
            if result == "DROPPED":
                reconnect_count += 1
                if reconnect_count >= self.max_reconnects:
                    await self._transition_to_failed(
                        "Call failed after all retry attempts"
                    )
                    return
                # Reset status BEFORE reconnecting to prevent duplicate detection
                await self.store.update(
                    self.session_id,
                    lambda s: setattr(s, "call_status", CallStatus.DIALING),
                )
                delay = 2 ** reconnect_count
                logger.warning(
                    "Session %s: call dropped, retry %d in %ds",
                    self.session_id, reconnect_count, delay,
                )
                await asyncio.sleep(delay)
                if self.start_agents:
                    await self._start_dispatch_agent()
            await asyncio.sleep(2)

    async def _check_call_status(self) -> str | None:
        snap = await self.store.load(self.session_id)
        if snap is None:
            return "RESOLVED"

        if snap.call_status == CallStatus.CONFIRMED:
            await self.store.update(
                self.session_id,
                lambda s: setattr(s, "phase", SessionPhase.RESOLVED),
            )
            await self.broadcast(self.session_id, {
                "type": "RESOLVED",
                "eta_minutes": snap.eta_minutes or 0,
                "message": "Help is on the way!",
            })
            logger.info("Session %s: LIVE_CALL -> RESOLVED", self.session_id)
            if self.tracer:
                await self.tracer.log_phase_transition("LIVE_CALL", "RESOLVED")
            return "RESOLVED"

        if snap.call_status == CallStatus.COMPLETED:
            await self.store.update(
                self.session_id,
                lambda s: setattr(s, "phase", SessionPhase.RESOLVED),
            )
            await self.broadcast(self.session_id, {
                "type": "RESOLVED",
                "eta_minutes": snap.eta_minutes or 0,
                "message": "Call completed.",
            })
            logger.info("Session %s: LIVE_CALL -> RESOLVED (call completed)", self.session_id)
            if self.tracer:
                await self.tracer.log_phase_transition("LIVE_CALL", "RESOLVED")
            return "RESOLVED"

        if snap.call_status == CallStatus.DROPPED:
            return "DROPPED"

        return None

    async def _transition_to_failed(self, reason: str) -> None:
        await self.store.update(self.session_id, lambda s: (
            setattr(s, "phase", SessionPhase.FAILED),
        ))
        await self.broadcast(self.session_id, {
            "type": "FAILED",
            "message": reason,
        })
        logger.error("Session %s: -> FAILED: %s", self.session_id, reason)
        if self.tracer:
            await self.tracer.log_phase_transition("*", "FAILED")

    def _launch_agent(self, name: str, coro) -> asyncio.Task:
        async def _run() -> None:
            try:
                await coro
            except Exception:
                logger.exception("%s crashed for session %s", name, self.session_id)
        return asyncio.create_task(_run())

    async def _start_user_agent(self) -> None:
        settings = get_settings()
        if settings.demo_mode:
            from demo_user_agent import run_demo_user_agent
            self._user_agent_task = self._launch_agent(
                "Demo User Agent",
                run_demo_user_agent(
                    self.session_id, self.store, self.broadcast,
                    scenario=settings.demo_scenario,
                ),
            )
        else:
            from user_agent import run_user_agent

            media_relay = None
            if self.user_media_registry is not None:
                media_relay = self.user_media_registry.create(self.session_id)

            self._user_agent_task = self._launch_agent(
                "User Agent",
                run_user_agent(self.session_id, self.store, self.broadcast, media_relay=media_relay, tracer=self.tracer),
            )

    async def _start_dispatch_agent(self) -> None:
        # Cancel any still-running previous dispatch agent
        if self._dispatch_agent_task is not None and not self._dispatch_agent_task.done():
            self._dispatch_agent_task.cancel()
            try:
                await self._dispatch_agent_task
            except asyncio.CancelledError:
                pass
            logger.info("Session %s: cancelled previous dispatch agent", self.session_id)

        settings = get_settings()
        if settings.demo_mode:
            from demo_dispatch_agent import run_demo_dispatch_agent
            self._dispatch_agent_task = self._launch_agent(
                "Demo Dispatch Agent",
                run_demo_dispatch_agent(self.session_id, self.store, self.broadcast),
            )
        else:
            from dispatch_agent import run_dispatch_agent

            bridge = None
            if self.bridge_registry is not None:
                bridge = self.bridge_registry.create(self.session_id)

            self._dispatch_agent_task = self._launch_agent(
                "Dispatch Agent",
                run_dispatch_agent(self.session_id, self.store, self.broadcast, bridge=bridge, tracer=self.tracer),
            )
            await asyncio.sleep(0)  # yield to let the task start
