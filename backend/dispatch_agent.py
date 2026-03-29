# backend/dispatch_agent.py
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from google import genai
from google.genai import types as genai_types
from twilio.rest import Client as TwilioClient

from config import create_genai_client, get_settings
from snapshot import (
    CallStatus,
    EmergencySnapshot,
    SnapshotStore,
)

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, dict], Awaitable[None]]


class DispatchAgentTools:
    """Tool implementations for the Dispatch Agent."""

    def __init__(
        self,
        session_id: str,
        store: SnapshotStore,
        broadcast: BroadcastFn,
    ) -> None:
        self.session_id = session_id
        self.store = store
        self.broadcast = broadcast

    async def get_emergency_brief(self) -> str:
        snap = await self.store.load(self.session_id)
        if snap is None:
            return "No session data available."

        loc = snap.location
        if loc.confirmed and loc.address:
            addr = loc.address
        elif loc.address:
            addr = f"{loc.address} (unconfirmed)"
        else:
            addr = f"GPS: {loc.lat}, {loc.lng}"

        parts = [
            f"Type: {snap.emergency_type or 'unknown'}",
            f"Address: {addr}",
            f"Victim count: {snap.victim_count if snap.victim_count is not None else 'unknown'}",
            f"Conscious: {'yes' if snap.conscious else 'no' if snap.conscious is not None else 'unknown'}",
            f"Breathing: {'yes' if snap.breathing else 'no' if snap.breathing is not None else 'unknown'}",
        ]
        if snap.free_text_details:
            parts.append(f"Details: {'; '.join(snap.free_text_details)}")
        if snap.input_conflicts:
            conflicts = [f"{c.field}: user says '{c.user_value}', environment shows '{c.env_value}'" for c in snap.input_conflicts]
            parts.append(f"Conflicts: {'; '.join(conflicts)}")

        return " | ".join(parts)

    async def queue_question_for_user(self, question: str) -> str:
        await self.store.update(
            self.session_id,
            lambda s: s.dispatch_questions.append(question),
        )
        return "Question queued for user agent"

    async def get_user_answer(self, question: str) -> str:
        snap = await self.store.load(self.session_id)
        if snap is None:
            return "PENDING"
        for entry in snap.ua_answers:
            if "|" in entry:
                q, a = entry.split("|", 1)
                if q == question:
                    return a
        return "PENDING"

    async def update_call_status(self, status: str) -> str:
        cs = CallStatus(status)
        await self.store.update(self.session_id, lambda s: setattr(s, "call_status", cs))
        return f"Call status: {cs}"

    async def confirm_dispatch(self, eta_minutes: int) -> str:
        def updater(s: EmergencySnapshot) -> None:
            s.call_status = CallStatus.CONFIRMED
            s.eta_minutes = eta_minutes

        await self.store.update(self.session_id, updater)
        return f"Dispatch confirmed, ETA {eta_minutes} minutes"


# --- Tool declarations for Gemini ---

DISPATCH_TOOL_DECLARATIONS = genai_types.Tool(
    function_declarations=[
        genai_types.FunctionDeclaration(
            name="queue_question_for_user",
            description="Ask the user a question through the relay. Use when operator asks something not in the brief.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"question": genai_types.Schema(type="STRING")},
                required=["question"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="get_user_answer",
            description="Check if the user answered a previously queued question. Returns answer or 'PENDING'.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"question": genai_types.Schema(type="STRING")},
                required=["question"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="confirm_dispatch",
            description="Confirm that emergency services are dispatched with ETA.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"eta_minutes": genai_types.Schema(type="INTEGER")},
                required=["eta_minutes"],
            ),
        ),
    ]
)

DISPATCH_AGENT_SYSTEM_PROMPT_TEMPLATE = """You are an automated emergency call relay service. You are calling 112 on behalf of a person who cannot speak.

EMERGENCY BRIEFING:
{brief}

RULES:
- First sentence: "This is an automated emergency call on behalf of a person who cannot speak."
- Then deliver the briefing from the data above ONCE — short and clear.
- After the briefing, WAIT for the operator's response. Do not repeat the briefing.
- Answer the operator's questions using data from the briefing.
- If you don't know the answer, say "One moment, checking with the caller" and use queue_question_for_user().
- Never speculate about unconfirmed fields. Say "that has not been confirmed yet".
- When the operator confirms dispatch, call confirm_dispatch(eta_minutes).
- Speak English, clearly and concisely.
- IMPORTANT: When the operator speaks, stop talking and listen. Only respond to questions."""


async def run_dispatch_agent(
    session_id: str,
    store: SnapshotStore,
    broadcast: BroadcastFn,
    bridge: "AudioBridge | None" = None,
) -> None:
    settings = get_settings()
    tools = DispatchAgentTools(session_id, store, broadcast)
    client = create_genai_client()

    tool_handlers = {
        "queue_question_for_user": lambda args: tools.queue_question_for_user(args["question"]),
        "get_user_answer": lambda args: tools.get_user_answer(args["question"]),
        "confirm_dispatch": lambda args: tools.confirm_dispatch(args["eta_minutes"]),
    }

    # Pre-load the emergency brief for the system prompt
    brief = await tools.get_emergency_brief()

    # Initiate Twilio call
    twilio_client = None
    call_sid = None
    if settings.twilio_account_sid and settings.emergency_number:
        try:
            twilio_client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
            twiml_url = f"{settings.backend_base_url}/api/session/{session_id}/twilio/twiml"
            status_url = f"{settings.backend_base_url}/api/session/{session_id}/twilio/status"
            # FIX: Wrap synchronous Twilio SDK call in to_thread to avoid blocking the event loop
            call = await asyncio.to_thread(
                twilio_client.calls.create,
                to=settings.emergency_number,
                from_=settings.twilio_from_number,
                url=twiml_url,
                status_callback=status_url,
            )
            call_sid = call.sid
            await tools.update_call_status("DIALING")
            logger.info("Twilio call initiated: %s", call_sid)
        except Exception:
            logger.exception("Failed to initiate Twilio call for session %s", session_id)
            await tools.update_call_status("DROPPED")
            return

    # Wait for Twilio WebSocket to connect before starting Gemini (30s timeout)
    if bridge is not None:
        connected = await bridge.wait_connected(timeout=30.0)
        if not connected:
            logger.error("Twilio WebSocket never connected for session %s", session_id)
            await tools.update_call_status("DROPPED")
            return

    # Connect Gemini Live session — brief pre-loaded in prompt, tools for Q&A relay
    system_prompt = DISPATCH_AGENT_SYSTEM_PROMPT_TEMPLATE.format(brief=brief)
    config = genai_types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=genai_types.Content(
            parts=[genai_types.Part(text=system_prompt)]
        ),
        tools=[DISPATCH_TOOL_DECLARATIONS],
        realtime_input_config=genai_types.RealtimeInputConfig(
            automatic_activity_detection=genai_types.AutomaticActivityDetection(
                start_of_speech_sensitivity=genai_types.StartSensitivity.START_SENSITIVITY_HIGH,
                end_of_speech_sensitivity=genai_types.EndSensitivity.END_SENSITIVITY_LOW,
                silence_duration_ms=500,
            ),
            activity_handling=genai_types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        ),
    )

    try:
        async with client.aio.live.connect(
            model="gemini-live-2.5-flash-native-audio",
            config=config,
        ) as session:
            logger.info("Dispatch Agent connected for session %s", session_id)

            await session.send_client_content(
                turns=genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text="The call is connected. Begin the briefing.")],
                )
            )

            async def _sender() -> None:
                """Forward inbound PCM 16kHz from Twilio to Gemini Live."""
                if bridge is None:
                    return
                while True:
                    try:
                        chunk = await bridge.inbound.get()
                    except asyncio.CancelledError:
                        break
                    try:
                        await session.send_realtime_input(
                            media=genai_types.Blob(
                                data=chunk,
                                mime_type="audio/pcm;rate=16000",
                            )
                        )
                    except Exception:
                        logger.exception("Sender task error for session %s", session_id)
                        break

            sender_task = asyncio.create_task(_sender())

            try:
                async for response in session.receive():
                    # Handle interruption — flush outbound audio queue
                    if (
                        response.server_content
                        and response.server_content.interrupted
                        and bridge is not None
                    ):
                        while not bridge.outbound.empty():
                            try:
                                bridge.outbound.get_nowait()
                            except asyncio.QueueEmpty:
                                break

                    # Audio output from Gemini → bridge.outbound
                    if bridge is not None and response.server_content:
                        turn = response.server_content.model_turn
                        if turn:
                            for part in turn.parts:
                                if (
                                    part.inline_data
                                    and part.inline_data.mime_type
                                    and part.inline_data.mime_type.startswith("audio/")
                                ):
                                    await bridge.outbound.put(part.inline_data.data)

                    # Tool calls — wrapped in try/except so flaky native audio
                    # tool support doesn't crash the entire session
                    if response.tool_call:
                        for fc in response.tool_call.function_calls:
                            handler = tool_handlers.get(fc.name)
                            if handler:
                                try:
                                    result = await handler(fc.args or {})
                                    await session.send_tool_response(
                                        function_responses=[{
                                            "id": fc.id,
                                            "name": fc.name,
                                            "response": {"result": result},
                                        }]
                                    )
                                except Exception:
                                    logger.warning(
                                        "Tool call %s failed for session %s, continuing",
                                        fc.name, session_id, exc_info=True,
                                    )
                                    await session.send_tool_response(
                                        function_responses=[{
                                            "id": fc.id,
                                            "name": fc.name,
                                            "response": {"result": "ERROR"},
                                        }]
                                    )

                    # Text transcript (from tool call text output)
                    if response.text:
                        await broadcast(session_id, {
                            "type": "transcript",
                            "speaker": "assistant",
                            "text": response.text,
                        })
            finally:
                sender_task.cancel()
                try:
                    await sender_task
                except asyncio.CancelledError:
                    pass

    except Exception:
        logger.exception("Dispatch Agent error for session %s", session_id)
        await tools.update_call_status("DROPPED")
