export type EmergencyType = "AMBULANCE" | "POLICE" | "FIRE";

export type QuickTag =
  | "TRAFFIC_ACCIDENT"
  | "HEART_ATTACK"
  | "FALL"
  | "FIRE_SCENE"
  | "VIOLENCE"
  | "BREATHING"
  | "UNCONSCIOUS"
  | "MULTIPLE_VICTIMS"
  | "CHILD";

export interface LocationData {
  latitude: number;
  longitude: number;
  accuracy: number | null;
}

export interface UserInfo {
  name: string;
  address: string;
  phone: string;
  medicalNotes: string;
  disability: "DEAF" | "MUTE" | "DEAF_MUTE" | "";
}

export interface EmergencyRequest {
  emergencyType: EmergencyType;
  description: string;
  quickTags: QuickTag[];
  location: LocationData;
  userInfo: UserInfo;
  photoBase64?: string;
}

export interface CallResponse {
  callId: string;
  status: "INITIATING";
  streamUrl: string;
}

export type CallStatus = "CALLING" | "CONNECTED" | "COMPLETED" | "ERROR";

export interface StatusEvent {
  status: CallStatus;
  message: string;
}

export interface TranscriptEvent {
  speaker: "AI" | "OPERATOR";
  text: string;
}

export interface NeedInputEvent {
  question: string;
}

export interface TranscriptEntry {
  id: string;
  speaker: "AI" | "OPERATOR" | "USER";
  text: string;
  timestamp: number;
}

export interface CallHistoryEntry {
  id: string;
  timestamp: number;
  emergencyType: EmergencyType;
  status: CallStatus;
  transcript: TranscriptEntry[];
}

export const QUICK_TAG_LABELS: Record<QuickTag, string> = {
  TRAFFIC_ACCIDENT: "Saobraćajna nesreća",
  HEART_ATTACK: "Srčani udar",
  FALL: "Pad",
  FIRE_SCENE: "Požar",
  VIOLENCE: "Nasilje",
  BREATHING: "Problemi sa disanjem",
  UNCONSCIOUS: "Bez svesti",
  MULTIPLE_VICTIMS: "Više povređenih",
  CHILD: "Dete",
};
