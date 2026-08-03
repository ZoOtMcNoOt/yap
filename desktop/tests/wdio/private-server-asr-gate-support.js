import { readFileSync } from "node:fs";
import path from "node:path";

export function readCanonicalPcm16Mono16KhzWav(filePath) {
  const bytes = readFileSync(filePath);
  if (
    bytes.length < 44
    || bytes.toString("ascii", 0, 4) !== "RIFF"
    || bytes.toString("ascii", 8, 12) !== "WAVE"
  ) {
    throw new Error("The ASR gate fixture is not a RIFF/WAVE file.");
  }
  let format;
  let pcm;
  for (let offset = 12; offset + 8 <= bytes.length;) {
    const id = bytes.toString("ascii", offset, offset + 4);
    const length = bytes.readUInt32LE(offset + 4);
    const start = offset + 8;
    const end = start + length;
    if (end > bytes.length) {
      throw new Error("The ASR gate fixture has a truncated WAV chunk.");
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
    throw new Error("The ASR gate fixture must be mono signed-PCM16 at 16 kHz.");
  }
  return pcm;
}

export function repeatedPcm(source, byteLength) {
  const output = Buffer.alloc(byteLength);
  for (let offset = 0; offset < output.length;) {
    const copied = Math.min(source.length, output.length - offset);
    source.copy(output, offset, 0, copied);
    offset += copied;
  }
  return output;
}

export function canonicalPcm16Mono16KhzWav(pcm) {
  if (!Buffer.isBuffer(pcm) || pcm.length < 2 || pcm.length % 2 !== 0) {
    throw new Error("Canonical ASR gate PCM must contain whole signed-16 samples.");
  }
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
  return Buffer.concat([header, pcm]);
}

export function meetingCheckpointFixture(sourcePcm, durationSeconds = 65) {
  if (!Number.isInteger(durationSeconds) || durationSeconds < 60 || durationSeconds > 120) {
    throw new Error("Meeting checkpoint duration must stay between 60 and 120 seconds.");
  }
  const silence = Buffer.alloc(16_000 * 2);
  const pattern = Buffer.concat([sourcePcm, silence]);
  return canonicalPcm16Mono16KhzWav(
    repeatedPcm(pattern, durationSeconds * 16_000 * 2),
  );
}

export function meetingLanguageConfirmationRequest(job, languageBcp47) {
  const review = job?.languageReview;
  if (!review) return undefined;
  if (
    job.status !== "preflighting"
    || job.route !== "serverBatch"
    || job.languageDecision?.mode !== "fixed"
    || job.languageDecision.languageBcp47 !== languageBcp47
    || review.kind !== "manual"
    || review.reason !== "server_preflight_unavailable"
    || !/^[0-9a-f]{64}$/.test(review.catalogRevision)
  ) {
    throw new Error(
      "The meeting import did not expose the expected manual fixed-language review.",
    );
  }
  return {
    jobId: job.id,
    languageBcp47,
    catalogRevision: review.catalogRevision,
  };
}

const defaultPrivateServerAsrGateTimeoutMs = 2_700_000;
const inFlightRemotePipelineStages = new Map([
  ["queued_server", ["notStarted", "notStarted"]],
  ["preflighting", ["running", "notStarted"]],
  ["preprocessing", ["running", "notStarted"]],
  ["uploading", ["done", "notStarted"]],
  ["server_processing", ["done", "running"]],
]);

function stripExtendedWindowsPrefix(candidate) {
  if (/^\\\\\?\\UNC\\/i.test(candidate)) return `\\\\${candidate.slice(8)}`;
  if (/^\\\\\?\\/i.test(candidate)) return candidate.slice(4);
  return candidate;
}

function normalizeWindowsPath(candidate) {
  const normalized = path.win32.normalize(stripExtendedWindowsPrefix(candidate));
  const root = path.win32.parse(normalized).root;
  return normalized.length > root.length
    ? normalized.replace(/[\\/]+$/, "")
    : normalized;
}

export function sameWindowsPath(left, right) {
  return normalizeWindowsPath(left).toLocaleLowerCase("en-US")
    === normalizeWindowsPath(right).toLocaleLowerCase("en-US");
}

export function isValidInFlightRemotePipeline(job) {
  const expectedStages = inFlightRemotePipelineStages.get(job?.status);
  if (!expectedStages || job.route !== "serverBatch") return false;
  const [preprocessing, transcription] = expectedStages;
  return job.pipeline?.intake === "done"
    && job.pipeline.preprocessing === preprocessing
    && job.pipeline.transcription === transcription
    && job.pipeline.alignment === "notStarted"
    && job.pipeline.diarization === "notStarted"
    && job.pipeline.postprocessing === "notStarted";
}

export function matchPublishedRemoteHistoryEntry(jobIdentity, catalog) {
  if (
    jobIdentity?.route !== "serverBatch"
    || !/^job-[0-9a-f]{24}$/.test(jobIdentity.id)
    || typeof jobIdentity.sourcePath !== "string"
    || !Array.isArray(catalog?.sessions)
  ) {
    return undefined;
  }
  const sessionId = `s-${jobIdentity.id.slice("job-".length)}`;
  return catalog.sessions.find(
    (session) => session?.origin === "remote"
      && session?.sessionId === sessionId
      && typeof session.sourcePath === "string"
      && sameWindowsPath(session.sourcePath, jobIdentity.sourcePath),
  );
}

export function matchesVerifiedHistoryDialog(dialogs, name, expectedTranscript) {
  if (
    !Array.isArray(dialogs)
    || typeof name !== "string"
    || typeof expectedTranscript !== "string"
  ) {
    return false;
  }
  return dialogs.some(
    (dialog) => dialog?.label === name && dialog.transcript === expectedTranscript,
  );
}

export function matchesEnabledLoopbackServerSettings(settings, expectedOrigin) {
  return settings
    && typeof settings === "object"
    && Object.keys(settings).length === 4
    && settings.schemaVersion === 2
    && settings.enabled === true
    && settings.baseUrl === expectedOrigin
    && settings.authentication === null;
}

export function resolvePrivateServerAsrGateTimeout(value) {
  const timeoutMs = Number(value ?? defaultPrivateServerAsrGateTimeoutMs);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 60_000 || timeoutMs > 7_200_000) {
    throw new Error(
      "YAP_PRIVATE_SERVER_ASR_GATE_TIMEOUT_MS must be between one minute and two hours.",
    );
  }
  return timeoutMs;
}

function childHasExited(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

function waitForChildExit(child, timeoutMs) {
  if (childHasExited(child)) return Promise.resolve(true);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (exited) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      child.removeListener("exit", handleExit);
      resolve(exited);
    };
    const handleExit = () => finish(true);
    const timeout = setTimeout(() => finish(childHasExited(child)), timeoutMs);
    child.once("exit", handleExit);
  });
}

export async function settleSshTunnelChild(child, {
  gracefulTimeoutMs = 10_000,
  forceTimeoutMs = 10_000,
} = {}) {
  if (
    !Number.isSafeInteger(gracefulTimeoutMs)
    || gracefulTimeoutMs <= 0
    || !Number.isSafeInteger(forceTimeoutMs)
    || forceTimeoutMs <= 0
  ) {
    throw new Error("SSH tunnel settlement bounds must be positive integers.");
  }
  if (childHasExited(child)) return { forceKillRequested: false };

  try {
    child.kill();
  } catch (error) {
    if (!childHasExited(child)) {
      throw new Error("The gate-owned SSH forward rejected graceful termination.", {
        cause: error,
      });
    }
  }
  if (await waitForChildExit(child, gracefulTimeoutMs)) {
    return { forceKillRequested: false };
  }

  try {
    child.kill("SIGKILL");
  } catch (error) {
    if (!childHasExited(child)) {
      throw new Error("The gate-owned SSH forward rejected forced termination.", {
        cause: error,
      });
    }
  }
  if (await waitForChildExit(child, forceTimeoutMs)) {
    return { forceKillRequested: true };
  }
  const error = new Error(
    "The gate-owned SSH forward did not settle after forced termination.",
  );
  error.code = "PRIVATE_SERVER_SSH_TUNNEL_CLEANUP_UNPROVEN";
  throw error;
}
