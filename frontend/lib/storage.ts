import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Crypto from "expo-crypto";
import { UserInfo } from "./types";

const KEYS = {
  USER_INFO: "medak_user_info",
  DEVICE_ID: "medak_device_id",
  USER_ID: "medak_user_id",
} as const;

export const DEFAULT_USER_INFO: UserInfo = {
  personalInfo: "",
};

export async function getUserInfo(): Promise<UserInfo> {
  const raw = await AsyncStorage.getItem(KEYS.USER_INFO);
  if (!raw) return { ...DEFAULT_USER_INFO };
  return { ...DEFAULT_USER_INFO, ...JSON.parse(raw) };
}

export async function saveUserInfo(info: UserInfo): Promise<void> {
  await AsyncStorage.setItem(KEYS.USER_INFO, JSON.stringify(info));
}

async function getOrCreateId(key: string): Promise<string> {
  let id = await AsyncStorage.getItem(key);
  if (!id) {
    id = Crypto.randomUUID();
    await AsyncStorage.setItem(key, id);
  }
  return id;
}

export const getDeviceId = () => getOrCreateId(KEYS.DEVICE_ID);
export const getUserId = () => getOrCreateId(KEYS.USER_ID);
