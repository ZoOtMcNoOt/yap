import { writeFileSync } from "node:fs";

import {
  assertRecordingRootEmpty,
  listRecordingArtifacts,
  ownedLiveSessionDeletion,
} from "./recording-artifact-ownership.js";
import { registerLiveSessionEventListeners } from "./live-session-event-listeners.js";

const RESTART_STOP_DELAYS_MS = Object.freeze([5, 25, 25, 25]);
const MINIMUM_TARGET_CAPTURE_MS = 30_000;
const MAXIMUM_TARGET_CAPTURE_MS = 30 * 60_000;
const AUTOMATED_STIMULUS_DELIVERY = "same-host-acoustic-playback";
const SPEECH_EVIDENCE_BOUNDARY = "checked-head-prepared-audio-short-boundaries";
export const EXPECTED_CLIPBOARD_FALLBACK_FEEDBACK =
  "Couldn't insert text here. Transcript copied; press Ctrl+V.";

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function boundedCaptureDuration(raw, enabled) {
  const fallback = enabled ? MINIMUM_TARGET_CAPTURE_MS : 750;
  if (raw === undefined || raw === "") return fallback;
  if (!/^[1-9][0-9]*$/.test(raw)) {
    throw new Error("YAP_HARDWARE_ACTIVE_CAPTURE_MS must be a positive integer.");
  }
  const value = Number.parseInt(raw, 10);
  const minimum = enabled ? MINIMUM_TARGET_CAPTURE_MS : 100;
  if (!Number.isSafeInteger(value) || value < minimum || value > MAXIMUM_TARGET_CAPTURE_MS) {
    throw new Error(
      `YAP_HARDWARE_ACTIVE_CAPTURE_MS must be between ${minimum} and ${MAXIMUM_TARGET_CAPTURE_MS}.`,
    );
  }
  return value;
}

export function createTargetClientLanguageRoutingHardwareGate({
  browser: configuredBrowser,
  browserProvider = () => configuredBrowser,
  environment = process.env,
  recordingRoot,
}) {
  const enabled = environment.YAP_TARGET_CLIENT_LANGUAGE_ROUTING_GATE === "1";
  const evidenceFile = environment.YAP_TARGET_CLIENT_UI_EVIDENCE_FILE;
  const activeCaptureMs = boundedCaptureDuration(
    environment.YAP_HARDWARE_ACTIVE_CAPTURE_MS,
    enabled,
  );
  const stimulusDelivery = environment.YAP_TARGET_CLIENT_STIMULUS_DELIVERY;
  const checkedHead = environment.YAP_CHECKED_HEAD;
  const preparedAudioEvidenceSha256 =
    environment.YAP_TARGET_CLIENT_PREPARED_AUDIO_EVIDENCE_SHA256;
  let restartCancellationEvidence = null;
  let verifiedBuildGitSha = null;

  if (enabled && !evidenceFile) {
    throw new Error("YAP_TARGET_CLIENT_UI_EVIDENCE_FILE is required for the target-client gate.");
  }
  if (enabled && stimulusDelivery !== AUTOMATED_STIMULUS_DELIVERY) {
    throw new Error(
      `YAP_TARGET_CLIENT_STIMULUS_DELIVERY must be ${AUTOMATED_STIMULUS_DELIVERY}.`,
    );
  }
  if (enabled && !/^[0-9a-f]{40}$/.test(checkedHead ?? "")) {
    throw new Error("YAP_CHECKED_HEAD must identify the exact target-client build.");
  }
  if (enabled && !/^[0-9a-f]{64}$/.test(preparedAudioEvidenceSha256 ?? "")) {
    throw new Error(
      "YAP_TARGET_CLIENT_PREPARED_AUDIO_EVIDENCE_SHA256 must identify passed prepared-audio evidence.",
    );
  }

  function requireActiveBrowser() {
    const activeBrowser = browserProvider();
    requireCondition(
      activeBrowser?.tauri,
      "The target-client gate requires an active WebdriverIO Tauri browser.",
    );
    return activeBrowser;
  }

  async function configureLanguageRouting() {
    if (!enabled) return null;
    const browser = requireActiveBrowser();
    await browser.tauri.switchWindow("main");
    return browser.tauri.execute(async ({ core }) => {
      const current = await core.invoke("live_language_routing_status");
      const german = current.automaticLanguages.find(({ languageCode }) => languageCode === "de");
      const selected = german?.locales.includes("de-DE") ? "de-DE" : german?.locales[0];
      if (!selected) throw new Error("The target-client gate could not select its German alternate.");
      return core.invoke("set_live_language_routing", {
        catalogRevision: current.catalogRevision,
        enabledAlternateLocales: [selected],
      });
    });
  }

  async function assertCheckedBuildIdentity() {
    if (!enabled) return null;
    const browser = requireActiveBrowser();
    await browser.tauri.switchWindow("main");
    const buildGitSha = await browser.tauri.execute(({ core }) =>
      core.invoke("wdio_build_git_sha"));
    requireCondition(
      buildGitSha === checkedHead,
      "The running target-client binary was not built from YAP_CHECKED_HEAD.",
    );
    verifiedBuildGitSha = buildGitSha;
    return buildGitSha;
  }

  async function assertResidentRuntimeReady(configuredRouting) {
    if (!enabled) return;
    const browser = requireActiveBrowser();
    await browser.tauri.switchWindow("main");
    const status = await browser.tauri.execute(async ({ core }) => ({
      acousticLanguageDetector: await core.invoke("acoustic_language_detector_status"),
      languageRouting: await core.invoke("live_language_routing_status"),
      model: await core.invoke("fallback_model_status"),
      serverConnection: await core.invoke("server_connection_status"),
      serverSettings: await core.invoke("server_settings"),
      silero: await core.invoke("silero_vad_status"),
    }));
    requireCondition(status.model.status === "ready", "Nemotron was not ready for qualification.");
    requireCondition(status.silero.status === "ready", "Silero was not ready for qualification.");
    requireCondition(
      status.acousticLanguageDetector.status === "ready",
      "AmberNet was not ready for qualification.",
    );
    requireCondition(
      status.languageRouting.preferenceIssue === null,
      "The language-routing preference was invalid.",
    );
    requireCondition(
      status.languageRouting.enabledLocales.length > 1 && configuredRouting?.enabledLocales.length > 1,
      "The target-client gate requires a primary locale and a German alternate.",
    );
    requireCondition(
      status.serverSettings.schemaVersion === 1
        && status.serverSettings.enabled === false
        && status.serverSettings.baseUrl === null
        && status.serverConnection.state === "disabled",
      "The target-client gate requires an isolated profile with the server disabled and no base URL.",
    );
  }

  async function startResponsivenessSampler() {
    if (!enabled) return null;
    const browser = requireActiveBrowser();
    await browser.tauri.switchWindow("live-overlay");
    return browser.tauri.execute((_tauri, tickMs) => {
      if (globalThis.__yapUiResponsivenessSampler) {
        throw new Error("UI responsiveness sampler was already active.");
      }
      const delays = [];
      let previous = performance.now();
      const timer = setInterval(() => {
        const now = performance.now();
        delays.push(Math.max(0, now - previous - tickMs));
        previous = now;
      }, tickMs);
      globalThis.__yapUiResponsivenessSampler = { delays, tickMs, timer };
      return tickMs;
    }, 10);
  }

  async function stopResponsivenessSampler() {
    if (!enabled) return null;
    const browser = requireActiveBrowser();
    await browser.tauri.switchWindow("live-overlay");
    return browser.tauri.execute(() => {
      const state = globalThis.__yapUiResponsivenessSampler;
      if (!state) throw new Error("UI responsiveness sampler was unavailable.");
      clearInterval(state.timer);
      delete globalThis.__yapUiResponsivenessSampler;
      const sorted = [...state.delays].sort((left, right) => left - right);
      const nearestRank = (percentile) => {
        if (sorted.length === 0) return 0;
        const rank = Math.ceil(sorted.length * percentile / 100);
        return sorted[Math.max(0, rank - 1)];
      };
      return {
        maximumDelayMs: sorted.at(-1) ?? 0,
        p50DelayMs: nearestRank(50),
        p95DelayMs: nearestRank(95),
        p99DelayMs: nearestRank(99),
        sampleCount: sorted.length,
        tickMs: state.tickMs,
      };
    });
  }

  async function runRestartCancellation({ classifyReadiness, nativeReadiness }) {
    requireCondition(enabled, "The target-client restart gate is not enabled.");
    const browser = requireActiveBrowser();
    await configureLanguageRouting();
    const readiness = classifyReadiness(await nativeReadiness());
    requireCondition(
      readiness.action !== "skip",
      `Target-client native readiness failed: ${readiness.reason}.`,
    );

    await browser.tauri.switchWindow("main");
    const listenerCount = await browser.tauri.execute(
      registerLiveSessionEventListeners,
      { includeSessions: true, target: "main" },
    );

    const cycles = [];
    let handledSaved = 0;
    try {
      requireCondition(listenerCount === 2, "The restart gate did not install both lifecycle listeners.");
      for (const [cycle, stopDelayMs] of RESTART_STOP_DELAYS_MS.entries()) {
        const runStartedAtMs = Date.now();
        const outcome = await browser.tauri.execute(async ({ core }, delayMs) => {
          const start = core.invoke("start_live_session");
          await new Promise((resolve) => setTimeout(resolve, delayMs));
          const stop = core.invoke("stop_live_session");
          const [started, stopped] = await Promise.allSettled([start, stop]);
          return {
            startError: started.status === "rejected" ? String(started.reason) : null,
            startStatus: started.status === "fulfilled" ? started.value.status : null,
            stopError: stopped.status === "rejected" ? String(stopped.reason) : null,
            stopStatus: stopped.status === "fulfilled" ? stopped.value.status : null,
          };
        }, stopDelayMs);
        requireCondition(outcome.startError === null, `Early-start cycle ${cycle + 1} failed to start.`);
        requireCondition(outcome.stopError === null, `Early-start cycle ${cycle + 1} failed to stop.`);

        await browser.waitUntil(async () => {
          await browser.tauri.switchWindow("main");
          const status = await browser.tauri.execute(({ core }) => core.invoke("live_status"));
          return status.status === "idle";
        }, {
          interval: 50,
          timeout: 30_000,
          timeoutMsg: `early-stop cycle ${cycle + 1} did not recover to idle`,
        });
        const recovered = await browser.tauri.execute(({ core }) => core.invoke("live_status"));
        requireCondition(recovered.status === "idle", `Early-stop cycle ${cycle + 1} was not idle.`);
        requireCondition(recovered.error === null, `Early-stop cycle ${cycle + 1} reported an error.`);
        requireCondition(
          recovered.transcriptionDegraded === false,
          `Early-stop cycle ${cycle + 1} degraded transcription.`,
        );

        if (listRecordingArtifacts(recordingRoot).length > 0) {
          await browser.waitUntil(async () => browser.tauri.execute(
            () => globalThis.__yapLiveSessionEventListeners?.saved.length ?? 0,
          ).then((count) => count > handledSaved), {
            interval: 25,
            timeout: 5_000,
            timeoutMsg: `early-stop cycle ${cycle + 1} retained audio without a saved event`,
          });
        }
        const saved = await browser.tauri.execute(() =>
          globalThis.__yapLiveSessionEventListeners?.saved ?? []);
        for (const candidate of saved.slice(handledSaved)) {
          const deletion = ownedLiveSessionDeletion(candidate, recordingRoot, { runStartedAtMs });
          await browser.tauri.execute(
            ({ core }, request) => core.invoke(request.command, request.identity),
            deletion,
          );
        }
        handledSaved = saved.length;
        assertRecordingRootEmpty(recordingRoot);
        cycles.push({ ...outcome, recoveredStatus: recovered.status });
      }

      const sessions = await browser.tauri.execute(() =>
        globalThis.__yapLiveSessionEventListeners?.sessions ?? []);
      requireCondition(
        sessions.some(({ status }) => status === "armed"),
        "The restart gate never observed an armed local session.",
      );
      requireCondition(sessions.every(({ error }) => error === null), "A restart event reported an error.");
      requireCondition(
        sessions.every(({ transcriptionDegraded }) => !transcriptionDegraded),
        "A restart event reported degraded transcription.",
      );
      requireCondition(
        cycles.every(({ recoveredStatus }) => recoveredStatus === "idle"),
        "Not every restart cycle recovered to idle.",
      );
      restartCancellationEvidence = {
        cycleCount: cycles.length,
        earlyStopDelaysMs: [...RESTART_STOP_DELAYS_MS],
        finalStatus: cycles.at(-1)?.recoveredStatus ?? null,
        savedSessionsDeleted: handledSaved,
      };
    } finally {
      await browser.tauri.switchWindow("main");
      const cleanupCounts = [];
      cleanupCounts.push(await browser.tauri.execute(() =>
        globalThis.__yapLiveSessionEventListeners?.cleanup?.() ?? 0));
      cleanupCounts.push(await browser.tauri.execute(() =>
        globalThis.__yapLiveSessionEventListeners?.cleanup?.() ?? 0));
      requireCondition(
        cleanupCounts[0] === 2 && cleanupCounts[1] === 0,
        "Restart lifecycle listeners did not clean up idempotently.",
      );
    }
    assertRecordingRootEmpty(recordingRoot);
  }

  function assertRenderedCaptureEvidence(input) {
    if (!enabled) return;
    const { evidence, statuses, uiResponsiveness } = input;
    requireCondition(
      statuses.some((status) => status === "listening" || status === "speaking"),
      "The target-client run never observed active microphone capture.",
    );
    requireCondition(
      evidence.levels.some(({ level }) => Number.isFinite(level)),
      "The target-client run did not observe a finite microphone level.",
    );
    requireCondition(
      evidence.mainSessions.some(({ route }) => route === "localFallback"),
      "The target-client run did not use the local fallback route.",
    );
    requireCondition(
      evidence.mainSessions.every(({ transcriptionDegraded }) => !transcriptionDegraded),
      "The target-client run reported degraded transcription.",
    );
    const feedbackSessions = evidence.mainSessions.filter(({ error }) => error !== null);
    requireCondition(
      feedbackSessions.every(({ error, status }) =>
        status === "idle" && error === EXPECTED_CLIPBOARD_FALLBACK_FEEDBACK),
      "The target-client run did not report only the expected idle clipboard fallback.",
    );
    requireCondition(
      uiResponsiveness.sampleCount > activeCaptureMs / 20,
      "The UI responsiveness sampler missed too many scheduled observations.",
    );
    requireCondition(uiResponsiveness.p95DelayMs <= 50, "UI responsiveness p95 exceeded 50 ms.");
    requireCondition(uiResponsiveness.maximumDelayMs <= 250, "UI responsiveness max exceeded 250 ms.");
  }

  function publishEvidence(input) {
    if (!enabled) return;
    const { configuredRouting, evidence, statuses, uiResponsiveness } = input;
    requireCondition(
      restartCancellationEvidence?.cycleCount === RESTART_STOP_DELAYS_MS.length,
      "Restart/cancellation evidence was incomplete.",
    );
    requireCondition(
      verifiedBuildGitSha === checkedHead,
      "The target-client build identity was not verified.",
    );
    const aggregate = {
      schemaVersion: 4,
      activeCaptureMs,
      buildGitSha: verifiedBuildGitSha,
      languageRoutingEnabledLocales: configuredRouting?.enabledLocales ?? [],
      levelEventCount: evidence.levels.length,
      lifecycleStatuses: statuses,
      preparedAudioEvidenceSha256,
      renderedUiResponsiveness: uiResponsiveness,
      restartCancellation: restartCancellationEvidence,
      route: evidence.mainSessions.find(({ route }) => route === "localFallback")?.route ?? null,
      speechEvidenceBoundary: SPEECH_EVIDENCE_BOUNDARY,
      stimulusLicense: environment.YAP_TARGET_CLIENT_STIMULUS_LICENSE ?? null,
      stimulusSha256: environment.YAP_TARGET_CLIENT_STIMULUS_SHA256 ?? null,
      stimulusDelivery,
      targetClientGate: true,
      transcriptTextRecorded: false,
    };
    writeFileSync(evidenceFile, `${JSON.stringify(aggregate, null, 2)}\n`, {
      encoding: "utf8",
      flag: "wx",
    });
  }

  return Object.freeze({
    activeCaptureMs,
    assertCheckedBuildIdentity,
    assertResidentRuntimeReady,
    assertRenderedCaptureEvidence,
    configureLanguageRouting,
    enabled,
    publishEvidence,
    runRestartCancellation,
    startResponsivenessSampler,
    stopResponsivenessSampler,
  });
}
