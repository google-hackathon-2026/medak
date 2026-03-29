import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  View,
  StyleSheet,
  ScrollView,
  TextInput,
  Alert,
  Animated,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  Text,
  Button,
  Surface,
  ProgressBar,
  ActivityIndicator,
  Icon,
} from "react-native-paper";
import * as Haptics from "expo-haptics";
import { useAppTheme } from "../lib/useAppTheme";
import { SessionWebSocket } from "../lib/websocket";
import { requestMicPermission, startMicCapture } from "../lib/audio";
import { CameraView, useCameraPermissions, startFrameCapture } from "../lib/camera";
import { STRINGS } from "../lib/strings";
import type { EmergencyType, SessionPhase, TranscriptEntry } from "../lib/types";

const EMERGENCY_NUMBERS: Record<EmergencyType, string> = {
  AMBULANCE: "194",
  POLICE: "192",
  FIRE: "193",
};

const EMERGENCY_LABELS: Record<EmergencyType, string> = {
  AMBULANCE: STRINGS.emergency_ambulance,
  POLICE: STRINGS.emergency_police,
  FIRE: STRINGS.emergency_fire,
};

export default function SessionScreen() {
  const { sessionId, emergencyType } = useLocalSearchParams<{ sessionId: string; emergencyType: EmergencyType }>();
  const router = useRouter();
  const emergencyNumber = EMERGENCY_NUMBERS[emergencyType] || "194";
  const emergencyLabel = EMERGENCY_LABELS[emergencyType] || STRINGS.emergency_ambulance;
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
    (speaker: "assistant" | "user" | "dispatch", text: string) => {
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

  const handleBackToHome = useCallback(() => {
    wsRef.current?.disconnect();
    stopMicRef.current?.();
    stopCameraRef.current?.stop();
    if (questionTimerRef.current) clearTimeout(questionTimerRef.current);
    router.replace("/");
  }, [router]);

  const handleEndCall = useCallback(() => {
    Alert.alert(
      "Prekini poziv?",
      "Da li ste sigurni da želite da prekinete poziv?",
      [
        { text: "Otkaži", style: "cancel" },
        {
          text: "Prekini",
          style: "destructive",
          onPress: () => {
            wsRef.current?.sendEndSession();
            wsRef.current?.disconnect();
            stopMicRef.current?.();
            stopCameraRef.current?.stop();
            if (questionTimerRef.current) clearTimeout(questionTimerRef.current);
            router.replace("/");
          },
        },
      ]
    );
  }, [router]);

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
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        {/* Main content area */}
        <View style={styles.flex}>
          {/* Camera is absolutely positioned behind everything */}
          {(phase === "INTAKE" || phase === "TRIAGE" || phase === "LIVE_CALL") &&
            cameraPermission?.granted && (
              <CameraView
                ref={cameraRef}
                style={styles.cameraAbsolute}
                facing="back"
                animateShutter={false}
                onCameraReady={onCameraReady}
              />
            )}

          {/* Phase views overlay on top of camera */}
          {phase === "INTAKE" && (
            <View style={styles.phaseOverlay}>
              <IntakeView theme={theme} />
            </View>
          )}

          {phase === "TRIAGE" && (
            <View style={styles.phaseOverlay}>
              <TriageView
                theme={theme}
                confidence={confidence}
                transcript={transcript}
                scrollRef={scrollRef}
                wsConnected={wsConnected}
              />
            </View>
          )}

          {phase === "LIVE_CALL" && (
            <View style={styles.phaseOverlay}>
              <LiveCallView
                theme={theme}
                transcript={transcript}
                scrollRef={scrollRef}
                emergencyLabel={emergencyLabel}
                emergencyNumber={emergencyNumber}
                emergencyType={emergencyType}
              />
            </View>
          )}

          {phase === "RESOLVED" && (
            <ResolvedView theme={theme} etaMinutes={etaMinutes} onBackToHome={handleBackToHome} />
          )}

          {phase === "FAILED" && (
            <FailedView theme={theme} message={failedMessage} emergencyNumber={emergencyNumber} onBackToHome={handleBackToHome} />
          )}
        </View>

        {/* Question banner + persistent chat bar */}
        {(phase === "TRIAGE" || phase === "LIVE_CALL") && (
          <>
            {pendingQuestion && (
              <Surface
                style={[
                  styles.questionBanner,
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
              </Surface>
            )}

            <View
              style={[
                styles.chatInputBar,
                { backgroundColor: theme.colors.surface, borderTopColor: theme.colors.outline },
              ]}
            >
              <TextInput
                value={userInput}
                onChangeText={setUserInput}
                placeholder="Unesite poruku..."
                placeholderTextColor={theme.colors.onSurfaceVariant}
                style={[
                  styles.chatTextInput,
                  {
                    color: theme.colors.onSurface,
                    borderColor: theme.colors.outline,
                    backgroundColor: theme.colors.surfaceVariant,
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
                style={styles.chatSendButton}
              >
                Pošalji
              </Button>
            </View>
          </>
        )}

        {/* End call button */}
        {(phase === "INTAKE" || phase === "TRIAGE" || phase === "LIVE_CALL") && (
          <View style={styles.endCallContainer}>
            <Button
              mode="contained"
              onPress={handleEndCall}
              buttonColor={theme.colors.error}
              textColor={theme.colors.onError}
              icon="phone-hangup"
              contentStyle={styles.endCallContent}
              labelStyle={styles.endCallLabel}
              style={styles.endCallButton}
            >
              Prekini poziv
            </Button>
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

type ThemeProp = { theme: ReturnType<typeof useAppTheme> };

function TranscriptBubble({ entry, theme }: { entry: TranscriptEntry } & ThemeProp) {
  const isUser = entry.speaker === "user";
  const isDispatch = entry.speaker === "dispatch";
  const bgColor = isDispatch
    ? "#D84315"
    : isUser
      ? theme.custom.bubbleUser
      : theme.custom.bubbleAssistant;
  const label = isDispatch ? "Dispatch" : isUser ? STRINGS.you : STRINGS.system;

  return (
    <View
      style={[
        styles.bubble,
        isUser ? styles.bubbleRight : styles.bubbleLeft,
        isDispatch && styles.bubbleLeft,
        { backgroundColor: bgColor },
        isDispatch && styles.bubbleDispatch,
      ]}
    >
      <Text
        variant="labelSmall"
        style={{
          color: isDispatch ? "#FFF3E0" : theme.colors.onSurfaceVariant,
          marginBottom: 2,
          fontWeight: isDispatch ? "700" : "400",
        }}
      >
        {label}
      </Text>
      <Text variant="bodyLarge" style={{ color: isDispatch ? "#FFFFFF" : theme.colors.onPrimary }}>
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
        {STRINGS.connecting}
      </Text>
      <Text
        variant="bodyLarge"
        style={{
          color: theme.colors.onSurfaceVariant,
          textAlign: "center",
          marginTop: 12,
        }}
      >
        {STRINGS.session_establishing}
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
            {STRINGS.analysis_in_progress}
          </Text>
        </View>
        <View style={styles.confidenceContainer}>
          <Text
            variant="labelSmall"
            style={{ color: theme.colors.onSurfaceVariant, marginBottom: 4 }}
          >
            {STRINGS.confidence}: {Math.round(confidence * 100)}%
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
          ● {STRINGS.mic_active}
        </Text>
      </View>

      <TranscriptList
        transcript={transcript}
        scrollRef={scrollRef}
        theme={theme}
        emptyMessage={STRINGS.listening}
      />
    </View>
  );
}

function LiveCallView({
  theme,
  transcript,
  scrollRef,
  emergencyLabel,
  emergencyNumber,
  emergencyType,
}: ThemeProp & {
  transcript: TranscriptEntry[];
  scrollRef: React.RefObject<ScrollView | null>;
  emergencyLabel: string;
  emergencyNumber: string;
  emergencyType: EmergencyType;
}) {
  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, { toValue: 0.3, duration: 800, useNativeDriver: true }),
        Animated.timing(pulseAnim, { toValue: 1, duration: 800, useNativeDriver: true }),
      ])
    );
    animation.start();
    return () => animation.stop();
  }, [pulseAnim]);

  const bannerColor = theme.custom[emergencyType] || theme.custom.AMBULANCE;

  return (
    <View style={styles.flex}>
      <View style={[styles.liveCallBanner, { backgroundColor: bannerColor }]}>
        <View style={styles.liveCallBannerRow}>
          <View style={styles.pulseDotContainer}>
            <Animated.View
              style={[styles.pulseDotOuter, { opacity: pulseAnim }]}
            />
            <View style={styles.pulseDotInner} />
          </View>
          <View style={styles.liveCallBannerText}>
            <Text
              variant="titleLarge"
              style={{ color: theme.colors.onPrimary, fontWeight: "700" }}
            >
              Poziv u toku
            </Text>
            <Text
              variant="bodyMedium"
              style={{ color: theme.colors.onPrimary, opacity: 0.85 }}
            >
              {emergencyLabel} — {emergencyNumber}
            </Text>
          </View>
          <Icon source="phone-in-talk" size={28} color={theme.colors.onPrimary} />
        </View>
      </View>

      <TranscriptList
        transcript={transcript}
        scrollRef={scrollRef}
        theme={theme}
      />
    </View>
  );
}

function ResolvedView({ theme, etaMinutes, onBackToHome }: ThemeProp & { etaMinutes: number | null; onBackToHome: () => void }) {
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
        {STRINGS.help_on_way}
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
        {STRINGS.stay_on_location}
      </Text>
      <Button
        mode="contained"
        onPress={onBackToHome}
        style={{ marginTop: 32, borderRadius: 28, minWidth: 200 }}
        contentStyle={{ height: 52 }}
        icon="home"
      >
        {STRINGS.home_screen}
      </Button>
    </View>
  );
}

function FailedView({ theme, message, emergencyNumber, onBackToHome }: ThemeProp & { message: string | null; emergencyNumber: string; onBackToHome: () => void }) {
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
        {STRINGS.auto_call_failed}
      </Text>
      <Text
        variant="titleLarge"
        style={{
          color: theme.colors.onBackground,
          textAlign: "center",
          marginTop: 24,
        }}
      >
        {STRINGS.ask_someone_to_call.replace("{number}", emergencyNumber)}
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
      <Button
        mode="contained"
        onPress={onBackToHome}
        style={{ marginTop: 32, borderRadius: 28, minWidth: 200 }}
        contentStyle={{ height: 52 }}
        icon="home"
      >
        {STRINGS.home_screen}
      </Button>
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
  cameraAbsolute: {
    ...StyleSheet.absoluteFillObject,
  },
  phaseOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0, 0, 0, 0.55)",
    zIndex: 1,
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
  bubbleDispatch: {
    borderWidth: 1,
    borderColor: "#FF6E40",
  },
  liveCallBanner: {
    paddingHorizontal: 20,
    paddingVertical: 16,
  },
  liveCallBannerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  liveCallBannerText: {
    flex: 1,
  },
  pulseDotContainer: {
    width: 16,
    height: 16,
    justifyContent: "center",
    alignItems: "center",
  },
  pulseDotOuter: {
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: "rgba(255,255,255,0.4)",
    position: "absolute",
  },
  pulseDotInner: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#ffffff",
  },
  questionBanner: {
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
  },
  questionButtons: {
    flexDirection: "row",
    gap: 12,
  },
  tapButton: {
    flex: 1,
    minHeight: 48,
  },
  chatInputBar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 12,
    paddingVertical: 8,
    gap: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  chatTextInput: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 24,
    paddingHorizontal: 16,
    paddingVertical: 10,
    fontSize: 16,
    minHeight: 48,
  },
  chatSendButton: {
    minHeight: 48,
    justifyContent: "center",
  },
  statusIcon: {
    fontSize: 80,
    marginBottom: 16,
    fontWeight: "900",
  },
  endCallContainer: {
    paddingHorizontal: 24,
    paddingVertical: 12,
    alignItems: "center",
  },
  endCallButton: {
    borderRadius: 28,
    minWidth: 200,
  },
  endCallContent: {
    height: 56,
    paddingHorizontal: 24,
  },
  endCallLabel: {
    fontSize: 18,
    fontWeight: "700",
    letterSpacing: 1,
  },
});
