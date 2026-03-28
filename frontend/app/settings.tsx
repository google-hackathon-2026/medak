import { useState, useEffect } from "react";
import { View, StyleSheet, ScrollView } from "react-native";
import { Text, TextInput, Chip, Button, Snackbar } from "react-native-paper";
import * as Haptics from "expo-haptics";
import { UserInfo } from "../lib/types";
import { getUserInfo, saveUserInfo } from "../lib/storage";
import { useAppTheme } from "../lib/useAppTheme";

const DISABILITY_OPTIONS: { value: UserInfo["disability"]; label: string }[] = [
  { value: "", label: "Nije navedeno" },
  { value: "DEAF", label: "Gluvoća" },
  { value: "MUTE", label: "Nemost" },
  { value: "DEAF_MUTE", label: "Gluvoća i nemost" },
];

export default function SettingsScreen() {
  const theme = useAppTheme();
  const [info, setInfo] = useState<UserInfo>({
    name: "",
    address: "",
    phone: "",
    medicalNotes: "",
    disability: "",
  });
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
    await saveUserInfo(info);
    setSaved(true);
    setSnackbarVisible(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
  }

  return (
    <View style={styles.wrapper}>
      <ScrollView
        style={styles.container}
        contentContainerStyle={styles.content}
      >
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
          style={styles.input}
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
          style={styles.input}
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
          style={styles.input}
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
              selectedColor="#ffffff"
              showSelectedCheck
              style={[
                styles.chip,
                info.disability === option.value && {
                  backgroundColor: theme.colors.secondary,
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
          style={[styles.input, { minHeight: 120 }]}
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
          textColor="#ffffff"
          contentStyle={{ height: 56 }}
          labelStyle={{ fontSize: 18, fontWeight: "700" }}
          style={{ borderRadius: 12, marginTop: 32 }}
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
  wrapper: {
    flex: 1,
    backgroundColor: "#1a1a1a",
  },
  container: {
    flex: 1,
  },
  content: {
    padding: 24,
    paddingBottom: 48,
  },
  input: {
    marginBottom: 16,
    backgroundColor: "#262626",
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
});
