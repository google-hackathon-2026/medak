import { Audio } from "expo-av";
import { File } from "expo-file-system";

const RECORDING_OPTIONS: Audio.RecordingOptions = {
  isMeteringEnabled: false,
  android: {
    extension: ".wav",
    outputFormat: Audio.AndroidOutputFormat.DEFAULT,
    audioEncoder: Audio.AndroidAudioEncoder.DEFAULT,
    sampleRate: 16000,
    numberOfChannels: 1,
    bitRate: 256000,
  },
  ios: {
    extension: ".wav",
    outputFormat: Audio.IOSOutputFormat.LINEARPCM,
    audioQuality: Audio.IOSAudioQuality.HIGH,
    sampleRate: 16000,
    numberOfChannels: 1,
    bitRate: 256000,
    linearPCMBitDepth: 16,
    linearPCMIsBigEndian: false,
    linearPCMIsFloat: false,
  },
  web: {},
};

const CHUNK_INTERVAL_MS = 250;

export async function requestMicPermission(): Promise<boolean> {
  const { granted } = await Audio.requestPermissionsAsync();
  return granted;
}

/**
 * Starts mic capture, calling onChunk with base64-encoded PCM data
 * every ~250ms. Returns a stop function.
 *
 * Uses short sequential recordings to approximate streaming,
 * since expo-av Recording writes to file rather than providing a stream.
 */
export async function startMicCapture(
  onChunk: (base64Pcm: string) => void
): Promise<() => void> {
  await Audio.setAudioModeAsync({
    allowsRecordingIOS: true,
    playsInSilentModeIOS: true,
  });

  let stopped = false;
  let currentRecording: Audio.Recording | null = null;

  async function recordChunk(): Promise<void> {
    if (stopped) return;

    const recording = new Audio.Recording();
    currentRecording = recording;

    try {
      await recording.prepareToRecordAsync(RECORDING_OPTIONS);
      await recording.startAsync();

      await new Promise<void>((resolve) =>
        setTimeout(resolve, CHUNK_INTERVAL_MS)
      );

      if (stopped) {
        await recording.stopAndUnloadAsync().catch(() => {});
        return;
      }

      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();

      if (uri) {
        const file = new File(uri);
        const base64 = await file.base64();
        onChunk(base64);
        file.delete();
      }
    } catch {
      // Recording may fail if permissions revoked or app backgrounded
    }

    if (!stopped) {
      recordChunk();
    }
  }

  recordChunk();

  return () => {
    stopped = true;
    if (currentRecording) {
      currentRecording.stopAndUnloadAsync().catch(() => {});
    }
  };
}
