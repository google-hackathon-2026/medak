# backend/tests/test_store.py
import pytest
import fakeredis.aioredis

from snapshot import (
    EmergencySnapshot,
    EmergencyType,
    Location,
    SnapshotStore,
)


@pytest.fixture
async def store():
    redis = fakeredis.aioredis.FakeRedis()
    s = SnapshotStore(redis)
    yield s
    await redis.aclose()


async def test_save_and_load(store: SnapshotStore):
    snap = EmergencySnapshot(session_id="s1")
    await store.save(snap)
    loaded = await store.load("s1")
    assert loaded is not None
    assert loaded.session_id == "s1"


async def test_load_missing_returns_none(store: SnapshotStore):
    result = await store.load("nonexistent")
    assert result is None


async def test_update_increments_version(store: SnapshotStore):
    snap = EmergencySnapshot(session_id="s1")
    await store.save(snap)

    def set_type(s: EmergencySnapshot) -> None:
        s.emergency_type = EmergencyType.MEDICAL

    updated = await store.update("s1", set_type)
    assert updated.snapshot_version == 1
    assert updated.emergency_type == EmergencyType.MEDICAL
    assert updated.confidence_score == 0.25  # recomputed

async def test_update_recomputes_confidence(store: SnapshotStore):
    snap = EmergencySnapshot(
        session_id="s1",
        location=Location(lat=44.8, lng=20.4),
    )
    await store.save(snap)

    def confirm_loc(s: EmergencySnapshot) -> None:
        s.location.confirmed = True
        s.location.address = "Test Address"

    updated = await store.update("s1", confirm_loc)
    assert updated.confidence_score == 0.35


async def test_ttl_is_set(store: SnapshotStore):
    snap = EmergencySnapshot(session_id="s1")
    await store.save(snap)
    ttl = await store._redis.ttl("session:s1")
    assert ttl > 0
    assert ttl <= 3600
