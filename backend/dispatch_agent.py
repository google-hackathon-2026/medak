# backend/dispatch_agent.py
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from google import genai
from google.genai import types as genai_types
from twilio.rest import Client as TwilioClient

from config import get_settings
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
            addr = f"{loc.address} (nepotvrdjeno)"
        else:
            addr = f"GPS: {loc.lat}, {loc.lng}"

        parts = [
            f"Tip: {snap.emergency_type or 'nepoznat'}",
            f"Adresa: {addr}",
            f"Broj zrtava: {snap.victim_count if snap.victim_count is not None else 'nepoznat'}",
            f"Svest: {'da' if snap.conscious else 'ne' if snap.conscious is not None else 'nepoznato'}",
            f"Disanje: {'da' if snap.breathing else 'ne' if snap.breathing is not None else 'nepoznato'}",
        ]
        if snap.free_text_details:
            parts.append(f"Detalji: {'; '.join(snap.free_text_details)}")
        if snap.input_conflicts:
            conflicts = [f"{c.field}: korisnik kaze '{c.user_value}', okruzenje pokazuje '{c.env_value}'" for c in snap.input_conflicts]
            parts.append(f"Neslaganja: {'; '.join(conflicts)}")

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
            name="get_emergency_brief",
            description="Get the full emergency briefing from user data. Call at start and on reconnect.",
            parameters=genai_types.Schema(type="OBJECT", properties={}),
        ),
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
            name="update_call_status",
            description="Update the call status: DIALING, CONNECTED, DROPPED.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"status": genai_types.Schema(type="STRING", enum=["DIALING", "CONNECTED", "DROPPED"])},
                required=["status"],
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

DISPATCH_AGENT_SYSTEM_PROMPT = """Ti si automatizovani servis za prenos hitnih poziva. Zoves 112 u ime osobe koja ne moze da govori.

PRAVILA:
- Prva recenica: "Ovo je automatizovani poziv hitne sluzbe u ime osobe koja ne moze da govori. Imam detalje o hitnom slucaju i odgovoricu na vasa pitanja."
- Odmah zatim izgovori ceo brifing koristeci get_emergency_brief().
- Odgovaraj na pitanja operatera koristeci podatke iz brifinga.
- Ako ne znas odgovor, reci "Jedan momenat, proveravam sa pozivaocem" i koristi queue_question_for_user().
- Zatim periodcno proveravaj get_user_answer() dok ne dobijes odgovor.
- Nikada ne spekulisi o nepotvdrjenim poljima. Reci "to jos nije potvrdjeno".
- Ako postoje neslaganja (input_conflicts), prijavi ih operateru kao nerazresene.
- Kada operator potvrdi slanje ekipe, pozovi confirm_dispatch(eta_minutes).
- Govori srpski, jasno i koncizno."""


async def run_dispatch_agent(
    session_id: str,
    store: SnapshotStore,
    broadcast: BroadcastFn,
) -> None:
    settings = get_settings()
    tools = DispatchAgentTools(session_id, store, broadcast)
    client = genai.Client(api_key=settings.google_api_key)

    tool_handlers = {
        "get_emergency_brief": lambda _: tools.get_emergency_brief(),
        "queue_question_for_user": lambda args: tools.queue_question_for_user(args["question"]),
        "get_user_answer": lambda args: tools.get_user_answer(args["question"]),
        "update_call_status": lambda args: tools.update_call_status(args["status"]),
        "confirm_dispatch": lambda args: tools.confirm_dispatch(args["eta_minutes"]),
    }

    # Initiate Twilio call
    twilio_client = None
    call_sid = None
    if settings.twilio_account_sid and settings.emergency_number:
        try:
            twilio_client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
            call = twilio_client.calls.create(
                to=settings.emergency_number,
                from_=settings.twilio_from_number,
                url=f"https://your-backend-url/api/session/{session_id}/twilio/twiml",
                status_callback=f"https://your-backend-url/api/session/{session_id}/twilio/status",
            )
            call_sid = call.sid
            await tools.update_call_status("DIALING")
            logger.info("Twilio call initiated: %s", call_sid)
        except Exception:
            logger.exception("Failed to initiate Twilio call for session %s", session_id)
            await tools.update_call_status("DROPPED")
            return

    # Connect Gemini Live session
    config = genai_types.LiveConnectConfig(
        response_modalities=["AUDIO", "TEXT"],
        system_instruction=genai_types.Content(
            parts=[genai_types.Part(text=DISPATCH_AGENT_SYSTEM_PROMPT)]
        ),
        tools=[DISPATCH_TOOL_DECLARATIONS],
    )

    try:
        async with client.aio.live.connect(
            model="gemini-2.0-flash-live-001",
            config=config,
        ) as session:
            logger.info("Dispatch Agent connected for session %s", session_id)

            # Instruct agent to begin
            await session.send(
                input="Poziv je uspostavljen. Pocni sa brifingom.",
                end_of_turn=True,
            )

            async for response in session.receive():
                if response.tool_call:
                    for fc in response.tool_call.function_calls:
                        handler = tool_handlers.get(fc.name)
                        if handler:
                            result = await handler(fc.args or {})
                            await session.send(
                                input=genai_types.LiveClientToolResponse(
                                    function_responses=[
                                        genai_types.FunctionResponse(
                                            name=fc.name,
                                            response={"result": result},
                                        )
                                    ]
                                )
                            )

                if response.text:
                    await broadcast(session_id, {
                        "type": "transcript",
                        "speaker": "assistant",
                        "text": response.text,
                    })

    except Exception:
        logger.exception("Dispatch Agent error for session %s", session_id)
        await tools.update_call_status("DROPPED")
