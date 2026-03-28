import { EmergencyRequest, CallResponse } from "./types";
import { API_BASE } from "./config";

export async function initiateCall(
  request: EmergencyRequest
): Promise<CallResponse> {
  const res = await fetch(`${API_BASE}/api/calls`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!res.ok) {
    throw new Error(`Failed to initiate call: ${res.status}`);
  }

  return res.json();
}

export async function sendUserInput(
  callId: string,
  text: string
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/calls/${callId}/input`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });

  if (!res.ok) {
    throw new Error(`Failed to send input: ${res.status}`);
  }
}
