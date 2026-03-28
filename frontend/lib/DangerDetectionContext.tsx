import React, { createContext, useContext, useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useRouter, usePathname } from "expo-router";
import { useDangerDetection } from "./useDangerDetection";
import {
  DangerSettings,
  getDangerSettings,
  DEFAULT_DANGER_SETTINGS,
} from "./dangerSettings";
import type { DangerType } from "./types";

interface DangerDetectionContextValue {
  alarmActive: boolean;
  dismissAlarm: () => void;
  isMonitoring: boolean;
  reloadSettings: () => Promise<void>;
}

const DangerDetectionContext = createContext<DangerDetectionContextValue>({
  alarmActive: false,
  dismissAlarm: () => {},
  isMonitoring: false,
  reloadSettings: async () => {},
});

export function useDangerDetectionContext() {
  return useContext(DangerDetectionContext);
}

export function DangerDetectionProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [settings, setSettings] = useState<DangerSettings>(DEFAULT_DANGER_SETTINGS);
  const [alarmActive, setAlarmActive] = useState(false);
  const navigatingRef = useRef(false);
  const alarmActiveRef = useRef(false);
  alarmActiveRef.current = alarmActive;

  // Don't detect on session/alarm screens or when alarm is already firing
  const suppressed = pathname === "/session" || pathname === "/alarm" || alarmActive;
  const enabled =
    !suppressed &&
    (settings.fallDetectionEnabled || settings.shakeSOSEnabled);

  const loadSettings = useCallback(async () => {
    const s = await getDangerSettings();
    setSettings(s);
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const handleDangerDetected = useCallback(
    (type: DangerType) => {
      if (navigatingRef.current || alarmActiveRef.current) return;
      navigatingRef.current = true;

      setAlarmActive(true);
      router.push({ pathname: "/alarm", params: { type } });

      setTimeout(() => {
        navigatingRef.current = false;
      }, 1000);
    },
    [router]
  );

  const dismissAlarm = useCallback(() => {
    setAlarmActive(false);
    navigatingRef.current = false;
  }, []);

  const { isMonitoring } = useDangerDetection({
    onDangerDetected: handleDangerDetected,
    enabled,
    fallEnabled: settings.fallDetectionEnabled,
    shakeEnabled: settings.shakeSOSEnabled,
    shakeSensitivity: settings.shakeSensitivity,
  });

  const contextValue = useMemo(
    () => ({
      alarmActive,
      dismissAlarm,
      isMonitoring,
      reloadSettings: loadSettings,
    }),
    [alarmActive, dismissAlarm, isMonitoring, loadSettings]
  );

  return (
    <DangerDetectionContext.Provider value={contextValue}>
      {children}
    </DangerDetectionContext.Provider>
  );
}
