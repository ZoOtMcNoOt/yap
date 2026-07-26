import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

import type {
  AcousticLanguageDetectorView,
  FallbackModelView,
  LocalComputeTargetView,
  ServerConnectionState,
  SileroVadDownloadProgress,
  SileroVadView,
} from "@/lib/setup-model";

export {
  saveServerSettings,
  serverSettings,
  testServerConnection,
} from "@/server";
export type { ServerSettings } from "@/server";

export function projectServerConnectionTestMessage(state: ServerConnectionState): string {
  switch (state) {
    case "not_set":
      return "Connection check unavailable.";
    case "disabled":
      return "Server is disabled.";
    case "connecting":
      return "Checking connection.";
    case "ready":
      return "Connection ready.";
    case "offline":
      return "Server is offline.";
    case "sign_in_required":
      return "Sign-in required.";
    case "retrying":
      return "Server reconnecting.";
  }
}

export function fallbackModelStatus(): Promise<FallbackModelView> {
  return invoke<FallbackModelView>("fallback_model_status");
}

export function installFallbackModel(options: { force?: boolean } = {}): Promise<FallbackModelView> {
  return options.force
    ? invoke<FallbackModelView>("fallback_model_install", { force: true })
    : invoke<FallbackModelView>("fallback_model_install");
}

export function cancelFallbackModelInstall(): Promise<FallbackModelView> {
  return invoke<FallbackModelView>("fallback_model_cancel_install");
}

export function verifyFallbackModel(): Promise<FallbackModelView> {
  return invoke<FallbackModelView>("fallback_model_verify");
}

export function removeFallbackModel(): Promise<FallbackModelView> {
  return invoke<FallbackModelView>("fallback_model_remove");
}

export function setFallbackModelEnabled(enabled: boolean): Promise<FallbackModelView> {
  return invoke<FallbackModelView>("fallback_model_set_enabled", { enabled });
}

export function openFallbackModelFolder(): Promise<void> {
  return invoke<void>("fallback_model_open_folder");
}

export function sileroVadStatus(): Promise<SileroVadView> {
  return invoke<SileroVadView>("silero_vad_status");
}

export function installSileroVad(): Promise<SileroVadView> {
  return invoke<SileroVadView>("silero_vad_install");
}

export function cancelSileroVadInstall(): Promise<SileroVadView> {
  return invoke<SileroVadView>("silero_vad_cancel_install");
}

export function verifySileroVad(): Promise<SileroVadView> {
  return invoke<SileroVadView>("silero_vad_verify");
}

export function removeSileroVad(): Promise<SileroVadView> {
  return invoke<SileroVadView>("silero_vad_remove");
}

export async function listenSileroVadProgress(
  onProgress: (progress: SileroVadDownloadProgress) => void,
): Promise<UnlistenFn> {
  if (!isTauri()) return () => undefined;
  return listen<SileroVadDownloadProgress>("silero-vad-progress", (event) => {
    onProgress(event.payload);
  });
}

export function acousticLanguageDetectorStatus(): Promise<AcousticLanguageDetectorView> {
  return invoke<AcousticLanguageDetectorView>("acoustic_language_detector_status");
}

export function importAcousticLanguageDetector(): Promise<AcousticLanguageDetectorView> {
  return invoke<AcousticLanguageDetectorView>("acoustic_language_detector_import");
}

export function cancelAcousticLanguageDetectorImport(): Promise<AcousticLanguageDetectorView> {
  return invoke<AcousticLanguageDetectorView>("acoustic_language_detector_cancel_import");
}

export function verifyAcousticLanguageDetector(): Promise<AcousticLanguageDetectorView> {
  return invoke<AcousticLanguageDetectorView>("acoustic_language_detector_verify");
}

export function removeAcousticLanguageDetector(): Promise<AcousticLanguageDetectorView> {
  return invoke<AcousticLanguageDetectorView>("acoustic_language_detector_remove");
}

export async function polishNumGpuLayers(): Promise<number> {
  return invoke<number>("polish_num_gpu");
}

export async function listLocalComputeTargets(): Promise<LocalComputeTargetView[]> {
  return invoke<LocalComputeTargetView[]>("list_local_compute_targets");
}

export async function setLocalComputeTarget(targetId: string): Promise<LocalComputeTargetView[]> {
  return invoke<LocalComputeTargetView[]>("set_local_compute_target", { targetId });
}

export async function listenFallbackModelProgress(
  onProgress: (view: FallbackModelView) => void,
): Promise<UnlistenFn> {
  if (!isTauri()) return () => undefined;
  return listen<FallbackModelView>("fallback-model-progress", (event) => onProgress(event.payload));
}

export async function listenFallbackModelStatus(
  onStatus: (view: FallbackModelView) => void,
): Promise<UnlistenFn> {
  if (!isTauri()) return () => undefined;
  return listen<FallbackModelView>("fallback-model-status", (event) => onStatus(event.payload));
}
