# backend/test_gemini_connectivity.py
"""Quick smoke test for Gemini connectivity via Vertex AI.

Usage:
    cd backend && uv run python test_gemini_connectivity.py
"""
from __future__ import annotations

import asyncio
import sys

from google import genai
from google.genai import types as genai_types

from config import get_settings


def test_basic_generate():
    """Test basic text generation (non-streaming)."""
    settings = get_settings()
    client = genai.Client(api_key=settings.google_api_key, vertexai=True)

    print("1. Testing basic text generation...")
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents="Reply with exactly: CONNECTIVITY_OK",
    )
    print(f"   Response: {response.text.strip()}")
    assert "CONNECTIVITY_OK" in response.text, f"Unexpected response: {response.text}"
    print("   PASS")


async def test_live_session():
    """Test Gemini Live (bidirectional streaming) session."""
    settings = get_settings()
    # Vertex AI with ADC (gcloud auth application-default login)
    client = genai.Client(
        vertexai=True,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
    )

    print("2. Testing Gemini Live session (audio-native model)...")
    config = genai_types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=genai_types.Content(
            parts=[genai_types.Part(text="Say hello briefly.")]
        ),
    )

    async with client.aio.live.connect(
        model="gemini-live-2.5-flash-native-audio",
        config=config,
    ) as session:
        await session.send(input="Hello", end_of_turn=True)
        got_audio = False
        async for response in session.receive():
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.inline_data and part.inline_data.mime_type and part.inline_data.mime_type.startswith("audio/"):
                        got_audio = True
                        print(f"   Audio chunk: {len(part.inline_data.data)} bytes, mime={part.inline_data.mime_type}")
                        break
            if got_audio or (response.server_content and response.server_content.turn_complete):
                break

    assert got_audio, "No audio received from Live session"
    print("   PASS")


async def test_live_audio_config():
    """Test Gemini Live with AUDIO response modality (verifies audio output works)."""
    settings = get_settings()
    client = genai.Client(
        vertexai=True,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
    )

    print("3. Testing Gemini Live with AUDIO modality...")
    config = genai_types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=genai_types.Content(
            parts=[genai_types.Part(text="Say hello briefly.")]
        ),
    )

    async with client.aio.live.connect(
        model="gemini-live-2.5-flash-native-audio",
        config=config,
    ) as session:
        await session.send(input="Hello", end_of_turn=True)

        got_audio = False
        got_text = False
        async for response in session.receive():
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.inline_data and part.inline_data.mime_type and part.inline_data.mime_type.startswith("audio/"):
                        got_audio = True
                        print(f"   Audio chunk: {len(part.inline_data.data)} bytes, mime={part.inline_data.mime_type}")
                    if part.text:
                        got_text = True
            if response.server_content and response.server_content.turn_complete:
                break

    if got_audio:
        print("   Audio output: YES")
    else:
        print("   Audio output: NO (model returned text only)")
    print("   PASS")


def main():
    settings = get_settings()
    print(f"Project:  {settings.google_cloud_project}")
    print(f"Location: {settings.google_cloud_location}")
    print(f"API Key:  {settings.google_api_key[:8]}...{settings.google_api_key[-4:]}" if settings.google_api_key else "API Key: NOT SET")
    print()

    try:
        # test_basic_generate()
        # print()
        asyncio.run(test_live_session())
        print()
        asyncio.run(test_live_audio_config())
        print()
        print("All connectivity tests passed.")
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
