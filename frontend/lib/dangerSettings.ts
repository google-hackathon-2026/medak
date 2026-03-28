import AsyncStorage from "@react-native-async-storage/async-storage";

const KEY = "medak_danger_settings";

export interface DangerSettings {
  fallDetectionEnabled: boolean;
  shakeSOSEnabled: boolean;
  shakeSensitivity: "LOW" | "MEDIUM" | "HIGH";
}

export const DEFAULT_DANGER_SETTINGS: DangerSettings = {
  fallDetectionEnabled: false,
  shakeSOSEnabled: false,
  shakeSensitivity: "MEDIUM",
};

export async function getDangerSettings(): Promise<DangerSettings> {
  const raw = await AsyncStorage.getItem(KEY);
  if (!raw) return { ...DEFAULT_DANGER_SETTINGS };
  return { ...DEFAULT_DANGER_SETTINGS, ...JSON.parse(raw) };
}

export async function saveDangerSettings(
  settings: DangerSettings
): Promise<void> {
  await AsyncStorage.setItem(KEY, JSON.stringify(settings));
}
