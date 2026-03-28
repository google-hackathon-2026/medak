import { CameraView } from "expo-camera";
import { useCameraPermissions } from "expo-camera";

export { CameraView, useCameraPermissions };

const FRAME_INTERVAL_MS = 750; // ~1.3 fps

export interface FrameCaptureHandle {
  stop: () => void;
}

/**
 * Starts periodic frame capture from a CameraView ref.
 * Captures JPEG frames at ~1-2fps and calls onFrame with base64 data.
 *
 * Usage: pass a ref to CameraView, call this after the camera is ready.
 */
export function startFrameCapture(
  cameraRef: React.RefObject<CameraView | null>,
  onFrame: (base64Jpeg: string) => void
): FrameCaptureHandle {
  let stopped = false;

  async function captureLoop() {
    if (stopped || !cameraRef.current) return;

    try {
      const photo = await cameraRef.current.takePictureAsync({
        quality: 0.3,
        base64: true,
        skipProcessing: true,
        shutterSound: false,
      });

      if (photo?.base64 && !stopped) {
        onFrame(photo.base64);
      }
    } catch {
      // Camera may not be ready or app may be backgrounded
    }

    if (!stopped) {
      setTimeout(captureLoop, FRAME_INTERVAL_MS);
    }
  }

  captureLoop();

  return {
    stop: () => {
      stopped = true;
    },
  };
}
