import { MD3DarkTheme } from "react-native-paper";
import type { MD3Theme } from "react-native-paper";
import type { EmergencyType } from "./types";

export type AppTheme = MD3Theme & {
  custom: Record<EmergencyType, string> & {
    success: string;
    warning: string;
    info: string;
    bubbleAI: string;
    bubbleOperator: string;
    bubbleUser: string;
    questionHighlight: string;
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
    AMBULANCE: "#dc2626",
    POLICE: "#2563eb",
    FIRE: "#ea580c",
    success: "#22c55e",
    warning: "#eab308",
    info: "#3b82f6",
    bubbleAI: "#1e3a5f",
    bubbleOperator: "#3f3f46",
    bubbleUser: "#166534",
    questionHighlight: "#fbbf24",
  },
};

export default theme;
