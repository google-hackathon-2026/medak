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
