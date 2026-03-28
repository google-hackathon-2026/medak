export type DangerType = "FALL" | "SHAKE";

// Session phases
export type SessionPhase =
  | "INTAKE"
  | "TRIAGE"
  | "LIVE_CALL"
  | "RESOLVED"
  | "FAILED";

// Emergency types — 3 buttons on home screen
export type EmergencyType = "AMBULANCE" | "POLICE" | "FIRE";

// Dispatch Agent call status
export type CallStatus =
  | "IDLE"
  | "DIALING"
  | "CONNECTED"
  | "CONFIRMED"
  | "DROPPED";

// Location from device
export interface LocationData {
  latitude: number;
  longitude: number;
  accuracy: number | null;
  address?: string;
}

// POST /api/sos request
export interface SOSRequest {
  emergency_type: EmergencyType;
  lat: number;
  lng: number;
  address?: string;
  user_id: string;
  device_id: string;
}

// POST /api/sos response
export interface SOSResponse {
  session_id: string;
  status: "TRIAGE";
}

// GET /api/session/{id}/status response
export interface SessionStatus {
  session_id: string;
  phase: SessionPhase;
  confidence: number;
  call_status: CallStatus;
  eta_minutes: number | null;
  snapshot_version: number;
}

// WebSocket messages: server -> client
export type WSMessageFromServer =
  | { type: "transcript"; speaker: "assistant" | "user"; text: string }
  | { type: "STATUS_UPDATE"; phase: SessionPhase; confidence: number }
  | { type: "user_question"; question: string }
  | { type: "pong" }
  | { type: "RESOLVED"; eta_minutes: number; message: string }
  | { type: "FAILED"; message: string };

// WebSocket messages: client -> server
export type WSMessageToServer =
  | { type: "audio"; data: string }
  | { type: "video_frame"; data: string }
  | { type: "ping" }
  | {
      type: "user_response";
      response_type: "TAP" | "TEXT";
      value: string;
    };

// Transcript entry for display
export interface TranscriptEntry {
  id: string;
  speaker: "assistant" | "user";
  text: string;
  timestamp: number;
}

// User info (persisted in AsyncStorage via settings screen)
export interface UserInfo {
  name: string;
  address: string;
  phone: string;
  medicalNotes: string;
  disability: "DEAF" | "MUTE" | "DEAF_MUTE" | "";
}
