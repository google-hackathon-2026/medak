import { useState, useEffect } from "react";
import { View, StyleSheet, ScrollView } from "react-native";
import { Text, TextInput, Chip, Button, Snackbar } from "react-native-paper";
import * as Haptics from "expo-haptics";
import { UserInfo } from "../lib/types";
import { getUserInfo, saveUserInfo, DEFAULT_USER_INFO } from "../lib/storage";
import { useAppTheme } from "../lib/useAppTheme";

const DISABILITY_OPTIONS: { value: UserInfo["disability"]; label: string }[] = [
  { value: "", label: "Nije navedeno" },
  { value: "DEAF", label: "Gluvoća" },
  { value: "MUTE", label: "Nemost" },
  { value: "DEAF_MUTE", label: "Gluvoća i nemost" },
];

export default function SettingsScreen() {
  const theme = useAppTheme();
  const [info, setInfo] = useState<UserInfo>({ ...DEFAULT_USER_INFO });
  const [saved, setSaved] = useState(false);
  const [snackbarVisible, setSnackbarVisible] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getUserInfo()
      .then((data) => { if (!cancelled) setInfo(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  function updateField(field: keyof UserInfo, value: string) {
    setInfo((prev) => ({ ...prev, [field]: value }));
    setSaved(false);
  }

  async function handleSave() {
    try {
      await saveUserInfo(info);
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
