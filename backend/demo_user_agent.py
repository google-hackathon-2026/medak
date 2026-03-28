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

# Each entry: (delay_seconds, action_type, action_args, transcript_text)
STROKE_NEIGHBOR_SCRIPT: list[tuple] = [
    (1.0, "transcript", None,
     "Analiziram okolinu... Detektujem osobu na podu."),

    (2.5, "tool_call", ("set_emergency_type", {"emergency_type": "MEDICAL"}),
     "Medicinski hitan slučaj detektovan."),

    (4.0, "tool_call", ("append_free_text", {"utterance": "Starija žena leži na podu kuhinje, moguć moždani udar"}),
     None),

    (5.5, "tool_call", ("confirm_location", {"address": "Bulevar kralja Aleksandra 73, Beograd"}),
     "Lokacija potvrđena: Bulevar kralja Aleksandra 73."),

    (7.0, "tool_call", ("set_clinical_fields", {"victim_count": 1, "conscious": True, "breathing": True}),
     "Jedna žrtva. Pri svesti — reaguje na dodir. Diše nepravilno."),

    (8.5, "tool_call", ("append_free_text", {"utterance": "Žrtva pokazuje znake konfuzije, otežan govor, asimetrija lica"}),
     "Detektujem znake moždanog udara: konfuzija, asimetrija lica."),
]

SCENARIOS: dict[str, list[tuple]] = {
    "stroke_neighbor": STROKE_NEIGHBOR_SCRIPT,
}

# Hardcoded answers for known dispatch questions
ANSWER_MAP: dict[str, str] = {
    "Da li je pacijent pri svesti?": "Da, pri svesti je ali je konfuzna i ima otežan govor.",
    "Da li pacijent diše?": "Da, diše ali nepravilno.",
    "Koliko ima godina?": "Oko 70 godina.",
    "Da li uzima neke lekove?": "Nije poznato, proveravam sa pozivaocem.",
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

            answer = ANSWER_MAP.get(pending, "Proveravam sa pozivaocem, jedan momenat.")
            await tools.answer_dispatch_question(pending, answer)

            await broadcast(session_id, {
                "type": "transcript",
                "speaker": "assistant",
                "text": f"Odgovor na pitanje dispečera: {answer}",
            })
            logger.info("Demo User Agent answered question: %s -> %s", pending, answer)

        await asyncio.sleep(2)
