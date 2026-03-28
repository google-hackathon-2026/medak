import { triggerSOS } from "./api";
import { getCurrentLocation, reverseGeocode } from "./location";
import { getDeviceId, getUserId } from "./storage";

export interface SOSResult {
  sessionId: string;
}

/**
 * Initiates an SOS call: gets location + IDs, calls backend.
 * If requireLocation is true, throws when location is unavailable.
 * Address reverse-geocoding runs in parallel and never blocks the call.
 */
export async function initiateSOSCall(options?: {
  requireLocation?: boolean;
}): Promise<SOSResult> {
  const requireLocation = options?.requireLocation ?? false;

  const [location, userId, deviceId] = await Promise.all([
    getCurrentLocation().catch(() => null),
    getUserId(),
    getDeviceId(),
  ]);

  if (requireLocation && !location) {
    throw new Error("LOCATION_UNAVAILABLE");
  }

  const lat = location?.latitude ?? 0;
  const lng = location?.longitude ?? 0;

  // Fire SOS and reverse geocode in parallel — don't block on address
  const [response] = await Promise.all([
    triggerSOS({ lat, lng, user_id: userId, device_id: deviceId }),
    reverseGeocode(lat, lng).catch(() => null),
  ]);

  return { sessionId: response.session_id };
}
