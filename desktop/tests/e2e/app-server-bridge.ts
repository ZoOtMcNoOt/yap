import type { Page } from "@playwright/test";


export async function installQueuedServerBridge(
  page: Page,
  serverState: "disabled" | "not_set" | "offline",
  options: {
    configuredServerUrl?: string;
    fallbackVerifyFails?: boolean;
    localModelStatus?: "missing" | "ready";
    localServerOffer?: boolean;
    primaryLanguageUnconfirmed?: boolean;
    serverRefreshNeverSettles?: boolean;
  } = {},
) {
  await page.addInitScript(({
    configuredServerUrl,
    fallbackVerifyFails,
    localModelStatus,
    state,
    localServerOffer,
    primaryLanguageUnconfirmed,
    serverRefreshNeverSettles,
  }) => {
    Object.defineProperty(globalThis, "isTauri", { value: true });
    const calls: string[] = [];
    const languageCalls: Array<{ args: unknown; command: string }> = [];
    const serverCalls: Array<{ args: unknown; command: string }> = [];
    const shortcutCalls: Array<{ args: unknown; command: string }> = [];
    let localServerAvailable = localServerOffer;
    Object.assign(globalThis, {
      __queuedServerBoundaryTest: {
        calls,
        languageCalls,
        serverCalls,
        setLocalServerAvailable: (available: boolean) => {
          localServerAvailable = available;
        },
        shortcutCalls,
      },
    });
    let callbackId = 0;
    let serverSnapshot = {
      apiVersion: null as string | null,
      capabilities: {
        batchJobs: false,
        jobStatus: false,
        liveStreaming: false,
        transcriptCorrection: false,
        archivistIngestions: false,
        analystAnswers: false,
        coordinatorBundles: false,
        auditorReports: false,
        curatorProposals: false,
        studentQuestions: false,
      },
      checkedAtMs: state === "offline" ? 1 : null,
      errorCode: state === "offline" ? "CONNECTION_FAILED" : null,
      retryAtMs: null,
      state: state as string,
    };
    let serverSettingsState = {
      authentication: null,
      baseUrl: configuredServerUrl ?? (state === "offline" ? "https://server.example" : null),
      enabled: state === "offline",
      schemaVersion: 2,
    };
    const queuedJob = {
      id: `durable-${state}-job`,
      name: `${state.replace("_", "-")}-interview.wav`,
      pipeline: {
        alignment: "notStarted",
        diarization: "notStarted",
        intake: "done",
        postprocessing: "notStarted",
        preprocessing: "notStarted",
        transcription: "notStarted",
      },
      playbackPath: "http://127.0.0.1:43123/media/queued-proof",
      route: "serverBatch",
      sessionMode: "meeting",
      sessionOrigin: "importedFile",
      sourcePath: `C:\\recordings\\${state}-interview.wav`,
      status: "queued_server",
    };
    const languageCatalog = {
      catalogRevision: "language-picker-keyboard-test-catalog-v1",
      providers: [{
        capabilities: ["en-US", "fr-FR"].map((languageBcp47) => ({
          languageBcp47,
          languageSuggestion: false,
          mode: "fixedBatch",
          promotionEvidenceRevision: "language-picker-keyboard-test-evidence-v1",
          providerLanguageCode: languageBcp47.startsWith("en") ? "en" : "fr",
          qualityTier: "transcriptionReady",
          segmentLanguageTags: false,
          wordAlignment: true,
        })),
        modelId: "test-model",
        modelLicense: "test-license",
        modelRevision: "0123456789abcdef0123456789abcdef01234567",
        modelSource: "https://example.invalid/model",
        poolId: "test-pool",
        providerId: "test-provider",
      }],
      schemaVersion: 1,
    };
    // Unconfirmed-and-serverless is the true first run: no catalog, so the
    // only path to a confirmed language is the local dictation catalog.
    let primaryLanguageStatus = primaryLanguageUnconfirmed
      ? {
          capabilityCatalog: null,
          confirmedLanguageAvailable: null,
          confirmedLanguageBcp47: null,
          lastKnownCapabilities: null,
          preferenceIssue: null,
          requiresConfirmation: true,
          schemaVersion: 1,
          suggestedLanguageBcp47: "en-US",
        }
      : {
          capabilityCatalog: languageCatalog,
          confirmedLanguageAvailable: true,
          confirmedLanguageBcp47: "en-US",
          lastKnownCapabilities: null,
          preferenceIssue: null,
          requiresConfirmation: false,
          schemaVersion: 1,
          suggestedLanguageBcp47: null,
        };
    const liveLanguageRoutingStatus = {
      catalogRevision: "local-language-catalog-v1",
      enabledLocales: ["en-US"],
      preferenceIssue: null,
      primaryLanguageBcp47: "en-US",
      automaticLanguages: [
        {
          languageCode: "es",
          locales: ["es-US"],
          selectedLocaleBcp47: null,
        },
      ],
      schemaVersion: 2,
    };
    let liveSnapshot = {
      captureMode: "pushToTalk",
      hotkey: "Ctrl+Shift+Space",
      pasteHotkey: "Ctrl+Shift+Alt+V",
      route: "localFallback",
      status: "idle",
      visibility: "enabled",
    };

    Object.assign(globalThis, {
      __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener() {} },
      __TAURI_INTERNALS__: {
        convertFileSrc: (path: string) => `asset:${path}`,
        metadata: {
          currentWebview: { label: "main" },
          currentWindow: { label: "main" },
        },
        transformCallback: () => ++callbackId,
        invoke: async (command: string, args?: unknown) => {
          calls.push(command);
          if (command === "plugin:event|listen") return ++callbackId;
          if (command === "plugin:event|unlisten") return undefined;
          if (command === "recording_jobs_snapshot") return [queuedJob];
          if (command === "history_catalog") {
            return { maintenanceWarnings: [], sessions: [] };
          }
          if (command === "setup_status") return {
            engineBinaryStatus: "ready",
            engineReady: localModelStatus === "ready",
            engineStatus: localModelStatus === "ready" ? "Ready" : "Setup",
            fallbackEnabled: true,
            model: "test",
            modelInstalled: localModelStatus === "ready",
            root: "C:\\Yap",
          };
          if (command === "fallback_model_status") return {
            id: "nemotron-3.5-asr-streaming-0.6b-1120ms-int8",
            label: "Nemotron",
            modelsDir: "C:\\Yap\\models",
            status: localModelStatus,
          };
          if (command === "fallback_model_verify" && fallbackVerifyFails) {
            throw new Error("simulated local verification failure");
          }
          if (command === "primary_language_status") return primaryLanguageStatus;
          if (command === "confirm_primary_language") {
            languageCalls.push({ args, command });
            const languageBcp47 = (args as { languageBcp47?: string } | undefined)
              ?.languageBcp47;
            primaryLanguageStatus = {
              ...primaryLanguageStatus,
              confirmedLanguageBcp47: languageBcp47 ?? primaryLanguageStatus.confirmedLanguageBcp47,
              requiresConfirmation: false,
            };
            return primaryLanguageStatus;
          }
          if (command === "local_dictation_languages") {
            return ["en-US", "en-GB", "de-DE", "fr-FR", "es-ES"];
          }
          if (command === "live_language_routing_status") return liveLanguageRoutingStatus;
          if (command === "refresh_server_connection" && serverRefreshNeverSettles) {
            return new Promise(() => undefined);
          }
          if (command === "server_connection_status" || command === "refresh_server_connection") {
            return serverSnapshot;
          }
          if (command === "probe_local_server") {
            return localServerAvailable && serverSettingsState.baseUrl === null
              ? { authRequired: false, baseUrl: "http://127.0.0.1:18765" }
              : null;
          }
          if (command === "server_settings") return serverSettingsState;
          if (command === "set_server_settings") {
            serverCalls.push({ args, command });
            const settings = (args as { settings?: typeof serverSettingsState } | undefined)
              ?.settings;
            if (settings) serverSettingsState = settings;
            // The real save approves the origin and the next health check
            // reports Ready; collapse that to the settled snapshot here.
            if (serverSettingsState.enabled && serverSettingsState.baseUrl) {
              serverSnapshot = {
                ...serverSnapshot,
                capabilities: {
                  batchJobs: true,
                  jobStatus: true,
                  liveStreaming: false,
                  transcriptCorrection: false,
                  archivistIngestions: false,
                  analystAnswers: false,
                  coordinatorBundles: false,
                  auditorReports: false,
                  curatorProposals: false,
                  studentQuestions: false,
                },
                checkedAtMs: 1,
                errorCode: null,
                state: "ready",
              };
            }
            return serverSettingsState;
          }
          if (command === "server_identity_status") {
            return { configured: false, signedIn: false };
          }
          if (command === "live_status") return liveSnapshot;
          if (command === "record_live_hotkey") {
            shortcutCalls.push({ args, command });
            liveSnapshot = { ...liveSnapshot, hotkey: "Ctrl+Shift+D" };
            return liveSnapshot;
          }
          if (command === "record_live_paste_hotkey") {
            shortcutCalls.push({ args, command });
            liveSnapshot = { ...liveSnapshot, pasteHotkey: "Ctrl+Shift+Alt+P" };
            return liveSnapshot;
          }
          if (command === "reset_live_hotkey") {
            shortcutCalls.push({ args, command });
            liveSnapshot = { ...liveSnapshot, hotkey: "Ctrl+Shift+Space" };
            return liveSnapshot;
          }
          if (command === "reset_live_paste_hotkey") {
            shortcutCalls.push({ args, command });
            liveSnapshot = { ...liveSnapshot, pasteHotkey: "Ctrl+Shift+Alt+V" };
            return liveSnapshot;
          }
          if (command === "list_local_compute_targets") {
            return [{ id: "auto", label: "Auto", selected: true }];
          }
          if (
            command === "list_input_devices" ||
            command === "resolve_owned_live_transcript_paths"
          ) return [];
          if (command === "read_text_file" || command === "read_text_preview") return "";
          return undefined;
        },
      },
    });
  }, {
    configuredServerUrl: options.configuredServerUrl,
    fallbackVerifyFails: options.fallbackVerifyFails ?? false,
    localModelStatus: options.localModelStatus ?? "ready",
    localServerOffer: options.localServerOffer ?? false,
    primaryLanguageUnconfirmed: options.primaryLanguageUnconfirmed ?? false,
    serverRefreshNeverSettles: options.serverRefreshNeverSettles ?? false,
    state: serverState,
  });
}

export async function serverCalls(page: Page) {
  return page.evaluate(() =>
    (globalThis as unknown as {
      __queuedServerBoundaryTest: {
        serverCalls: Array<{ args: unknown; command: string }>;
      };
    }).__queuedServerBoundaryTest.serverCalls,
  );
}

export async function shortcutCalls(page: Page) {
  return page.evaluate(() =>
    (globalThis as unknown as {
      __queuedServerBoundaryTest: {
        shortcutCalls: Array<{ args: unknown; command: string }>;
      };
    }).__queuedServerBoundaryTest.shortcutCalls,
  );
}

export async function languageCalls(page: Page) {
  return page.evaluate(() =>
    (globalThis as unknown as {
      __queuedServerBoundaryTest: {
        languageCalls: Array<{ args: unknown; command: string }>;
      };
    }).__queuedServerBoundaryTest.languageCalls,
  );
}
