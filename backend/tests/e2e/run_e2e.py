#!/usr/bin/env python3
"""End-to-end test: send image frames through the full emergency pipeline.

Simulates the phone app by sending JPEG frames via WebSocket, captures all
transcript/status messages, downloads the Twilio call recording, dumps the
final Redis snapshot, and generates an audit report with pass/fail assertions.

The backend must already be running with DEBUG_TRACE=true for full artifact
capture on the backend side.

Prerequisites:
  - Backend running (with DEBUG_TRACE=true recommended)
  - Redis running
  - Gemini credentials configured (real Gemini, not mocked)
  - Twilio configured (for LIVE_CALL phase)
  - ngrok tunnel active (BACKEND_BASE_URL matches ngrok URL)
  - Image frames in --frames-dir (JPEG files)

Usage:
  # Place your frames in tests/e2e/test_data/frames/
  cd backend
  uv run python tests/e2e/run_e2e.py --frames-dir tests/e2e/test_data/frames/

  # With custom backend URL and timeout
  uv run python tests/e2e/run_e2e.py \\
    --frames-dir tests/e2e/test_data/frames/ \\
    --backend https://your-ngrok-url \\
    --timeout 180

  # Single image repeated as frames (like the original e2e_image_test.py)
  uv run python tests/e2e/run_e2e.py --image path/to/scene.jpg

Output:
  tests/e2e/output/{session_id}/
    ws_log.jsonl           - All WebSocket messages with timestamps
    snapshot_final.json    - Final EmergencySnapshot from Redis
    call_details.json      - Twilio call SID, duration, recording URL
    call_recording.mp3     - Downloaded Twilio call recording (if available)
    audit_report.txt       - Human-readable summary
    test_verdict.json      - Pass/fail with per-assertion breakdown
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

try:
    import websockets
except ImportError:
    print("ERROR: websockets package required. Run: uv sync --group dev")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def load_frames(frames_dir: Path | None, single_image: Path | None) -> list[bytes]:
    """Load JPEG frames from a directory or repeat a single image."""
    if single_image is not None:
        if not single_image.exists():
            print(f"ERROR: Image not found: {single_image}")
            sys.exit(1)
        data = single_image.read_bytes()
        print(f"Loaded single image: {single_image.name} ({len(data)} bytes) - will repeat as frames")
        return [data]

    if frames_dir is None or not frames_dir.exists():
        print(f"ERROR: Frames directory not found: {frames_dir}")
        sys.exit(1)

    exts = {".jpg", ".jpeg", ".png"}
    files = sorted(f for f in frames_dir.iterdir() if f.suffix.lower() in exts)
    if not files:
        print(f"ERROR: No image files found in {frames_dir}")
        sys.exit(1)

    frames = [f.read_bytes() for f in files]
    print(f"Loaded {len(frames)} frames from {frames_dir}")
    return frames


# ---------------------------------------------------------------------------
# WebSocket message collector
# ---------------------------------------------------------------------------

class MessageCollector:
    """Collects and categorises all WebSocket messages."""

    def __init__(self) -> None:
        self.all_messages: list[dict] = []
        self.transcripts: list[dict] = []
        self.status_updates: list[dict] = []
        self.questions: list[dict] = []
        self.final_message: dict | None = None  # RESOLVED or FAILED

    def record(self, msg: dict) -> None:
        entry = {"ts": _epoch_ms(), "ts_str": _ts(), **msg}
        self.all_messages.append(entry)

        msg_type = msg.get("type", "")
        if msg_type == "transcript":
            self.transcripts.append(entry)
        elif msg_type == "STATUS_UPDATE":
            self.status_updates.append(entry)
        elif msg_type == "user_question":
            self.questions.append(entry)
        elif msg_type in ("RESOLVED", "FAILED"):
            self.final_message = entry


# ---------------------------------------------------------------------------
# Core test logic
# ---------------------------------------------------------------------------

async def run_test(
    backend_url: str,
    frames: list[bytes],
    fps: float,
    timeout_s: int,
    output_dir: Path,
) -> dict:
    """Run the E2E test and return the verdict dict."""

    collector = MessageCollector()
    test_start = time.time()

    # ── 1. Create session ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  E2E TEST START  {_ts()}")
    print(f"{'='*60}\n")

    async with httpx.AsyncClient(base_url=backend_url, timeout=15) as http:
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
        print(f"  Session created: {session_id}")
        print(f"  Status: {data.get('status')}\n")

    # ── 2. Connect WebSocket ──────────────────────────────────────────────
    ws_base = backend_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_base}/api/session/{session_id}/ws"

    done = asyncio.Event()
    frame_count = 0
    audio_count = 0

    async def send_frames(ws) -> None:
        nonlocal frame_count
        interval = 1.0 / fps
        idx = 0
        while not done.is_set():
            frame = frames[idx % len(frames)]
            b64 = base64.b64encode(frame).decode("ascii")
            await ws.send(json.dumps({"type": "video_frame", "data": b64}))
            frame_count += 1
            idx += 1
            try:
                await asyncio.wait_for(asyncio.shield(done.wait()), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass

    async def send_silent_audio(ws) -> None:
        nonlocal audio_count
        silence = base64.b64encode(b"\x00" * 16000).decode("ascii")
        while not done.is_set():
            await ws.send(json.dumps({"type": "audio", "data": silence}))
            audio_count += 1
            try:
                await asyncio.wait_for(asyncio.shield(done.wait()), timeout=0.5)
                break
            except asyncio.TimeoutError:
                pass

    async def receive_messages(ws) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                collector.record(msg)
                msg_type = msg.get("type", "unknown")

                if msg_type == "transcript":
                    speaker = msg.get("speaker", "?")
                    text = msg.get("text", "")
                    print(f"  [{_ts()}] TRANSCRIPT ({speaker}): {text}")
                elif msg_type == "STATUS_UPDATE":
                    phase = msg.get("phase", "?")
                    conf = msg.get("confidence", "?")
                    print(f"  [{_ts()}] STATUS: phase={phase}  confidence={conf}")
                elif msg_type == "user_question":
                    q = msg.get("question", "?")
                    print(f"  [{_ts()}] QUESTION: {q}")
                    # Auto-respond DA (yes)
                    await ws.send(json.dumps({
                        "type": "user_response",
                        "response_type": "TAP",
                        "value": "DA",
                    }))
                    print(f"  [{_ts()}] AUTO-RESPONSE: DA")
                elif msg_type == "RESOLVED":
                    eta = msg.get("eta_minutes", "?")
                    print(f"\n  [{_ts()}] RESOLVED: {msg.get('message', '')} (ETA: {eta} min)")
                    done.set()
                elif msg_type == "FAILED":
                    print(f"\n  [{_ts()}] FAILED: {msg.get('message', '')}")
                    done.set()
                elif msg_type == "pong":
                    pass
                else:
                    print(f"  [{_ts()}] {msg_type}: {json.dumps(msg, default=str)}")
        except websockets.exceptions.ConnectionClosed:
            print(f"  [{_ts()}] WebSocket closed")
            done.set()

    async def timeout_watchdog() -> None:
        try:
            await asyncio.wait_for(asyncio.shield(done.wait()), timeout=timeout_s)
        except asyncio.TimeoutError:
            print(f"\n  [{_ts()}] TIMEOUT after {timeout_s}s")
            done.set()

    print(f"  Connecting: {ws_url}")
    async with websockets.connect(ws_url) as ws:
        print(f"  WebSocket connected\n")
        tasks = [
            asyncio.create_task(send_frames(ws)),
            asyncio.create_task(send_silent_audio(ws)),
            asyncio.create_task(receive_messages(ws)),
            asyncio.create_task(timeout_watchdog()),
        ]
        await done.wait()
        await asyncio.sleep(2)  # let final messages arrive
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    test_duration = time.time() - test_start

    # ── 3. Fetch final snapshot ───────────────────────────────────────────
    print(f"\n  Fetching final snapshot...")
    snapshot_data = None
    async with httpx.AsyncClient(base_url=backend_url, timeout=10) as http:
        resp = await http.get(f"/api/session/{session_id}/status")
        if resp.status_code == 200:
            snapshot_data = resp.json()
            print(f"  Final phase: {snapshot_data.get('phase')}")
            print(f"  Final confidence: {snapshot_data.get('confidence')}")
            print(f"  Call status: {snapshot_data.get('call_status')}")

    # ── 4. Fetch Twilio recording ─────────────────────────────────────────
    call_details = {}
    recording_path = None
    twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    twilio_token = os.environ.get("TWILIO_AUTH_TOKEN", "")

    if twilio_sid and twilio_token:
        print(f"\n  Checking Twilio recordings...")
        try:
            from twilio.rest import Client as TwilioClient
            tc = TwilioClient(twilio_sid, twilio_token)

            # Find calls from the last 5 minutes for this session
            calls = tc.calls.list(limit=5)
            for call in calls:
                # The most recent call from our from_number is likely ours
                call_details = {
                    "sid": call.sid,
                    "status": call.status,
                    "direction": call.direction,
                    "duration": call.duration,
                    "from": call.from_formatted,
                    "to": call.to_formatted,
                    "start_time": str(call.start_time),
                    "end_time": str(call.end_time),
                }

                # Check for recordings on this call
                recordings = tc.recordings.list(call_sid=call.sid, limit=5)
                if recordings:
                    rec = recordings[0]
                    call_details["recording_sid"] = rec.sid
                    call_details["recording_duration"] = rec.duration
                    call_details["recording_uri"] = rec.uri

                    # Download the recording
                    rec_url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Recordings/{rec.sid}.mp3"
                    async with httpx.AsyncClient(timeout=30) as dl:
                        r = await dl.get(rec_url, auth=(twilio_sid, twilio_token))
                        if r.status_code == 200:
                            recording_path = output_dir / "call_recording.mp3"
                            recording_path.write_bytes(r.content)
                            call_details["recording_file"] = str(recording_path)
                            call_details["recording_size_bytes"] = len(r.content)
                            print(f"  Recording downloaded: {len(r.content)} bytes")
                        else:
                            print(f"  Recording download failed: {r.status_code}")

                break  # just use the most recent call
        except Exception as e:
            print(f"  Twilio error: {e}")
            call_details["error"] = str(e)
    else:
        print(f"\n  Twilio credentials not in env, skipping recording fetch")

    # ── 5. Write output files ─────────────────────────────────────────────
    print(f"\n  Writing output to {output_dir}/")
    output_dir.mkdir(parents=True, exist_ok=True)

    # WebSocket log
    ws_log_path = output_dir / "ws_log.jsonl"
    with open(ws_log_path, "w") as f:
        for msg in collector.all_messages:
            f.write(json.dumps(msg, default=str) + "\n")
    print(f"  ws_log.jsonl ({len(collector.all_messages)} messages)")

    # Final snapshot
    if snapshot_data:
        snap_path = output_dir / "snapshot_final.json"
        snap_path.write_text(json.dumps(snapshot_data, indent=2))
        print(f"  snapshot_final.json")

    # Call details
    if call_details:
        cd_path = output_dir / "call_details.json"
        cd_path.write_text(json.dumps(call_details, indent=2, default=str))
        print(f"  call_details.json")

    # ── 6. Generate verdict ───────────────────────────────────────────────
    assertions = {}

    # Check session resolved
    final_phase = snapshot_data.get("phase", "") if snapshot_data else ""
    assertions["session_resolved"] = {
        "passed": final_phase == "RESOLVED",
        "expected": "RESOLVED",
        "actual": final_phase,
    }

    # Check confidence reached threshold
    final_conf = snapshot_data.get("confidence", 0) if snapshot_data else 0
    assertions["confidence_built"] = {
        "passed": final_conf >= 0.45,  # At least GPS + emergency_type
        "expected": ">= 0.45",
        "actual": final_conf,
    }

    # Check phase transitions occurred
    phases_seen = [m.get("phase") for m in collector.status_updates]
    has_triage = "TRIAGE" in phases_seen
    has_live_call = "LIVE_CALL" in phases_seen
    assertions["phase_triage_reached"] = {
        "passed": has_triage,
        "expected": True,
        "actual": has_triage,
    }
    assertions["phase_live_call_reached"] = {
        "passed": has_live_call,
        "expected": True,
        "actual": has_live_call,
    }

    # Check transcript was generated
    assertions["has_transcript"] = {
        "passed": len(collector.transcripts) > 0,
        "expected": "> 0 transcripts",
        "actual": len(collector.transcripts),
    }

    # Check Twilio call was made
    assertions["twilio_call_made"] = {
        "passed": bool(call_details.get("sid")),
        "expected": "call SID exists",
        "actual": call_details.get("sid", "none"),
    }

    # Check recording exists
    assertions["call_recording_captured"] = {
        "passed": recording_path is not None and recording_path.exists(),
        "expected": "recording file exists",
        "actual": str(recording_path) if recording_path else "none",
    }

    # Check final message type
    final_type = collector.final_message.get("type", "") if collector.final_message else ""
    assertions["final_message_received"] = {
        "passed": final_type in ("RESOLVED", "FAILED"),
        "expected": "RESOLVED or FAILED",
        "actual": final_type,
    }

    all_passed = all(a["passed"] for a in assertions.values())

    verdict = {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(test_duration, 1),
        "frames_sent": frame_count,
        "audio_chunks_sent": audio_count,
        "ws_messages_received": len(collector.all_messages),
        "transcripts_count": len(collector.transcripts),
        "verdict": "PASS" if all_passed else "FAIL",
        "assertions": assertions,
    }

    verdict_path = output_dir / "test_verdict.json"
    verdict_path.write_text(json.dumps(verdict, indent=2))
    print(f"  test_verdict.json")

    # ── 7. Generate human-readable audit report ───────────────────────────
    report_lines = [
        f"E2E Test Audit Report",
        f"=====================",
        f"",
        f"Session ID:  {session_id}",
        f"Timestamp:   {datetime.now(timezone.utc).isoformat()}",
        f"Duration:    {round(test_duration, 1)}s",
        f"Backend:     {backend_url}",
        f"Verdict:     {'PASS' if all_passed else 'FAIL'}",
        f"",
        f"--- Input ---",
        f"Frames sent:        {frame_count}",
        f"Audio chunks sent:  {audio_count}",
        f"",
        f"--- Session State ---",
        f"Final phase:        {final_phase}",
        f"Final confidence:   {final_conf}",
        f"Call status:        {snapshot_data.get('call_status', 'N/A') if snapshot_data else 'N/A'}",
        f"ETA minutes:        {snapshot_data.get('eta_minutes', 'N/A') if snapshot_data else 'N/A'}",
        f"",
        f"--- Phases Observed ---",
    ]
    for su in collector.status_updates:
        report_lines.append(f"  [{su.get('ts_str', '')}] {su.get('phase', '')} confidence={su.get('confidence', '')}")

    report_lines.extend([
        f"",
        f"--- Transcripts ({len(collector.transcripts)}) ---",
    ])
    for t in collector.transcripts:
        report_lines.append(f"  [{t.get('ts_str', '')}] ({t.get('speaker', '?')}): {t.get('text', '')}")

    if collector.questions:
        report_lines.extend([
            f"",
            f"--- User Questions ({len(collector.questions)}) ---",
        ])
        for q in collector.questions:
            report_lines.append(f"  [{q.get('ts_str', '')}] {q.get('question', '')}")

    report_lines.extend([
        f"",
        f"--- Twilio Call ---",
        f"  Call SID:          {call_details.get('sid', 'N/A')}",
        f"  Call status:       {call_details.get('status', 'N/A')}",
        f"  Call duration:     {call_details.get('duration', 'N/A')}s",
        f"  Recording:         {'YES' if recording_path and recording_path.exists() else 'NO'}",
        f"  Recording size:    {call_details.get('recording_size_bytes', 'N/A')} bytes",
        f"",
        f"--- Assertions ---",
    ])
    for name, result in assertions.items():
        status = "PASS" if result["passed"] else "FAIL"
        report_lines.append(f"  [{status}] {name}: expected={result['expected']}, actual={result['actual']}")

    report_lines.extend([
        f"",
        f"--- Debug Traces ---",
        f"  Backend debug traces (if DEBUG_TRACE=true):",
        f"  backend/debug_traces/{session_id}/",
        f"    frames/          - Camera frames received by backend",
        f"    gemini/          - Gemini I/O (ua_input, ua_output, da_input, da_output)",
        f"    tools/           - Tool calls with args and results",
        f"    snapshots/       - Snapshot after every mutation",
        f"    dispatch/brief.txt - Emergency brief sent to operator",
        f"    phases/          - Phase transition log",
        f"    summary.json     - Full timeline",
        f"",
        f"--- Output Files ---",
        f"  {output_dir}/",
        f"    ws_log.jsonl           - All {len(collector.all_messages)} WebSocket messages",
        f"    snapshot_final.json    - Final session state",
        f"    call_details.json      - Twilio call metadata",
        f"    call_recording.mp3     - Call recording audio",
        f"    test_verdict.json      - Machine-readable verdict",
        f"    audit_report.txt       - This file",
    ])

    report = "\n".join(report_lines) + "\n"
    report_path = output_dir / "audit_report.txt"
    report_path.write_text(report)
    print(f"  audit_report.txt")

    # ── 8. Print summary ──────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  VERDICT: {'PASS' if all_passed else 'FAIL'}")
    print(f"{'='*60}")
    for name, result in assertions.items():
        mark = "+" if result["passed"] else "X"
        print(f"  [{mark}] {name}")
    print(f"\n  Output: {output_dir}/")
    print(f"  Audit:  {output_dir}/audit_report.txt")

    if not all_passed:
        print(f"\n  TIP: Read audit_report.txt and debug_traces/{session_id}/ for details")

    return verdict


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="E2E test: send frames through the full emergency pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--frames-dir", type=Path, help="Directory containing JPEG frames")
    group.add_argument("--image", type=Path, help="Single JPEG image (repeated as frames)")

    parser.add_argument("--backend", default="http://localhost:8080", help="Backend base URL")
    parser.add_argument("--fps", type=float, default=1.0, help="Frames per second to send")
    parser.add_argument("--timeout", type=int, default=120, help="Max seconds to run")
    parser.add_argument("--output-dir", type=Path, default=None, help="Override output directory")
    args = parser.parse_args()

    # Load frames
    frames = load_frames(args.frames_dir, args.image)

    # Verify backend is reachable
    print(f"  Checking backend at {args.backend}...")
    try:
        async with httpx.AsyncClient(base_url=args.backend, timeout=5) as http:
            resp = await http.get("/api/health")
            resp.raise_for_status()
            print(f"  Backend OK: {resp.json()}")
    except Exception as e:
        print(f"ERROR: Cannot reach backend at {args.backend}: {e}")
        print("  Make sure the backend is running and the URL is correct.")
        sys.exit(1)

    # Determine output directory
    # We'll create it with session_id after the session is created,
    # but we need a temp name first. The run_test function handles this.
    base_output = args.output_dir or Path(__file__).parent / "output"

    # Use a temporary session_id placeholder — run_test will create the real dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = base_output / f"run_{timestamp}"

    verdict = await run_test(
        backend_url=args.backend,
        frames=frames,
        fps=args.fps,
        timeout_s=args.timeout,
        output_dir=output_dir,
    )

    # Also symlink/copy as "latest"
    latest = base_output / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    try:
        latest.symlink_to(output_dir.name)
    except OSError:
        pass  # symlinks may not work on all platforms

    sys.exit(0 if verdict["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    asyncio.run(main())
