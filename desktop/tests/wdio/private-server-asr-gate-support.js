import path from "node:path";

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

export function matchCompletedRemoteHistoryEntry(jobIdentity, catalog) {
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

export function resolvePrivateServerAsrGateTimeout(value) {
  const timeoutMs = Number(value ?? defaultPrivateServerAsrGateTimeoutMs);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 60_000 || timeoutMs > 7_200_000) {
    throw new Error(
      "YAP_PRIVATE_SERVER_ASR_GATE_TIMEOUT_MS must be between one minute and two hours.",
    );
  }
  return timeoutMs;
}
