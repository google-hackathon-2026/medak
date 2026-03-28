# backend/user_agent.py
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Awaitable, Callable

from google import genai
from google.genai import types as genai_types

from config import create_genai_client, get_settings
from snapshot import (
    EmergencyType,
    SnapshotStore,
    UserInput,
)

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, dict], Awaitable[None]]


class UserAgentTools:
    """Tool implementations that modify the EmergencySnapshot."""

    def __init__(
        self,
        session_id: str,
        store: SnapshotStore,
        broadcast: BroadcastFn,
    ) -> None:
        self.session_id = session_id
        self.store = store
        self.broadcast = broadcast

    async def confirm_location(self, address: str) -> str:
        await self.store.update(self.session_id, lambda s: (
            setattr(s.location, "confirmed", True),
            setattr(s.location, "address", address),
        ))
        return f"Location confirmed: {address}"

    async def set_emergency_type(self, emergency_type: str) -> str:
        et = EmergencyType(emergency_type)
        await self.store.update(self.session_id, lambda s: setattr(s, "emergency_type", et))
        return f"Emergency type set: {et}"

    async def set_clinical_fields(
        self,
        conscious: bool | None = None,
        breathing: bool | None = None,
        victim_count: int | None = None,
    ) -> str:
        def updater(s):
            if conscious is not None:
                s.conscious = conscious
            if breathing is not None:
                s.breathing = breathing
            if victim_count is not None:
                s.victim_count = victim_count

        await self.store.update(self.session_id, updater)
        return "Clinical fields updated"

    async def append_free_text(self, utterance: str) -> str:
        await self.store.update(
            self.session_id,
            lambda s: s.free_text_details.append(utterance),
        )
        return "Text appended"

    async def get_pending_dispatch_question(self) -> str:
        snap = await self.store.load(self.session_id)
        if snap is None:
            return "NONE"
        answered = {a.split("|")[0] for a in snap.ua_answers}
        for q in snap.dispatch_questions:
            if q not in answered:
                return q
        return "NONE"

    async def answer_dispatch_question(self, question: str, answer: str) -> str:
        await self.store.update(
            self.session_id,
            lambda s: s.ua_answers.append(f"{question}|{answer}"),
        )
        return "Answer recorded"

    async def surface_user_question(self, question: str) -> str:
        await self.broadcast(self.session_id, {
            "type": "user_question",
            "question": question,
        })
        return "Question sent to user"

    async def record_user_input(self, response_type: str, value: str) -> str:
        inp = UserInput(question="agent_prompted", response_type=response_type, value=value)
        await self.store.update(
            self.session_id,
            lambda s: s.user_input.append(inp),
        )
        return "User input recorded"


# --- Tool declarations for Gemini ---

TOOL_DECLARATIONS = genai_types.Tool(
    function_declarations=[
        genai_types.FunctionDeclaration(
            name="confirm_location",
            description="Confirm the user's location address. Call when address is verbally confirmed.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"address": genai_types.Schema(type="STRING", description="Confirmed address")},
                required=["address"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="set_emergency_type",
            description="Set the type of emergency: MEDICAL, FIRE, POLICE, GAS, or OTHER.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"emergency_type": genai_types.Schema(type="STRING", enum=["MEDICAL", "FIRE", "POLICE", "GAS", "OTHER"])},
                required=["emergency_type"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="set_clinical_fields",
            description="Set clinical assessment fields. All parameters are optional — set only what is confirmed.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "conscious": genai_types.Schema(type="BOOLEAN", description="Is the victim conscious?"),
                    "breathing": genai_types.Schema(type="BOOLEAN", description="Is the victim breathing?"),
                    "victim_count": genai_types.Schema(type="INTEGER", description="Number of victims"),
                },
            ),
        ),
        genai_types.FunctionDeclaration(
            name="append_free_text",
            description="Append a raw user utterance for context. Call for every meaningful thing the user says.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"utterance": genai_types.Schema(type="STRING")},
                required=["utterance"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="get_pending_dispatch_question",
            description="Check if the 112 operator asked a question the AI cannot answer. Returns the question or 'NONE'.",
            parameters=genai_types.Schema(type="OBJECT", properties={}),
        ),
        genai_types.FunctionDeclaration(
            name="answer_dispatch_question",
            description="Answer a question relayed from the 112 operator.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "question": genai_types.Schema(type="STRING"),
                    "answer": genai_types.Schema(type="STRING"),
                },
                required=["question", "answer"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="surface_user_question",
            description="Show a yes/no question on the user's screen. Use sparingly — max one at a time.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"question": genai_types.Schema(type="STRING")},
                required=["question"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="record_user_input",
            description="Record a user's response (tap or text) to a question.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "response_type": genai_types.Schema(type="STRING", enum=["TAP", "TEXT"]),
                    "value": genai_types.Schema(type="STRING"),
                },
                required=["response_type", "value"],
            ),
        ),
    ]
)

USER_AGENT_SYSTEM_PROMPT = """You are an emergency relay assistant. You observe the user's environment via microphone and camera to gather information about the emergency.

RULES:
- Operate in observation mode. Never demand a response from the user.
- Immediately call a tool when information is confirmed from audio/video context.
- Ask at most one yes/no question at a time using surface_user_question.
- Never speculate beyond what is directly observed or confirmed.
- Never say "I am an artificial intelligence". Say "I am your emergency relay assistant."
- Speak English.

INFORMATION PRIORITY:
1. Address confirmation (pre-filled from GPS)
2. Emergency type (medical, fire, police, gas, other)
3. Number of victims
4. Consciousness status
5. Breathing

If a question appears in dispatch_questions, handle it immediately."""


class UserMediaRelay:
    """Per-session queue for forwarding user audio/video/text to the User Agent."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict] = asyncio.Queue()

    async def put(self, msg: dict) -> None:
        await self.queue.put(msg)


class UserMediaRegistry:
    """Maps session_id → UserMediaRelay. Stored in app.state."""

    def __init__(self) -> None:
        self._relays: dict[str, UserMediaRelay] = {}

    def create(self, session_id: str) -> UserMediaRelay:
        relay = UserMediaRelay()
        self._relays[session_id] = relay
        return relay

    def get(self, session_id: str) -> UserMediaRelay | None:
        return self._relays.get(session_id)

    def remove(self, session_id: str) -> None:
        self._relays.pop(session_id, None)


async def run_user_agent(
    session_id: str,
    store: SnapshotStore,
    broadcast: BroadcastFn,
    media_relay: UserMediaRelay | None = None,
) -> None:
    settings = get_settings()
    tools = UserAgentTools(session_id, store, broadcast)
    client = create_genai_client()

    tool_handlers = {
        "confirm_location": lambda args: tools.confirm_location(args["address"]),
        "set_emergency_type": lambda args: tools.set_emergency_type(args["emergency_type"]),
        "set_clinical_fields": lambda args: tools.set_clinical_fields(
            conscious=args.get("conscious"),
            breathing=args.get("breathing"),
            victim_count=args.get("victim_count"),
        ),
        "append_free_text": lambda args: tools.append_free_text(args["utterance"]),
        "get_pending_dispatch_question": lambda _: tools.get_pending_dispatch_question(),
        "answer_dispatch_question": lambda args: tools.answer_dispatch_question(args["question"], args["answer"]),
        "surface_user_question": lambda args: tools.surface_user_question(args["question"]),
        "record_user_input": lambda args: tools.record_user_input(args["response_type"], args["value"]),
    }

    config = genai_types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=genai_types.Content(
            parts=[genai_types.Part(text=USER_AGENT_SYSTEM_PROMPT)]
        ),
        tools=[TOOL_DECLARATIONS],
    )

    try:
        async with client.aio.live.connect(
            model="gemini-live-2.5-flash-native-audio",
            config=config,
        ) as session:
            logger.info("User Agent connected for session %s", session_id)

            # Send initial context from snapshot
            snap = await store.load(session_id)
            if snap:
                initial_context = (
                    f"Emergency reported. GPS location: {snap.location.lat}, {snap.location.lng}. "
                    f"Address: {snap.location.address or 'unknown'}. "
                    f"Begin observation and information gathering."
                )
                await session.send_client_content(
                    turns=genai_types.Content(
                        role="user",
                        parts=[genai_types.Part(text=initial_context)],
                    )
                )

            async def _media_sender() -> None:
                """Forward user audio/video/text from the phone to Gemini."""
                if media_relay is None:
                    return
                while True:
                    try:
                        msg = await media_relay.queue.get()
                    except asyncio.CancelledError:
                        break
                    try:
                        msg_type = msg.get("type")
                        if msg_type == "audio":
                            audio_bytes = base64.b64decode(msg["data"])
                            await session.send(
                                input=genai_types.LiveClientRealtimeInput(
                                    media_chunks=[
                                        genai_types.Blob(
                                            data=audio_bytes,
                                            mime_type="audio/pcm;rate=16000",
                                        )
                                    ]
                                )
                            )
                        elif msg_type == "video_frame":
                            image_bytes = base64.b64decode(msg["data"])
                            await session.send(
                                input=genai_types.LiveClientRealtimeInput(
                                    media_chunks=[
                                        genai_types.Blob(
                                            data=image_bytes,
                                            mime_type="image/jpeg",
                                        )
                                    ]
                                )
                            )
                        elif msg_type == "user_response":
                            text = msg.get("value", "")
                            await session.send_client_content(
                                turns=genai_types.Content(
                                    role="user",
                                    parts=[genai_types.Part(text=f"User responded: {text}")],
                                )
                            )
                    except Exception:
                        logger.exception("Media sender error for session %s", session_id)

            sender_task = asyncio.create_task(_media_sender())

            try:
                async for response in session.receive():
                    # Handle tool calls
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

                    # Handle text responses — broadcast as transcript
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
        logger.exception("User Agent error for session %s", session_id)
