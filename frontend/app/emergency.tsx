import { useState, useEffect } from "react";
import { View, StyleSheet, ScrollView, Alert } from "react-native";
import { Text, TextInput, Chip, Button, Surface, Icon } from "react-native-paper";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import {
  EmergencyType,
  QuickTag,
  LocationData,
  QUICK_TAG_LABELS,
} from "../lib/types";
import { getCurrentLocation } from "../lib/location";
import { getUserInfo } from "../lib/storage";
import { initiateCall } from "../lib/api";
import { useAppTheme } from "../lib/useAppTheme";

const TAGS_BY_TYPE: Record<EmergencyType, QuickTag[]> = {
  AMBULANCE: [
    "TRAFFIC_ACCIDENT",
    "HEART_ATTACK",
    "FALL",
    "BREATHING",
    "UNCONSCIOUS",
    "MULTIPLE_VICTIMS",
    "CHILD",
  ],
  POLICE: ["TRAFFIC_ACCIDENT", "VIOLENCE"],
  FIRE: ["FIRE_SCENE", "MULTIPLE_VICTIMS", "CHILD"],
};

const TYPE_COLOR_KEY: Record<EmergencyType, "ambulance" | "police" | "fire"> = {
  AMBULANCE: "ambulance",
  POLICE: "police",
  FIRE: "fire",
};

export default function EmergencyFormScreen() {
  const { type } = useLocalSearchParams<{ type: EmergencyType }>();
  const router = useRouter();
  const theme = useAppTheme();
  const emergencyType = (type as EmergencyType) || "AMBULANCE";
  const typeColor = theme.custom[TYPE_COLOR_KEY[emergencyType]];

  const [selectedTags, setSelectedTags] = useState<QuickTag[]>([]);
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState<LocationData | null>(null);
  const [loadingLocation, setLoadingLocation] = useState(true);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getCurrentLocation()
      .then((loc) => { if (!cancelled) setLocation(loc); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoadingLocation(false); });
    return () => { cancelled = true; };
  }, []);

  function toggleTag(tag: QuickTag) {
    Haptics.selectionAsync();
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  }

  async function handleCall() {
    if (!location) {
      Alert.alert("Lokacija", "Lokacija nije dostupna. Pokušajte ponovo.");
      return;
    }

    setSending(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);

    try {
      const userInfo = await getUserInfo();
      const response = await initiateCall({
        emergencyType,
        description,
        quickTags: selectedTags,
        location,
        userInfo,
      });

      router.replace({
        pathname: "/call",
        params: { callId: response.callId },
      });
    } catch (error) {
      console.error("Failed to initiate call:", error);
      setSending(false);
      Alert.alert("Greška", "Nije moguće pokrenuti poziv. Pokušajte ponovo.");
    }
  }

  const availableTags = TAGS_BY_TYPE[emergencyType] || [];

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
    >
      <Text variant="titleLarge" style={styles.sectionTitle}>
        Šta se desilo?
      </Text>
      <View style={styles.chipContainer}>
        {availableTags.map((tag) => (
          <Chip
            key={tag}
            mode="flat"
            selected={selectedTags.includes(tag)}
            onPress={() => toggleTag(tag)}
            selectedColor="#ffffff"
            style={[
              styles.chip,
              selectedTags.includes(tag) && { backgroundColor: typeColor },
            ]}
            textStyle={styles.chipText}
            accessibilityLabel={QUICK_TAG_LABELS[tag]}
            accessibilityState={{ selected: selectedTags.includes(tag) }}
          >
            {QUICK_TAG_LABELS[tag]}
          </Chip>
        ))}
      </View>

      <Text variant="titleLarge" style={styles.sectionTitle}>
        Dodatne informacije
      </Text>
      <TextInput
        mode="outlined"
        label="Opišite situaciju..."
        value={description}
        onChangeText={setDescription}
        multiline
        numberOfLines={4}
        style={[styles.textInput, { minHeight: 120 }]}
        outlineColor={theme.colors.outline}
        activeOutlineColor={typeColor}
        textColor={theme.colors.onSurface}
        accessibilityLabel="Opis situacije"
      />

      <Text variant="titleLarge" style={styles.sectionTitle}>
        Lokacija
      </Text>
      <Surface style={styles.locationBox} elevation={1}>
        {loadingLocation ? (
          <Text
            variant="bodyLarge"
            style={{ color: theme.colors.onSurfaceVariant }}
          >
            Učitavanje lokacije...
          </Text>
        ) : location ? (
          <View style={styles.locationRow}>
            <Icon
              source="map-marker"
              size={20}
              color={theme.colors.onSurfaceVariant}
            />
            <Text
              variant="bodyLarge"
              style={{ color: theme.colors.onSurfaceVariant }}
            >
              {location.latitude.toFixed(5)}, {location.longitude.toFixed(5)}
              {location.accuracy
                ? ` (±${Math.round(location.accuracy)}m)`
                : ""}
            </Text>
          </View>
        ) : (
          <Text variant="bodyLarge" style={{ color: theme.colors.error }}>
            Lokacija nije dostupna
          </Text>
        )}
      </Surface>

      <Button
        mode="contained"
        icon="phone"
        onPress={handleCall}
        disabled={sending || !location}
        loading={sending}
        buttonColor={typeColor}
        textColor="#ffffff"
        contentStyle={{ height: 72 }}
        labelStyle={{ fontSize: 24, fontWeight: "900" }}
        style={{ borderRadius: 16, marginTop: 8 }}
        accessibilityLabel="Pozovi hitnu pomoć"
      >
        {sending ? "POZIVANJE..." : "POZOVI"}
      </Button>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#1a1a1a",
  },
  content: {
    padding: 24,
    paddingBottom: 48,
  },
  sectionTitle: {
    color: "#ffffff",
    fontWeight: "700",
    marginBottom: 12,
    marginTop: 8,
  },
  chipContainer: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    marginBottom: 24,
  },
  chip: {
    minHeight: 48,
    justifyContent: "center",
    backgroundColor: "#333333",
  },
  chipText: {
    fontSize: 16,
    fontWeight: "600",
  },
  textInput: {
    marginBottom: 24,
    backgroundColor: "#262626",
  },
  locationBox: {
    borderRadius: 12,
    padding: 16,
    marginBottom: 32,
    backgroundColor: "#262626",
  },
  locationRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
});
