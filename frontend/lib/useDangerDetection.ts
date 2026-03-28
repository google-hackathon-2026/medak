import { useEffect, useRef, useCallback } from "react";
import { DeviceMotion } from "expo-sensors";
import type { DangerType } from "./types";

// Fall detection uses accelerationIncludingGravity:
// at rest ~1g, freefall ~0g, impact >2g
const FREEFALL_THRESHOLD_SQ = 0.3 ** 2; // must be genuinely close to 0g
const FREEFALL_MIN_DURATION = 150;
const IMPACT_THRESHOLD_SQ = 2.5 ** 2;
const IMPACT_WINDOW = 1500;

// Shake detection uses acceleration (gravity removed):
// at rest ~0, shaking produces clear oscillation
const SHAKE_AMPLITUDE = 1.5;
const SHAKE_WINDOW = 2000;
const SHAKE_REQUIRED = 5;

const COOLDOWN = 30000;
const UPDATE_INTERVAL = 100;

interface Options {
  onDangerDetected: (type: DangerType) => void;
  enabled: boolean;
}

export function useDangerDetection(options: Options) {
  const { onDangerDetected, enabled } = options;
  const callbackRef = useRef(onDangerDetected);
  callbackRef.current = onDangerDetected;
  const lastTrigger = useRef(0);

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

  const trigger = useCallback((type: DangerType) => {
    const now = Date.now();
    if (now - lastTrigger.current < COOLDOWN) return;
    lastTrigger.current = now;

    fallState.current = { phase: "IDLE", freefallStart: null, freefallEnd: null };
    shakeState.current = { lastMagnitude: null, lastDelta: null, events: [] };

    callbackRef.current(type);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    let subscription: ReturnType<typeof DeviceMotion.addListener> | null = null;
    let cancelled = false;

    (async () => {
      const available = await DeviceMotion.isAvailableAsync();
      if (!available || cancelled) return;

      DeviceMotion.setUpdateInterval(UPDATE_INTERVAL);

      subscription = DeviceMotion.addListener((data) => {
        const g = data.accelerationIncludingGravity;
        const a = data.acceleration;
        if (!g && !a) return;

        const now = Date.now();

        // Fall detection: accelerationIncludingGravity (at rest ~1g, freefall ~0g)
        if (g) {
          const gMagSq = g.x * g.x + g.y * g.y + g.z * g.z;
          const fs = fallState.current;

          if (fs.phase === "IDLE") {
            if (gMagSq < FREEFALL_THRESHOLD_SQ) {
              fs.phase = "FREEFALL";
              fs.freefallStart = now;
            }
          } else if (fs.phase === "FREEFALL") {
            if (gMagSq >= FREEFALL_THRESHOLD_SQ) {
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
            if (gMagSq > IMPACT_THRESHOLD_SQ) {
              trigger("FALL");
              return;
            }
            if (now - (fs.freefallEnd ?? now) > IMPACT_WINDOW) {
              fs.phase = "IDLE";
              fs.freefallStart = null;
              fs.freefallEnd = null;
            }
          }
        }

        // Shake detection: acceleration without gravity (at rest ~0)
        if (a) {
          const magnitude = Math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z);
          const ss = shakeState.current;

          if (ss.lastMagnitude !== null) {
            const delta = magnitude - ss.lastMagnitude;

            if (
              ss.lastDelta !== null &&
              delta * ss.lastDelta < 0 &&
              Math.abs(delta) > SHAKE_AMPLITUDE
            ) {
              ss.events.push(now);
            }

            while (ss.events.length > 0 && now - ss.events[0] > SHAKE_WINDOW) {
              ss.events.shift();
            }

            if (ss.events.length >= SHAKE_REQUIRED) {
              ss.events = [];
              trigger("SHAKE");
              return;
            }

            ss.lastDelta = delta;
          }
          ss.lastMagnitude = magnitude;
        }
      });
    })();

    return () => {
      cancelled = true;
      subscription?.remove();
    };
  }, [enabled, trigger]);
}
