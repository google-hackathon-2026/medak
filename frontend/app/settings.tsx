import { useState, useEffect } from "react";
import { StyleSheet, ScrollView } from "react-native";
import { Text, TextInput, Button, Snackbar } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";
import { getUserInfo, saveUserInfo, DEFAULT_USER_INFO } from "../lib/storage";
import { useAppTheme } from "../lib/useAppTheme";
import { STRINGS } from "../lib/strings";
import type { UserInfo } from "../lib/types";

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
    <SafeAreaView
      style={[styles.container, { backgroundColor: theme.colors.background }]}
    >
      <Text
        variant="headlineMedium"
        style={[styles.title, { color: theme.colors.onBackground }]}
      >
        {STRINGS.settings_title}
      </Text>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <Text
          variant="bodyLarge"
          style={{ color: theme.colors.onSurfaceVariant, marginBottom: 24 }}
        >
          {STRINGS.settings_description}
        </Text>

        <TextInput
          mode="outlined"
          label={STRINGS.personal_data}
          value={info.personalInfo}
          onChangeText={(v) => {
            setInfo((prev) => ({ ...prev, personalInfo: v }));
            setSaved(false);
          }}
          placeholder={STRINGS.personal_data_placeholder}
          multiline
          numberOfLines={8}
          style={[styles.input, { backgroundColor: theme.colors.surface }]}
          outlineColor={theme.colors.outline}
          activeOutlineColor={theme.colors.secondary}
          textColor={theme.colors.onSurface}
          accessibilityLabel={STRINGS.personal_data}
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
          accessibilityLabel={STRINGS.save_settings}
        >
          {saved ? STRINGS.saved : STRINGS.save}
        </Button>
      </ScrollView>

      <Snackbar
        visible={snackbarVisible}
        onDismiss={() => setSnackbarVisible(false)}
        duration={3000}
        action={{ label: "OK", onPress: () => setSnackbarVisible(false) }}
        style={{ backgroundColor: theme.custom.success }}
      >
        {STRINGS.data_saved}
      </Snackbar>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  title: {
    fontWeight: "700",
    paddingHorizontal: 24,
    paddingTop: 16,
    paddingBottom: 8,
  },
  scroll: {
    flex: 1,
  },
  content: {
    padding: 24,
    paddingBottom: 48,
  },
  input: {
    marginBottom: 16,
    minHeight: 200,
  },
  saveButton: {
    borderRadius: 12,
    marginTop: 16,
  },
  saveButtonContent: {
    height: 56,
  },
  saveButtonLabel: {
    fontSize: 18,
    fontWeight: "700",
  },
});
