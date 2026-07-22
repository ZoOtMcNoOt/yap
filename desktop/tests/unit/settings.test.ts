import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock, isTauriMock, listenMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  isTauriMock: vi.fn(() => true),
  listenMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: invokeMock,
  isTauri: isTauriMock,
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: listenMock,
}));

import {
  acousticLanguageDetectorStatus,
  cancelAcousticLanguageDetectorImport,
  cancelFallbackModelInstall,
  cancelSileroVadInstall,
  fallbackModelStatus,
  installFallbackModel,
  installSileroVad,
  importAcousticLanguageDetector,
  listenFallbackModelProgress,
  listenFallbackModelStatus,
  listenSileroVadProgress,
  openFallbackModelFolder,
  projectServerConnectionTestMessage,
  removeFallbackModel,
  removeSileroVad,
  removeAcousticLanguageDetector,
  saveServerSettings,
  serverSettings,
  setFallbackModelEnabled,
  sileroVadStatus,
  testServerConnection,
  verifyFallbackModel,
  verifySileroVad,
  verifyAcousticLanguageDetector,
} from "@/settings";
import { serverAsrCapabilities } from "@/server";
import {
  liveLanguageRoutingStatus,
  saveLiveLanguageRouting,
  updateAutomaticLanguageSelection,
  type LiveLanguageRoutingStatus,
} from "@/live-language-routing";

describe("settings model lifecycle bindings", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    isTauriMock.mockReset();
    isTauriMock.mockReturnValue(true);
    listenMock.mockReset();
  });

  it("invokes the typed fallback model commands", async () => {
    invokeMock.mockResolvedValue({ status: "ready" });

    await fallbackModelStatus();
    await installFallbackModel();
    await installFallbackModel({ force: true });
    await cancelFallbackModelInstall();
    await verifyFallbackModel();
    await removeFallbackModel();
    await setFallbackModelEnabled(false);
    await openFallbackModelFolder();

    expect(invokeMock.mock.calls).toEqual([
      ["fallback_model_status"],
      ["fallback_model_install"],
      ["fallback_model_install", { force: true }],
      ["fallback_model_cancel_install"],
      ["fallback_model_verify"],
      ["fallback_model_remove"],
      ["fallback_model_set_enabled", { enabled: false }],
      ["fallback_model_open_folder"],
    ]);
  });

  it("wraps fallback model events behind typed listeners", async () => {
    const stopProgress = vi.fn();
    const stopStatus = vi.fn();
    listenMock
      .mockResolvedValueOnce(stopProgress)
      .mockResolvedValueOnce(stopStatus);

    const onProgress = vi.fn();
    const onStatus = vi.fn();

    const unlistenProgress = await listenFallbackModelProgress(onProgress);
    const progressEvent = listenMock.mock.calls[0]?.[1];
    progressEvent?.({ payload: { status: "downloading" } });

    const unlistenStatus = await listenFallbackModelStatus(onStatus);
    const statusEvent = listenMock.mock.calls[1]?.[1];
    statusEvent?.({ payload: { status: "ready" } });

    expect(listenMock.mock.calls[0]?.[0]).toBe("fallback-model-progress");
    expect(listenMock.mock.calls[1]?.[0]).toBe("fallback-model-status");
    expect(onProgress).toHaveBeenCalledWith({ status: "downloading" });
    expect(onStatus).toHaveBeenCalledWith({ status: "ready" });
    expect(unlistenProgress).toBe(stopProgress);
    expect(unlistenStatus).toBe(stopStatus);
  });

  it("invokes the explicit Silero lifecycle commands", async () => {
    invokeMock.mockResolvedValue({ status: "ready" });

    await sileroVadStatus();
    await installSileroVad();
    await cancelSileroVadInstall();
    await verifySileroVad();
    await removeSileroVad();

    expect(invokeMock.mock.calls).toEqual([
      ["silero_vad_status"],
      ["silero_vad_install"],
      ["silero_vad_cancel_install"],
      ["silero_vad_verify"],
      ["silero_vad_remove"],
    ]);
  });

  it("wraps Silero download progress behind a typed listener", async () => {
    const stop = vi.fn();
    listenMock.mockResolvedValue(stop);
    const onProgress = vi.fn();

    const unlisten = await listenSileroVadProgress(onProgress);
    const event = listenMock.mock.calls[0]?.[1];
    event?.({ payload: { downloadedBytes: 512, totalBytes: 1024, elapsedMs: 10 } });

    expect(listenMock.mock.calls[0]?.[0]).toBe("silero-vad-progress");
    expect(onProgress).toHaveBeenCalledWith({
      downloadedBytes: 512,
      totalBytes: 1024,
      elapsedMs: 10,
    });
    expect(unlisten).toBe(stop);
  });

  it("invokes the explicit offline language-detector lifecycle commands", async () => {
    invokeMock.mockResolvedValue({ status: "ready" });

    await acousticLanguageDetectorStatus();
    await importAcousticLanguageDetector();
    await cancelAcousticLanguageDetectorImport();
    await verifyAcousticLanguageDetector();
    await removeAcousticLanguageDetector();

    expect(invokeMock.mock.calls).toEqual([
      ["acoustic_language_detector_status"],
      ["acoustic_language_detector_import"],
      ["acoustic_language_detector_cancel_import"],
      ["acoustic_language_detector_verify"],
      ["acoustic_language_detector_remove"],
    ]);
  });

  it("invokes version-bound automatic language-routing commands", async () => {
    invokeMock.mockResolvedValue({ schemaVersion: 2 });

    await liveLanguageRoutingStatus();
    await saveLiveLanguageRouting(["es-US"], "catalog-revision");

    expect(invokeMock.mock.calls).toEqual([
      ["live_language_routing_status"],
      ["set_live_language_routing", {
        enabledAlternateLocales: ["es-US"],
        catalogRevision: "catalog-revision",
      }],
    ]);
  });

  it("updates one explicit automatic language without changing other selections", () => {
    const status: LiveLanguageRoutingStatus = {
      schemaVersion: 2,
      catalogRevision: "catalog-revision",
      primaryLanguageBcp47: "en-US",
      enabledLocales: [],
      preferenceIssue: null,
      automaticLanguages: [
        {
          languageCode: "es",
          locales: ["es-US"],
          selectedLocaleBcp47: null,
        },
        {
          languageCode: "pt",
          locales: ["pt-BR", "pt-PT"],
          selectedLocaleBcp47: "pt-PT",
        },
      ],
    };

    expect(updateAutomaticLanguageSelection(status, "es", "es-US")).toEqual([
      "pt-PT",
      "es-US",
    ]);
    expect(() => updateAutomaticLanguageSelection(status, "fr", "fr-CA")).toThrow(
      "Choose an available automatic language.",
    );
  });

  it("returns a noop listener outside Tauri", async () => {
    isTauriMock.mockReturnValue(false);

    const unlisten = await listenFallbackModelProgress(vi.fn());

    expect(listenMock).not.toHaveBeenCalled();
    expect(unlisten()).toBeUndefined();
  });

  it("invokes typed server settings and connection commands", async () => {
    const settings = {
      schemaVersion: 1 as const,
      enabled: true,
      baseUrl: "https://server.example",
    };
    invokeMock.mockResolvedValue(settings);

    await serverSettings();
    await saveServerSettings(settings);
    await testServerConnection();
    await serverAsrCapabilities();

    expect(invokeMock.mock.calls).toEqual([
      ["server_settings"],
      ["set_server_settings", { settings }],
      ["refresh_server_connection"],
      ["server_asr_capabilities"],
    ]);
  });

  it("projects terse inline connection results", () => {
    expect(projectServerConnectionTestMessage("ready")).toBe("Connection ready.");
    expect(projectServerConnectionTestMessage("offline")).toBe("Server is offline.");
    expect(projectServerConnectionTestMessage("sign_in_required")).toBe("Sign-in required.");
  });
});
