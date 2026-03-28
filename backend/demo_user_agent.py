"""
Demo User Agent — scripted tool-call sequence that mimics
what a real Gemini Live session would do.

The key insight: we call the EXACT SAME tool functions (UserAgentTools)
as the real agent. The snapshot mutations, confidence recalculation,
and WebSocket broadcasts are all real. Only the "brain" is scripted.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from snapshot import SnapshotStore
from user_agent import UserAgentTools

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, dict], Awaitable[None]]

# ---------------------------------------------------------------------------
# Localisable strings — swap this dict to change the demo language
# ---------------------------------------------------------------------------
STRINGS = {
    "analyzing_env": "Analyzing environment... Detecting person on the floor.",
    "medical_detected": "Medical emergency detected.",
    "free_text_scene": "Elderly woman lying on kitchen floor, possible stroke",
    "location_confirmed": "Location confirmed: Bulevar kralja Aleksandra 73.",
    "clinical_summary": "One victim. Conscious — responds to touch. Breathing irregularly.",
    "stroke_signs": "Detecting signs of stroke: confusion, facial asymmetry.",
    "free_text_stroke": "Victim showing signs of confusion, slurred speech, facial asymmetry",
    "dispatcher_answer_prefix": "Response to dispatcher's question",
    "checking_with_caller": "Checking with the caller, one moment.",
    # Q&A answers keyed by the English dispatch questions
    "answer_conscious": "Yes, conscious but confused and has slurred speech.",
    "answer_breathing": "Yes, breathing but irregularly.",
    "answer_age": "Approximately 70 years old.",
    "answer_medication": "Unknown, checking with the caller.",
}

# Each entry: (delay_seconds, action_type, action_args, transcript_text)
STROKE_NEIGHBOR_SCRIPT: list[tuple] = [
    (1.0, "transcript", None,
     STRINGS["analyzing_env"]),

    (2.5, "tool_call", ("set_emergency_type", {"emergency_type": "MEDICAL"}),
     STRINGS["medical_detected"]),

    (4.0, "tool_call", ("append_free_text", {"utterance": STRINGS["free_text_scene"]}),
     None),

    (5.5, "tool_call", ("confirm_location", {"address": "Bulevar kralja Aleksandra 73, Beograd"}),
     STRINGS["location_confirmed"]),

    (7.0, "tool_call", ("set_clinical_fields", {"victim_count": 1, "conscious": True, "breathing": True}),
     STRINGS["clinical_summary"]),

    (8.5, "tool_call", ("append_free_text", {"utterance": STRINGS["free_text_stroke"]}),
     STRINGS["stroke_signs"]),
]

SCENARIOS: dict[str, list[tuple]] = {
    "stroke_neighbor": STROKE_NEIGHBOR_SCRIPT,
}

# Hardcoded answers for known dispatch questions
ANSWER_MAP: dict[str, str] = {
    "Is the patient conscious?": STRINGS["answer_conscious"],
    "Is the patient breathing?": STRINGS["answer_breathing"],
    "How old is the patient?": STRINGS["answer_age"],
    "Is the patient taking any medication?": STRINGS["answer_medication"],
}


async def run_demo_user_agent(
    session_id: str,
    store: SnapshotStore,
    broadcast: BroadcastFn,
    scenario: str = "stroke_neighbor",
) -> None:
    """Run the scripted user agent for the given scenario."""
    tools = UserAgentTools(session_id, store, broadcast)
    script = SCENARIOS.get(scenario, STROKE_NEIGHBOR_SCRIPT)

    tool_map = {
        "confirm_location": lambda args: tools.confirm_location(args["address"]),
        "set_emergency_type": lambda args: tools.set_emergency_type(args["emergency_type"]),
        "set_clinical_fields": lambda args: tools.set_clinical_fields(**args),
        "append_free_text": lambda args: tools.append_free_text(args["utterance"]),
    }

    start = asyncio.get_event_loop().time()
    logger.info("Demo User Agent started for session %s (scenario: %s)", session_id, scenario)

    # --- Execute scripted sequence ---
    for delay, action_type, action_args, transcript_text in script:
        elapsed = asyncio.get_event_loop().time() - start
        wait = delay - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

        # Execute tool call (real snapshot mutation)
        if action_type == "tool_call":
            tool_name, kwargs = action_args
            handler = tool_map.get(tool_name)
            if handler:
                result = await handler(kwargs)
                logger.info("Demo User Agent tool: %s -> %s", tool_name, result)

        # Broadcast transcript (real WebSocket message)
        if transcript_text:
            await broadcast(session_id, {
                "type": "transcript",
                "speaker": "assistant",
                "text": transcript_text,
            })

    logger.info("Demo User Agent script complete for session %s, entering monitoring loop", session_id)

    # --- Monitoring loop for dispatch questions (cross-agent Q&A relay) ---
    while True:
        snap = await store.load(session_id)
        if snap is None or snap.phase.value in ("RESOLVED", "FAILED"):
            logger.info("Demo User Agent exiting: session %s phase=%s",
                        session_id, snap.phase if snap else "None")
            break

        # Check for pending dispatch questions
        pending = await tools.get_pending_dispatch_question()
        if pending != "NONE":
            # Brief "checking" delay for visual effect
            await asyncio.sleep(1.5)

            answer = ANSWER_MAP.get(pending, STRINGS["checking_with_caller"])
            await tools.answer_dispatch_question(pending, answer)

            await broadcast(session_id, {
                "type": "transcript",
                "speaker": "assistant",
                "text": f"{STRINGS['dispatcher_answer_prefix']}: {answer}",
            })
            logger.info("Demo User Agent answered question: %s -> %s", pending, answer)

        await asyncio.sleep(2)
