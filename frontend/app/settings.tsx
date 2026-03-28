import { useState, useEffect } from "react";
import { View, StyleSheet, ScrollView } from "react-native";
import { Text, TextInput, Chip, Button, Snackbar, Switch, Divider } from "react-native-paper";
import * as Haptics from "expo-haptics";
import { UserInfo } from "../lib/types";
import { getUserInfo, saveUserInfo, DEFAULT_USER_INFO } from "../lib/storage";
import { useAppTheme } from "../lib/useAppTheme";
import {
  DangerSettings,
  getDangerSettings,
  saveDangerSettings,
  DEFAULT_DANGER_SETTINGS,
} from "../lib/dangerSettings";
import { useDangerDetectionContext } from "../lib/DangerDetectionContext";

const DISABILITY_OPTIONS: { value: UserInfo["disability"]; label: string }[] = [
  { value: "", label: "Nije navedeno" },
  { value: "DEAF", label: "Gluvoća" },
  { value: "MUTE", label: "Nemost" },
  { value: "DEAF_MUTE", label: "Gluvoća i nemost" },
];

const SENSITIVITY_OPTIONS: {
  value: DangerSettings["shakeSensitivity"];
  label: string;
}[] = [
  { value: "LOW", label: "Niska" },
  { value: "MEDIUM", label: "Srednja" },
  { value: "HIGH", label: "Visoka" },
];

export default function SettingsScreen() {
  const theme = useAppTheme();
  const [info, setInfo] = useState<UserInfo>({ ...DEFAULT_USER_INFO });
  const [dangerSettings, setDangerSettings] = useState<DangerSettings>({
    ...DEFAULT_DANGER_SETTINGS,
  });
  const [saved, setSaved] = useState(false);
  const [snackbarVisible, setSnackbarVisible] = useState(false);
  const { reloadSettings } = useDangerDetectionContext();

  useEffect(() => {
    let cancelled = false;
    Promise.all([getUserInfo(), getDangerSettings()])
      .then(([userData, dangerData]) => {
        if (cancelled) return;
        setInfo(userData);
        setDangerSettings(dangerData);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  function updateField(field: keyof UserInfo, value: string) {
    setInfo((prev) => ({ ...prev, [field]: value }));
    setSaved(false);
  }

  function updateDanger<K extends keyof DangerSettings>(
    field: K,
    value: DangerSettings[K]
  ) {
    setDangerSettings((prev) => ({ ...prev, [field]: value }));
    setSaved(false);
  }

  async function handleSave() {
    try {
      await Promise.all([
        saveUserInfo(info),
        saveDangerSettings(dangerSettings),
      ]);
      await reloadSettings();
      setSaved(true);
      setSnackbarVisible(true);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    }
  }

  return (
    <View style={{ flex: 1, backgroundColor: theme.colors.background }}>
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <Text
          variant="bodyLarge"
          style={{ color: theme.colors.onSurfaceVariant, marginBottom: 24 }}
        >
          Ovi podaci se automatski šalju hitnim službama prilikom poziva.
        </Text>

        <TextInput
          mode="outlined"
          label="Ime i prezime"
          value={info.name}
          onChangeText={(v) => updateField("name", v)}
          placeholder="Marko Marković"
          style={[styles.input, { backgroundColor: theme.colors.surface }]}
          outlineColor={theme.colors.outline}
          activeOutlineColor={theme.colors.secondary}
          textColor={theme.colors.onSurface}
          accessibilityLabel="Ime i prezime"
        />

        <TextInput
          mode="outlined"
          label="Adresa"
          value={info.address}
          onChangeText={(v) => updateField("address", v)}
          placeholder="Bulevar Kralja Aleksandra 73, Beograd"
          style={[styles.input, { backgroundColor: theme.colors.surface }]}
          outlineColor={theme.colors.outline}
          activeOutlineColor={theme.colors.secondary}
          textColor={theme.colors.onSurface}
          accessibilityLabel="Adresa"
        />

        <TextInput
          mode="outlined"
          label="Telefon"
          value={info.phone}
          onChangeText={(v) => updateField("phone", v)}
          placeholder="+381 64 123 4567"
          keyboardType="phone-pad"
          style={[styles.input, { backgroundColor: theme.colors.surface }]}
          outlineColor={theme.colors.outline}
          activeOutlineColor={theme.colors.secondary}
          textColor={theme.colors.onSurface}
          accessibilityLabel="Broj telefona"
        />

        <Text
          variant="labelLarge"
          style={{
            color: theme.colors.onSurfaceVariant,
            marginBottom: 8,
            marginTop: 8,
          }}
        >
          Vrsta invaliditeta
        </Text>
        <View style={styles.chipContainer}>
          {DISABILITY_OPTIONS.map((option) => (
            <Chip
              key={option.value}
              mode="flat"
              selected={info.disability === option.value}
              onPress={() => {
                updateField("disability", option.value);
                Haptics.selectionAsync();
              }}
              selectedColor={theme.colors.onPrimary}
              showSelectedCheck
              style={[
                styles.chip,
                {
                  backgroundColor:
                    info.disability === option.value
                      ? theme.colors.secondary
                      : theme.colors.surfaceVariant,
                },
              ]}
              textStyle={styles.chipText}
              accessibilityLabel={option.label}
              accessibilityState={{ selected: info.disability === option.value }}
            >
              {option.label}
            </Chip>
          ))}
        </View>

        <TextInput
          mode="outlined"
          label="Medicinske napomene"
          value={info.medicalNotes}
          onChangeText={(v) => updateField("medicalNotes", v)}
          placeholder="Alergije, hronične bolesti, lekovi..."
          multiline
          numberOfLines={4}
          style={[
            styles.input,
            { minHeight: 120, backgroundColor: theme.colors.surface },
          ]}
          outlineColor={theme.colors.outline}
          activeOutlineColor={theme.colors.secondary}
          textColor={theme.colors.onSurface}
          accessibilityLabel="Medicinske napomene"
        />

        <Divider style={{ marginVertical: 24, backgroundColor: theme.colors.outline }} />

        <Text
          variant="titleLarge"
          style={{
            color: theme.colors.onBackground,
            fontWeight: "700",
            marginBottom: 16,
          }}
        >
          Automatsko otkrivanje opasnosti
        </Text>

        <View style={styles.switchRow}>
          <View style={styles.switchTextContainer}>
            <Text variant="bodyLarge" style={{ color: theme.colors.onSurface }}>
              Detekcija pada
            </Text>
            <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
              Automatski detektuje padove pomoću senzora telefona
            </Text>
          </View>
          <Switch
            value={dangerSettings.fallDetectionEnabled}
            onValueChange={(v) => {
              updateDanger("fallDetectionEnabled", v);
              Haptics.selectionAsync();
            }}
            color={theme.colors.secondary}
          />
        </View>

        <View style={styles.switchRow}>
          <View style={styles.switchTextContainer}>
            <Text variant="bodyLarge" style={{ color: theme.colors.onSurface }}>
              Protresanje za SOS
            </Text>
            <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
              Protresite telefon snažno za hitni alarm
            </Text>
          </View>
          <Switch
            value={dangerSettings.shakeSOSEnabled}
            onValueChange={(v) => {
              updateDanger("shakeSOSEnabled", v);
              Haptics.selectionAsync();
            }}
            color={theme.colors.secondary}
          />
        </View>

        {dangerSettings.shakeSOSEnabled && (
          <View style={{ marginBottom: 16 }}>
            <Text
              variant="labelLarge"
              style={{
                color: theme.colors.onSurfaceVariant,
                marginBottom: 8,
              }}
            >
              Osetljivost protresanja
            </Text>
            <View style={styles.chipContainer}>
              {SENSITIVITY_OPTIONS.map((option) => (
                <Chip
                  key={option.value}
                  mode="flat"
                  selected={dangerSettings.shakeSensitivity === option.value}
                  onPress={() => {
                    updateDanger("shakeSensitivity", option.value);
                    Haptics.selectionAsync();
                  }}
                  selectedColor={theme.colors.onPrimary}
                  showSelectedCheck
                  style={[
                    styles.chip,
                    {
                      backgroundColor:
                        dangerSettings.shakeSensitivity === option.value
                          ? theme.colors.secondary
                          : theme.colors.surfaceVariant,
                    },
                  ]}
                  textStyle={styles.chipText}
                >
                  {option.label}
                </Chip>
              ))}
            </View>
          </View>
        )}

        <Button
          mode="contained"
          icon={saved ? "check" : "content-save"}
          onPress={handleSave}
          buttonColor={theme.custom.success}
          textColor={theme.colors.onPrimary}
          contentStyle={styles.saveButtonContent}
          labelStyle={styles.saveButtonLabel}
          style={styles.saveButton}
          accessibilityLabel="Sačuvaj podešavanja"
        >
          {saved ? "Sačuvano" : "Sačuvaj"}
        </Button>
      </ScrollView>

      <Snackbar
        visible={snackbarVisible}
        onDismiss={() => setSnackbarVisible(false)}
        duration={3000}
        action={{ label: "OK", onPress: () => setSnackbarVisible(false) }}
        style={{ backgroundColor: theme.custom.success }}
      >
        Vaši podaci su sačuvani.
      </Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: {
    flex: 1,
  },
  content: {
    padding: 24,
    paddingBottom: 48,
  },
  input: {
    marginBottom: 16,
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
  switchRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 12,
    gap: 16,
  },
  switchTextContainer: {
    flex: 1,
  },
  saveButton: {
    borderRadius: 12,
    marginTop: 32,
  },
  saveButtonContent: {
    height: 56,
  },
  saveButtonLabel: {
    fontSize: 18,
    fontWeight: "700",
  },
});
