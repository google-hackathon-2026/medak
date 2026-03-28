import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { PaperProvider } from "react-native-paper";
import theme from "../lib/theme";
import { DangerDetectionProvider } from "../lib/DangerDetectionContext";

const screenOptions = {
  headerStyle: { backgroundColor: theme.colors.background },
  headerTintColor: theme.colors.onBackground,
  headerTitleStyle: { fontWeight: "bold" as const, fontSize: 20 },
  headerStatusBarHeight: 70,
  contentStyle: { backgroundColor: theme.colors.background },
};

export default function RootLayout() {
  return (
    <PaperProvider theme={theme}>
      <StatusBar style="light" />
      <DangerDetectionProvider>
        <Stack screenOptions={screenOptions}>
          <Stack.Screen
            name="index"
            options={{ title: "Medak", headerShown: false }}
          />
          <Stack.Screen
            name="session"
            options={{
              title: "Hitna sesija",
              headerBackVisible: false,
              gestureEnabled: false,
            }}
          />
          <Stack.Screen
            name="settings"
            options={{ headerShown: false }}
          />
          <Stack.Screen
            name="alarm"
            options={{
              presentation: "fullScreenModal",
              headerShown: false,
              gestureEnabled: false,
              animation: "fade",
            }}
          />
        </Stack>
      </DangerDetectionProvider>
    </PaperProvider>
  );
}
