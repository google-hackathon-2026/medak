import { useTheme } from "react-native-paper";
import type { AppTheme } from "./theme";

export function useAppTheme() {
  return useTheme<AppTheme>();
}
