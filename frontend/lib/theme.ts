import { MD3DarkTheme } from "react-native-paper";
import type { MD3Theme } from "react-native-paper";

export type AppTheme = MD3Theme & {
  custom: {
    ambulance: string;
    police: string;
    fire: string;
    success: string;
  };
};

const theme: AppTheme = {
  ...MD3DarkTheme,
  colors: {
    ...MD3DarkTheme.colors,
    background: "#1a1a1a",
    surface: "#262626",
    surfaceVariant: "#333333",

    primary: "#dc2626",
    onPrimary: "#ffffff",
    primaryContainer: "#dc2626",
    onPrimaryContainer: "#ffffff",

    secondary: "#2563eb",
    onSecondary: "#ffffff",
    secondaryContainer: "#2563eb",
    onSecondaryContainer: "#ffffff",

    tertiary: "#ea580c",
    onTertiary: "#ffffff",
    tertiaryContainer: "#ea580c",
    onTertiaryContainer: "#ffffff",

    onBackground: "#ffffff",
    onSurface: "#ffffff",
    onSurfaceVariant: "#a3a3a3",
    outline: "#404040",
    outlineVariant: "#333333",

    error: "#ef4444",
    onError: "#ffffff",
    errorContainer: "#7f1d1d",
    onErrorContainer: "#fecaca",

    elevation: {
      ...MD3DarkTheme.colors.elevation,
      level0: "#1a1a1a",
      level1: "#262626",
      level2: "#333333",
      level3: "#3f3f46",
      level4: "#404040",
      level5: "#525252",
    },
  },
  custom: {
    ambulance: "#dc2626",
    police: "#2563eb",
    fire: "#ea580c",
    success: "#22c55e",
  },
};

export default theme;
