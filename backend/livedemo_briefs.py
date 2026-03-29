# backend/livedemo_briefs.py
"""
Hardcoded emergency briefs for live demo scenarios.
Used in LIVEDEMO_MODE="full" (always) and "lite" (as fallback).
"""

ARMED_THREAT_BRIEF = (
    "Type: POLICE | "
    "Address: {address} | "
    "Victim count: 2 | "
    "Conscious: yes | "
    "Breathing: yes | "
    "Details: Armed confrontation in progress at a public event venue. "
    "One individual has drawn a firearm and is threatening another person "
    "who is kneeling on the ground. Immediate police response required. "
    "Two individuals involved — the aggressor is armed with a handgun, "
    "the victim is compliant and kneeling. No shots fired yet. "
    "The situation is tense and could escalate."
)

LIVEDEMO_BRIEFS: dict[str, str] = {
    "armed_threat": ARMED_THREAT_BRIEF,
}


def get_livedemo_brief(scenario: str, address: str = "GPS location provided") -> str:
    """Return the hardcoded brief for the given scenario, with address filled in."""
    template = LIVEDEMO_BRIEFS.get(scenario)
    if template is None:
        raise ValueError(
            f"Unknown livedemo scenario: {scenario}. "
            f"Available: {list(LIVEDEMO_BRIEFS.keys())}"
        )
    return template.format(address=address)
