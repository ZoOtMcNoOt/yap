import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";

import {
  isValidInFlightRemotePipeline,
  matchCompletedRemoteHistoryEntry,
  matchesVerifiedHistoryDialog,
} from "./private-server-asr-gate-support.js";

const tunnelHost = "127.0.0.1";
const tunnelPort = 18765;
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

function requireSshAlias() {
  const alias = requireEnvironment("YAP_PRIVATE_SERVER_ASR_GATE_SSH_ALIAS");
  if (!/^[A-Za-z0-9._-]+$/.test(alias)) {
    throw new Error(
      "YAP_PRIVATE_SERVER_ASR_GATE_SSH_ALIAS must be one explicit SSH config alias.",
    );
  }
  return alias;
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

function readCanonicalPcm16Mono16KhzWav(filePath) {
  const bytes = readFileSync(filePath);
  if (
    bytes.length < 44
    || bytes.toString("ascii", 0, 4) !== "RIFF"
    || bytes.toString("ascii", 8, 12) !== "WAVE"
  ) {
    throw new Error("The language-preflight fixture is not a RIFF/WAVE file.");
  }
  let format;
  let pcm;
  for (let offset = 12; offset + 8 <= bytes.length;) {
    const id = bytes.toString("ascii", offset, offset + 4);
    const length = bytes.readUInt32LE(offset + 4);
    const start = offset + 8;
    const end = start + length;
    if (end > bytes.length) {
      throw new Error("The language-preflight fixture has a truncated WAV chunk.");
    }
    if (id === "fmt ") format = bytes.subarray(start, end);
    if (id === "data") pcm = bytes.subarray(start, end);
    offset = end + (length % 2);
  }
  if (
    !format
    || format.length < 16
    || format.readUInt16LE(0) !== 1
    || format.readUInt16LE(2) !== 1
    || format.readUInt32LE(4) !== 16_000
    || format.readUInt16LE(12) !== 2
    || format.readUInt16LE(14) !== 16
    || !pcm
    || pcm.length < 2
    || pcm.length % 2 !== 0
  ) {
    throw new Error(
      "The language-preflight fixture must be mono signed-PCM16 at 16 kHz.",
    );
  }
  return pcm;
}

function repeatedPcm(source, byteLength) {
  const output = Buffer.alloc(byteLength);
  for (let offset = 0; offset < output.length;) {
    const copied = Math.min(source.length, output.length - offset);
    source.copy(output, offset, 0, copied);
    offset += copied;
  }
  return output;
}

function canonicalWavSha256(pcm) {
  const header = Buffer.alloc(44);
  header.write("RIFF", 0, "ascii");
  header.writeUInt32LE(pcm.length + 36, 4);
  header.write("WAVEfmt ", 8, "ascii");
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(16_000, 24);
  header.writeUInt32LE(32_000, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36, "ascii");
  header.writeUInt32LE(pcm.length, 40);
  return createHash("sha256").update(header).update(pcm).digest("hex");
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

async function startTunnel(alias) {
  if (await healthIsReachable()) {
    throw new Error("Port 18765 was already reachable before the gate-owned SSH forward.");
  }
  const child = spawn(
    "ssh.exe",
    [
      "-o", "BatchMode=yes",
      "-o", "ExitOnForwardFailure=yes",
      "-o", "ServerAliveInterval=15",
      "-o", "ServerAliveCountMax=3",
      "-N", "-T",
      "-L", `${tunnelHost}:${tunnelPort}:${tunnelHost}:${tunnelPort}`,
      alias,
    ],
    { stdio: "ignore", windowsHide: true },
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
  child.once("error", () => {});
  try {
    await waitForHealth(true, child, "become reachable");
  } catch (error) {
    await stopTunnel(child);
    throw error;
  }
  return child;
}

async function stopTunnel(child) {
  if (child.exitCode === null) {
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error("The gate-owned SSH forward did not stop within 10 seconds.")),
        10_000,
      );
      child.once("exit", () => {
        clearTimeout(timeout);
        resolve();
      });
      if (!child.kill()) {
        clearTimeout(timeout);
        reject(new Error("The private-server ASR gate could not stop its SSH forward."));
      }
    });
  }
  await waitForHealth(false, undefined, "become unreachable");
  const processEntry = tunnelProcessEntries.get(child);
  if (!processEntry) {
    throw new Error("The stopped SSH forward was absent from the owned-process ledger.");
  }
  processEntry.exitedAt = new Date().toISOString();
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
  writeFileSync(
    path.join(evidenceDirectory, "tunnel-process-ledger.json"),
    `${JSON.stringify({
      schemaVersion: 1,
      checkedHead: requireEnvironment("YAP_CHECKED_HEAD"),
      startedProcessCount: tunnelProcesses.length,
      exitedProcessCount: tunnelProcesses.length,
      processes: tunnelProcesses,
      status: "passed",
    }, null, 2)}\n`,
    { encoding: "utf8", flag: "wx" },
  );
}

describe("checked-head private-server ASR gate", () => {
  before(async () => {
    tunnelProcess = await startTunnel(requireSshAlias());
  });

  after(async () => {
    if (tunnelProcess) {
      const owned = tunnelProcess;
      tunnelProcess = undefined;
      await stopTunnel(owned);
    }
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

    const settings = await invoke("server_settings");
    expect(settings).toEqual({ schemaVersion: 1, enabled: true, baseUrl: expectedOrigin });
    await invoke("refresh_server_connection");
    const connection = await waitForConnectionState("ready", "become ready");
    expect(connection.capabilities).toEqual({
      batchJobs: true,
      jobStatus: true,
      liveStreaming: false,
    });

    const catalog = await invoke("server_asr_capabilities");
    expect(catalog?.catalogRevision).toMatch(/^[0-9a-f]{64}$/);
    const languagePreflightExecution = await runLanguagePreflightExecution(
      catalog,
      fixturePath,
      checkedHead,
    );
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

    const interruptedTunnel = tunnelProcess;
    tunnelProcess = undefined;
    await stopTunnel(interruptedTunnel);
    const interruptedConnection = await invoke("refresh_server_connection");
    expect(interruptedConnection.state).toBe("retrying");
    expect((await invoke("server_settings")).baseUrl).toBe(expectedOrigin);
    const interruptedSnapshot = await invoke("recording_jobs_snapshot");
    const interruptedJob = interruptedSnapshot.find((candidate) => candidate.id === clientJobId);
    expect(interruptedJob).toBeDefined();
    expect(isValidInFlightRemotePipeline(interruptedJob)).toBe(true);
    observedStatuses.add(interruptedJob.status);
    observedPreprocessingStates.add(interruptedJob.pipeline.preprocessing);

    tunnelProcess = await startTunnel(requireSshAlias());
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
        history = matchCompletedRemoteHistoryEntry(createdJob, catalog);
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
    expect(result.status).toBe("complete");
    expect(result.transcript.trim().length).toBeGreaterThan(0);
    expect(result.language?.languageBcp47).toBe(createdJob.languageDecision.languageBcp47);
    expect(result.modelProvenance).toContainEqual({
      calibrationRevision: "asr-not-applicable",
      modelId: expectedModelId,
      revision: expectedModelRevision,
    });

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

    const reviewButton = await browser.$(
      `[aria-label=${JSON.stringify(`Review recording ${history.name}`)}]`,
    );
    await reviewButton.waitForDisplayed({ timeout: 15_000 });
    await reviewButton.click();
    await browser.waitUntil(
      async () => {
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
        timeoutMsg: "History did not open the verified server-authoritative transcript.",
      },
    );

    writeFileSync(
      path.join(evidenceDirectory, "native-vertical-slice.json"),
      `${JSON.stringify({
        schemaVersion: 3,
        checkedHead,
        fixtureSha256,
        clientJobId,
        clientRoute: createdJob.route,
        serverOrigin: expectedOrigin,
        sessionId: result.sessionId,
        resultRevision: result.revision,
        resultAuthority: result.authority,
        resultArtifactSha256: createHash("sha256").update(resultBytes).digest("hex"),
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
      }, null, 2)}\n`,
      { encoding: "utf8", flag: "wx" },
    );
  });
});
