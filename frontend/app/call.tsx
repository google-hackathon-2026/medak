import { useState, useEffect, useRef } from "react";
import { View, StyleSheet, ScrollView } from "react-native";
import { Text, TextInput, IconButton, Surface, Icon } from "react-native-paper";
import { useLocalSearchParams } from "expo-router";
import * as Haptics from "expo-haptics";
import { CallStatus, TranscriptEntry } from "../lib/types";
import { sendUserInput } from "../lib/api";
import { connectToCallStream } from "../lib/sse";
import { useAppTheme } from "../lib/useAppTheme";

const STATUS_LABELS: Record<CallStatus, string> = {
  CALLING: "Pozivanje...",
  CONNECTED: "Povezano",
  COMPLETED: "Poziv završen",
  ERROR: "Greška",
};

const STATUS_COLORS: Record<CallStatus, string> = {
  CALLING: "#eab308",
  CONNECTED: "#22c55e",
  COMPLETED: "#3b82f6",
  ERROR: "#ef4444",
};

const SPEAKER_ICONS: Record<string, string> = {
  AI: "robot",
  OPERATOR: "headset",
  USER: "account",
};

const SPEAKER_LABELS: Record<string, string> = {
  AI: "AI",
  OPERATOR: "Operator",
  USER: "Vi",
};

export default function CallScreen() {
  const { callId } = useLocalSearchParams<{ callId: string }>();
  const theme = useAppTheme();
  const [status, setStatus] = useState<CallStatus>("CALLING");
  const [statusMessage, setStatusMessage] = useState("Pozivanje hitne pomoći...");
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [userInput, setUserInput] = useState("");
  const [sendingInput, setSendingInput] = useState(false);
  const scrollRef = useRef<ScrollView>(null);
  const lastStatusRef = useRef<CallStatus | null>(null);
  const entryCounter = useRef(0);

  useEffect(() => {
    if (!callId) return;

    const disconnect = connectToCallStream(callId, {
      onStatus(event) {
        setStatus(event.status);
        setStatusMessage(event.message);
        if (event.status !== lastStatusRef.current) {
          lastStatusRef.current = event.status;
          if (event.status === "CONNECTED" || event.status === "COMPLETED") {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
          }
        }
      },
      onTranscript(event) {
        const id = String(entryCounter.current++);
        setTranscript((prev) => [
          ...prev,
          { id, speaker: event.speaker, text: event.text, timestamp: Date.now() },
        ]);
      },
      onNeedInput(event) {
        setPendingQuestion(event.question);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      },
      onError() {
        setStatus("ERROR");
        setStatusMessage("Veza sa serverom je prekinuta");
      },
    });

    return disconnect;
  }, [callId]);

  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: true });
  }, [transcript]);

  async function handleSendInput() {
    if (!userInput.trim() || !callId) return;
    setSendingInput(true);

    try {
      await sendUserInput(callId, userInput.trim());
      const id = String(entryCounter.current++);
      setTranscript((prev) => [
        ...prev,
        { id, speaker: "USER", text: userInput.trim(), timestamp: Date.now() },
      ]);
      setUserInput("");
      setPendingQuestion(null);
    } catch {
      // Keep the input so user can retry
    } finally {
      setSendingInput(false);
    }
  }

  return (
    <View style={styles.container}>
      <View style={styles.statusBar}>
        <View
          style={[
            styles.statusDot,
            { backgroundColor: STATUS_COLORS[status] },
          ]}
        />
        <Text variant="titleLarge" style={styles.statusLabel}>
          {STATUS_LABELS[status]}
        </Text>
      </View>
      <Text
        variant="bodyLarge"
        style={{
          color: theme.colors.onSurfaceVariant,
          textAlign: "center",
          paddingHorizontal: 24,
          marginBottom: 16,
        }}
      >
        {statusMessage}
      </Text>

      <ScrollView
        ref={scrollRef}
        style={styles.transcript}
        contentContainerStyle={styles.transcriptContent}
      >
        {transcript.length === 0 && (
          <Text
            variant="bodyLarge"
            style={{ color: "#525252", textAlign: "center", marginTop: 48 }}
          >
            Transkript razgovora će se pojaviti ovde...
          </Text>
        )}
        {transcript.map((entry) => (
          <Surface
            key={entry.id}
            style={[
              styles.message,
              entry.speaker === "OPERATOR"
                ? styles.messageOperator
                : entry.speaker === "USER"
                  ? styles.messageUser
                  : styles.messageAI,
            ]}
            elevation={1}
          >
            <View style={styles.speakerRow}>
              <Icon
                source={SPEAKER_ICONS[entry.speaker] || "account"}
                size={16}
                color={theme.colors.onSurfaceVariant}
              />
              <Text variant="labelMedium" style={styles.messageSpeaker}>
                {SPEAKER_LABELS[entry.speaker] || entry.speaker}
              </Text>
            </View>
            <Text variant="bodyLarge" style={styles.messageText}>
              {entry.text}
            </Text>
          </Surface>
        ))}
      </ScrollView>

      {pendingQuestion && (
        <Surface style={styles.inputSection} elevation={2}>
          <Text
            variant="titleSmall"
            style={{ color: "#fbbf24", marginBottom: 12 }}
          >
            {pendingQuestion}
          </Text>
          <View style={styles.inputRow}>
            <TextInput
              mode="flat"
              placeholder="Unesite odgovor..."
              value={userInput}
              onChangeText={setUserInput}
              style={styles.input}
              textColor={theme.colors.onSurface}
              accessibilityLabel="Vaš odgovor"
            />
            <IconButton
              icon="send"
              mode="contained"
              containerColor={theme.colors.primary}
              iconColor="#ffffff"
              size={28}
              onPress={handleSendInput}
              disabled={sendingInput || !userInput.trim()}
              accessibilityLabel="Pošalji"
              style={styles.sendButton}
            />
          </View>
        </Surface>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#1a1a1a",
  },
  statusBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 16,
    gap: 10,
  },
  statusDot: {
    width: 16,
    height: 16,
    borderRadius: 8,
  },
  statusLabel: {
    fontWeight: "700",
    color: "#ffffff",
  },
  transcript: {
    flex: 1,
  },
  transcriptContent: {
    padding: 16,
    gap: 12,
  },
  message: {
    padding: 14,
    borderRadius: 12,
    maxWidth: "85%",
  },
  messageAI: {
    backgroundColor: "#1e3a5f",
    alignSelf: "flex-start",
  },
  messageOperator: {
    backgroundColor: "#3f3f46",
    alignSelf: "flex-start",
  },
  messageUser: {
    backgroundColor: "#166534",
    alignSelf: "flex-end",
  },
  speakerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginBottom: 4,
  },
  messageSpeaker: {
    color: "#a3a3a3",
    fontWeight: "600",
  },
  messageText: {
    color: "#ffffff",
    lineHeight: 24,
  },
  inputSection: {
    backgroundColor: "#262626",
    padding: 16,
    borderTopWidth: 1,
    borderTopColor: "#404040",
  },
  inputRow: {
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
  },
  input: {
    flex: 1,
    backgroundColor: "#333333",
    minHeight: 48,
  },
  sendButton: {
    width: 56,
    height: 56,
  },
});
