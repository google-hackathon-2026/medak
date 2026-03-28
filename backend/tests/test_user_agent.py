# backend/tests/test_user_agent.py
import pytest
import fakeredis.aioredis

from snapshot import (
    EmergencySnapshot,
    EmergencyType,
    Location,
    SnapshotStore,
)
from user_agent import UserAgentTools


@pytest.fixture
async def setup():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    messages = []

    async def broadcast(sid, msg):
        messages.append(msg)

    tools = UserAgentTools("s1", store, broadcast)
    yield tools, store, messages
    await redis.aclose()


async def test_confirm_location(setup):
    tools, store, _ = setup
    result = await tools.confirm_location("Knez Mihailova 5, Beograd")
    assert "confirmed" in result.lower()
    snap = await store.load("s1")
    assert snap.location.confirmed is True
    assert snap.location.address == "Knez Mihailova 5, Beograd"


async def test_set_emergency_type(setup):
    tools, store, _ = setup
    result = await tools.set_emergency_type("MEDICAL")
    snap = await store.load("s1")
    assert snap.emergency_type == EmergencyType.MEDICAL


async def test_set_clinical_fields(setup):
    tools, store, _ = setup
    await tools.set_clinical_fields(conscious=False, breathing=True, victim_count=2)
    snap = await store.load("s1")
    assert snap.conscious is False
    assert snap.breathing is True
    assert snap.victim_count == 2


async def test_append_free_text(setup):
    tools, store, _ = setup
    await tools.append_free_text("otac pao niz stepenice")
    snap = await store.load("s1")
    assert "otac pao niz stepenice" in snap.free_text_details


async def test_dispatch_question_flow(setup):
    tools, store, _ = setup
    # Initially no questions
    result = await tools.get_pending_dispatch_question()
    assert result == "NONE"

    # Simulate dispatch agent queuing a question
    await store.update("s1", lambda s: s.dispatch_questions.append("Da li je pri svesti?"))

    # Now there should be a pending question
    result = await tools.get_pending_dispatch_question()
    assert result == "Da li je pri svesti?"

    # Answer it
    await tools.answer_dispatch_question("Da li je pri svesti?", "Ne, nije pri svesti")
    snap = await store.load("s1")
    assert "Da li je pri svesti?|Ne, nije pri svesti" in snap.ua_answers


async def test_surface_user_question(setup):
    tools, _, messages = setup
    await tools.surface_user_question("Da li je pacijent pri svesti?")
    question_msgs = [m for m in messages if m.get("type") == "user_question"]
    assert len(question_msgs) == 1
    assert question_msgs[0]["question"] == "Da li je pacijent pri svesti?"
