import { triggerSOS } from "./api";
import { getCurrentLocation } from "./location";
import { getDeviceId, getUserId } from "./storage";
import type { EmergencyType } from "./types";

export const LOCATION_UNAVAILABLE = "LOCATION_UNAVAILABLE";

export interface SOSResult {
  sessionId: string;
}

/**
 * Initiates an SOS call: gets location + IDs, calls backend.
 * If requireLocation is true, throws when location is unavailable.
 * Address reverse-geocoding runs in parallel and never blocks the call.
 */
export async function initiateSOSCall(options: {
  emergencyType: EmergencyType;
  requireLocation?: boolean;
}): Promise<SOSResult> {
  const { emergencyType, requireLocation = false } = options;

  const [location, userId, deviceId] = await Promise.all([
    getCurrentLocation().catch(() => null),
    getUserId(),
    getDeviceId(),
  ]);

  if (requireLocation && !location) {
    throw new Error(LOCATION_UNAVAILABLE);
  }

  const lat = location?.latitude ?? 0;
  const lng = location?.longitude ?? 0;

  const response = await triggerSOS({
    emergency_type: emergencyType,
    lat,
    lng,
    user_id: userId,
    device_id: deviceId,
  });

  return { sessionId: response.session_id };
}
