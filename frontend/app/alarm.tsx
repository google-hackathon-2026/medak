import { useState, useEffect, useRef, useCallback } from "react";
import { View, StyleSheet, Animated } from "react-native";
import { Text, Button } from "react-native-paper";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import { useDangerDetectionContext } from "../lib/DangerDetectionContext";
import { initiateSOSCall } from "../lib/sosFlow";
import { useAppTheme } from "../lib/useAppTheme";
import type { DangerType } from "../lib/types";

const COUNTDOWN_SECONDS = 15;

export default function AlarmScreen() {
  const { type } = useLocalSearchParams<{ type: DangerType }>();
  const router = useRouter();
  const theme = useAppTheme();
  const { dismissAlarm } = useDangerDetectionContext();
  const dangerType: DangerType = type === "FALL" || type === "SHAKE" ? type : "FALL";

  const [seconds, setSeconds] = useState(COUNTDOWN_SECONDS);
  const [calling, setCalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pulseAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, {
          toValue: 1,
          duration: 500,
          useNativeDriver: false,
        }),
        Animated.timing(pulseAnim, {
          toValue: 0,
          duration: 500,
          useNativeDriver: false,
        }),
      ])
    );
    animation.start();
    return () => animation.stop();
  }, [pulseAnim]);

  // Haptic feedback — faster when countdown is critical (<= 5s)
  const isCritical = seconds <= 5;
  useEffect(() => {
    if (calling || error) return;

    const interval = isCritical ? 250 : 500;
    const timer = setInterval(() => {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    }, interval);

    return () => clearInterval(timer);
  }, [isCritical, calling, error]);

  const handleAutoCall = useCallback(async () => {
    setCalling(true);

    try {
      const { sessionId } = await initiateSOSCall();
      dismissAlarm();
      router.replace({
        pathname: "/session",
        params: { sessionId },
      });
    } catch {
      setCalling(false);
      setError("Poziv nije uspeo. Pokušajte ručno.");
    }
  }, [router, dismissAlarm]);

  useEffect(() => {
    if (calling || error) return;

    if (seconds <= 0) {
      handleAutoCall();
      return;
    }

    const timer = setTimeout(() => setSeconds((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [seconds, calling, error, handleAutoCall]);

  const handleCancel = useCallback(() => {
    dismissAlarm();
    router.back();
  }, [dismissAlarm, router]);

  const handleGoHome = useCallback(() => {
    dismissAlarm();
    router.replace("/");
  }, [dismissAlarm, router]);

  const backgroundColor = pulseAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [theme.colors.errorContainer, theme.colors.primary],
  });

  if (error) {
    return (
      <View style={[styles.container, { backgroundColor: theme.colors.errorContainer }]}>
        <Text style={[styles.errorIcon, { color: theme.colors.onPrimary }]}>!</Text>
        <Text variant="headlineMedium" style={[styles.errorText, { color: theme.colors.onPrimary }]}>
          {error}
        </Text>
        <Button
          mode="contained"
          onPress={handleGoHome}
          buttonColor={theme.colors.onPrimary}
          textColor={theme.colors.errorContainer}
          contentStyle={styles.cancelContent}
          labelStyle={styles.cancelLabel}
          style={styles.cancelButton}
        >
          POČETNI EKRAN
        </Button>
      </View>
    );
  }

  return (
    <Animated.View style={[styles.container, { backgroundColor }]}>
      <View style={styles.content}>
        <Text style={[styles.countdown, { color: theme.colors.onPrimary }]}>
          {calling ? "..." : seconds}
        </Text>

        <Text variant="headlineSmall" style={[styles.typeText, { color: theme.colors.onPrimary }]}>
          {dangerType === "FALL"
            ? "Detektovan mogući pad"
            : "SOS aktiviran"}
        </Text>

        <Text variant="titleMedium" style={styles.subText}>
          {calling
            ? "Pozivanje hitne pomoći..."
            : `Poziv hitnoj pomoći za ${seconds} sek...`}
        </Text>
      </View>

      {!calling && (
        <View style={styles.cancelContainer}>
          <Button
            mode="contained"
            onPress={handleCancel}
            buttonColor={theme.colors.onPrimary}
            textColor={theme.colors.primary}
            contentStyle={styles.cancelContent}
            labelStyle={styles.cancelLabel}
            style={styles.cancelButton}
            accessibilityLabel="Otkaži alarm"
          >
            OTKAŽI
          </Button>
        </View>
      )}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  content: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
  },
  countdown: {
    fontSize: 96,
    fontWeight: "900",
    marginBottom: 16,
  },
  typeText: {
    fontWeight: "700",
    textAlign: "center",
    marginBottom: 8,
  },
  subText: {
    color: "rgba(255, 255, 255, 0.8)",
    textAlign: "center",
  },
  cancelContainer: {
    width: "100%",
    paddingBottom: 48,
  },
  cancelButton: {
    borderRadius: 16,
  },
  cancelContent: {
    height: 120,
    justifyContent: "center",
  },
  cancelLabel: {
    fontSize: 28,
    fontWeight: "900",
    letterSpacing: 2,
  },
  errorIcon: {
    fontSize: 80,
    fontWeight: "900",
    marginBottom: 16,
  },
  errorText: {
    textAlign: "center",
    fontWeight: "700",
    marginBottom: 32,
  },
});
