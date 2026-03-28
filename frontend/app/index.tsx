import { View, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  Text,
  Surface,
  TouchableRipple,
  Icon,
  Button,
} from "react-native-paper";
import { EmergencyType } from "../lib/types";
import { useAppTheme } from "../lib/useAppTheme";

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

  function handleEmergency(type: EmergencyType) {
    router.push({ pathname: "/emergency", params: { type } });
  }

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
              style={styles.buttonInner}
              accessibilityRole="button"
              accessibilityLabel={option.label}
              rippleColor="rgba(255, 255, 255, 0.2)"
            >
              <View style={styles.buttonRow}>
                <Icon
                  source={option.icon}
                  size={36}
                  color={theme.colors.onPrimary}
                />
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
