import { useState, useCallback, useRef } from "react";
import { View, StyleSheet, Alert } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  Text,
  Surface,
  TouchableRipple,
  Icon,
  Button,
  ActivityIndicator,
} from "react-native-paper";
import * as Haptics from "expo-haptics";
import { useAppTheme } from "../lib/useAppTheme";
import { initiateSOSCall, LOCATION_UNAVAILABLE } from "../lib/sosFlow";
import type { EmergencyType } from "../lib/types";

const EMERGENCY_OPTIONS: {
  type: EmergencyType;
  label: string;
  icon: string;
}[] = [
  { type: "AMBULANCE", label: "Hitna pomoć", icon: "ambulance" },
  { type: "POLICE", label: "Policija", icon: "police-badge" },
  { type: "FIRE", label: "Vatrogasci", icon: "fire-truck" },
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
          params: { sessionId },
        });
      } catch (err) {
        const message =
          err instanceof Error && err.message === LOCATION_UNAVAILABLE
            ? "Nije moguće dobiti lokaciju. Proverite dozvole."
            : "Nije moguće pokrenuti sesiju. Proverite internet konekciju.";
        Alert.alert("Greška", message);
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

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    justifyContent: "center",
  },
  header: {
    alignItems: "center",
    marginBottom: 48,
  },
  title: {
    fontWeight: "900",
    letterSpacing: 4,
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
    alignSelf: "center",
    marginTop: 48,
  },
});
