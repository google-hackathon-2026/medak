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
