# backend/tests/test_unit_comprehensive.py
"""
Comprehensive unit tests for the Medak emergency relay backend.

Tests behavior through public interfaces only.
Uses fakeredis — no external dependencies.
"""
from __future__ import annotations

import pytest
import fakeredis.aioredis

from snapshot import (
    CallStatus,
    Conflict,
    EmergencySnapshot,
    EmergencyType,
    Location,
    SessionPhase,
    SnapshotStore,
    UserInput,
    compute_confidence,
    SNAPSHOT_TTL,
)
from user_agent import UserAgentTools
from dispatch_agent import DispatchAgentTools
from config import Settings


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

def _make_snapshot(**overrides) -> EmergencySnapshot:
    """Factory for EmergencySnapshot with sensible defaults."""
    defaults = {"session_id": "test-session"}
    defaults.update(overrides)
    return EmergencySnapshot(**defaults)


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def store(redis):
    return SnapshotStore(redis)


@pytest.fixture
async def user_tools(store):
    """UserAgentTools with a pre-saved GPS-only snapshot and a broadcast spy."""
    snap = _make_snapshot(location=Location(lat=44.8, lng=20.4))
    await store.save(snap)
    messages: list[dict] = []

    async def broadcast(sid, msg):
        messages.append(msg)

    tools = UserAgentTools("test-session", store, broadcast)
    return tools, store, messages


@pytest.fixture
async def dispatch_tools(store):
    """DispatchAgentTools with a rich snapshot and a broadcast spy."""
    snap = _make_snapshot(
        phase=SessionPhase.LIVE_CALL,
        location=Location(lat=44.8, lng=20.4, address="Knez Mihailova 5", confirmed=True),
        emergency_type=EmergencyType.MEDICAL,
        conscious=False,
        breathing=True,
        victim_count=1,
        free_text_details=["otac pao niz stepenice", "krv na glavi"],
    )
    await store.save(snap)
    messages: list[dict] = []

    async def broadcast(sid, msg):
        messages.append(msg)

    tools = DispatchAgentTools("test-session", store, broadcast)
    return tools, store, messages


# ===========================================================================
# 1. EmergencySnapshot model
# ===========================================================================

class TestEmergencySnapshot:
    """Tests for field defaults, enum values, and serialization."""

    def test_defaults(self):
        snap = _make_snapshot()
        assert snap.phase == SessionPhase.INTAKE
        assert snap.snapshot_version == 0
        assert snap.device_id is None
        assert snap.location.lat is None
        assert snap.location.lng is None
        assert snap.location.address is None
        assert snap.location.confirmed is False
        assert snap.emergency_type is None
        assert snap.victim_count is None
        assert snap.conscious is None
        assert snap.breathing is None
        assert snap.free_text_details == []
        assert snap.user_input == []
        assert snap.input_conflicts == []
        assert snap.confidence_score == 0.0
        assert snap.dispatch_questions == []
        assert snap.ua_answers == []
        assert snap.call_status == CallStatus.IDLE
        assert snap.eta_minutes is None

    def test_created_at_is_positive(self):
        snap = _make_snapshot()
        assert snap.created_at > 0

    def test_session_phase_values(self):
        assert set(SessionPhase) == {"INTAKE", "TRIAGE", "LIVE_CALL", "RESOLVED", "FAILED"}

    def test_emergency_type_values(self):
        assert set(EmergencyType) == {"MEDICAL", "FIRE", "POLICE", "GAS", "OTHER"}

    def test_call_status_values(self):
        assert set(CallStatus) == {"IDLE", "DIALING", "CONNECTED", "CONFIRMED", "DROPPED", "COMPLETED"}

    def test_roundtrip_json_serialization(self):
        snap = _make_snapshot(
            location=Location(lat=1.0, lng=2.0, address="Addr", confirmed=True),
            emergency_type=EmergencyType.FIRE,
            victim_count=3,
            conscious=True,
            breathing=False,
            free_text_details=["detail1"],
            user_input=[UserInput(question="q", response_type="TAP", value="DA")],
            input_conflicts=[Conflict(field="conscious", env_value="true", user_value="false")],
            call_status=CallStatus.CONNECTED,
            eta_minutes=5,
        )
        json_str = snap.model_dump_json()
        restored = EmergencySnapshot.model_validate_json(json_str)
        assert restored.session_id == snap.session_id
        assert restored.location.address == "Addr"
        assert restored.emergency_type == EmergencyType.FIRE
        assert restored.victim_count == 3
        assert restored.conscious is True
        assert restored.breathing is False
        assert restored.call_status == CallStatus.CONNECTED
        assert restored.eta_minutes == 5
        assert len(restored.user_input) == 1
        assert len(restored.input_conflicts) == 1

    def test_each_list_field_is_independent_instance(self):
        a = _make_snapshot()
        b = _make_snapshot()
        a.free_text_details.append("x")
        assert b.free_text_details == []  # no shared mutable state

    def test_location_model_defaults(self):
        loc = Location()
        assert loc.lat is None
        assert loc.lng is None
        assert loc.address is None
        assert loc.confirmed is False

    def test_user_input_model(self):
        ui = UserInput(question="q1", response_type="TAP", value="DA")
        assert ui.question == "q1"
        assert ui.response_type == "TAP"
        assert ui.value == "DA"

    def test_conflict_model(self):
        c = Conflict(field="breathing", env_value="true", user_value="false")
        assert c.field == "breathing"
        assert c.env_value == "true"
        assert c.user_value == "false"

    def test_conflict_model_optional_values(self):
        c = Conflict(field="location")
        assert c.env_value is None
        assert c.user_value is None


# ===========================================================================
# 2. compute_confidence()
# ===========================================================================

class TestComputeConfidence:
    """Exhaustive tests for the confidence scoring function."""

    def test_empty_snapshot_scores_zero(self):
        assert compute_confidence(_make_snapshot()) == 0.0

    # --- Location contribution ---

    def test_gps_only_adds_020(self):
        snap = _make_snapshot(location=Location(lat=44.8, lng=20.4))
        assert compute_confidence(snap) == 0.20

    def test_confirmed_address_adds_035(self):
        snap = _make_snapshot(
            location=Location(lat=44.8, lng=20.4, address="Addr", confirmed=True),
        )
        assert compute_confidence(snap) == 0.35

    def test_confirmed_without_address_falls_to_gps(self):
        """confirmed=True but address=None → should fall through to GPS branch."""
        snap = _make_snapshot(
            location=Location(lat=44.8, lng=20.4, confirmed=True),
        )
        assert compute_confidence(snap) == 0.20

    def test_address_without_confirmed_falls_to_gps(self):
        """address set but confirmed=False → GPS branch."""
        snap = _make_snapshot(
            location=Location(lat=44.8, lng=20.4, address="Addr", confirmed=False),
        )
        assert compute_confidence(snap) == 0.20

    def test_only_lat_no_lng_scores_zero_location(self):
        snap = _make_snapshot(location=Location(lat=44.8))
        assert compute_confidence(snap) == 0.0

    def test_only_lng_no_lat_scores_zero_location(self):
        snap = _make_snapshot(location=Location(lng=20.4))
        assert compute_confidence(snap) == 0.0

    # --- Emergency type contribution ---

    def test_emergency_type_adds_025(self):
        snap = _make_snapshot(emergency_type=EmergencyType.MEDICAL)
        assert compute_confidence(snap) == 0.25

    def test_each_emergency_type_adds_same_score(self):
        for et in EmergencyType:
            snap = _make_snapshot(emergency_type=et)
            assert compute_confidence(snap) == 0.25, f"Failed for {et}"

    # --- Clinical fields contribution ---

    def test_conscious_only_adds_015(self):
        snap = _make_snapshot(conscious=True)
        assert compute_confidence(snap) == 0.15

    def test_conscious_false_also_adds_015(self):
        snap = _make_snapshot(conscious=False)
        assert compute_confidence(snap) == 0.15

    def test_breathing_only_adds_015(self):
        snap = _make_snapshot(breathing=True)
        assert compute_confidence(snap) == 0.15

    def test_breathing_false_also_adds_015(self):
        snap = _make_snapshot(breathing=False)
        assert compute_confidence(snap) == 0.15

    def test_victim_count_only_adds_010(self):
        snap = _make_snapshot(victim_count=1)
        assert compute_confidence(snap) == 0.10

    def test_victim_count_zero_counts(self):
        """victim_count=0 is not None, so it still contributes."""
        snap = _make_snapshot(victim_count=0)
        assert compute_confidence(snap) == 0.10

    # --- User input bonus ---

    def test_one_user_input_adds_005(self):
        snap = _make_snapshot(
            user_input=[UserInput(question="q", response_type="TAP", value="v")],
        )
        assert compute_confidence(snap) == 0.05

    def test_two_user_inputs_adds_010(self):
        snap = _make_snapshot(
            user_input=[
                UserInput(question=f"q{i}", response_type="TAP", value="v")
                for i in range(2)
            ],
        )
        assert compute_confidence(snap) == 0.10

    def test_user_input_capped_at_two(self):
        snap = _make_snapshot(
            user_input=[
                UserInput(question=f"q{i}", response_type="TAP", value="v")
                for i in range(10)
            ],
        )
        assert compute_confidence(snap) == 0.10

    def test_zero_user_inputs_no_bonus(self):
        snap = _make_snapshot()
        assert compute_confidence(snap) == 0.0

    # --- Combination / capping ---

    def test_full_data_caps_at_1_0(self):
        snap = _make_snapshot(
            location=Location(lat=44.8, lng=20.4, address="A", confirmed=True),
            emergency_type=EmergencyType.FIRE,
            conscious=True,
            breathing=True,
            victim_count=2,
            user_input=[
                UserInput(question="q1", response_type="TAP", value="v"),
                UserInput(question="q2", response_type="TAP", value="v"),
            ],
        )
        # 0.35+0.25+0.15+0.15+0.10+0.10 = 1.10 → capped to 1.0
        assert compute_confidence(snap) == 1.0

    def test_gps_plus_type_plus_conscious(self):
        snap = _make_snapshot(
            location=Location(lat=44.8, lng=20.4),
            emergency_type=EmergencyType.POLICE,
            conscious=True,
        )
        # 0.20 + 0.25 + 0.15 = 0.60
        assert compute_confidence(snap) == 0.60

    def test_confirmed_address_plus_all_clinical(self):
        snap = _make_snapshot(
            location=Location(lat=44.8, lng=20.4, address="A", confirmed=True),
            emergency_type=EmergencyType.GAS,
            conscious=False,
            breathing=False,
            victim_count=5,
        )
        # 0.35 + 0.25 + 0.15 + 0.15 + 0.10 = 1.00
        assert compute_confidence(snap) == 1.0

    def test_just_below_cap(self):
        snap = _make_snapshot(
            location=Location(lat=44.8, lng=20.4, address="A", confirmed=True),
            emergency_type=EmergencyType.MEDICAL,
            conscious=True,
            breathing=True,
        )
        # 0.35 + 0.25 + 0.15 + 0.15 = 0.90
        assert compute_confidence(snap) == 0.90


# ===========================================================================
# 3. SnapshotStore
# ===========================================================================

class TestSnapshotStore:
    """Tests for the Redis-backed snapshot store."""

    async def test_save_and_load_roundtrip(self, store):
        snap = _make_snapshot()
        await store.save(snap)
        loaded = await store.load("test-session")
        assert loaded is not None
        assert loaded.session_id == "test-session"

    async def test_load_missing_returns_none(self, store):
        assert await store.load("nonexistent") is None

    async def test_update_raises_key_error_for_missing(self, store):
        with pytest.raises(KeyError, match="not found"):
            await store.update("ghost", lambda s: None)

    async def test_update_increments_version(self, store):
        snap = _make_snapshot()
        await store.save(snap)
        updated = await store.update("test-session", lambda s: None)
        assert updated.snapshot_version == 1

    async def test_update_increments_version_twice(self, store):
        snap = _make_snapshot()
        await store.save(snap)
        await store.update("test-session", lambda s: None)
        updated = await store.update("test-session", lambda s: None)
        assert updated.snapshot_version == 2

    async def test_update_recomputes_confidence(self, store):
        snap = _make_snapshot(location=Location(lat=44.8, lng=20.4))
        await store.save(snap)

        def add_type(s):
            s.emergency_type = EmergencyType.MEDICAL

        updated = await store.update("test-session", add_type)
        # 0.20 (GPS) + 0.25 (type) = 0.45
        assert updated.confidence_score == 0.45

    async def test_update_persists_changes(self, store):
        snap = _make_snapshot()
        await store.save(snap)
        await store.update(
            "test-session",
            lambda s: setattr(s, "emergency_type", EmergencyType.FIRE),
        )
        loaded = await store.load("test-session")
        assert loaded.emergency_type == EmergencyType.FIRE

    async def test_ttl_is_set(self, store, redis):
        snap = _make_snapshot()
        await store.save(snap)
        ttl = await redis.ttl("session:test-session")
        assert 0 < ttl <= SNAPSHOT_TTL

    async def test_save_overwrites_previous(self, store):
        snap = _make_snapshot(victim_count=1)
        await store.save(snap)
        snap2 = _make_snapshot(victim_count=5)
        await store.save(snap2)
        loaded = await store.load("test-session")
        assert loaded.victim_count == 5

    async def test_sequential_updates_accumulate(self, store):
        snap = _make_snapshot()
        await store.save(snap)
        await store.update("test-session", lambda s: setattr(s, "emergency_type", EmergencyType.MEDICAL))
        await store.update("test-session", lambda s: setattr(s, "conscious", True))
        await store.update("test-session", lambda s: setattr(s, "breathing", False))
        loaded = await store.load("test-session")
        assert loaded.snapshot_version == 3
        assert loaded.emergency_type == EmergencyType.MEDICAL
        assert loaded.conscious is True
        assert loaded.breathing is False
        # 0.25 + 0.15 + 0.15 = 0.55
        assert loaded.confidence_score == 0.55


# ===========================================================================
# 4. UserAgentTools
# ===========================================================================

class TestUserAgentTools:
    """Tests for all 8 UserAgentTools methods via snapshot side-effects."""

    # --- confirm_location ---

    async def test_confirm_location_sets_address_and_confirmed(self, user_tools):
        tools, store, _ = user_tools
        result = await tools.confirm_location("Knez Mihailova 5")
        snap = await store.load("test-session")
        assert snap.location.confirmed is True
        assert snap.location.address == "Knez Mihailova 5"

    async def test_confirm_location_returns_confirmation_string(self, user_tools):
        tools, _, _ = user_tools
        result = await tools.confirm_location("Addr")
        assert "Addr" in result

    async def test_confirm_location_bumps_confidence(self, user_tools):
        tools, store, _ = user_tools
        await tools.confirm_location("Addr")
        snap = await store.load("test-session")
        # confirmed address = 0.35
        assert snap.confidence_score == 0.35

    # --- set_emergency_type ---

    async def test_set_emergency_type_medical(self, user_tools):
        tools, store, _ = user_tools
        await tools.set_emergency_type("MEDICAL")
        snap = await store.load("test-session")
        assert snap.emergency_type == EmergencyType.MEDICAL

    async def test_set_emergency_type_all_values(self, user_tools):
        tools, store, _ = user_tools
        for et in EmergencyType:
            await tools.set_emergency_type(et.value)
            snap = await store.load("test-session")
            assert snap.emergency_type == et

    async def test_set_emergency_type_invalid_raises(self, user_tools):
        tools, _, _ = user_tools
        with pytest.raises(ValueError):
            await tools.set_emergency_type("TORNADO")

    # --- set_clinical_fields ---

    async def test_set_clinical_fields_all(self, user_tools):
        tools, store, _ = user_tools
        await tools.set_clinical_fields(conscious=False, breathing=True, victim_count=3)
        snap = await store.load("test-session")
        assert snap.conscious is False
        assert snap.breathing is True
        assert snap.victim_count == 3

    async def test_set_clinical_fields_partial_conscious_only(self, user_tools):
        tools, store, _ = user_tools
        await tools.set_clinical_fields(conscious=True)
        snap = await store.load("test-session")
        assert snap.conscious is True
        assert snap.breathing is None  # untouched
        assert snap.victim_count is None  # untouched

    async def test_set_clinical_fields_partial_breathing_only(self, user_tools):
        tools, store, _ = user_tools
        await tools.set_clinical_fields(breathing=False)
        snap = await store.load("test-session")
        assert snap.breathing is False
        assert snap.conscious is None

    async def test_set_clinical_fields_partial_victim_count_only(self, user_tools):
        tools, store, _ = user_tools
        await tools.set_clinical_fields(victim_count=2)
        snap = await store.load("test-session")
        assert snap.victim_count == 2
        assert snap.conscious is None

    async def test_set_clinical_fields_no_args_no_change(self, user_tools):
        tools, store, _ = user_tools
        snap_before = await store.load("test-session")
        await tools.set_clinical_fields()
        snap_after = await store.load("test-session")
        assert snap_after.conscious is None
        assert snap_after.breathing is None
        assert snap_after.victim_count is None

    # --- append_free_text ---

    async def test_append_free_text_single(self, user_tools):
        tools, store, _ = user_tools
        await tools.append_free_text("on ne dise")
        snap = await store.load("test-session")
        assert snap.free_text_details == ["on ne dise"]

    async def test_append_free_text_multiple(self, user_tools):
        tools, store, _ = user_tools
        await tools.append_free_text("first")
        await tools.append_free_text("second")
        snap = await store.load("test-session")
        assert snap.free_text_details == ["first", "second"]

    # --- get_pending_dispatch_question ---

    async def test_pending_question_none_when_empty(self, user_tools):
        tools, _, _ = user_tools
        assert await tools.get_pending_dispatch_question() == "NONE"

    async def test_pending_question_returns_unanswered(self, user_tools):
        tools, store, _ = user_tools
        await store.update(
            "test-session",
            lambda s: s.dispatch_questions.extend(["Q1", "Q2"]),
        )
        assert await tools.get_pending_dispatch_question() == "Q1"

    async def test_pending_question_skips_answered(self, user_tools):
        tools, store, _ = user_tools
        await store.update(
            "test-session",
            lambda s: (
                s.dispatch_questions.extend(["Q1", "Q2"]),
                s.ua_answers.append("Q1|answer1"),
            ),
        )
        assert await tools.get_pending_dispatch_question() == "Q2"

    async def test_pending_question_all_answered_returns_none(self, user_tools):
        tools, store, _ = user_tools
        await store.update(
            "test-session",
            lambda s: (
                s.dispatch_questions.append("Q1"),
                s.ua_answers.append("Q1|answer1"),
            ),
        )
        assert await tools.get_pending_dispatch_question() == "NONE"

    # --- answer_dispatch_question ---

    async def test_answer_dispatch_question(self, user_tools):
        tools, store, _ = user_tools
        await tools.answer_dispatch_question("Is conscious?", "No")
        snap = await store.load("test-session")
        assert "Is conscious?|No" in snap.ua_answers

    async def test_answer_dispatch_question_multiple(self, user_tools):
        tools, store, _ = user_tools
        await tools.answer_dispatch_question("Q1", "A1")
        await tools.answer_dispatch_question("Q2", "A2")
        snap = await store.load("test-session")
        assert len(snap.ua_answers) == 2
        assert "Q1|A1" in snap.ua_answers
        assert "Q2|A2" in snap.ua_answers

    # --- surface_user_question ---

    async def test_surface_user_question_broadcasts(self, user_tools):
        tools, _, messages = user_tools
        await tools.surface_user_question("Da li ste OK?")
        assert len(messages) == 1
        assert messages[0]["type"] == "user_question"
        assert messages[0]["question"] == "Da li ste OK?"

    async def test_surface_user_question_returns_string(self, user_tools):
        tools, _, _ = user_tools
        result = await tools.surface_user_question("Test?")
        assert isinstance(result, str)

    # --- record_user_input ---

    async def test_record_user_input(self, user_tools):
        tools, store, _ = user_tools
        await tools.record_user_input("TAP", "DA")
        snap = await store.load("test-session")
        assert len(snap.user_input) == 1
        assert snap.user_input[0].response_type == "TAP"
        assert snap.user_input[0].value == "DA"
        assert snap.user_input[0].question == "agent_prompted"

    async def test_record_user_input_text_type(self, user_tools):
        tools, store, _ = user_tools
        await tools.record_user_input("TEXT", "On lezi na podu")
        snap = await store.load("test-session")
        assert snap.user_input[0].response_type == "TEXT"
        assert snap.user_input[0].value == "On lezi na podu"

    async def test_record_user_input_increases_confidence(self, user_tools):
        tools, store, _ = user_tools
        await tools.record_user_input("TAP", "DA")
        snap = await store.load("test-session")
        # GPS 0.20 + 1 user_input 0.05 = 0.25
        assert snap.confidence_score == 0.25

    async def test_record_user_input_twice_more_confidence(self, user_tools):
        tools, store, _ = user_tools
        await tools.record_user_input("TAP", "DA")
        await tools.record_user_input("TAP", "NE")
        snap = await store.load("test-session")
        # GPS 0.20 + 2 user_inputs 0.10 = 0.30
        assert snap.confidence_score == 0.30


# ===========================================================================
# 5. DispatchAgentTools
# ===========================================================================

class TestDispatchAgentTools:
    """Tests for all 5 DispatchAgentTools methods."""

    # --- get_emergency_brief ---

    async def test_brief_contains_emergency_type(self, dispatch_tools):
        tools, _, _ = dispatch_tools
        brief = await tools.get_emergency_brief()
        assert "MEDICAL" in brief

    async def test_brief_contains_confirmed_address(self, dispatch_tools):
        tools, _, _ = dispatch_tools
        brief = await tools.get_emergency_brief()
        assert "Knez Mihailova 5" in brief
        # confirmed address should NOT have "(unconfirmed)"
        assert "unconfirmed" not in brief

    async def test_brief_contains_victim_count(self, dispatch_tools):
        tools, _, _ = dispatch_tools
        brief = await tools.get_emergency_brief()
        assert "1" in brief

    async def test_brief_contains_clinical_fields(self, dispatch_tools):
        tools, _, _ = dispatch_tools
        brief = await tools.get_emergency_brief()
        # conscious=False → "no", breathing=True → "yes"
        assert "no" in brief.lower()
        assert "yes" in brief.lower()

    async def test_brief_contains_free_text(self, dispatch_tools):
        tools, _, _ = dispatch_tools
        brief = await tools.get_emergency_brief()
        assert "otac pao niz stepenice" in brief
        assert "krv na glavi" in brief

    async def test_brief_missing_session_returns_no_data(self, store):
        messages = []

        async def broadcast(sid, msg):
            messages.append(msg)

        tools = DispatchAgentTools("ghost-session", store, broadcast)
        brief = await tools.get_emergency_brief()
        assert "No session data" in brief

    async def test_brief_unconfirmed_address_shows_unconfirmed(self, store):
        snap = _make_snapshot(
            location=Location(lat=44.8, lng=20.4, address="Some Addr", confirmed=False),
        )
        await store.save(snap)
        messages = []

        async def broadcast(sid, msg):
            messages.append(msg)

        tools = DispatchAgentTools("test-session", store, broadcast)
        brief = await tools.get_emergency_brief()
        assert "unconfirmed" in brief

    async def test_brief_no_address_shows_gps(self, store):
        snap = _make_snapshot(
            location=Location(lat=44.8, lng=20.4),
        )
        await store.save(snap)
        messages = []

        async def broadcast(sid, msg):
            messages.append(msg)

        tools = DispatchAgentTools("test-session", store, broadcast)
        brief = await tools.get_emergency_brief()
        assert "GPS" in brief
        assert "44.8" in brief
        assert "20.4" in brief

    async def test_brief_unknown_fields(self, store):
        snap = _make_snapshot(location=Location(lat=44.8, lng=20.4))
        await store.save(snap)
        messages = []

        async def broadcast(sid, msg):
            messages.append(msg)

        tools = DispatchAgentTools("test-session", store, broadcast)
        brief = await tools.get_emergency_brief()
        assert "unknown" in brief.lower()  # type/conscious/breathing unknown

    async def test_brief_with_conflicts(self, store):
        snap = _make_snapshot(
            location=Location(lat=44.8, lng=20.4, address="A", confirmed=True),
            input_conflicts=[
                Conflict(field="conscious", env_value="true", user_value="false"),
            ],
        )
        await store.save(snap)
        messages = []

        async def broadcast(sid, msg):
            messages.append(msg)

        tools = DispatchAgentTools("test-session", store, broadcast)
        brief = await tools.get_emergency_brief()
        assert "conscious" in brief.lower()
        assert "true" in brief
        assert "false" in brief

    # --- queue_question_for_user ---

    async def test_queue_question(self, dispatch_tools):
        tools, store, _ = dispatch_tools
        result = await tools.queue_question_for_user("Da li krvarenje?")
        snap = await store.load("test-session")
        assert "Da li krvarenje?" in snap.dispatch_questions

    async def test_queue_multiple_questions(self, dispatch_tools):
        tools, store, _ = dispatch_tools
        await tools.queue_question_for_user("Q1")
        await tools.queue_question_for_user("Q2")
        snap = await store.load("test-session")
        assert snap.dispatch_questions == ["Q1", "Q2"]

    # --- get_user_answer ---

    async def test_get_user_answer_pending(self, dispatch_tools):
        tools, _, _ = dispatch_tools
        result = await tools.get_user_answer("Unknown Q")
        assert result == "PENDING"

    async def test_get_user_answer_found(self, dispatch_tools):
        tools, store, _ = dispatch_tools
        await store.update(
            "test-session",
            lambda s: s.ua_answers.append("Bleeding?|Yes, heavily"),
        )
        result = await tools.get_user_answer("Bleeding?")
        assert result == "Yes, heavily"

    async def test_get_user_answer_partial_match_is_pending(self, dispatch_tools):
        tools, store, _ = dispatch_tools
        await store.update(
            "test-session",
            lambda s: s.ua_answers.append("Bleeding?|Yes"),
        )
        # Different question → PENDING
        result = await tools.get_user_answer("Is bleeding?")
        assert result == "PENDING"

    async def test_get_user_answer_missing_session(self, store):
        messages = []

        async def broadcast(sid, msg):
            messages.append(msg)

        tools = DispatchAgentTools("ghost", store, broadcast)
        result = await tools.get_user_answer("Q?")
        assert result == "PENDING"

    async def test_get_user_answer_pipe_in_answer(self, dispatch_tools):
        """Answers containing '|' should be handled (split on first '|')."""
        tools, store, _ = dispatch_tools
        await store.update(
            "test-session",
            lambda s: s.ua_answers.append("Q1|answer|with|pipes"),
        )
        result = await tools.get_user_answer("Q1")
        assert result == "answer|with|pipes"

    # --- update_call_status ---

    async def test_update_call_status_dialing(self, dispatch_tools):
        tools, store, _ = dispatch_tools
        await tools.update_call_status("DIALING")
        snap = await store.load("test-session")
        assert snap.call_status == CallStatus.DIALING

    async def test_update_call_status_connected(self, dispatch_tools):
        tools, store, _ = dispatch_tools
        await tools.update_call_status("CONNECTED")
        snap = await store.load("test-session")
        assert snap.call_status == CallStatus.CONNECTED

    async def test_update_call_status_dropped(self, dispatch_tools):
        tools, store, _ = dispatch_tools
        await tools.update_call_status("DROPPED")
        snap = await store.load("test-session")
        assert snap.call_status == CallStatus.DROPPED

    async def test_update_call_status_invalid_raises(self, dispatch_tools):
        tools, _, _ = dispatch_tools
        with pytest.raises(ValueError):
            await tools.update_call_status("EXPLODED")

    # --- confirm_dispatch ---

    async def test_confirm_dispatch_sets_confirmed_and_eta(self, dispatch_tools):
        tools, store, _ = dispatch_tools
        result = await tools.confirm_dispatch(10)
        snap = await store.load("test-session")
        assert snap.call_status == CallStatus.CONFIRMED
        assert snap.eta_minutes == 10

    async def test_confirm_dispatch_returns_string_with_eta(self, dispatch_tools):
        tools, _, _ = dispatch_tools
        result = await tools.confirm_dispatch(5)
        assert "5" in result

    async def test_confirm_dispatch_zero_eta(self, dispatch_tools):
        tools, store, _ = dispatch_tools
        await tools.confirm_dispatch(0)
        snap = await store.load("test-session")
        assert snap.eta_minutes == 0
        assert snap.call_status == CallStatus.CONFIRMED


# ===========================================================================
# 6. Settings validation
# ===========================================================================

class TestSettings:
    """Tests for config.Settings, focusing on emergency number rejection."""

    def test_defaults(self):
        s = Settings(google_api_key="k", emergency_number="+381601234567")
        assert s.redis_url == "redis://localhost:6379"
        assert s.triage_timeout_seconds == 10
        assert s.confidence_threshold == 0.85
        assert s.reconnect_max_attempts == 3
        assert s.backend_base_url == "http://localhost:8080"

    def test_rejects_112(self):
        with pytest.raises(ValueError, match="real emergency"):
            Settings(google_api_key="k", emergency_number="112")

    def test_rejects_194(self):
        with pytest.raises(ValueError, match="real emergency"):
            Settings(google_api_key="k", emergency_number="194")

    def test_rejects_padded_112(self):
        with pytest.raises(ValueError, match="real emergency"):
            Settings(google_api_key="k", emergency_number=" 112 ")

    def test_rejects_plus_112(self):
        with pytest.raises(ValueError, match="real emergency"):
            Settings(google_api_key="k", emergency_number="+112")

    def test_rejects_plus_zero_112(self):
        with pytest.raises(ValueError, match="real emergency"):
            Settings(google_api_key="k", emergency_number="+0112")

    def test_rejects_plus_194(self):
        with pytest.raises(ValueError, match="real emergency"):
            Settings(google_api_key="k", emergency_number="+194")

    def test_accepts_valid_number(self):
        s = Settings(google_api_key="k", emergency_number="+381601234567")
        assert s.emergency_number == "+381601234567"

    def test_accepts_empty_number(self):
        s = Settings(google_api_key="k", emergency_number="")
        assert s.emergency_number == ""

    def test_accepts_local_number(self):
        s = Settings(google_api_key="k", emergency_number="0601234567")
        assert s.emergency_number == "0601234567"

    def test_custom_thresholds(self):
        s = Settings(
            google_api_key="k",
            emergency_number="",
            confidence_threshold=0.5,
            triage_timeout_seconds=30,
            reconnect_max_attempts=5,
        )
        assert s.confidence_threshold == 0.5
        assert s.triage_timeout_seconds == 30
        assert s.reconnect_max_attempts == 5
