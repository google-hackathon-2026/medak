import { triggerSOS } from "./api";
import { getCurrentLocation, reverseGeocode } from "./location";
import { getDeviceId, getUserId } from "./storage";
import type { EmergencyType } from "./types";

export const LOCATION_UNAVAILABLE = "LOCATION_UNAVAILABLE";

/** Timeout in ms for the SOS API call */
const SOS_TIMEOUT_MS = 10_000;

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

  // Attempt reverse geocode — non-blocking, returns null on failure
  let address: string | null = null;
  if (location) {
    address = await reverseGeocode(lat, lng).catch(() => null);
  }

  // Use AbortController to enforce a 10-second timeout on the SOS request
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), SOS_TIMEOUT_MS);

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
  } catch (e: any) {
    if (e?.name === "AbortError") {
      throw new Error("Connection timed out. Check your network.");
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}
