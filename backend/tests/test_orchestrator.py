# backend/tests/test_orchestrator.py
import asyncio

import pytest
import fakeredis.aioredis

from orchestrator import SessionOrchestrator
from snapshot import (
    CallStatus,
    EmergencySnapshot,
    EmergencyType,
    Location,
    SessionPhase,
    SnapshotStore,
)


@pytest.fixture
async def store():
    redis = fakeredis.aioredis.FakeRedis()
    s = SnapshotStore(redis)
    yield s
    await redis.aclose()


class FakeBroadcaster:
    def __init__(self):
        self.messages: list[dict] = []

    async def __call__(self, session_id: str, message: dict) -> None:
        self.messages.append(message)


async def test_intake_to_triage(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    broadcaster = FakeBroadcaster()

    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=broadcaster,
        start_agents=False,
    )
    # Run just the intake->triage transition
    await orch._transition_to_triage()

    updated = await store.load("s1")
    assert updated.phase == SessionPhase.TRIAGE
    assert any(m.get("type") == "STATUS_UPDATE" for m in broadcaster.messages)


async def test_triage_timeout_triggers_live_call(store: SnapshotStore):
    import time
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
        created_at=time.time() - 15,  # 15 seconds ago
    )
    await store.save(snap)
    broadcaster = FakeBroadcaster()

    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=broadcaster,
        start_agents=False,
        triage_timeout=10,
    )
    should_transition = await orch._check_triage_complete()
    assert should_transition is True


async def test_confidence_threshold_triggers_live_call(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4, address="Addr", confirmed=True),
        emergency_type=EmergencyType.MEDICAL,
        conscious=False,
        breathing=True,
        confidence_score=0.90,
    )
    await store.save(snap)
    broadcaster = FakeBroadcaster()

    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=broadcaster,
        start_agents=False,
    )
    should_transition = await orch._check_triage_complete()
    assert should_transition is True


async def test_confirmed_call_resolves(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.LIVE_CALL,
        call_status=CallStatus.CONFIRMED,
        eta_minutes=8,
    )
    await store.save(snap)
    broadcaster = FakeBroadcaster()

    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=broadcaster,
        start_agents=False,
    )
    result = await orch._check_call_status()
    assert result == "RESOLVED"
    resolved_msgs = [m for m in broadcaster.messages if m.get("type") == "RESOLVED"]
    assert len(resolved_msgs) == 1
    assert resolved_msgs[0]["eta_minutes"] == 8


import unittest.mock as mock
from audio_bridge import AudioBridge, AudioBridgeRegistry


async def test_orchestrator_accepts_bridge_registry_param():
    """SessionOrchestrator.__init__ must accept bridge_registry kwarg."""
    import inspect
    sig = inspect.signature(SessionOrchestrator.__init__)
    assert "bridge_registry" in sig.parameters
    param = sig.parameters["bridge_registry"]
    assert param.default is None


async def test_orchestrator_creates_bridge_in_registry(store: SnapshotStore):
    """_start_dispatch_agent must call registry.create(session_id) before launching agent."""
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    registry = AudioBridgeRegistry()
    dispatched_bridges = []

    async def mock_run_dispatch_agent(session_id, s, b, bridge=None, **kwargs):
        dispatched_bridges.append(bridge)

    broadcaster = FakeBroadcaster()
    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=broadcaster,
        start_agents=True,
        bridge_registry=registry,
    )

    with mock.patch("dispatch_agent.run_dispatch_agent", mock_run_dispatch_agent):
        await orch._start_dispatch_agent()

    assert registry.get("s1") is not None, "Bridge not in registry"
    assert len(dispatched_bridges) == 1
    assert isinstance(dispatched_bridges[0], AudioBridge)
    assert dispatched_bridges[0] is registry.get("s1")


async def test_orchestrator_no_bridge_registry_passes_none(store: SnapshotStore):
    """When bridge_registry=None, run_dispatch_agent receives bridge=None."""
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    dispatched_bridges = []

    async def mock_run_dispatch_agent(session_id, s, b, bridge=None, **kwargs):
        dispatched_bridges.append(bridge)

    broadcaster = FakeBroadcaster()
    orch = SessionOrchestrator(
        session_id="s1",
        store=store,
        broadcast=broadcaster,
        start_agents=True,
        bridge_registry=None,
    )

    with mock.patch("dispatch_agent.run_dispatch_agent", mock_run_dispatch_agent):
        await orch._start_dispatch_agent()

    assert dispatched_bridges[0] is None
