import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { PaperProvider } from "react-native-paper";
import theme from "../lib/theme";

const screenOptions = {
  headerStyle: { backgroundColor: theme.colors.background },
  headerTintColor: theme.colors.onBackground,
  headerTitleStyle: { fontWeight: "bold" as const, fontSize: 20 },
  contentStyle: { backgroundColor: theme.colors.background },
};

export default function RootLayout() {
  return (
    <PaperProvider theme={theme}>
      <StatusBar style="light" />
      <Stack screenOptions={screenOptions}>
        <Stack.Screen
          name="index"
          options={{ title: "Medak", headerShown: false }}
        />
        <Stack.Screen
          name="emergency"
          options={{ title: "Opis hitnog slučaja" }}
        />
        <Stack.Screen
          name="call"
          options={{
            title: "Poziv u toku",
            headerBackVisible: false,
            gestureEnabled: false,
          }}
        />
        <Stack.Screen name="settings" options={{ title: "Podešavanja" }} />
      </Stack>
    </PaperProvider>
  );
}
