import { useEffect, useRef, useState, useCallback } from "react";
import { Accelerometer } from "expo-sensors";
import type { DangerType } from "./types";
import type { DangerSettings } from "./dangerSettings";

const FREEFALL_THRESHOLD = 0.6;
const FREEFALL_THRESHOLD_SQ = FREEFALL_THRESHOLD ** 2;
const FREEFALL_MIN_DURATION = 150;
const IMPACT_THRESHOLD = 1.8;
const IMPACT_THRESHOLD_SQ = IMPACT_THRESHOLD ** 2;
const IMPACT_WINDOW = 1000;
const SHAKE_AMPLITUDE = 1.2;
const SHAKE_WINDOW = 2000;
const COOLDOWN = 30000;
const UPDATE_INTERVAL = 100;

const SHAKE_COUNTS: Record<DangerSettings["shakeSensitivity"], number> = {
  LOW: 7,
  MEDIUM: 5,
  HIGH: 3,
};

interface Options {
  onDangerDetected: (type: DangerType) => void;
  enabled: boolean;
  shakeSensitivity?: DangerSettings["shakeSensitivity"];
}

export function useDangerDetection(options: Options) {
  const { onDangerDetected, enabled, shakeSensitivity = "MEDIUM" } = options;

  const [isMonitoring, setIsMonitoring] = useState(false);
  const [sensorAvailable, setSensorAvailable] = useState<boolean | null>(null);
  const lastTrigger = useRef(0);
  const callbackRef = useRef(onDangerDetected);
  callbackRef.current = onDangerDetected;
  const sensitivityRef = useRef(shakeSensitivity);
  sensitivityRef.current = shakeSensitivity;

  const fallState = useRef<{
    phase: "IDLE" | "FREEFALL" | "IMPACT_WINDOW";
    freefallStart: number | null;
    freefallEnd: number | null;
  }>({ phase: "IDLE", freefallStart: null, freefallEnd: null });

  const shakeState = useRef<{
    lastMagnitude: number | null;
    lastDelta: number | null;
    events: number[];
  }>({ lastMagnitude: null, lastDelta: null, events: [] });

  const trigger = useCallback(
    (type: DangerType) => {
      const now = Date.now();
      if (now - lastTrigger.current < COOLDOWN) return;
      lastTrigger.current = now;

      fallState.current = {
        phase: "IDLE",
        freefallStart: null,
        freefallEnd: null,
      };
      shakeState.current = {
        lastMagnitude: null,
        lastDelta: null,
        events: [],
      };

      callbackRef.current(type);
    },
    []
  );

  useEffect(() => {
    if (!enabled) {
      setIsMonitoring(false);
      return;
    }

    let subscription: ReturnType<typeof Accelerometer.addListener> | null =
      null;

    (async () => {
      const available = await Accelerometer.isAvailableAsync();
      setSensorAvailable(available);
      if (!available) return;

      Accelerometer.setUpdateInterval(UPDATE_INTERVAL);
      setIsMonitoring(true);

      subscription = Accelerometer.addListener(({ x, y, z }) => {
        const now = Date.now();
        const magnitudeSq = x * x + y * y + z * z;

        // Fall detection: compare squared magnitudes to avoid sqrt
        const fs = fallState.current;

        if (fs.phase === "IDLE") {
          if (magnitudeSq < FREEFALL_THRESHOLD_SQ) {
            fs.phase = "FREEFALL";
            fs.freefallStart = now;
          }
        } else if (fs.phase === "FREEFALL") {
          if (magnitudeSq >= FREEFALL_THRESHOLD_SQ) {
            const duration = now - (fs.freefallStart ?? now);
            if (duration >= FREEFALL_MIN_DURATION) {
              fs.phase = "IMPACT_WINDOW";
              fs.freefallEnd = now;
            } else {
              fs.phase = "IDLE";
              fs.freefallStart = null;
            }
          }
        } else if (fs.phase === "IMPACT_WINDOW") {
          if (magnitudeSq > IMPACT_THRESHOLD_SQ) {
            trigger("FALL");
            return;
          }
          if (now - (fs.freefallEnd ?? now) > IMPACT_WINDOW) {
            fs.phase = "IDLE";
            fs.freefallStart = null;
            fs.freefallEnd = null;
          }
        }

        // Shake detection: needs actual magnitude for delta calculation
        const ss = shakeState.current;
        const magnitude = Math.sqrt(magnitudeSq);

        if (ss.lastMagnitude !== null) {
          const delta = magnitude - ss.lastMagnitude;

          if (
            ss.lastDelta !== null &&
            Math.sign(delta) !== Math.sign(ss.lastDelta) &&
            Math.abs(delta) > SHAKE_AMPLITUDE
          ) {
            ss.events.push(now);
          }

          // Prune old events — in-place shift since timestamps are sorted
          while (ss.events.length > 0 && now - ss.events[0] > SHAKE_WINDOW) {
            ss.events.shift();
          }

          const required = SHAKE_COUNTS[sensitivityRef.current];
          if (ss.events.length >= required) {
            ss.events = [];
            trigger("SHAKE");
            return;
          }

          ss.lastDelta = delta;
        }
        ss.lastMagnitude = magnitude;
      });
    })();

    return () => {
      subscription?.remove();
      setIsMonitoring(false);
    };
  }, [enabled, trigger]);

  return { isMonitoring, sensorAvailable };
}
