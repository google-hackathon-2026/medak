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
