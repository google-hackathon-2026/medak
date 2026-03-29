import { SOSRequest, SOSResponse, SessionStatus } from "./types";
import { API_BASE } from "./config";

export async function triggerSOS(request: SOSRequest, signal?: AbortSignal): Promise<SOSResponse> {
  const res = await fetch(`${API_BASE}/api/sos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });

  if (!res.ok) {
    throw new Error(`SOS request failed: ${res.status}`);
  }

  return res.json();
}

export async function getSessionStatus(
  sessionId: string
): Promise<SessionStatus> {
  const res = await fetch(`${API_BASE}/api/session/${sessionId}/status`);

  if (!res.ok) {
    throw new Error(`Status request failed: ${res.status}`);
  }

  return res.json();
}
