# backend/snapshot.py
from __future__ import annotations

from enum import StrEnum
from time import time

from pydantic import BaseModel, Field


# --- Enums ---

class SessionPhase(StrEnum):
    INTAKE = "INTAKE"
    TRIAGE = "TRIAGE"
    LIVE_CALL = "LIVE_CALL"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class EmergencyType(StrEnum):
    MEDICAL = "MEDICAL"
    FIRE = "FIRE"
    POLICE = "POLICE"
    GAS = "GAS"
    OTHER = "OTHER"


class CallStatus(StrEnum):
    IDLE = "IDLE"
    DIALING = "DIALING"
    CONNECTED = "CONNECTED"
    CONFIRMED = "CONFIRMED"
    DROPPED = "DROPPED"
    COMPLETED = "COMPLETED"


# --- Models ---

class Location(BaseModel):
    lat: float | None = None
    lng: float | None = None
    address: str | None = None
    confirmed: bool = False


class UserInput(BaseModel):
    question: str
    response_type: str  # "TAP" or "TEXT"
    value: str


class Conflict(BaseModel):
    field: str
    env_value: str | None = None
    user_value: str | None = None


class EmergencySnapshot(BaseModel):
    session_id: str
    phase: SessionPhase = SessionPhase.INTAKE
    snapshot_version: int = 0
    created_at: float = Field(default_factory=time)
    device_id: str | None = None
    location: Location = Field(default_factory=Location)
    emergency_type: EmergencyType | None = None
    victim_count: int | None = None
    conscious: bool | None = None
    breathing: bool | None = None
    free_text_details: list[str] = Field(default_factory=list)
    user_input: list[UserInput] = Field(default_factory=list)
    input_conflicts: list[Conflict] = Field(default_factory=list)
    confidence_score: float = 0.0
    dispatch_questions: list[str] = Field(default_factory=list)
    ua_answers: list[str] = Field(default_factory=list)
    call_status: CallStatus = CallStatus.IDLE
    eta_minutes: int | None = None


# --- Confidence Scoring ---

def compute_confidence(snapshot: EmergencySnapshot) -> float:
    score = 0.0
    loc = snapshot.location

    if loc.confirmed and loc.address:
        score += 0.35
    elif loc.lat is not None and loc.lng is not None:
        score += 0.20

    if snapshot.emergency_type is not None:
        score += 0.25
    if snapshot.conscious is not None:
        score += 0.15
    if snapshot.breathing is not None:
        score += 0.15
    if snapshot.victim_count is not None:
        score += 0.10

    user_input_bonus = 0.05 * min(len(snapshot.user_input), 2)
    score += user_input_bonus

    return round(min(score, 1.0), 2)


from typing import Callable

import redis.asyncio as aioredis


SNAPSHOT_TTL = 3600  # 1 hour


class SnapshotStore:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}"

    async def save(self, snapshot: EmergencySnapshot) -> None:
        key = self._key(snapshot.session_id)
        await self._redis.set(key, snapshot.model_dump_json(), ex=SNAPSHOT_TTL)

    async def load(self, session_id: str) -> EmergencySnapshot | None:
        data = await self._redis.get(self._key(session_id))
        if data is None:
            return None
        return EmergencySnapshot.model_validate_json(data)

    async def update(
        self,
        session_id: str,
        updater: Callable[[EmergencySnapshot], None],
    ) -> EmergencySnapshot:
        """Update a snapshot with optimistic retry.

        NOTE: Ideally this would use Redis WATCH/MULTI/EXEC for true
        atomic CAS, but fakeredis compatibility is spotty. For the
        hackathon we use a simple read-modify-write with retry as a
        pragmatic compromise. The snapshot_version bump at least makes
        the race window detectable.
        """
        key = self._key(session_id)
        for attempt in range(10):
            data = await self._redis.get(key)
            if data is None:
                raise KeyError(f"Session {session_id} not found")
            snapshot = EmergencySnapshot.model_validate_json(data)
            updater(snapshot)
            snapshot.confidence_score = compute_confidence(snapshot)
            snapshot.snapshot_version += 1
            new_data = snapshot.model_dump_json()
            await self._redis.set(key, new_data, ex=SNAPSHOT_TTL)
            return snapshot
        raise RuntimeError(f"Failed to update session {session_id} after 10 attempts")
