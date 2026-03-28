import { useState, useCallback, useRef } from "react";
import { View, StyleSheet, Alert } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  Text,
  Surface,
  TouchableRipple,
  Icon,
  IconButton,
  ActivityIndicator,
} from "react-native-paper";
import * as Haptics from "expo-haptics";
import { useAppTheme } from "../lib/useAppTheme";
import { initiateSOSCall, LOCATION_UNAVAILABLE } from "../lib/sosFlow";
import { STRINGS } from "../lib/strings";
import type { EmergencyType } from "../lib/types";

const EMERGENCY_OPTIONS: {
  type: EmergencyType;
  label: string;
  icon: string;
}[] = [
  { type: "AMBULANCE", label: STRINGS.emergency_ambulance, icon: "ambulance" },
  { type: "POLICE", label: STRINGS.emergency_police, icon: "police-badge" },
  { type: "FIRE", label: STRINGS.emergency_fire, icon: "fire-truck" },
];

export default function HomeScreen() {
  const router = useRouter();
  const theme = useAppTheme();
  const [triggering, setTriggering] = useState<EmergencyType | null>(null);
  const triggeringRef = useRef(false);

  const handleEmergency = useCallback(
    async (type: EmergencyType) => {
      if (triggeringRef.current) return;
      triggeringRef.current = true;
      setTriggering(type);

      try {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);

        const { sessionId } = await initiateSOSCall({
          emergencyType: type,
          requireLocation: true,
        });

        router.push({
          pathname: "/session",
          params: { sessionId, emergencyType: type },
        });
      } catch (err) {
        const message =
          err instanceof Error && err.message === LOCATION_UNAVAILABLE
            ? STRINGS.error_location
            : STRINGS.error_session;
        Alert.alert(STRINGS.error_title, message);
      } finally {
        triggeringRef.current = false;
        setTriggering(null);
      }
    },
    [router]
  );

  return (
    <SafeAreaView
      style={[styles.container, { backgroundColor: theme.colors.background }]}
    >
      <View style={styles.grid}>
        {EMERGENCY_OPTIONS.map((option) => (
          <Surface
            key={option.type}
            style={[
              styles.button,
              { backgroundColor: theme.custom[option.type] },
            ]}
            elevation={2}
          >
            <TouchableRipple
              onPress={() => handleEmergency(option.type)}
              disabled={triggering !== null}
              style={styles.buttonInner}
              accessibilityRole="button"
              accessibilityLabel={option.label}
              rippleColor="rgba(255, 255, 255, 0.2)"
            >
              <View style={styles.buttonRow}>
                {triggering === option.type ? (
                  <ActivityIndicator size={36} color={theme.colors.onPrimary} />
                ) : (
                  <Icon
                    source={option.icon}
                    size={36}
                    color={theme.colors.onPrimary}
                  />
                )}
                <Text
                  variant="headlineSmall"
                  style={{ fontWeight: "700", color: theme.colors.onPrimary }}
                >
                  {option.label}
                </Text>
              </View>
            </TouchableRipple>
          </Surface>
        ))}
      </View>

      <IconButton
        icon="cog"
        onPress={() => router.push("/settings")}
        iconColor={theme.colors.onSurfaceVariant}
        style={styles.settingsButton}
        accessibilityLabel={STRINGS.settings}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    justifyContent: "center",
  },
  grid: {
    gap: 16,
  },
  button: {
    borderRadius: 16,
    overflow: "hidden",
  },
  buttonInner: {
    paddingVertical: 28,
    paddingHorizontal: 24,
    minHeight: 80,
    justifyContent: "center",
  },
  buttonRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 16,
  },
  settingsButton: {
    position: "absolute",
    bottom: 32,
    right: 24,
  },
});
