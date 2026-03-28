# backend/tests/test_audio_bridge.py
"""Tests for audio format conversion utilities.

10ms of audio durations (used throughout):
  mulaw 8kHz  = 80 samples × 1 byte  =   80 bytes
  PCM 8kHz    = 80 samples × 2 bytes =  160 bytes
  PCM 16kHz   = 158 samples × 2 bytes = 318 bytes  (via audioop.ratecv with state=None)
  PCM 24kHz   = 240 samples × 2 bytes = 480 bytes
"""
import audioop

import pytest

from audio_bridge import ulaw8k_to_pcm16k, pcm24k_to_ulaw8k


# ── ulaw8k_to_pcm16k ──────────────────────────────────────────────────────────

def test_ulaw8k_to_pcm16k_returns_bytes():
    mulaw = audioop.lin2ulaw(bytes(160), 2)  # 80 bytes mulaw silence
    result = ulaw8k_to_pcm16k(mulaw)
    assert isinstance(result, bytes)


def test_ulaw8k_to_pcm16k_upsamples_correctly():
    """80 mulaw-8kHz bytes → 318 PCM-16kHz bytes (via audioop.ratecv with state=None)."""
    pcm8 = bytes(160)  # 80 samples of silence, 2 bytes each
    mulaw = audioop.lin2ulaw(pcm8, 2)   # 80 bytes
    result = ulaw8k_to_pcm16k(mulaw)
    assert len(result) == 318


def test_ulaw8k_to_pcm16k_empty_returns_empty():
    result = ulaw8k_to_pcm16k(b"")
    assert result == b""


# ── pcm24k_to_ulaw8k ──────────────────────────────────────────────────────────

def test_pcm24k_to_ulaw8k_returns_bytes():
    pcm24 = bytes(480)  # 240 samples of silence at 24kHz (10ms)
    result = pcm24k_to_ulaw8k(pcm24)
    assert isinstance(result, bytes)


def test_pcm24k_to_ulaw8k_downsamples_correctly():
    """480 PCM-24kHz bytes → 80 mulaw-8kHz bytes (÷6: ÷3 rate, ÷2 linear→mulaw)."""
    pcm24 = bytes(480)
    result = pcm24k_to_ulaw8k(pcm24)
    assert len(result) == 80


def test_pcm24k_to_ulaw8k_empty_returns_empty():
    result = pcm24k_to_ulaw8k(b"")
    assert result == b""


# ── round-trip duration coherence ─────────────────────────────────────────────

def test_round_trip_duration_coherence():
    """10ms in → 10ms out at each stage of the pipeline.

    Due to resampling rounding, allow ±2 bytes variance on upsampling.
    """
    # Inbound: 10ms mulaw 8kHz = 80 bytes → PCM 16kHz = 318 bytes
    pcm8_silence = bytes(160)
    mulaw_in = audioop.lin2ulaw(pcm8_silence, 2)  # 80 bytes
    assert len(mulaw_in) == 80
    pcm16 = ulaw8k_to_pcm16k(mulaw_in)
    assert len(pcm16) == 318  # audioop.ratecv(state=None) produces 158 samples × 2 bytes

    # Outbound: 10ms PCM 24kHz = 480 bytes → mulaw 8kHz = 80 bytes
    pcm24 = bytes(480)
    mulaw_out = pcm24k_to_ulaw8k(pcm24)
    assert len(mulaw_out) == 80  # 10ms × 8kHz × 1 byte/sample


# ── AudioBridge ───────────────────────────────────────────────────────────────

import asyncio
from audio_bridge import AudioBridge, AudioBridgeRegistry


async def test_bridge_inbound_queue():
    bridge = AudioBridge()
    await bridge.inbound.put(b"chunk1")
    data = await bridge.inbound.get()
    assert data == b"chunk1"


async def test_bridge_outbound_queue():
    bridge = AudioBridge()
    await bridge.outbound.put(b"chunk2")
    data = await bridge.outbound.get()
    assert data == b"chunk2"


async def test_on_twilio_connected_sets_stream_sid():
    bridge = AudioBridge()
    assert bridge.stream_sid is None
    bridge.on_twilio_connected("SM123abc")
    assert bridge.stream_sid == "SM123abc"


async def test_on_twilio_connected_fires_event():
    bridge = AudioBridge()
    assert not bridge._connected.is_set()
    bridge.on_twilio_connected("SM123abc")
    assert bridge._connected.is_set()


async def test_wait_connected_resolves_when_connected():
    bridge = AudioBridge()

    async def connect_soon():
        await asyncio.sleep(0.02)
        bridge.on_twilio_connected("SM456")

    asyncio.create_task(connect_soon())
    result = await bridge.wait_connected(timeout=1.0)
    assert result is True
    assert bridge.stream_sid == "SM456"


async def test_wait_connected_returns_false_on_timeout():
    bridge = AudioBridge()
    result = await bridge.wait_connected(timeout=0.05)
    assert result is False


async def test_wait_connected_returns_true_if_already_connected():
    bridge = AudioBridge()
    bridge.on_twilio_connected("SM789")
    result = await bridge.wait_connected(timeout=0.1)
    assert result is True


# ── AudioBridgeRegistry ───────────────────────────────────────────────────────

def test_registry_create_returns_bridge():
    reg = AudioBridgeRegistry()
    bridge = reg.create("session-1")
    assert isinstance(bridge, AudioBridge)


def test_registry_get_returns_same_instance():
    reg = AudioBridgeRegistry()
    created = reg.create("session-1")
    got = reg.get("session-1")
    assert got is created


def test_registry_get_missing_returns_none():
    reg = AudioBridgeRegistry()
    assert reg.get("nonexistent") is None


def test_registry_remove_deletes_entry():
    reg = AudioBridgeRegistry()
    reg.create("session-1")
    reg.remove("session-1")
    assert reg.get("session-1") is None


def test_registry_remove_missing_is_noop():
    reg = AudioBridgeRegistry()
    reg.remove("nonexistent")  # must not raise


def test_registry_independent_sessions():
    reg = AudioBridgeRegistry()
    b1 = reg.create("s1")
    b2 = reg.create("s2")
    assert b1 is not b2
    assert reg.get("s1") is b1
    assert reg.get("s2") is b2
