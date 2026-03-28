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
import staticTheme from "../lib/theme";
import type { UserInfo } from "../lib/types";

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

export default function EmergencyFormScreen() {
  const { type } = useLocalSearchParams<{ type: EmergencyType }>();
  const router = useRouter();
  const theme = useAppTheme();
  const emergencyType = (type as EmergencyType) || "AMBULANCE";
  const typeColor = theme.custom[emergencyType];

  const [selectedTags, setSelectedTags] = useState<QuickTag[]>([]);
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState<LocationData | null>(null);
  const [loadingLocation, setLoadingLocation] = useState(true);
  const [sending, setSending] = useState(false);
  const [cachedUserInfo, setCachedUserInfo] = useState<UserInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getCurrentLocation(), getUserInfo()])
      .then(([loc, info]) => {
        if (cancelled) return;
        setLocation(loc);
        setCachedUserInfo(info);
      })
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
      const userInfo = cachedUserInfo ?? await getUserInfo();
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
      style={{ flex: 1, backgroundColor: theme.colors.background }}
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
            selectedColor={theme.colors.onPrimary}
            style={[
              styles.chip,
              { backgroundColor: selectedTags.includes(tag) ? typeColor : theme.colors.surfaceVariant },
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
        style={[styles.textInput, { backgroundColor: theme.colors.surface }]}
        outlineColor={theme.colors.outline}
        activeOutlineColor={typeColor}
        textColor={theme.colors.onSurface}
        accessibilityLabel="Opis situacije"
      />

      <Text variant="titleLarge" style={styles.sectionTitle}>
        Lokacija
      </Text>
      <Surface
        style={[styles.locationBox, { backgroundColor: theme.colors.surface }]}
        elevation={1}
      >
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
        textColor={theme.colors.onPrimary}
        contentStyle={styles.callButtonContent}
        labelStyle={styles.callButtonLabel}
        style={styles.callButton}
        accessibilityLabel="Pozovi hitnu pomoć"
      >
        {sending ? "POZIVANJE..." : "POZOVI"}
      </Button>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {
    padding: 24,
    paddingBottom: 48,
  },
  sectionTitle: {
    color: staticTheme.colors.onBackground,
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
  },
  chipText: {
    fontSize: 16,
    fontWeight: "600",
  },
  textInput: {
    marginBottom: 24,
    minHeight: 120,
  },
  locationBox: {
    borderRadius: 12,
    padding: 16,
    marginBottom: 32,
  },
  locationRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  callButton: {
    borderRadius: 16,
    marginTop: 8,
  },
  callButtonContent: {
    height: 72,
  },
  callButtonLabel: {
    fontSize: 24,
    fontWeight: "900",
  },
});
