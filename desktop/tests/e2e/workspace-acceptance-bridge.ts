import type { Page } from "@playwright/test";
import { installRecordingJourneyBridge } from "./recording-journey-bridge";

// Native-boundary UI fixtures, not filesystem, identity, or inference proof.
export async function installWorkspaceAcceptanceBridge(page: Page, options: {
  serverState?: "ready" | "offline" | "disabled" | "sign_in_required" | "access_denied";
  historyBlocked?: boolean;
  maintenance?: boolean;
  settingsFailOnce?: boolean;
  modelLifecycle?: boolean;
} = {}) {
  await installRecordingJourneyBridge(page, "complete");
  await page.addInitScript((options) => {
    const host = globalThis as unknown as { __TAURI_INTERNALS__: {
      invoke: (command: string, args?: unknown) => Promise<unknown>;
    } };
    const baseInvoke = host.__TAURI_INTERNALS__.invoke;
    const calls: Array<{ command: string; args: unknown }> = [];
    let historyFails = false;
    let hideFails = true;
    let recoveryFails = true;
    let deleteFails = true;
    let settingsLoadFails = options.settingsFailOnce;
    let settingsSaveFails = options.settingsFailOnce;
    let connectionFails = options.settingsFailOnce;
    let settingsSaved = false;
    let modelStatus = options.modelLifecycle ? "missing" : "ready";
    let installs = 0;
    let releaseHistory: (() => void) | undefined;
    const historyGate = options.historyBlocked ? new Promise<void>((resolve) => { releaseHistory = resolve; }) : Promise.resolve();
    const sessions = [
      {
        sessionId: "partial-1", name: "live-partial-1", origin: "live",
        createdAtMs: Date.parse("2026-10-02T11:00:00Z"),
        sourcePath: "C:\\Yap\\live-recordings\\live-partial-1.wav.part",
        outputPath: "C:\\Yap\\live-recordings\\live-partial-1.wav.part",
        captureCommitPath: null as string | null, recoveryState: "recoverable" as string | null,
        warning: "Capture stopped before publication.",
      },
      {
        sessionId: "saved-1", name: "live-saved-1", origin: "live",
        createdAtMs: Date.parse("2026-10-02T10:00:00Z"),
        sourcePath: "C:\\Yap\\live-recordings\\live-saved-1.wav",
        outputPath: "C:\\Yap\\live-recordings\\live-saved-1.txt",
        captureCommitPath: "C:\\Yap\\live-recordings\\live-saved-1.commit.json",
        recoveryState: null, warning: null as string | null,
      },
    ];
    Object.assign(globalThis, { __workspaceAcceptance: {
      calls,
      releaseHistory: () => releaseHistory?.(),
      setHistoryFails: (fails: boolean) => { historyFails = fails; },
      allowSettingsLoad: () => { settingsLoadFails = false; },
      failModelInstall: () => {
        modelStatus = "error";
        const view = { id: "nemotron-3.5-asr-streaming-0.6b-1120ms-int8", label: "Nemotron", modelsDir: "C:\\Yap\\models", status: modelStatus, message: "Download interrupted. Retry or cancel." };
        (globalThis as unknown as { __recordingJourney: { emitNativeEvent: (event: string, payload: unknown) => void } }).__recordingJourney.emitNativeEvent("fallback-model-status", view);
      },
    } });
    host.__TAURI_INTERNALS__.invoke = async (command, args) => {
      calls.push({ command, args });
      if (options.modelLifecycle && command === "setup_status") {
        const setup = await baseInvoke(command, args) as object;
        return { ...setup, engineReady: modelStatus === "ready", engineStatus: modelStatus === "ready" ? "Ready" : "Setup", modelInstalled: modelStatus === "ready" };
      }
      if (options.modelLifecycle && ["fallback_model_status", "fallback_model_install", "fallback_model_cancel_install"].includes(command)) {
        if (command === "fallback_model_install") modelStatus = ++installs === 3 ? "ready" : "downloading";
        if (command === "fallback_model_cancel_install") modelStatus = "missing";
        return { id: "nemotron-3.5-asr-streaming-0.6b-1120ms-int8", label: "Nemotron", modelsDir: "C:\\Yap\\models", status: modelStatus, progressPercent: modelStatus === "downloading" ? 20 : null };
      }
      if (command === "history_catalog") {
        await historyGate;
        if (historyFails) throw new Error("History load interrupted.");
        return options.maintenance ? { maintenanceWarnings: [], sessions: [...sessions] } : baseInvoke(command, args);
      }
      if (command === "server_connection_status" || command === "refresh_server_connection") {
        if (command === "refresh_server_connection" && connectionFails && settingsSaved) {
          connectionFails = false;
          throw new Error("Connection check failed. Try again.");
        }
        const snapshot = await baseInvoke(command, args) as { capabilities: Record<string, boolean> };
        return { ...snapshot, state: options.serverState ?? "ready", capabilities: {
          ...snapshot.capabilities, batchJobs: false, jobStatus: false,
        } };
      }
      if (command === "server_settings" && settingsLoadFails) {
        throw new Error("Server settings could not be read.");
      }
      if (command === "set_server_settings" && settingsSaveFails) {
        settingsSaveFails = false;
        throw new Error("Server settings could not be saved.");
      }
      if (command === "set_server_settings") settingsSaved = true;
      if (command === "history_hide_native") {
        if (hideFails) { hideFails = false; throw new Error("Hide was not saved. Try again."); }
        const { identity } = args as { identity: { sessionId: string } };
        sessions.splice(sessions.findIndex((entry) => entry.sessionId === identity.sessionId), 1);
        return;
      }
      if (command === "recover_live_session") {
        if (recoveryFails) { recoveryFails = false; throw new Error("Recovery interrupted. Try again."); }
        const session = sessions.find((entry) => entry.sessionId === (args as { sessionId: string }).sessionId)!;
        session.sourcePath = session.sourcePath.replace(/\.part$/, "");
        session.outputPath = session.sourcePath;
        session.recoveryState = "recovered";
        session.warning = "Partial audio recovered. No transcript was produced.";
        return { ...session };
      }
      if (command === "delete_saved_live_session" || command === "delete_recoverable_live_session") {
        if (deleteFails) { deleteFails = false; throw new Error("Native identity changed. Refresh and try again."); }
        sessions.splice(sessions.findIndex((entry) => entry.sessionId === (args as { sessionId: string }).sessionId), 1);
        return;
      }
      return baseInvoke(command, args);
    };
  }, options);
}
