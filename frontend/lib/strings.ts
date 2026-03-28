// Simple localization — swap this object to change language
export const STRINGS = {
  // index.tsx (SOS screen)
  emergency_ambulance: "Ambulance",
  emergency_fire: "Fire Department",
  emergency_police: "Police",
  error_location: "Unable to get location. Check permissions.",
  error_session: "Unable to start session. Check internet connection.",
  error_title: "Error",
  settings: "Settings",

  // session.tsx
  send: "Send",
  listening: "Listening to environment...",
  help_on_way: "Help is on the way",
  stay_on_location: "Stay at your location and wait for the team to arrive",
  connecting: "Connecting...",
  session_establishing: "Session is being established",
  analysis_in_progress: "Analysis in progress",
  confidence: "Confidence",
  mic_active: "Microphone active",
  you: "You",
  system: "System",
  call_in_progress: "Call in progress",
  auto_call_failed: "Automatic call failed",
  ask_someone_to_call: "Ask someone nearby to call {number}",
  or_enter_response: "Or enter a response...",
  yes: "YES",
  no: "NO",

  // alarm.tsx
  call_failed: "Call failed. Try calling manually.",
  home_screen: "HOME SCREEN",
  fall_detected: "Possible fall detected",
  sos_activated: "SOS activated",
  calling_emergency: "Calling emergency services...",
  calling_emergency_countdown: "Calling emergency services in {seconds} sec...",
  cancel_alarm: "Cancel alarm",
  cancel: "CANCEL",

  // settings.tsx
  settings_title: "Settings",
  settings_description: "This data is automatically sent to emergency services during a call.",
  personal_data: "Personal data",
  personal_data_placeholder: "Full name, address, floor, apartment,\nphone number, medical notes...",
  save_settings: "Save settings",
  saved: "Saved",
  save: "Save",
  data_saved: "Your data has been saved.",
} as const;
