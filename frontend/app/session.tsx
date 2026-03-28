import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  View,
  StyleSheet,
  ScrollView,
  TextInput,
} from "react-native";
import { useLocalSearchParams } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  Text,
  Button,
  Surface,
  ProgressBar,
  ActivityIndicator,
} from "react-native-paper";
import * as Haptics from "expo-haptics";
import { useAppTheme } from "../lib/useAppTheme";
import { SessionWebSocket } from "../lib/websocket";
import { requestMicPermission, startMicCapture } from "../lib/audio";
import { CameraView, useCameraPermissions, startFrameCapture } from "../lib/camera";
import type { SessionPhase, TranscriptEntry } from "../lib/types";

export default function SessionScreen() {
  const { sessionId } = useLocalSearchParams<{ sessionId: string }>();
  const theme = useAppTheme();

  const [phase, setPhase] = useState<SessionPhase>("INTAKE");
  const [confidence, setConfidence] = useState(0);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [etaMinutes, setEtaMinutes] = useState<number | null>(null);
  const [failedMessage, setFailedMessage] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [userInput, setUserInput] = useState("");

  const wsRef = useRef<SessionWebSocket | null>(null);
  const stopMicRef = useRef<(() => void) | null>(null);
  const stopCameraRef = useRef<{ stop: () => void } | null>(null);
  const scrollRef = useRef<ScrollView>(null);
  const cameraRef = useRef<CameraView>(null);
  const questionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [cameraPermission, requestCameraPermission] = useCameraPermissions();

  const addTranscript = useCallback(
    (speaker: "assistant" | "user", text: string) => {
      setTranscript((prev) => [
        ...prev,
        {
          id: `${Date.now()}-${Math.random()}`,
          speaker,
          text,
          timestamp: Date.now(),
        },
      ]);
    },
    []
  );

  useEffect(() => {
    if (!sessionId) return;

    const ws = new SessionWebSocket(sessionId, {
      onTranscript: addTranscript,
      onStatusUpdate: (newPhase, newConfidence) => {
        setPhase(newPhase);
        setConfidence(newConfidence);
      },
      onUserQuestion: (question) => {
        setPendingQuestion(question);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
        // Auto-dismiss after 5 seconds
        if (questionTimerRef.current) clearTimeout(questionTimerRef.current);
        questionTimerRef.current = setTimeout(() => {
          setPendingQuestion(null);
        }, 5000);
      },
      onResolved: (eta, message) => {
        setPhase("RESOLVED");
        setEtaMinutes(eta);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        addTranscript("assistant", message);
      },
      onFailed: (message) => {
        setPhase("FAILED");
        setFailedMessage(message);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      },
      onConnectionChange: setWsConnected,
    });

    wsRef.current = ws;
    ws.connect();

    (async () => {
      const micGranted = await requestMicPermission();
      if (micGranted) {
        const stop = await startMicCapture((base64) => {
          ws.sendAudio(base64);
        });
        stopMicRef.current = stop;
      }
    })();

    requestCameraPermission();

    return () => {
      ws.disconnect();
      stopMicRef.current?.();
      stopCameraRef.current?.stop();
      if (questionTimerRef.current) clearTimeout(questionTimerRef.current);
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const onCameraReady = useCallback(() => {
    if (cameraRef.current && wsRef.current) {
      stopCameraRef.current?.stop();
      const handle = startFrameCapture(cameraRef, (base64) => {
        wsRef.current?.sendVideoFrame(base64);
      });
      stopCameraRef.current = handle;
    }
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: true });
  }, [transcript]);

  useEffect(() => {
    if (phase !== "INTAKE") return;
    const interval = setInterval(() => {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    }, 1500);
    return () => clearInterval(interval);
  }, [phase]);

  const handleUserResponse = useCallback(
    (responseType: "TAP" | "TEXT", value: string) => {
      wsRef.current?.sendUserResponse(responseType, value);
      addTranscript("user", value);
      setPendingQuestion(null);
      if (questionTimerRef.current) clearTimeout(questionTimerRef.current);
      setUserInput("");
    },
    [addTranscript]
  );

  const handleTextSubmit = useCallback(() => {
    if (!userInput.trim()) return;
    handleUserResponse("TEXT", userInput.trim());
  }, [userInput, handleUserResponse]);

  const backgroundColor =
    phase === "RESOLVED"
      ? theme.custom.resolvedBackground
      : phase === "FAILED"
        ? theme.custom.failedBackground
        : phase === "TRIAGE"
          ? theme.custom.triageBackground
          : theme.colors.background;

  return (
    <SafeAreaView style={[styles.container, { backgroundColor }]}>
      {(phase === "INTAKE" || phase === "TRIAGE") &&
        cameraPermission?.granted && (
          <CameraView
            ref={cameraRef}
            style={styles.hiddenCamera}
            facing="back"
            onCameraReady={onCameraReady}
          />
        )}

      {phase === "INTAKE" && <IntakeView theme={theme} />}

      {phase === "TRIAGE" && (
        <TriageView
          theme={theme}
          confidence={confidence}
          transcript={transcript}
          scrollRef={scrollRef}
          wsConnected={wsConnected}
        />
      )}

      {phase === "LIVE_CALL" && (
        <LiveCallView
          theme={theme}
          transcript={transcript}
          scrollRef={scrollRef}
        />
      )}

      {phase === "RESOLVED" && (
        <ResolvedView theme={theme} etaMinutes={etaMinutes} />
      )}

      {phase === "FAILED" && (
        <FailedView theme={theme} message={failedMessage} />
      )}

      {pendingQuestion && (phase === "TRIAGE" || phase === "LIVE_CALL") && (
        <Surface
          style={[
            styles.questionOverlay,
            { backgroundColor: theme.colors.surface },
          ]}
          elevation={4}
        >
          <Text
            variant="titleMedium"
            style={{ color: theme.custom.questionHighlight, marginBottom: 12 }}
          >
            {pendingQuestion}
          </Text>

          <View style={styles.questionButtons}>
            <Button
              mode="contained"
              onPress={() => handleUserResponse("TAP", "DA")}
              style={styles.tapButton}
              buttonColor={theme.custom.success}
            >
              DA
            </Button>
            <Button
              mode="contained"
              onPress={() => handleUserResponse("TAP", "NE")}
              style={styles.tapButton}
              buttonColor={theme.colors.error}
            >
              NE
            </Button>
          </View>

          <View style={styles.textInputRow}>
            <TextInput
              value={userInput}
              onChangeText={setUserInput}
              placeholder="Ili unesite odgovor..."
              placeholderTextColor={theme.colors.onSurfaceVariant}
              style={[
                styles.textInput,
                {
                  color: theme.colors.onSurface,
                  borderColor: theme.colors.outline,
                },
              ]}
              onSubmitEditing={handleTextSubmit}
              returnKeyType="send"
            />
            <Button
              mode="contained"
              onPress={handleTextSubmit}
              disabled={!userInput.trim()}
              compact
            >
              Pošalji
            </Button>
          </View>
        </Surface>
      )}
    </SafeAreaView>
  );
}

type ThemeProp = { theme: ReturnType<typeof useAppTheme> };

function TranscriptBubble({ entry, theme }: { entry: TranscriptEntry } & ThemeProp) {
  const isUser = entry.speaker === "user";
  const bgColor = isUser
    ? theme.custom.bubbleUser
    : theme.custom.bubbleAssistant;

  return (
    <View
      style={[
        styles.bubble,
        isUser ? styles.bubbleRight : styles.bubbleLeft,
        { backgroundColor: bgColor },
      ]}
    >
      <Text
        variant="labelSmall"
        style={{ color: theme.colors.onSurfaceVariant, marginBottom: 2 }}
      >
        {isUser ? "Vi" : "Sistem"}
      </Text>
      <Text variant="bodyLarge" style={{ color: theme.colors.onPrimary }}>
        {entry.text}
      </Text>
    </View>
  );
}

function TranscriptList({
  transcript,
  scrollRef,
  theme,
  emptyMessage,
}: {
  transcript: TranscriptEntry[];
  scrollRef: React.RefObject<ScrollView | null>;
  emptyMessage?: string;
} & ThemeProp) {
  return (
    <ScrollView
      ref={scrollRef}
      style={styles.flex}
      contentContainerStyle={styles.transcriptContent}
    >
      {transcript.map((entry) => (
        <TranscriptBubble key={entry.id} entry={entry} theme={theme} />
      ))}
      {transcript.length === 0 && emptyMessage && (
        <Text
          variant="bodyLarge"
          style={{
            color: theme.colors.onSurfaceVariant,
            textAlign: "center",
            marginTop: 48,
          }}
        >
          {emptyMessage}
        </Text>
      )}
    </ScrollView>
  );
}

function IntakeView({ theme }: ThemeProp) {
  return (
    <View style={styles.centeredView}>
      <ActivityIndicator
        size="large"
        color={theme.custom.AMBULANCE}
        style={{ marginBottom: 24 }}
      />
      <Text
        variant="headlineLarge"
        style={{ color: theme.colors.onBackground, textAlign: "center" }}
      >
        Povezivanje...
      </Text>
      <Text
        variant="bodyLarge"
        style={{
          color: theme.colors.onSurfaceVariant,
          textAlign: "center",
          marginTop: 12,
        }}
      >
        Sesija se uspostavlja
      </Text>
    </View>
  );
}

function TriageView({
  theme,
  confidence,
  transcript,
  scrollRef,
  wsConnected,
}: ThemeProp & {
  confidence: number;
  transcript: TranscriptEntry[];
  scrollRef: React.RefObject<ScrollView | null>;
  wsConnected: boolean;
}) {
  return (
    <View style={styles.flex}>
      <View style={styles.statusBar}>
        <View style={styles.statusRow}>
          <View
            style={[
              styles.statusDot,
              { backgroundColor: wsConnected ? theme.custom.success : theme.colors.error },
            ]}
          />
          <Text
            variant="labelLarge"
            style={{ color: theme.colors.onSurfaceVariant }}
          >
            Analiza u toku
          </Text>
        </View>
        <View style={styles.confidenceContainer}>
          <Text
            variant="labelSmall"
            style={{ color: theme.colors.onSurfaceVariant, marginBottom: 4 }}
          >
            Pouzdanost: {Math.round(confidence * 100)}%
          </Text>
          <ProgressBar
            progress={confidence}
            color={theme.custom.confidenceBar}
            style={styles.confidenceBar}
          />
        </View>
      </View>

      <View style={styles.micIndicator}>
        <Text variant="labelMedium" style={{ color: theme.custom.AMBULANCE }}>
          ● Mikrofon aktivan
        </Text>
      </View>

      <TranscriptList
        transcript={transcript}
        scrollRef={scrollRef}
        theme={theme}
        emptyMessage="Slušam okolinu..."
      />
    </View>
  );
}

function LiveCallView({
  theme,
  transcript,
  scrollRef,
}: ThemeProp & {
  transcript: TranscriptEntry[];
  scrollRef: React.RefObject<ScrollView | null>;
}) {
  return (
    <View style={styles.flex}>
      <Surface
        style={[styles.callHeader, { backgroundColor: theme.custom.warning }]}
        elevation={2}
      >
        <Text
          variant="titleLarge"
          style={{ color: theme.colors.background, fontWeight: "700", textAlign: "center" }}
        >
          Poziv u toku — 112
        </Text>
      </Surface>

      <TranscriptList
        transcript={transcript}
        scrollRef={scrollRef}
        theme={theme}
      />
    </View>
  );
}

function ResolvedView({ theme, etaMinutes }: ThemeProp & { etaMinutes: number | null }) {
  return (
    <View style={styles.centeredView}>
      <Text style={[styles.statusIcon, { color: theme.custom.success }]}>✓</Text>
      <Text
        variant="headlineLarge"
        style={{
          color: theme.custom.success,
          textAlign: "center",
          fontWeight: "700",
        }}
      >
        Pomoć je na putu
      </Text>
      {etaMinutes != null && (
        <Text
          variant="displaySmall"
          style={{
            color: theme.colors.onBackground,
            textAlign: "center",
            marginTop: 16,
          }}
        >
          ETA: {etaMinutes} min
        </Text>
      )}
      <Text
        variant="bodyLarge"
        style={{
          color: theme.colors.onSurfaceVariant,
          textAlign: "center",
          marginTop: 24,
        }}
      >
        Ostanite na lokaciji i sačekajte dolazak ekipe
      </Text>
    </View>
  );
}

function FailedView({ theme, message }: ThemeProp & { message: string | null }) {
  return (
    <View style={styles.centeredView}>
      <Text style={[styles.statusIcon, { color: theme.colors.error }]}>!</Text>
      <Text
        variant="headlineLarge"
        style={{
          color: theme.colors.error,
          textAlign: "center",
          fontWeight: "700",
        }}
      >
        Automatski poziv nije uspeo
      </Text>
      <Text
        variant="titleLarge"
        style={{
          color: theme.colors.onBackground,
          textAlign: "center",
          marginTop: 24,
        }}
      >
        Zamolite nekoga u blizini da pozove 112
      </Text>
      {message && (
        <Text
          variant="bodyMedium"
          style={{
            color: theme.colors.onSurfaceVariant,
            textAlign: "center",
            marginTop: 16,
          }}
        >
          {message}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  flex: {
    flex: 1,
  },
  centeredView: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 32,
  },
  hiddenCamera: {
    position: "absolute",
    width: 1,
    height: 1,
    opacity: 0,
  },
  statusBar: {
    padding: 16,
    paddingBottom: 8,
  },
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 8,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  confidenceContainer: {
    marginTop: 4,
  },
  confidenceBar: {
    height: 8,
    borderRadius: 4,
  },
  micIndicator: {
    paddingHorizontal: 16,
    paddingBottom: 8,
  },
  transcriptContent: {
    padding: 16,
    gap: 8,
    flexGrow: 1,
  },
  bubble: {
    padding: 12,
    borderRadius: 12,
    maxWidth: "80%",
  },
  bubbleLeft: {
    alignSelf: "flex-start",
  },
  bubbleRight: {
    alignSelf: "flex-end",
  },
  callHeader: {
    padding: 16,
    margin: 16,
    borderRadius: 12,
  },
  questionOverlay: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    padding: 20,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
  },
  questionButtons: {
    flexDirection: "row",
    gap: 12,
    marginBottom: 12,
  },
  tapButton: {
    flex: 1,
    minHeight: 48,
  },
  textInputRow: {
    flexDirection: "row",
    gap: 8,
    alignItems: "center",
  },
  textInput: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    minHeight: 48,
  },
  statusIcon: {
    fontSize: 80,
    marginBottom: 16,
    fontWeight: "900",
  },
});
