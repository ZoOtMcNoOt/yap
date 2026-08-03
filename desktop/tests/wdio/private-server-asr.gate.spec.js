import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
  realpathSync,
  statSync,
} from "node:fs";
import path from "node:path";

import {
  canonicalPcm16Mono16KhzWav,
  isValidInFlightRemotePipeline,
  matchPublishedRemoteHistoryEntry,
  matchesEnabledLoopbackServerSettings,
  matchesVerifiedHistoryDialog,
  readCanonicalPcm16Mono16KhzWav,
  repeatedPcm,
  settleSshTunnelChild,
} from "./private-server-asr-gate-support.js";
import {
  loadPrivateServerSshProfile,
  privateServerSshEnvironment,
  privateServerTunnelSshInvocation,
} from "../../../verification/private-server-ssh-profile.mjs";
import {
  writeExclusivePrivateFile,
} from "../../../verification/private-gate-artifacts.mjs";

const tunnelHost = "127.0.0.1";
const tunnelPort = 18765;
const meetingTranscriptionProfile = "meeting-transcription";
const tunnelProcesses = [];
const tunnelProcessEntries = new WeakMap();
let tunnelProcess;

function requireEnvironment(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required for the private-server ASR gate.`);
  return value;
}

async function invoke(command, args = {}) {
  const result = await browser.executeAsync((commandName, commandArgs, done) => {
    const invokeCommand = window.__TAURI__?.core?.invoke;
    if (typeof invokeCommand !== "function") {
      done({ error: "Tauri invoke bridge unavailable", ok: false });
      return;
    }
    invokeCommand(commandName, commandArgs).then(
      (value) => done({ ok: true, value }),
      (error) => done({
        error: typeof error === "object" && error && "code" in error
          ? String(error.code)
          : "native command failed",
        ok: false,
      }),
    );
  }, command, args);
  if (!result?.ok) {
    throw new Error(`Tauri command ${command} failed: ${result?.error ?? "unknown error"}`);
  }
  return result.value;
}

async function waitForConnectionState(expectedState, label) {
  let connection;
  await browser.waitUntil(
    async () => {
      connection = await invoke("server_connection_status");
      return connection.state === expectedState;
    },
    {
      interval: 100,
      timeout: 15_000,
      timeoutMsg: `The private-server connection did not ${label} within 15 seconds.`,
    },
  );
  return connection;
}

function canonicalPath(value) {
  return path.resolve(realpathSync.native(value));
}

async function healthIsReachable() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 750);
  try {
    const response = await fetch(`http://${tunnelHost}:${tunnelPort}/v1/health`, {
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

function canonicalWavSha256(pcm) {
  return createHash("sha256")
    .update(canonicalPcm16Mono16KhzWav(pcm))
    .digest("hex");
}

function activeGateProfile() {
  const profile = requireEnvironment("YAP_PRIVATE_SERVER_ASR_GATE_PROFILE");
  if (!["dictation", meetingTranscriptionProfile].includes(profile)) {
    throw new Error(`Unsupported private-server ASR gate profile: ${profile}`);
  }
  return profile;
}

async function runLanguagePreflightExecution(catalog, fixturePath, checkedHead) {
  const capability = catalog?.languagePreflight;
  expect(capability?.componentId).toBe("ambernet-batch-language-preflight");
  expect(capability?.policy).toMatchObject({
    sampleRateHz: 16_000,
    channelCount: 1,
    sampleWidthBytes: 2,
    minimumSourceSamples: 480_000,
    maximumWindows: 5,
    maximumWindowSamples: 96_000,
    minimumVoicedSamplesPerWindow: 51_200,
    userConfirmationRequired: true,
  });
  expect(capability?.transport?.mediaType)
    .toBe("application/vnd.yap.lid-preflight.v1+octet-stream");

  const sourceSamples = capability.policy.minimumSourceSamples;
  const windowSamples = capability.policy.maximumWindowSamples;
  expect(sourceSamples).toBe(windowSamples * capability.policy.maximumWindows);
  const sourcePcm = repeatedPcm(
    readCanonicalPcm16Mono16KhzWav(fixturePath),
    sourceSamples * capability.policy.sampleWidthBytes,
  );
  const sourcePcmSha256 = createHash("sha256").update(sourcePcm).digest("hex");
  const probes = [];
  const probePcm = [];
  const expectedWavSha256 = [];
  for (let index = 0; index < capability.policy.maximumWindows; index += 1) {
    const sourceStartSample = index * windowSamples;
    const sourceEndSample = sourceStartSample + windowSamples;
    const pcm = sourcePcm.subarray(
      sourceStartSample * capability.policy.sampleWidthBytes,
      sourceEndSample * capability.policy.sampleWidthBytes,
    );
    probePcm.push(pcm);
    expectedWavSha256.push(canonicalWavSha256(pcm));
    probes.push({
      index,
      sourceStartSample,
      sourceEndSample,
      voicedSamples: windowSamples,
      pcmByteLength: pcm.length,
      pcmSha256: createHash("sha256").update(pcm).digest("hex"),
      vadIntervals: [{ startSample: sourceStartSample, endSampleExclusive: sourceEndSample }],
    });
  }
  const requestId = `lid-gate-${checkedHead.slice(0, 24)}`;
  const manifest = Buffer.from(JSON.stringify({
    schemaVersion: 1,
    requestId,
    sourceSamples,
    sourcePcmSha256,
    catalogRevision: catalog.catalogRevision,
    policyRevision: capability.policy.revision,
    probes,
  }));
  const length = Buffer.alloc(4);
  length.writeUInt32BE(manifest.length);
  const body = Buffer.concat([length, manifest, ...probePcm]);
  expect(body.length).toBeLessThanOrEqual(capability.transport.maximumBodyBytes);

  const response = await fetch(`http://${tunnelHost}:${tunnelPort}/v1/lid/preflight`, {
    body,
    headers: { "content-type": capability.transport.mediaType },
    method: "POST",
    redirect: "error",
    signal: AbortSignal.timeout(
      (capability.transport.maximumResponseSeconds + 5) * 1_000,
    ),
  });
  const responseBytes = Buffer.from(await response.arrayBuffer());
  expect(responseBytes.length).toBeLessThanOrEqual(64 * 1024);
  const result = JSON.parse(responseBytes.toString("utf8"));
  expect(response.ok).toBe(true);
  expect(result).toMatchObject({
    schemaVersion: 1,
    requestId,
    sourceSamples,
    sourcePcmSha256,
    catalogRevision: catalog.catalogRevision,
    userConfirmationRequired: true,
    component: {
      id: capability.componentId,
      runtime: capability.runtime,
      model: capability.model,
      policyRevision: capability.policy.revision,
      scoreSemantics: capability.policy.scoreSemantics,
    },
  });
  expect(["manual", "suggestion"]).toContain(result.status);
  expect(typeof result.reason).toBe("string");
  expect(result.reason.length).toBeGreaterThan(0);
  expect(result.observations).toHaveLength(capability.policy.maximumWindows);
  for (const [index, observation] of result.observations.entries()) {
    expect(observation).toMatchObject({
      index,
      probeSha256: expectedWavSha256[index],
      sourceStartSample: probes[index].sourceStartSample,
      sourceEndSample: probes[index].sourceEndSample,
      voicedSamples: windowSamples,
    });
    expect(typeof observation.rawLabel).toBe("string");
    expect(observation.rawLabel.length).toBeGreaterThan(0);
    expect(Number.isFinite(observation.topScore)).toBe(true);
    expect(Number.isFinite(observation.scoreMargin)).toBe(true);
  }
  return {
    componentId: result.component.id,
    modelId: result.component.model.id,
    modelRevision: result.component.model.revision,
    observationCount: result.observations.length,
    policyRevision: result.component.policyRevision,
    requestIdSha256: createHash("sha256").update(requestId).digest("hex"),
    resultStatus: result.status,
    runtimeCpuOnly: result.component.runtime.cpuOnly,
    runtimePythonVersion: result.component.runtime.pythonVersion,
    sourcePcmSha256,
  };
}

async function waitForHealth(expected, child, label) {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    if (child && child.exitCode !== null) {
      throw new Error(`The gate-owned SSH forward exited before it could ${label}.`);
    }
    if (await healthIsReachable() === expected) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`The gate-owned SSH forward did not ${label} within 15 seconds.`);
}

async function startActiveTunnel() {
  if (tunnelProcess) {
    throw new Error("A gate-owned SSH forward is already active.");
  }
  if (await healthIsReachable()) {
    throw new Error("Port 18765 was already reachable before the gate-owned SSH forward.");
  }
  const invocation = privateServerTunnelSshInvocation(
    loadPrivateServerSshProfile(),
  );
  const child = spawn(
    invocation.executable,
    invocation.args,
    {
      env: privateServerSshEnvironment(),
      stdio: "ignore",
      windowsHide: true,
    },
  );
  if (!Number.isSafeInteger(child.pid) || child.pid <= 0) {
    if (child.exitCode === null) child.kill();
    throw new Error("The gate-owned SSH forward did not expose its process identity.");
  }
  const processEntry = {
    pid: child.pid,
    startedAt: new Date().toISOString(),
    exitedAt: null,
  };
  tunnelProcesses.push(processEntry);
  tunnelProcessEntries.set(child, processEntry);
  tunnelProcess = child;
  child.once("error", () => {});
  try {
    await waitForHealth(true, child, "become reachable");
  } catch (error) {
    await stopActiveTunnel();
    throw error;
  }
  return child;
}

async function stopTunnel(child) {
  await settleSshTunnelChild(child);
  await waitForHealth(false, undefined, "become unreachable");
  const processEntry = tunnelProcessEntries.get(child);
  if (!processEntry) {
    throw new Error("The stopped SSH forward was absent from the owned-process ledger.");
  }
  processEntry.exitedAt = new Date().toISOString();
}

async function stopActiveTunnel() {
  const owned = tunnelProcess;
  if (!owned) return;
  await stopTunnel(owned);
  if (tunnelProcess === owned) tunnelProcess = undefined;
}

function publishTunnelProcessLedger() {
  if (
    tunnelProcesses.length !== 2
    || tunnelProcesses.some(({ pid, startedAt, exitedAt }) => (
      !Number.isSafeInteger(pid)
      || pid <= 0
      || !Number.isFinite(Date.parse(startedAt))
      || !Number.isFinite(Date.parse(exitedAt))
      || Date.parse(exitedAt) < Date.parse(startedAt)
    ))
    || new Set(tunnelProcesses.map(({ pid }) => pid)).size !== tunnelProcesses.length
  ) {
    throw new Error("The private-server gate did not retire exactly two owned SSH forwards.");
  }
  const evidenceDirectory = requireEnvironment("YAP_PRIVATE_SERVER_ASR_GATE_EVIDENCE_DIR");
  writeExclusivePrivateFile(
    path.join(evidenceDirectory, "tunnel-process-ledger.json"),
    Buffer.from(`${JSON.stringify({
      schemaVersion: 1,
      checkedHead: requireEnvironment("YAP_CHECKED_HEAD"),
      startedProcessCount: tunnelProcesses.length,
      exitedProcessCount: tunnelProcesses.length,
      processes: tunnelProcesses,
      status: "passed",
    }, null, 2)}\n`),
  );
}

describe("checked-head private-server ASR gate", () => {
  before(async () => {
    await startActiveTunnel();
  });

  after(async () => {
    await stopActiveTunnel();
    publishTunnelProcessLedger();
  });

  it("imports through the real tunneled GB10 worker and opens the verified History result", async () => {
    await browser.tauri.switchWindow("main");

    const checkedHead = requireEnvironment("YAP_CHECKED_HEAD");
    const expectedOrigin = requireEnvironment("YAP_PRIVATE_SERVER_ASR_GATE_BASE_URL");
    const evidenceDirectory = requireEnvironment("YAP_PRIVATE_SERVER_ASR_GATE_EVIDENCE_DIR");
    const fixturePath = requireEnvironment("YAP_WDIO_PICKER_PATH");
    const fixtureSha256 = requireEnvironment("YAP_PRIVATE_SERVER_ASR_GATE_FIXTURE_SHA256");
    const expectedModelId = requireEnvironment("YAP_PRIVATE_SERVER_ASR_GATE_MODEL_ID");
    const expectedModelRevision = requireEnvironment(
      "YAP_PRIVATE_SERVER_ASR_GATE_MODEL_REVISION",
    );
    const appDataRoot = canonicalPath(requireEnvironment("YAP_APP_DATA_DIR"));
    const timeoutMs = Number(
      requireEnvironment("YAP_PRIVATE_SERVER_ASR_GATE_TIMEOUT_MS"),
    );

    expect(await invoke("wdio_build_git_sha")).toBe(checkedHead);
    const settings = await invoke("server_settings");
    expect(matchesEnabledLoopbackServerSettings(settings, expectedOrigin)).toBe(true);
    await invoke("refresh_server_connection");
    const connection = await waitForConnectionState("ready", "become ready");
    expect(connection.capabilities).toEqual({
      batchJobs: true,
      jobStatus: true,
      liveStreaming: false,
    });

    const profile = activeGateProfile();
    const meetingProfile = profile === meetingTranscriptionProfile;
    const catalog = await invoke("server_asr_capabilities");
    expect(catalog?.catalogRevision).toMatch(/^[0-9a-f]{64}$/);
    const languagePreflightExecution = meetingProfile
      ? undefined
      : await runLanguagePreflightExecution(catalog, fixturePath, checkedHead);
    const created = await invoke("recording_jobs_pick_imports", {
      languageBcp47: "en-US",
      catalogRevision: catalog.catalogRevision,
    });
    expect(created).toHaveLength(1);
    expect(created[0].status).toBe("preflighting");
    expect(isValidInFlightRemotePipeline(created[0])).toBe(true);
    expect(created[0].languageDecision).toEqual({
      mode: "fixed",
      languageBcp47: "en-US",
      disposition: "primary",
    });
    expect(canonicalPath(created[0].sourcePath)).toBe(canonicalPath(fixturePath));
    const createdJob = created[0];
    const clientJobId = createdJob.id;
    const observedStatuses = new Set([createdJob.status]);
    const observedPreprocessingStates = new Set([createdJob.pipeline.preprocessing]);
    let history;
    let completedJobRetiredFromRecoverableQueue = false;
    let terminalFailure;

    await stopActiveTunnel();
    const interruptedConnection = await invoke("refresh_server_connection");
    expect(interruptedConnection.state).toBe("retrying");
    expect((await invoke("server_settings")).baseUrl).toBe(expectedOrigin);
    const interruptedSnapshot = await invoke("recording_jobs_snapshot");
    const interruptedJob = interruptedSnapshot.find((candidate) => candidate.id === clientJobId);
    expect(interruptedJob).toBeDefined();
    expect(isValidInFlightRemotePipeline(interruptedJob)).toBe(true);
    observedStatuses.add(interruptedJob.status);
    observedPreprocessingStates.add(interruptedJob.pipeline.preprocessing);

    await startActiveTunnel();
    await invoke("refresh_server_connection");
    const restoredConnection = await waitForConnectionState("ready", "recover after tunnel restart");
    expect((await invoke("server_settings")).baseUrl).toBe(expectedOrigin);

    await browser.waitUntil(
      async () => {
        const snapshot = await invoke("recording_jobs_snapshot");
        const job = snapshot.find((candidate) => candidate.id === clientJobId);
        if (job) {
          observedStatuses.add(job.status);
          observedPreprocessingStates.add(job.pipeline.preprocessing);
        }
        if (job && ["failed", "cancelled"].includes(job.status)) {
          terminalFailure = new Error(
            `The private-server ASR job reached ${job.status} (${job.error ?? "no private-safe error projection"}).`,
          );
          return true;
        }
        const catalog = await invoke("history_catalog");
        if (catalog.maintenanceWarnings.length > 0) {
          terminalFailure = new Error(
            `The private-server History catalog reported maintenance warnings: ${catalog.maintenanceWarnings.join("; ")}`,
          );
          return true;
        }
        history = matchPublishedRemoteHistoryEntry(createdJob, catalog);
        completedJobRetiredFromRecoverableQueue = !job && Boolean(history);
        return completedJobRetiredFromRecoverableQueue;
      },
      {
        interval: 1_000,
        timeout: timeoutMs,
        timeoutMsg: "The checked-head private-server ASR job did not complete within the gate timeout.",
      },
    );

    if (terminalFailure) throw terminalFailure;
    expect(createdJob.route).toBe("serverBatch");
    expect(completedJobRetiredFromRecoverableQueue).toBe(true);
    expect(history).toBeDefined();
    expect(history.warning).toBeNull();
    expect(canonicalPath(history.sourcePath)).toBe(canonicalPath(fixturePath));

    const transcriptPath = canonicalPath(history.outputPath);
    const remoteRoot = path.join(appDataRoot, "remote-jobs");
    const transcriptRelative = path.relative(remoteRoot, transcriptPath);
    expect(transcriptRelative.startsWith("..")).toBe(false);
    expect(path.isAbsolute(transcriptRelative)).toBe(false);
    expect(lstatSync(transcriptPath).isSymbolicLink()).toBe(false);
    expect(statSync(transcriptPath).isFile()).toBe(true);

    const resultPath = path.join(path.dirname(transcriptPath), "result.json");
    const resultMetadata = lstatSync(resultPath);
    expect(resultMetadata.isSymbolicLink()).toBe(false);
    expect(resultMetadata.isFile()).toBe(true);
    const resultBytes = readFileSync(resultPath);
    const result = JSON.parse(resultBytes.toString("utf8"));
    expect(result.sessionId).toBe(history.sessionId);
    expect(result.revision).toBe(1);
    expect(result.authority).toBe("server_authoritative");
    if (meetingProfile) {
      expect(["complete", "partial"]).toContain(result.status);
    } else {
      expect(result.status).toBe("complete");
    }
    expect(result.transcript.trim().length).toBeGreaterThan(0);
    expect(result.language?.languageBcp47).toBe(createdJob.languageDecision.languageBcp47);
    const expectedModel = result.modelProvenance.find(
      ({ modelId }) => modelId === expectedModelId,
    );
    expect(expectedModel).toMatchObject({
      modelId: expectedModelId,
      revision: expectedModelRevision,
    });
    if (meetingProfile) {
      expect(expectedModel.calibrationRevision).toBe(
        requireEnvironment("YAP_PRIVATE_SERVER_ASR_GATE_RUNTIME_LOCK_SHA256"),
      );
    } else {
      expect(expectedModel.calibrationRevision).toBe("asr-not-applicable");
    }

    const captureManifestPath = path.join(
      path.dirname(path.dirname(transcriptPath)),
      "capture-manifest.json",
    );
    const captureManifestMetadata = lstatSync(captureManifestPath);
    expect(captureManifestMetadata.isSymbolicLink()).toBe(false);
    expect(captureManifestMetadata.isFile()).toBe(true);
    const captureManifestBytes = readFileSync(captureManifestPath);
    expect(createHash("sha256").update(captureManifestBytes).digest("hex"))
      .toBe(result.captureManifestSha256);
    const captureManifest = JSON.parse(captureManifestBytes.toString("utf8"));
    expect(captureManifest.source?.sha256).toBe(fixtureSha256);
    expect(captureManifest.preprocessing?.normalization?.status).toBe("complete");
    expect(["complete", "error"]).toContain(captureManifest.preprocessing?.vad?.status);
    expect(captureManifest.languageDecision).toEqual(createdJob.languageDecision);
    expect(captureManifest.chunks?.length).toBeGreaterThan(0);

    const resultArtifactSha256 = createHash("sha256").update(resultBytes).digest("hex");
    let speakerResult;
    let speakerResultArtifactSha256;
    let speakerTranscript;
    if (meetingProfile) {
      expect(history.speakerTranscriptAvailable).toBe(true);
      const speakerResultPath = path.join(path.dirname(transcriptPath), "speaker-result.json");
      const speakerResultMetadata = lstatSync(speakerResultPath);
      expect(speakerResultMetadata.isSymbolicLink()).toBe(false);
      expect(speakerResultMetadata.isFile()).toBe(true);
      const speakerResultBytes = readFileSync(speakerResultPath);
      speakerResultArtifactSha256 = createHash("sha256")
        .update(speakerResultBytes)
        .digest("hex");
      expect(speakerResultArtifactSha256).toBe(result.speakerResultSha256);
      speakerResult = JSON.parse(speakerResultBytes.toString("utf8"));
      expect(speakerResult).toMatchObject({
        authority: result.authority,
        revision: result.revision,
        runtimeLockSha256: requireEnvironment(
          "YAP_PRIVATE_SERVER_ASR_GATE_RUNTIME_LOCK_SHA256",
        ),
        sessionId: result.sessionId,
        status: result.status,
      });
      expect(speakerResult.speakerTurns.length).toBeGreaterThan(0);
      speakerTranscript = await invoke("history_speaker_transcript", {
        identity: {
          origin: "remote",
          outputPath: history.outputPath,
          sessionId: history.sessionId,
        },
      });
      expect(speakerTranscript.sessionId).toBe(history.sessionId);
      expect(speakerTranscript.sourceResultSha256).toBe(resultArtifactSha256);
      expect(speakerTranscript.turns).toHaveLength(speakerResult.speakerTurns.length);
    }

    const reviewButton = await browser.$(
      `[aria-label=${JSON.stringify(`Review recording ${history.name}`)}]`,
    );
    await reviewButton.waitForDisplayed({ timeout: 15_000 });
    await reviewButton.click();
    await browser.waitUntil(
      async () => {
        if (meetingProfile) {
          const firstTurn = speakerTranscript.turns[0];
          return browser.execute((name, speakerId, turnText) => (
            [...document.querySelectorAll('[role="dialog"][data-state="open"]')].some(
              (dialog) => (
                dialog.querySelector('[data-slot="dialog-title"]')?.textContent?.trim() === name
                && dialog.querySelector('[data-testid="speaker-attributed-transcript"]')
                  ?.textContent?.includes(speakerId.replace("speaker-", "Speaker "))
                && dialog.querySelector('[data-testid="speaker-attributed-transcript"]')
                  ?.textContent?.includes(turnText)
              ),
            )
          ), history.name, firstTurn.speakerId, firstTurn.text);
        }
        const dialogs = await browser.execute(() => (
          [...document.querySelectorAll('[role="dialog"][data-state="open"]')].map((dialog) => ({
            label: dialog.querySelector('[data-slot="dialog-title"]')?.textContent?.trim() ?? "",
            transcript: dialog.querySelector("pre")?.textContent?.trim() ?? "",
          }))
        ));
        return matchesVerifiedHistoryDialog(
          dialogs,
          history.name,
          result.transcript.trim(),
        );
      },
      {
        interval: 250,
        timeout: 15_000,
        timeoutMsg: meetingProfile
          ? "History did not render the verified speaker-attributed transcript."
          : "History did not open the verified server-authoritative transcript.",
      },
    );

    if (meetingProfile) {
      const speakerIds = new Set(speakerTranscript.turns.map(({ speakerId }) => speakerId));
      writeExclusivePrivateFile(
        path.join(evidenceDirectory, "meeting-transcription-vertical.json"),
        Buffer.from(`${JSON.stringify({
          schemaVersion: 1,
          checkedHead,
          profile,
          fixtureSha256,
          fixtureDurationMs: Number(requireEnvironment(
            "YAP_PRIVATE_SERVER_ASR_GATE_FIXTURE_DURATION_MS",
          )),
          clientJobId,
          clientRoute: createdJob.route,
          serverOrigin: expectedOrigin,
          sessionId: result.sessionId,
          resultRevision: result.revision,
          resultAuthority: result.authority,
          resultStatus: result.status,
          resultArtifactSha256,
          transcriptBytes: Buffer.byteLength(result.transcript, "utf8"),
          modelId: expectedModel.modelId,
          modelRevision: expectedModel.revision,
          speakerResultRevision: speakerResult.revision,
          speakerResultArtifactSha256,
          speakerResultSourceSha256: speakerTranscript.sourceResultSha256,
          speakerTurnCount: speakerTranscript.turns.length,
          speakerCount: speakerIds.size,
          runtimeLockSha256: speakerResult.runtimeLockSha256,
          completedJobRetiredFromRecoverableQueue,
          historyOpenedVerifiedResult: true,
          historyLoadedSpeakerTranscript: true,
          historyRenderedSpeakerTranscript: true,
          status: "passed",
        }, null, 2)}\n`),
      );
      return;
    }

    writeExclusivePrivateFile(
      path.join(evidenceDirectory, "native-vertical-slice.json"),
      Buffer.from(`${JSON.stringify({
        schemaVersion: 3,
        checkedHead,
        fixtureSha256,
        clientJobId,
        clientRoute: createdJob.route,
        serverOrigin: expectedOrigin,
        sessionId: result.sessionId,
        resultRevision: result.revision,
        resultAuthority: result.authority,
        resultArtifactSha256,
        transcriptBytes: Buffer.byteLength(result.transcript, "utf8"),
        modelProvenance: result.modelProvenance,
        observedStatuses: [...observedStatuses].sort(),
        observedPreprocessingStates: [...observedPreprocessingStates].sort(),
        captureManifestSha256: result.captureManifestSha256,
        durablePreprocessingManifestVerified: true,
        completedJobRetiredFromRecoverableQueue,
        tunnelInterruptionState: interruptedConnection.state,
        tunnelRestoredState: restoredConnection.state,
        immutableJobSurvivedTunnelInterruption: true,
        historyOpenedVerifiedResult: true,
        languagePreflightExecution,
        status: "passed",
      }, null, 2)}\n`),
    );
  });

  if (process.env.YAP_PRIVATE_SERVER_ASR_GATE_PROFILE === meetingTranscriptionProfile) {
    it("cancels an active meeting transcription without publishing History", async () => {
      await browser.tauri.switchWindow("main");

      const checkedHead = requireEnvironment("YAP_CHECKED_HEAD");
      const evidenceDirectory = requireEnvironment(
        "YAP_PRIVATE_SERVER_ASR_GATE_EVIDENCE_DIR",
      );
      const fixtureSha256 = requireEnvironment(
        "YAP_PRIVATE_SERVER_ASR_GATE_FIXTURE_SHA256",
      );
      const timeoutMs = Number(
        requireEnvironment("YAP_PRIVATE_SERVER_ASR_GATE_TIMEOUT_MS"),
      );
      const catalog = await invoke("server_asr_capabilities");
      const created = await invoke("recording_jobs_pick_imports", {
        languageBcp47: "en-US",
        catalogRevision: catalog.catalogRevision,
      });
      expect(created).toHaveLength(1);
      const createdJob = created[0];
      expect(createdJob.route).toBe("serverBatch");

      let terminalFailure;
      let activeRemoteLifecycle;
      await browser.waitUntil(
        async () => {
          const snapshot = await invoke("recording_jobs_snapshot");
          const job = snapshot.find((candidate) => candidate.id === createdJob.id);
          if (job && ["failed", "cancelled"].includes(job.status)) {
            terminalFailure = new Error(
              `The cancellation candidate reached ${job.status} before active inference.`,
            );
            return true;
          }
          const history = matchPublishedRemoteHistoryEntry(
            createdJob,
            await invoke("history_catalog"),
          );
          if (!job && history) {
            terminalFailure = new Error(
              "The cancellation candidate completed before active cancellation could be exercised.",
            );
            return true;
          }
          if (job?.status !== "server_processing") return false;
          const remoteLifecycle = await invoke(
            "wdio_recording_job_remote_lifecycle",
            { jobId: createdJob.id },
          );
          if (
            remoteLifecycle.remoteStatus === "server_processing"
            && remoteLifecycle.asrStageState === "running"
          ) {
            activeRemoteLifecycle = remoteLifecycle;
            return true;
          }
          if (["complete", "partial", "cancelled"].includes(remoteLifecycle.remoteStatus)) {
            terminalFailure = new Error(
              `The remote cancellation candidate reached ${remoteLifecycle.remoteStatus} before active inference was observed.`,
            );
            return true;
          }
          return false;
        },
        {
          interval: 100,
          timeout: timeoutMs,
          timeoutMsg: "The meeting cancellation candidate did not enter active inference.",
        },
      );
      if (terminalFailure) throw terminalFailure;

      const cancelled = await invoke("recording_job_cancel", { jobId: createdJob.id });
      expect(cancelled.status).toBe("cancelled");
      let cancelledRemoteLifecycle;
      await browser.waitUntil(
        async () => {
          const remoteLifecycle = await invoke(
            "wdio_recording_job_remote_lifecycle",
            { jobId: createdJob.id },
          );
          if (
            remoteLifecycle.remoteStatus === "cancelled"
            && remoteLifecycle.asrStageState === "cancelled"
            && Number.isSafeInteger(remoteLifecycle.cancellationAcknowledgedAtMs)
            && remoteLifecycle.cancellationAcknowledgedAtMs > 0
          ) {
            cancelledRemoteLifecycle = remoteLifecycle;
            return true;
          }
          return false;
        },
        {
          interval: 100,
          timeout: timeoutMs,
          timeoutMsg: "The server did not acknowledge active meeting cancellation and worker cleanup.",
        },
      );
      expect(activeRemoteLifecycle.clientJobId).toBe(createdJob.id);
      expect(cancelledRemoteLifecycle.clientJobId).toBe(createdJob.id);
      expect(cancelledRemoteLifecycle.serverJobId).toBe(activeRemoteLifecycle.serverJobId);
      const stabilityDeadline = Date.now() + 5_000;
      await browser.waitUntil(
        async () => {
          const history = matchPublishedRemoteHistoryEntry(
            createdJob,
            await invoke("history_catalog"),
          );
          if (history) {
            throw new Error("The cancelled meeting transcription was published to History.");
          }
          return Date.now() >= stabilityDeadline;
        },
        {
          interval: 250,
          timeout: 6_000,
          timeoutMsg: "The meeting cancellation did not remain stable.",
        },
      );

      writeExclusivePrivateFile(
        path.join(evidenceDirectory, "meeting-cancellation.json"),
        Buffer.from(`${JSON.stringify({
          schemaVersion: 1,
          checkedHead,
          profile: meetingTranscriptionProfile,
          fixtureSha256,
          clientJobId: createdJob.id,
          clientRoute: createdJob.route,
          serverJobId: activeRemoteLifecycle.serverJobId,
          observedRemoteServerProcessing: true,
          observedAsrRunning: true,
          cancelReturnedStatus: cancelled.status,
          remoteCancellationAcknowledgedAtMs:
            cancelledRemoteLifecycle.cancellationAcknowledgedAtMs,
          remoteCancelled: true,
          asrStageCancelled: true,
          historyNotPublished: true,
          status: "passed",
        }, null, 2)}\n`),
      );
    });
  }
});
