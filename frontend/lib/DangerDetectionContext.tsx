import React, { createContext, useContext, useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useRouter, usePathname } from "expo-router";
import { useDangerDetection } from "./useDangerDetection";
import { initiateSOSCall } from "./sosFlow";
import type { DangerType } from "./types";

interface DangerDetectionContextValue {
  dismissAlarm: () => void;
}

const DangerDetectionContext = createContext<DangerDetectionContextValue>({
  dismissAlarm: () => {},
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
  const [alarmActive, setAlarmActive] = useState(false);
  const navigatingRef = useRef(false);
  const alarmActiveRef = useRef(false);
  alarmActiveRef.current = alarmActive;
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clean up timeouts on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  const suppressed = pathname === "/session" || pathname === "/alarm" || alarmActive;

  const handleShakeDirectCall = useCallback(async () => {
    try {
      const { sessionId } = await initiateSOSCall({ emergencyType: "AMBULANCE" });
      router.push({ pathname: "/session", params: { sessionId } });
    } catch {
      router.push({ pathname: "/alarm", params: { type: "SHAKE" } });
    } finally {
      timeoutRef.current = setTimeout(() => {
        navigatingRef.current = false;
        setAlarmActive(false);
      }, 1000);
    }
  }, [router]);

  const handleDangerDetected = useCallback(
    (type: DangerType) => {
      if (navigatingRef.current || alarmActiveRef.current) return;
      navigatingRef.current = true;
      setAlarmActive(true);

      if (timeoutRef.current) clearTimeout(timeoutRef.current);

      if (type === "SHAKE") {
        handleShakeDirectCall();
      } else {
        router.push({ pathname: "/alarm", params: { type } });
        timeoutRef.current = setTimeout(() => {
          navigatingRef.current = false;
        }, 1000);
      }
    },
    [router, handleShakeDirectCall]
  );

  const dismissAlarm = useCallback(() => {
    setAlarmActive(false);
    navigatingRef.current = false;
  }, []);

  useDangerDetection({
    onDangerDetected: handleDangerDetected,
    enabled: !suppressed,
  });

  const contextValue = useMemo(
    () => ({ dismissAlarm }),
    [dismissAlarm]
  );

  return (
    <DangerDetectionContext.Provider value={contextValue}>
      {children}
    </DangerDetectionContext.Provider>
  );
}
