import { triggerSOS } from "./api";
import { getCurrentLocation, reverseGeocode } from "./location";
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

  // Reverse-geocode address in parallel (best-effort, never blocks)
  const address = location
    ? await reverseGeocode(lat, lng).catch(() => null)
    : null;

  // Abort controller with 10s timeout
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);

  try {
    const response = await triggerSOS(
      {
        emergency_type: emergencyType,
        lat,
        lng,
        address: address ?? undefined,
        user_id: userId,
        device_id: deviceId,
      },
      controller.signal,
    );

    return { sessionId: response.session_id };
  } finally {
    clearTimeout(timeout);
  }
}
