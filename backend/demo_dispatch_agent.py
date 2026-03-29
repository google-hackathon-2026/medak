"""
Demo Dispatch Agent — scripted voice call to simulated 112.

This agent doesn't actually call anyone. It:
1. Simulates DIALING → CONNECTED status changes
2. Broadcasts a scripted transcript of the 112 conversation
3. Handles the Q&A relay through the snapshot (same as real agent)
4. Confirms dispatch with ETA
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from snapshot import SnapshotStore
from dispatch_agent import DispatchAgentTools

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, dict], Awaitable[None]]

# ---------------------------------------------------------------------------
# Localisable strings — swap this dict to change the demo language
# ---------------------------------------------------------------------------
STRINGS = {
    "calling_112": "Calling 112...",
    "dispatcher_greeting": "Emergency services, what happened?",
    "opening_statement": (
        "This is an automated emergency call on behalf of a person who cannot speak. "
        "I have information about the emergency."
    ),
    "dispatcher_ask_conscious": "Is the patient conscious? Does the patient respond to questions?",
    "question_conscious": "Is the patient conscious?",
    "dispatcher_ask_age": "How old is the patient?",
    "question_age": "How old is the patient?",
    "dispatcher_confirm": (
        "Understood. We're sending an emergency team. "
        "Estimated arrival time is 8 minutes. "
        "Stay with the patient and do not move them."
    ),
    "checking_with_caller": "One moment, I'm checking with the caller.",
    "still_waiting": "Still waiting for response from caller...",
    "team_dispatched": "Team has been dispatched. Arriving in {eta} minutes.",
}

# Each entry: (delay_from_phase_start, action, arg1, arg2)
DISPATCH_SCRIPT: list[tuple] = [
    # --- Call setup ---
    (0.0, "status_dialing", None, None),
    (0.5, "transcript", "assistant", STRINGS["calling_112"]),
    (2.0, "status_connected", None, None),

    # --- Dispatcher greeting ---
    (2.5, "transcript", "dispatch",
     STRINGS["dispatcher_greeting"]),

    # --- Agent delivers brief ---
    (4.0, "get_brief_and_speak", None, None),

    # --- Dispatcher asks about consciousness ---
    (12.0, "transcript", "dispatch",
     STRINGS["dispatcher_ask_conscious"]),
    (12.5, "queue_question", STRINGS["question_conscious"], None),

    # --- Wait for answer from user agent, then relay ---
    (15.0, "relay_answer", STRINGS["question_conscious"], None),

    # --- Dispatcher asks about age ---
    (20.0, "transcript", "dispatch",
     STRINGS["dispatcher_ask_age"]),
    (20.5, "queue_question", STRINGS["question_age"], None),
    (23.0, "relay_answer", STRINGS["question_age"], None),

    # --- Dispatcher confirms dispatch ---
    (28.0, "transcript", "dispatch",
     STRINGS["dispatcher_confirm"]),

    # --- Agent confirms dispatch ---
    (30.0, "confirm", 8, None),
]


def _brief_to_speech(brief: str) -> str:
    """Convert the pipe-separated brief into natural speech."""
    parts = [p.strip() for p in brief.split("|")]
    sentences: list[str] = []
    for part in parts:
        if part.startswith("Type:"):
            val = part.split(":", 1)[1].strip()
            type_map = {"MEDICAL": "medical", "FIRE": "fire", "POLICE": "police", "GAS": "gas"}
            sentences.append(f"This is a {type_map.get(val, val)} emergency.")
        elif part.startswith("Address:"):
            val = part.split(":", 1)[1].strip()
            sentences.append(f"The location is {val}.")
        elif part.startswith("Victim count:"):
            val = part.split(":", 1)[1].strip()
            sentences.append(f"Number of victims: {val}.")
        elif part.startswith("Conscious:"):
            val = part.split(":", 1)[1].strip()
            sentences.append(f"Patient is conscious: {val}.")
        elif part.startswith("Breathing:"):
            val = part.split(":", 1)[1].strip()
            sentences.append(f"Patient is breathing: {val}.")
        elif part.startswith("Details:"):
            val = part.split(":", 1)[1].strip()
            sentences.append(f"Additional details: {val}.")
    return " ".join(sentences)


async def run_demo_dispatch_agent(
    session_id: str,
    store: SnapshotStore,
    broadcast: BroadcastFn,
) -> None:
    """Run the scripted dispatch agent."""
    tools = DispatchAgentTools(session_id, store, broadcast)
    start = asyncio.get_event_loop().time()

    logger.info("Demo Dispatch Agent started for session %s", session_id)

    for entry in DISPATCH_SCRIPT:
        delay, action = entry[0], entry[1]

        # Wait for the right moment
        elapsed = asyncio.get_event_loop().time() - start
        wait = delay - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

        if action == "status_dialing":
            await tools.update_call_status("DIALING")
            snap = await store.load(session_id)
            await broadcast(session_id, {
                "type": "STATUS_UPDATE",
                "phase": "LIVE_CALL",
                "call_status": "DIALING",
                "confidence": snap.confidence_score if snap else 0.0,
            })
            logger.info("Demo Dispatch: DIALING")

        elif action == "status_connected":
            await tools.update_call_status("CONNECTED")
            snap = await store.load(session_id)
            await broadcast(session_id, {
                "type": "STATUS_UPDATE",
                "phase": "LIVE_CALL",
                "call_status": "CONNECTED",
                "confidence": snap.confidence_score if snap else 0.0,
            })
            logger.info("Demo Dispatch: CONNECTED")

        elif action == "transcript":
            speaker, text = entry[2], entry[3]
            await broadcast(session_id, {
                "type": "transcript",
                "speaker": speaker,
                "text": text,
            })
            logger.info("Demo Dispatch transcript [%s]: %s", speaker, text[:60])

        elif action == "get_brief_and_speak":
            brief = await tools.get_emergency_brief()
            speech = (
                f"{STRINGS['opening_statement']} {_brief_to_speech(brief)}"
            )
            await broadcast(session_id, {
                "type": "transcript",
                "speaker": "assistant",
                "text": speech,
            })
            logger.info("Demo Dispatch: delivered brief")

        elif action == "queue_question":
            question = entry[2]
            await tools.queue_question_for_user(question)
            # Also broadcast a "waiting" message
            await broadcast(session_id, {
                "type": "transcript",
                "speaker": "assistant",
                "text": STRINGS["checking_with_caller"],
            })
            # Surface the question to the user's phone
            await broadcast(session_id, {
                "type": "user_question",
                "question": question,
            })
            logger.info("Demo Dispatch: queued question: %s", question)

        elif action == "relay_answer":
            question = entry[2]
            # Poll for answer (demo user agent should have answered by now)
            answer = None
            for _ in range(10):
                answer = await tools.get_user_answer(question)
                if answer != "PENDING":
                    break
                await asyncio.sleep(0.5)

            if answer and answer != "PENDING":
                await broadcast(session_id, {
                    "type": "transcript",
                    "speaker": "assistant",
                    "text": answer,
                })
                logger.info("Demo Dispatch: relayed answer: %s", answer)
            else:
                await broadcast(session_id, {
                    "type": "transcript",
                    "speaker": "assistant",
                    "text": STRINGS["still_waiting"],
                })
                logger.warning("Demo Dispatch: no answer received for: %s", question)

        elif action == "confirm":
            eta = entry[2]
            await tools.confirm_dispatch(eta)
            await broadcast(session_id, {
                "type": "transcript",
                "speaker": "assistant",
                "text": STRINGS["team_dispatched"].format(eta=eta),
            })
            logger.info("Demo Dispatch: confirmed dispatch, ETA %d min", eta)

    logger.info("Demo Dispatch Agent complete for session %s", session_id)
