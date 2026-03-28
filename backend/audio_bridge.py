# backend/audio_bridge.py
from __future__ import annotations

import asyncio
import logging

import audioop

logger = logging.getLogger(__name__)


# ── Audio conversion ───────────────────────────────────────────────────────────

def ulaw8k_to_pcm16k(data: bytes) -> bytes:
    """Convert mulaw 8kHz audio (from Twilio) to linear PCM 16kHz (for Gemini).

    Steps:
      1. ulaw2lin: mulaw → linear PCM 8kHz (1 byte/sample → 2 bytes/sample)
      2. ratecv:   8kHz → 16kHz (doubles sample count)
    """
    if not data:
        return b""
    try:
        pcm8 = audioop.ulaw2lin(data, 2)
        pcm16, _ = audioop.ratecv(pcm8, 2, 1, 8000, 16000, None)
        return pcm16
    except Exception:
        logger.exception("ulaw8k_to_pcm16k conversion error — skipping chunk")
        return b""


def pcm24k_to_ulaw8k(data: bytes) -> bytes:
    """Convert linear PCM 24kHz audio (from Gemini) to mulaw 8kHz (for Twilio).

    Steps:
      1. ratecv:   24kHz → 8kHz (reduces sample count by 3)
      2. lin2ulaw: linear PCM → mulaw (2 bytes/sample → 1 byte/sample)
    """
    if not data:
        return b""
    try:
        pcm8, _ = audioop.ratecv(data, 2, 1, 24000, 8000, None)
        return audioop.lin2ulaw(pcm8, 2)
    except Exception:
        logger.exception("pcm24k_to_ulaw8k conversion error — skipping chunk")
        return b""


# ── AudioBridge ───────────────────────────────────────────────────────────────

class AudioBridge:
    """Per-session audio pipeline connecting Twilio WebSocket ↔ Gemini Live.

    inbound:  PCM 16kHz bytes  — Twilio → Gemini
    outbound: PCM 24kHz bytes  — Gemini → Twilio
    """

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self.outbound: asyncio.Queue[bytes] = asyncio.Queue()
        self.stream_sid: str | None = None
        self._connected: asyncio.Event = asyncio.Event()

    def on_twilio_connected(self, stream_sid: str) -> None:
        """Called when the Twilio Media Streams WebSocket sends a 'start' event."""
        self.stream_sid = stream_sid
        self._connected.set()

    async def wait_connected(self, timeout: float = 30.0) -> bool:
        """Wait until on_twilio_connected is called. Returns False on timeout."""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


# ── AudioBridgeRegistry ───────────────────────────────────────────────────────

class AudioBridgeRegistry:
    """Singleton stored in app.state.bridge_registry. Maps session_id → AudioBridge."""

    def __init__(self) -> None:
        self._bridges: dict[str, AudioBridge] = {}

    def create(self, session_id: str) -> AudioBridge:
        bridge = AudioBridge()
        self._bridges[session_id] = bridge
        return bridge

    def get(self, session_id: str) -> AudioBridge | None:
        return self._bridges.get(session_id)

    def remove(self, session_id: str) -> None:
        self._bridges.pop(session_id, None)
