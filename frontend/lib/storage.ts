import AsyncStorage from "@react-native-async-storage/async-storage";
import { UserInfo, CallHistoryEntry } from "./types";

const KEYS = {
  USER_INFO: "medak_user_info",
  CALL_HISTORY: "medak_call_history",
} as const;

export const DEFAULT_USER_INFO: UserInfo = {
  name: "",
  address: "",
  phone: "",
  medicalNotes: "",
  disability: "",
};

export async function getUserInfo(): Promise<UserInfo> {
  const raw = await AsyncStorage.getItem(KEYS.USER_INFO);
  if (!raw) return { ...DEFAULT_USER_INFO };
  return { ...DEFAULT_USER_INFO, ...JSON.parse(raw) };
}

export async function saveUserInfo(info: UserInfo): Promise<void> {
  await AsyncStorage.setItem(KEYS.USER_INFO, JSON.stringify(info));
}

export async function getCallHistory(): Promise<CallHistoryEntry[]> {
  const raw = await AsyncStorage.getItem(KEYS.CALL_HISTORY);
  if (!raw) return [];
  return JSON.parse(raw);
}

export async function addCallToHistory(entry: CallHistoryEntry): Promise<void> {
  const history = await getCallHistory();
  history.unshift(entry);
  // Keep last 50 entries
  await AsyncStorage.setItem(
    KEYS.CALL_HISTORY,
    JSON.stringify(history.slice(0, 50))
  );
}
