#!/usr/bin/env python3
"""E2E test: send a static image through the full emergency flow.

Bypasses the phone app entirely. Sends a JPEG image as repeated video
frames to the running backend, prints all transcript/status messages.

Prerequisites:
  - Backend running (uvicorn or docker compose)
  - Redis running
  - Gemini credentials configured
  - Twilio configured (for LIVE_CALL phase)

Usage:
  uv run python e2e_image_test.py path/to/car_crash.jpg
  uv run python e2e_image_test.py photo.jpg --backend http://localhost:8080 --fps 2
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

import httpx
import websockets


async def main() -> None:
    parser = argparse.ArgumentParser(description="E2E test with a static image")
    parser.add_argument("image", help="Path to a JPEG image file")
    parser.add_argument("--backend", default="http://localhost:8080", help="Backend base URL")
    parser.add_argument("--fps", type=float, default=1.0, help="Frames per second to send")
    parser.add_argument("--timeout", type=int, default=120, help="Max seconds to run")
    args = parser.parse_args()

    # Load image
    image_path = Path(args.image)
    if not image_path.exists():
        print(f"ERROR: Image not found: {image_path}")
        return
    image_bytes = image_path.read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    print(f"Loaded image: {image_path.name} ({len(image_bytes)} bytes)")

    # Create session
    async with httpx.AsyncClient(base_url=args.backend, timeout=10) as http:
        resp = await http.post("/api/sos", json={
            "lat": 44.8176,
            "lng": 20.4633,
            "address": "Knez Mihailova 5, Beograd",
            "user_id": "e2e-test-user",
            "device_id": "e2e-test-device",
        })
        resp.raise_for_status()
        data = resp.json()
        session_id = data["session_id"]
        print(f"Session created: {session_id}  status={data['status']}")

    # WebSocket URL
    ws_base = args.backend.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_base}/api/session/{session_id}/ws"

    done = asyncio.Event()

    async def send_frames(ws) -> None:
        interval = 1.0 / args.fps
        count = 0
        while not done.is_set():
            msg = json.dumps({"type": "video_frame", "data": image_b64})
            await ws.send(msg)
            count += 1
            print(f"  [SENT] video_frame #{count}")
            try:
                await asyncio.wait_for(asyncio.shield(done.wait()), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass

    async def send_silent_audio(ws) -> None:
        # 16kHz mono 16-bit, 0.5s = 16000 bytes of silence
        silent_chunk = base64.b64encode(b"\x00" * 16000).decode("ascii")
        while not done.is_set():
            msg = json.dumps({"type": "audio", "data": silent_chunk})
            await ws.send(msg)
            try:
                await asyncio.wait_for(asyncio.shield(done.wait()), timeout=0.5)
                break
            except asyncio.TimeoutError:
                pass

    async def receive_messages(ws) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                ts = time.strftime("%H:%M:%S")
                msg_type = msg.get("type", "unknown")

                if msg_type == "transcript":
                    speaker = msg.get("speaker", "?")
                    text = msg.get("text", "")
                    print(f"  [{ts}] TRANSCRIPT ({speaker}): {text}")
                elif msg_type == "STATUS_UPDATE":
                    phase = msg.get("phase", "?")
                    confidence = msg.get("confidence", "?")
                    print(f"  [{ts}] STATUS: phase={phase}  confidence={confidence}")
                elif msg_type == "user_question":
                    print(f"  [{ts}] QUESTION FOR USER: {msg.get('question', '?')}")
                elif msg_type == "RESOLVED":
                    eta = msg.get("eta_minutes", "?")
                    print(f"  [{ts}] RESOLVED: {msg.get('message', '')} (ETA: {eta} min)")
                    done.set()
                elif msg_type == "FAILED":
                    print(f"  [{ts}] FAILED: {msg.get('message', '')}")
                    done.set()
                elif msg_type == "pong":
                    pass
                else:
                    print(f"  [{ts}] {msg_type}: {json.dumps(msg)}")
        except websockets.exceptions.ConnectionClosed:
            print("  WebSocket closed")
            done.set()

    async def timeout_watchdog() -> None:
        try:
            await asyncio.wait_for(asyncio.shield(done.wait()), timeout=args.timeout)
        except asyncio.TimeoutError:
            print(f"\n  TIMEOUT after {args.timeout}s")
            done.set()

    # Connect and run
    print(f"Connecting WebSocket: {ws_url}")
    async with websockets.connect(ws_url) as ws:
        print("WebSocket connected\n")
        tasks = [
            asyncio.create_task(send_frames(ws)),
            asyncio.create_task(send_silent_audio(ws)),
            asyncio.create_task(receive_messages(ws)),
            asyncio.create_task(timeout_watchdog()),
        ]

        await done.wait()

        # Give a moment for final messages
        await asyncio.sleep(1)

        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Final status
    print()
    async with httpx.AsyncClient(base_url=args.backend, timeout=10) as http:
        resp = await http.get(f"/api/session/{session_id}/status")
        if resp.status_code == 200:
            print(f"Final status:\n{json.dumps(resp.json(), indent=2)}")
        else:
            print(f"Could not fetch final status: {resp.status_code}")


if __name__ == "__main__":
    asyncio.run(main())
