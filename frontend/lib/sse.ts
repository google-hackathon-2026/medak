import EventSource from "react-native-sse";
import { StatusEvent, TranscriptEvent, NeedInputEvent } from "./types";
import { API_BASE } from "./config";

type SSECustomEvents = "status" | "transcript" | "needInput";

export interface SSECallbacks {
  onStatus: (event: StatusEvent) => void;
  onTranscript: (event: TranscriptEvent) => void;
  onNeedInput: (event: NeedInputEvent) => void;
  onError: (error: Error) => void;
}

export function connectToCallStream(
  callId: string,
  callbacks: SSECallbacks
): () => void {
  const es = new EventSource<SSECustomEvents>(
    `${API_BASE}/api/calls/${callId}/stream`,
    { headers: { Accept: "text/event-stream" } }
  );

  es.addEventListener("status", (event) => {
    if (event.data) {
      try { callbacks.onStatus(JSON.parse(event.data)); } catch {}
    }
  });

  es.addEventListener("transcript", (event) => {
    if (event.data) {
      try { callbacks.onTranscript(JSON.parse(event.data)); } catch {}
    }
  });

  es.addEventListener("needInput", (event) => {
    if (event.data) {
      try { callbacks.onNeedInput(JSON.parse(event.data)); } catch {}
    }
  });

  es.addEventListener("error", (event) => {
    if (event.type === "error") {
      callbacks.onError(new Error(event.message ?? "SSE connection failed"));
    }
  });

  return () => es.close();
}
