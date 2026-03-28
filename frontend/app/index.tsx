import { useRef, useState, useCallback, useMemo } from "react";
import {
  View,
  StyleSheet,
  Animated,
  Pressable,
  Alert,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Text, Button, ActivityIndicator } from "react-native-paper";
import * as Haptics from "expo-haptics";
import { useAppTheme } from "../lib/useAppTheme";
import { initiateSOSCall } from "../lib/sosFlow";

const HOLD_DURATION_MS = 1500;

export default function HomeScreen() {
  const router = useRouter();
  const theme = useAppTheme();

  const [isHolding, setIsHolding] = useState(false);
  const [isTriggering, setIsTriggering] = useState(false);
  const progress = useRef(new Animated.Value(0)).current;
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSOS = useCallback(async () => {
    if (isTriggering) return;
    setIsTriggering(true);

    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);

      const { sessionId } = await initiateSOSCall({ requireLocation: true });

      router.push({
        pathname: "/session",
        params: { sessionId },
      });
    } catch (err) {
      const message =
        err instanceof Error && err.message === "LOCATION_UNAVAILABLE"
          ? "Nije moguće dobiti lokaciju. Proverite dozvole."
          : "Nije moguće pokrenuti sesiju. Proverite internet konekciju.";
      Alert.alert("Greška", message);
    } finally {
      setIsTriggering(false);
    }
  }, [isTriggering, router]);

  const onPressIn = useCallback(() => {
    setIsHolding(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

    Animated.timing(progress, {
      toValue: 1,
      duration: HOLD_DURATION_MS,
      useNativeDriver: false,
    }).start();

    holdTimer.current = setTimeout(() => {
      setIsHolding(false);
      progress.setValue(0);
      handleSOS();
    }, HOLD_DURATION_MS);
  }, [handleSOS, progress]);

  const onPressOut = useCallback(() => {
    if (holdTimer.current) {
      clearTimeout(holdTimer.current);
      holdTimer.current = null;
    }
    setIsHolding(false);
    Animated.timing(progress, {
      toValue: 0,
      duration: 150,
      useNativeDriver: false,
    }).start();
  }, [progress]);

  const ringScale = useMemo(
    () => progress.interpolate({ inputRange: [0, 1], outputRange: [1, 1.25] }),
    [progress]
  );

  const ringOpacity = useMemo(
    () => progress.interpolate({ inputRange: [0, 0.5, 1], outputRange: [0, 0.4, 0.8] }),
    [progress]
  );

  const buttonScale = useMemo(
    () => progress.interpolate({ inputRange: [0, 1], outputRange: [1, 0.95] }),
    [progress]
  );

  return (
    <SafeAreaView
      style={[styles.container, { backgroundColor: theme.colors.background }]}
    >
      <View style={styles.header}>
        <Text
          variant="displayMedium"
          style={[styles.title, { color: theme.colors.onBackground }]}
        >
          MEDAK
        </Text>
        <Text
          variant="titleMedium"
          style={{ color: theme.colors.onSurfaceVariant, textAlign: "center" }}
        >
          Hitna pomoć za gluve i neme osobe
        </Text>
      </View>

      <View style={styles.sosContainer}>
        {/* Progress ring */}
        <Animated.View
          style={[
            styles.sosRing,
            {
              backgroundColor: theme.custom.sosRing,
              transform: [{ scale: ringScale }],
              opacity: ringOpacity,
            },
          ]}
        />

        {/* SOS button */}
        <Animated.View
          style={{ transform: [{ scale: buttonScale }] }}
        >
          <Pressable
            onPressIn={onPressIn}
            onPressOut={onPressOut}
            disabled={isTriggering}
            accessibilityRole="button"
            accessibilityLabel="SOS dugme. Držite 1.5 sekundi za aktiviranje."
            accessibilityHint="Držite dugme da pokrenete hitnu sesiju"
            style={[
              styles.sosButton,
              {
                backgroundColor: isHolding
                  ? theme.custom.sosActive
                  : theme.custom.sosPrimary,
              },
            ]}
          >
            {isTriggering ? (
              <ActivityIndicator size="large" color="#ffffff" />
            ) : (
              <>
                <Text style={styles.sosText}>SOS</Text>
                <Text style={styles.sosHint}>DRŽI ZA POZIV</Text>
              </>
            )}
          </Pressable>
        </Animated.View>
      </View>

      <Text
        variant="bodySmall"
        style={[styles.instruction, { color: theme.colors.onSurfaceVariant }]}
      >
        Držite SOS dugme 1.5 sekundi da pokrenete poziv
      </Text>

      <Button
        mode="text"
        icon="cog"
        onPress={() => router.push("/settings")}
        textColor={theme.colors.onSurfaceVariant}
        style={styles.settingsButton}
        accessibilityLabel="Podešavanja"
      >
        Podešavanja
      </Button>
    </SafeAreaView>
  );
}

const SOS_SIZE = 200;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    justifyContent: "center",
    alignItems: "center",
  },
  header: {
    alignItems: "center",
    marginBottom: 64,
  },
  title: {
    fontWeight: "900",
    letterSpacing: 4,
  },
  sosContainer: {
    width: SOS_SIZE * 1.3,
    height: SOS_SIZE * 1.3,
    alignItems: "center",
    justifyContent: "center",
  },
  sosRing: {
    position: "absolute",
    width: SOS_SIZE * 1.25,
    height: SOS_SIZE * 1.25,
    borderRadius: (SOS_SIZE * 1.25) / 2,
  },
  sosButton: {
    width: SOS_SIZE,
    height: SOS_SIZE,
    borderRadius: SOS_SIZE / 2,
    alignItems: "center",
    justifyContent: "center",
    elevation: 8,
    shadowColor: "#dc2626",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 12,
  },
  sosText: {
    fontSize: 48,
    fontWeight: "900",
    color: "#ffffff",
    letterSpacing: 8,
  },
  sosHint: {
    fontSize: 12,
    fontWeight: "600",
    color: "rgba(255, 255, 255, 0.7)",
    marginTop: 4,
    letterSpacing: 2,
  },
  instruction: {
    textAlign: "center",
    marginTop: 32,
  },
  settingsButton: {
    position: "absolute",
    bottom: 48,
    alignSelf: "center",
  },
});
