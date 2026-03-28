# backend/tests/test_snapshot.py
from snapshot import (
    CallStatus,
    EmergencySnapshot,
    EmergencyType,
    Location,
    SessionPhase,
    UserInput,
    compute_confidence,
)


def test_empty_snapshot_no_location():
    snap = EmergencySnapshot(session_id="s1")
    assert compute_confidence(snap) == 0.0


def test_gps_only():
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
    )
    assert compute_confidence(snap) == 0.20


def test_confirmed_location():
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4, address="Knez Mihailova 5", confirmed=True),
    )
    assert compute_confidence(snap) == 0.35


def test_full_snapshot():
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4, address="Addr", confirmed=True),
        emergency_type=EmergencyType.MEDICAL,
        conscious=False,
        breathing=True,
        victim_count=1,
        user_input=[
            UserInput(question="q1", response_type="TAP", value="DA"),
            UserInput(question="q2", response_type="TAP", value="NE"),
        ],
    )
    # 0.35 + 0.25 + 0.15 + 0.15 + 0.10 + 0.10 = 1.10 -> capped at 1.0
    assert compute_confidence(snap) == 1.0


def test_partial_clinical():
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
        emergency_type=EmergencyType.FIRE,
        conscious=True,
    )
    # 0.20 + 0.25 + 0.15 = 0.60
    assert compute_confidence(snap) == 0.60


def test_user_input_capped_at_two():
    snap = EmergencySnapshot(
        session_id="s1",
        user_input=[
            UserInput(question=f"q{i}", response_type="TAP", value="v") for i in range(5)
        ],
    )
    # 0.05 * min(5, 2) = 0.10
    assert compute_confidence(snap) == 0.10


def test_snapshot_defaults():
    snap = EmergencySnapshot(session_id="s1")
    assert snap.phase == SessionPhase.INTAKE
    assert snap.snapshot_version == 0
    assert snap.call_status == CallStatus.IDLE
    assert snap.confidence_score == 0.0
    assert snap.eta_minutes is None
    assert snap.dispatch_questions == []
    assert snap.ua_answers == []
