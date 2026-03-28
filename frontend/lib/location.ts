import * as Location from "expo-location";
import { LocationData } from "./types";

export async function requestLocationPermission(): Promise<boolean> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  return status === "granted";
}

export async function getCurrentLocation(): Promise<LocationData | null> {
  const granted = await requestLocationPermission();
  if (!granted) return null;

  const location = await Promise.race([
    Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    }),
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("Location timeout")), 10000)
    ),
  ]);

  return {
    latitude: location.coords.latitude,
    longitude: location.coords.longitude,
    accuracy: location.coords.accuracy,
  };
}
