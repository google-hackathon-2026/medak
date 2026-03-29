// API base URL — configure via EXPO_PUBLIC_API_URL environment variable.
// For Android emulator use http://10.0.2.2:8080
// For physical device on LAN, set EXPO_PUBLIC_API_URL=http://<your-lan-ip>:8080
// Default: localhost (works for iOS simulator and web)
export const API_BASE =
  process.env.EXPO_PUBLIC_API_URL || "http://localhost:8080";
