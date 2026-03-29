# backend/tests/test_livedemo.py
import pytest
import fakeredis.aioredis
from unittest.mock import patch

from snapshot import (
    EmergencySnapshot,
    EmergencyType,
    Location,
    SessionPhase,
    SnapshotStore,
)
from dispatch_agent import (
    DispatchAgentTools,
    _brief_is_sufficient,
    _resolve_brief,
)
from livedemo_briefs import get_livedemo_brief


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def store_with_snapshot():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    snap = EmergencySnapshot(
        session_id="s1",
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8, lng=20.4, address="Knez Mihailova 5", confirmed=True),
        emergency_type=EmergencyType.POLICE,
        conscious=True,
        breathing=True,
        victim_count=2,
        free_text_details=["Armed man threatening another person"],
    )
    await store.save(snap)
    messages = []

    async def broadcast(sid, msg):
        messages.append(msg)

    tools = DispatchAgentTools("s1", store, broadcast)
    yield tools, store
    await redis.aclose()


@pytest.fixture
async def store_empty_snapshot():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    snap = EmergencySnapshot(
        session_id="s2",
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)
    messages = []

    async def broadcast(sid, msg):
        messages.append(msg)

    tools = DispatchAgentTools("s2", store, broadcast)
    yield tools, store
    await redis.aclose()


# ---------------------------------------------------------------------------
# _brief_is_sufficient tests
# ---------------------------------------------------------------------------

def test_brief_is_sufficient_with_details():
    brief = "Type: POLICE | Address: Main St | Details: Armed confrontation"
    assert _brief_is_sufficient(brief) is True


def test_brief_is_insufficient_without_details():
    brief = "Type: POLICE | Address: Main St | Victim count: unknown"
    assert _brief_is_sufficient(brief) is False


def test_brief_is_insufficient_when_empty():
    assert _brief_is_sufficient("") is False


def test_brief_is_insufficient_when_short():
    assert _brief_is_sufficient("Type: unknown") is False


def test_brief_is_insufficient_when_no_session():
    assert _brief_is_sufficient("No session data available.") is False


def test_brief_is_insufficient_when_type_unknown():
    brief = "Type: unknown | Address: Main St | Details: something happened"
    assert _brief_is_sufficient(brief) is False


# ---------------------------------------------------------------------------
# _resolve_brief tests
# ---------------------------------------------------------------------------

async def test_resolve_brief_full_mode(store_with_snapshot):
    tools, store = store_with_snapshot
    with patch("dispatch_agent.get_settings") as mock_settings:
        mock_settings.return_value.livedemo_mode = "full"
        mock_settings.return_value.livedemo_scenario = "armed_threat"
        brief = await _resolve_brief(tools, "s1", store)
    assert "POLICE" in brief
    assert "firearm" in brief
    assert "Knez Mihailova 5" in brief


async def test_resolve_brief_lite_mode_sufficient(store_with_snapshot):
    tools, store = store_with_snapshot
    with patch("dispatch_agent.get_settings") as mock_settings:
        mock_settings.return_value.livedemo_mode = "lite"
        mock_settings.return_value.livedemo_scenario = "armed_threat"
        brief = await _resolve_brief(tools, "s1", store)
    # Real brief should be used since it has Details
    assert "Armed man threatening another person" in brief
    assert "firearm" not in brief  # not the hardcoded one


async def test_resolve_brief_lite_mode_fallback(store_empty_snapshot):
    tools, store = store_empty_snapshot
    with patch("dispatch_agent.get_settings") as mock_settings:
        mock_settings.return_value.livedemo_mode = "lite"
        mock_settings.return_value.livedemo_scenario = "armed_threat"
        brief = await _resolve_brief(tools, "s2", store)
    # Should fall back to hardcoded
    assert "firearm" in brief
    assert "POLICE" in brief


async def test_resolve_brief_off_mode(store_with_snapshot):
    tools, store = store_with_snapshot
    with patch("dispatch_agent.get_settings") as mock_settings:
        mock_settings.return_value.livedemo_mode = "off"
        brief = await _resolve_brief(tools, "s1", store)
    # Real brief returned
    assert "Armed man threatening another person" in brief


async def test_resolve_brief_full_mode_uses_gps_when_no_address():
    redis = fakeredis.aioredis.FakeRedis()
    store = SnapshotStore(redis)
    snap = EmergencySnapshot(
        session_id="s3",
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8176, lng=20.4633),
    )
    await store.save(snap)

    async def broadcast(sid, msg):
        pass

    tools = DispatchAgentTools("s3", store, broadcast)
    with patch("dispatch_agent.get_settings") as mock_settings:
        mock_settings.return_value.livedemo_mode = "full"
        mock_settings.return_value.livedemo_scenario = "armed_threat"
        brief = await _resolve_brief(tools, "s3", store)
    assert "GPS: 44.8176, 20.4633" in brief
    await redis.aclose()


# ---------------------------------------------------------------------------
# livedemo_briefs module tests
# ---------------------------------------------------------------------------

def test_get_livedemo_brief_armed_threat():
    brief = get_livedemo_brief("armed_threat", address="Main Street 1")
    assert "POLICE" in brief
    assert "firearm" in brief
    assert "Main Street 1" in brief


def test_get_livedemo_brief_unknown_scenario():
    with pytest.raises(ValueError, match="Unknown livedemo scenario"):
        get_livedemo_brief("nonexistent_scenario")


def test_get_livedemo_brief_default_address():
    brief = get_livedemo_brief("armed_threat")
    assert "GPS location provided" in brief


# ---------------------------------------------------------------------------
# demo_user_agent armed_threat scenario tests
# ---------------------------------------------------------------------------

def test_armed_threat_scenario_exists():
    from demo_user_agent import SCENARIOS
    assert "armed_threat" in SCENARIOS


def test_armed_threat_scenario_has_police_type():
    from demo_user_agent import SCENARIOS
    script = SCENARIOS["armed_threat"]
    tool_calls = [(a[2][0], a[2][1]) for a in script if a[1] == "tool_call"]
    types = [args for name, args in tool_calls if name == "set_emergency_type"]
    assert any(t["emergency_type"] == "POLICE" for t in types)


def test_armed_threat_answer_map_exists():
    from demo_user_agent import SCENARIO_ANSWER_MAPS
    assert "armed_threat" in SCENARIO_ANSWER_MAPS
    answers = SCENARIO_ANSWER_MAPS["armed_threat"]
    assert len(answers) > 0
