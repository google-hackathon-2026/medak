# backend/tests/test_dispatch_agent.py
import pytest
import fakeredis.aioredis

from snapshot import (
    CallStatus,
    EmergencySnapshot,
    EmergencyType,
    Location,
    SessionPhase,
    SnapshotStore,
)
from dispatch_agent import DispatchAgentTools


@pytest.fixture
async def setup():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8, lng=20.4, address="Knez Mihailova 5", confirmed=True),
        emergency_type=EmergencyType.MEDICAL,
        conscious=False,
        breathing=True,
        victim_count=1,
        free_text_details=["otac pao niz stepenice", "krv na glavi"],
    )
    await store.save(snap)
    messages = []

    async def broadcast(sid, msg):
        messages.append(msg)

    tools = DispatchAgentTools("s1", store, broadcast)
    yield tools, store, messages
    await redis.aclose()


async def test_get_emergency_brief(setup):
    tools, _, _ = setup
    brief = await tools.get_emergency_brief()
    assert "MEDICAL" in brief
    assert "Knez Mihailova 5" in brief
    assert "1" in brief  # victim count


async def test_queue_question_for_user(setup):
    tools, store, _ = setup
    await tools.queue_question_for_user("Da li je pri svesti?")
    snap = await store.load("s1")
    assert "Da li je pri svesti?" in snap.dispatch_questions


async def test_get_user_answer_pending(setup):
    tools, _, _ = setup
    result = await tools.get_user_answer("Da li je pri svesti?")
    assert result == "PENDING"


async def test_get_user_answer_found(setup):
    tools, store, _ = setup
    await store.update("s1", lambda s: s.ua_answers.append("Da li je pri svesti?|Ne"))
    result = await tools.get_user_answer("Da li je pri svesti?")
    assert result == "Ne"


async def test_update_call_status(setup):
    tools, store, _ = setup
    await tools.update_call_status("CONNECTED")
    snap = await store.load("s1")
    assert snap.call_status == CallStatus.CONNECTED


async def test_confirm_dispatch(setup):
    tools, store, messages = setup
    await tools.confirm_dispatch(8)
    snap = await store.load("s1")
    assert snap.call_status == CallStatus.CONFIRMED
    assert snap.eta_minutes == 8


def test_run_dispatch_agent_accepts_bridge_none_kwarg():
    """run_dispatch_agent must accept bridge=None without raising TypeError."""
    from dispatch_agent import run_dispatch_agent
    import inspect
    sig = inspect.signature(run_dispatch_agent)
    assert "bridge" in sig.parameters
    param = sig.parameters["bridge"]
    # Default must be None so callers without bridge= still work
    assert param.default is None
