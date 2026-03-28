import { API_BASE } from "./config";
import type { SessionPhase, WSMessageFromServer, WSMessageToServer } from "./types";

export interface WSCallbacks {
  onTranscript: (speaker: "assistant" | "user", text: string) => void;
  onStatusUpdate: (phase: SessionPhase, confidence: number) => void;
  onUserQuestion: (question: string) => void;
  onResolved: (etaMinutes: number, message: string) => void;
  onFailed: (message: string) => void;
  onConnectionChange: (connected: boolean) => void;
}

const MAX_RECONNECT_ATTEMPTS = 3;
const PING_INTERVAL_MS = 15_000;

function buildWsUrl(sessionId: string): string {
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/api/session/${sessionId}/ws`;
}

export class SessionWebSocket {
  private ws: WebSocket | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectAttempts = 0;
  private closed = false;
  private sessionId: string;
  private callbacks: WSCallbacks;

  constructor(sessionId: string, callbacks: WSCallbacks) {
    this.sessionId = sessionId;
    this.callbacks = callbacks;
  }

  connect(): void {
    this.closed = false;
    this.reconnectAttempts = 0;
    this.openSocket();
  }

  disconnect(): void {
    this.closed = true;
    this.stopPing();
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.callbacks.onConnectionChange(false);
  }

  sendAudio(base64Pcm: string): void {
    this.send({ type: "audio", data: base64Pcm });
  }

  sendVideoFrame(base64Jpeg: string): void {
    this.send({ type: "video_frame", data: base64Jpeg });
  }

  sendUserResponse(responseType: "TAP" | "TEXT", value: string): void {
    this.send({ type: "user_response", response_type: responseType, value });
  }

  private send(msg: WSMessageToServer): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  private openSocket(): void {
    const url = buildWsUrl(this.sessionId);
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.callbacks.onConnectionChange(true);
      this.startPing();
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSMessageFromServer;
        this.dispatch(msg);
      } catch {
        // ignore malformed messages
      }
    };

    this.ws.onclose = () => {
      this.callbacks.onConnectionChange(false);
      this.stopPing();
      this.tryReconnect();
    };

    this.ws.onerror = () => {
      // onclose will fire after onerror
    };
  }

  private dispatch(msg: WSMessageFromServer): void {
    switch (msg.type) {
      case "transcript":
        this.callbacks.onTranscript(msg.speaker, msg.text);
        break;
      case "STATUS_UPDATE":
        this.callbacks.onStatusUpdate(msg.phase, msg.confidence);
        break;
      case "user_question":
        this.callbacks.onUserQuestion(msg.question);
        break;
      case "RESOLVED":
        this.callbacks.onResolved(msg.eta_minutes, msg.message);
        break;
      case "FAILED":
        this.callbacks.onFailed(msg.message);
        break;
      case "pong":
        break;
    }
  }

  private tryReconnect(): void {
    if (this.closed) return;
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      this.callbacks.onFailed("WebSocket connection lost after retries");
      return;
    }
    this.reconnectAttempts++;
    const delay = Math.pow(2, this.reconnectAttempts) * 1000; // 2s, 4s, 8s
    setTimeout(() => {
      if (!this.closed) this.openSocket();
    }, delay);
  }

  private startPing(): void {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      this.send({ type: "ping" });
    }, PING_INTERVAL_MS);
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }
}
