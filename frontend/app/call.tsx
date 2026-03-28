import { useState, useEffect, useRef } from "react";
import { View, StyleSheet, ScrollView } from "react-native";
import { Text, TextInput, IconButton, Surface, Icon } from "react-native-paper";
import { useLocalSearchParams } from "expo-router";
import * as Haptics from "expo-haptics";
import { CallStatus, TranscriptEntry } from "../lib/types";
import { sendUserInput } from "../lib/api";
import { connectToCallStream } from "../lib/sse";
import { useAppTheme } from "../lib/useAppTheme";
import staticTheme from "../lib/theme";

const STATUS_LABELS: Record<CallStatus, string> = {
  CALLING: "Pozivanje...",
  CONNECTED: "Povezano",
  COMPLETED: "Poziv završen",
  ERROR: "Greška",
};

type Speaker = TranscriptEntry["speaker"];

const SPEAKER_ICONS: Record<Speaker, string> = {
  AI: "robot",
  OPERATOR: "headset",
  USER: "account",
};

const SPEAKER_LABELS: Record<Speaker, string> = {
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

  const statusColors: Record<CallStatus, string> = {
    CALLING: theme.custom.warning,
    CONNECTED: theme.custom.success,
    COMPLETED: theme.custom.info,
    ERROR: theme.colors.error,
  };

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
    const timer = setTimeout(() => {
      scrollRef.current?.scrollToEnd({ animated: true });
    }, 100);
    return () => clearTimeout(timer);
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
    <View style={{ flex: 1, backgroundColor: theme.colors.background }}>
      <View style={styles.statusBar}>
        <View
          style={[styles.statusDot, { backgroundColor: statusColors[status] }]}
        />
        <Text variant="titleLarge" style={styles.statusLabel}>
          {STATUS_LABELS[status]}
        </Text>
      </View>
      <Text
        variant="bodyLarge"
        style={[styles.statusMessage, { color: theme.colors.onSurfaceVariant }]}
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
            style={[styles.emptyText, { color: theme.colors.onSurfaceVariant }]}
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
                ? { backgroundColor: theme.custom.bubbleOperator, alignSelf: "flex-start" as const }
                : entry.speaker === "USER"
                  ? { backgroundColor: theme.custom.bubbleUser, alignSelf: "flex-end" as const }
                  : { backgroundColor: theme.custom.bubbleAI, alignSelf: "flex-start" as const },
            ]}
            elevation={1}
          >
            <View style={styles.speakerRow}>
              <Icon
                source={SPEAKER_ICONS[entry.speaker]}
                size={16}
                color={theme.colors.onSurfaceVariant}
              />
              <Text
                variant="labelMedium"
                style={{ fontWeight: "600", color: theme.colors.onSurfaceVariant }}
              >
                {SPEAKER_LABELS[entry.speaker]}
              </Text>
            </View>
            <Text
              variant="bodyLarge"
              style={{ color: theme.colors.onSurface, lineHeight: 24 }}
            >
              {entry.text}
            </Text>
          </Surface>
        ))}
      </ScrollView>

      {pendingQuestion && (
        <Surface
          style={[
            styles.inputSection,
            {
              backgroundColor: theme.colors.surface,
              borderTopColor: theme.colors.outline,
            },
          ]}
          elevation={2}
        >
          <Text
            variant="titleSmall"
            style={[styles.questionText, { color: theme.custom.questionHighlight }]}
          >
            {pendingQuestion}
          </Text>
          <View style={styles.inputRow}>
            <TextInput
              mode="flat"
              placeholder="Unesite odgovor..."
              value={userInput}
              onChangeText={setUserInput}
              style={{ flex: 1, backgroundColor: theme.colors.surfaceVariant }}
              textColor={theme.colors.onSurface}
              accessibilityLabel="Vaš odgovor"
            />
            <IconButton
              icon="send"
              mode="contained"
              containerColor={theme.colors.primary}
              iconColor={theme.colors.onPrimary}
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
    color: staticTheme.colors.onBackground,
  },
  statusMessage: {
    textAlign: "center",
    paddingHorizontal: 24,
    marginBottom: 16,
  },
  transcript: {
    flex: 1,
  },
  transcriptContent: {
    padding: 16,
    gap: 12,
  },
  emptyText: {
    textAlign: "center",
    marginTop: 48,
  },
  message: {
    padding: 14,
    borderRadius: 12,
    maxWidth: "85%",
  },
  speakerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginBottom: 4,
  },
  inputSection: {
    padding: 16,
    borderTopWidth: 1,
  },
  questionText: {
    marginBottom: 12,
  },
  inputRow: {
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
  },
  sendButton: {
    width: 56,
    height: 56,
  },
});
