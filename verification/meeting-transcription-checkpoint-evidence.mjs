import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  readFileSync,
  realpathSync,
  statSync,
} from "node:fs";
import path from "node:path";

import {
  INTEGRATED_GATE_BYTE_LIMITS,
  readBoundedJsonArtifact,
  readBoundedRegularFile,
} from "./integrated-gate-artifact-bounds.mjs";
import {
  assertPrivateDirectory,
  assertPrivateFile,
} from "./private-gate-artifacts.mjs";

const GATE_ID = "meeting-transcription-maintainability-checkpoint";
const SHA40 = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const IMAGE_ID = /^sha256:[0-9a-f]{64}$/;
const PLAN_KEYS = new Set([
  "schemaVersion",
  "gateId",
  "checkedHead",
  "tironPreparation",
  "productLifecycle",
]);
const PREPARATION_PLAN_KEYS = new Set(["receiptFile", "receiptSha256"]);
const LIFECYCLE_PLAN_KEYS = new Set([
  "evidenceDirectory",
  "remoteCleanupLogFile",
  "teardownEvidenceFile",
]);
const PREPARATION_RECEIPT_KEYS = new Set([
  "schemaVersion",
  "checkedHead",
  "runtime",
  "dockerfileSha256",
  "image",
  "imageId",
  "architecture",
  "baseDigest",
]);
const CONTEXT_KEYS = new Set([
  "schemaVersion",
  "checkedHead",
  "profile",
  "fixtureLicense",
  "fixtureSha256",
  "fixtureDurationMs",
  "serverOrigin",
  "runtimeImageId",
  "preparationReceiptSha256",
  "status",
]);
const VERTICAL_KEYS = new Set([
  "schemaVersion",
  "checkedHead",
  "profile",
  "fixtureSha256",
  "fixtureDurationMs",
  "clientJobId",
  "clientRoute",
  "serverOrigin",
  "sessionId",
  "resultRevision",
  "resultAuthority",
  "resultStatus",
  "resultArtifactSha256",
  "transcriptBytes",
  "modelId",
  "modelRevision",
  "speakerResultRevision",
  "speakerResultArtifactSha256",
  "speakerResultSourceSha256",
  "speakerTurnCount",
  "speakerCount",
  "runtimeLockSha256",
  "completedJobRetiredFromRecoverableQueue",
  "historyOpenedVerifiedResult",
  "historyLoadedSpeakerTranscript",
  "historyRenderedSpeakerTranscript",
  "status",
]);
const CANCELLATION_KEYS = new Set([
  "schemaVersion",
  "checkedHead",
  "profile",
  "fixtureSha256",
  "clientJobId",
  "clientRoute",
  "serverJobId",
  "observedRemoteServerProcessing",
  "observedAsrRunning",
  "cancelReturnedStatus",
  "remoteCancellationAcknowledgedAtMs",
  "remoteCancelled",
  "asrStageCancelled",
  "historyNotPublished",
  "status",
]);
const TUNNEL_LEDGER_KEYS = new Set([
  "schemaVersion",
  "checkedHead",
  "startedProcessCount",
  "exitedProcessCount",
  "processes",
  "status",
]);
const TUNNEL_PROCESS_KEYS = new Set(["pid", "startedAt", "exitedAt"]);
const TEARDOWN_KEYS = new Set([
  "schemaVersion",
  "checkedHead",
  "remoteCleanupPassed",
  "localForwardAbsent",
  "remainingOwnedProcesses",
  "ownedProcessCount",
  "remainingOwnedContainers",
  "remainingOwnedListeners",
  "remainingOwnedNetworks",
  "remoteCleanupLogSha256",
  "tunnelProcessLedgerSha256",
  "status",
]);

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function requireExactKeys(value, allowed, label) {
  requireCondition(
    value && typeof value === "object" && !Array.isArray(value),
    `${label} must be an object.`,
  );
  const keys = Object.keys(value);
  const extra = keys.filter((key) => !allowed.has(key));
  const missing = [...allowed].filter((key) => !keys.includes(key));
  requireCondition(
    extra.length === 0 && missing.length === 0,
    `${label} fields differ from the current contract.`,
  );
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function combinedEvidenceSha256(...values) {
  const digest = createHash("sha256");
  for (const value of values) {
    const bytes = Buffer.isBuffer(value) ? value : Buffer.from(value);
    const length = Buffer.alloc(8);
    length.writeBigUInt64BE(BigInt(bytes.length));
    digest.update(length);
    digest.update(bytes);
  }
  return digest.digest("hex");
}

function samePath(left, right) {
  const normalizedLeft = path.normalize(left);
  const normalizedRight = path.normalize(right);
  return process.platform === "win32"
    ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight;
}

function requireOutsideRepository(candidate, repositoryRoot, label) {
  requireCondition(
    typeof candidate === "string" && path.isAbsolute(candidate),
    `${label} must be an absolute path.`,
  );
  const relative = path.relative(repositoryRoot, candidate);
  requireCondition(
    relative !== "" && (relative.startsWith("..") || path.isAbsolute(relative)),
    `${label} must stay outside the repository.`,
  );
}

function requireContained(candidate, root, label) {
  const relative = path.relative(root, candidate);
  requireCondition(
    relative !== ""
      && relative !== ".."
      && !relative.startsWith(`..${path.sep}`)
      && !path.isAbsolute(relative),
    `${label} must stay beneath the lifecycle evidence directory.`,
  );
}

function requireRealPrivateParent(candidate, label) {
  const parent = path.dirname(candidate);
  requireCondition(
    existsSync(parent)
      && statSync(parent).isDirectory()
      && !lstatSync(parent).isSymbolicLink()
      && samePath(realpathSync.native(parent), parent),
    `${label} parent must be an existing real directory.`,
  );
  assertPrivateDirectory(parent);
}

function readPrivateJson(candidate, label) {
  assertPrivateFile(candidate);
  return readBoundedJsonArtifact(
    candidate,
    label,
    INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes,
  );
}

function readPreparation(plan, expectedHead, repositoryRoot) {
  const artifact = readPrivateJson(
    plan.tironPreparation.receiptFile,
    "Tiron preparation receipt",
  );
  const receipt = artifact.value;
  requireExactKeys(
    receipt,
    PREPARATION_RECEIPT_KEYS,
    "Tiron preparation receipt",
  );
  const dockerfile = path.join(
    repositoryRoot,
    "server",
    "runtime",
    "tiron",
    "Dockerfile",
  );
  const runtimeLock = JSON.parse(readFileSync(
    path.join(repositoryRoot, "server", "meeting-transcription-runtime.lock.json"),
    "utf8",
  ));
  requireCondition(
    receipt.schemaVersion === 1
      && receipt.checkedHead === expectedHead
      && receipt.runtime === "meeting-transcription"
      && receipt.dockerfileSha256 === sha256(readFileSync(dockerfile))
      && receipt.image === `yap-tiron:checked-head-${expectedHead}`
      && IMAGE_ID.test(receipt.imageId ?? "")
      && receipt.architecture === "arm64"
      && receipt.baseDigest === runtimeLock?.baseRuntime?.digest
      && sha256(artifact.bytes) === plan.tironPreparation.receiptSha256,
    "Tiron preparation receipt does not bind the exact checkpoint image.",
  );
  return artifact;
}

export function validateMeetingTranscriptionCheckpointPlan(
  plan,
  {
    expectedHead,
    repositoryRoot,
    requireDestinationsAbsent = false,
  },
) {
  requireExactKeys(plan, PLAN_KEYS, "Meeting-transcription checkpoint plan");
  requireCondition(
    plan.schemaVersion === 1
      && plan.gateId === GATE_ID
      && SHA40.test(expectedHead ?? "")
      && plan.checkedHead === expectedHead,
    "Meeting-transcription checkpoint plan identity is invalid.",
  );
  requireExactKeys(
    plan.tironPreparation,
    PREPARATION_PLAN_KEYS,
    "Tiron preparation plan",
  );
  requireCondition(
    SHA256.test(plan.tironPreparation.receiptSha256 ?? ""),
    "Tiron preparation receipt identity is invalid.",
  );
  requireOutsideRepository(
    plan.tironPreparation.receiptFile,
    repositoryRoot,
    "Tiron preparation receipt",
  );
  readPreparation(plan, expectedHead, repositoryRoot);

  requireExactKeys(
    plan.productLifecycle,
    LIFECYCLE_PLAN_KEYS,
    "Product lifecycle plan",
  );
  for (const [label, candidate] of [
    ["Lifecycle evidence directory", plan.productLifecycle.evidenceDirectory],
    ["Remote cleanup log", plan.productLifecycle.remoteCleanupLogFile],
    ["Teardown evidence file", plan.productLifecycle.teardownEvidenceFile],
  ]) {
    requireOutsideRepository(candidate, repositoryRoot, label);
  }
  requireContained(
    plan.productLifecycle.teardownEvidenceFile,
    plan.productLifecycle.evidenceDirectory,
    "Teardown evidence file",
  );
  requireRealPrivateParent(
    plan.productLifecycle.evidenceDirectory,
    "Lifecycle evidence directory",
  );
  requireRealPrivateParent(
    plan.productLifecycle.remoteCleanupLogFile,
    "Remote cleanup log",
  );
  if (requireDestinationsAbsent) {
    for (const [label, candidate] of [
      ["Lifecycle evidence directory", plan.productLifecycle.evidenceDirectory],
      ["Remote cleanup log", plan.productLifecycle.remoteCleanupLogFile],
      ["Teardown evidence file", plan.productLifecycle.teardownEvidenceFile],
    ]) {
      requireCondition(!existsSync(candidate), `${label} must be new at admission.`);
    }
  }
  return plan;
}

function validTunnelLedger(value, expectedHead) {
  return value?.schemaVersion === 1
    && value.checkedHead === expectedHead
    && value.startedProcessCount === 2
    && value.exitedProcessCount === 2
    && value.status === "passed"
    && Array.isArray(value.processes)
    && value.processes.length === 2
    && new Set(value.processes.map(({ pid }) => pid)).size === 2
    && value.processes.every(({ pid, startedAt, exitedAt }) => (
      Number.isSafeInteger(pid)
      && pid > 0
      && Number.isFinite(Date.parse(startedAt))
      && Number.isFinite(Date.parse(exitedAt))
      && Date.parse(exitedAt) >= Date.parse(startedAt)
    ));
}

export function validateMeetingTranscriptionCheckpointEvidence(
  plan,
  expectedHead,
  repositoryRoot,
) {
  validateMeetingTranscriptionCheckpointPlan(plan, {
    expectedHead,
    repositoryRoot,
  });
  const preparation = readPreparation(plan, expectedHead, repositoryRoot);
  const root = plan.productLifecycle.evidenceDirectory;
  requireCondition(
    existsSync(root)
      && statSync(root).isDirectory()
      && !lstatSync(root).isSymbolicLink()
      && samePath(realpathSync.native(root), root),
    "Lifecycle evidence directory is unavailable.",
  );
  assertPrivateDirectory(root);

  const context = readPrivateJson(
    path.join(root, "gate-context.json"),
    "Meeting gate context",
  );
  const vertical = readPrivateJson(
    path.join(root, "meeting-transcription-vertical.json"),
    "Meeting product vertical",
  );
  const cancellation = readPrivateJson(
    path.join(root, "meeting-cancellation.json"),
    "Meeting cancellation evidence",
  );
  const tunnelLedger = readPrivateJson(
    path.join(root, "tunnel-process-ledger.json"),
    "Meeting tunnel process ledger",
  );
  const teardown = readPrivateJson(
    plan.productLifecycle.teardownEvidenceFile,
    "Meeting teardown receipt",
  );
  assertPrivateFile(plan.productLifecycle.remoteCleanupLogFile);
  const cleanupLog = readBoundedRegularFile(
    plan.productLifecycle.remoteCleanupLogFile,
    "Meeting remote cleanup log",
    INTEGRATED_GATE_BYTE_LIMITS.privateLogEvidenceBytes,
  );

  requireExactKeys(context.value, CONTEXT_KEYS, "Meeting gate context");
  requireCondition(
    context.value.schemaVersion === 2
      && context.value.checkedHead === expectedHead
      && context.value.profile === "meeting-transcription"
      && context.value.fixtureLicense === "CC-BY-4.0"
      && SHA256.test(context.value.fixtureSha256 ?? "")
      && Number.isSafeInteger(context.value.fixtureDurationMs)
      && context.value.fixtureDurationMs >= 60_000
      && context.value.fixtureDurationMs <= 120_000
      && context.value.serverOrigin === "http://127.0.0.1:18765"
      && context.value.runtimeImageId === preparation.value.imageId
      && context.value.preparationReceiptSha256
        === plan.tironPreparation.receiptSha256
      && context.value.status === "started",
    "Meeting gate context does not bind the exact multi-window runtime.",
  );

  requireExactKeys(vertical.value, VERTICAL_KEYS, "Meeting product vertical");
  const runtimeLockBytes = readFileSync(
    path.join(repositoryRoot, "server", "meeting-transcription-runtime.lock.json"),
  );
  const runtimeLock = JSON.parse(runtimeLockBytes.toString("utf8"));
  requireCondition(
    vertical.value.schemaVersion === 1
      && vertical.value.checkedHead === expectedHead
      && vertical.value.profile === context.value.profile
      && vertical.value.fixtureSha256 === context.value.fixtureSha256
      && vertical.value.fixtureDurationMs === context.value.fixtureDurationMs
      && /^job-[0-9a-f]{24}$/.test(vertical.value.clientJobId ?? "")
      && vertical.value.clientRoute === "serverBatch"
      && vertical.value.serverOrigin === context.value.serverOrigin
      && typeof vertical.value.sessionId === "string"
      && vertical.value.sessionId.length > 0
      && vertical.value.resultRevision === 1
      && vertical.value.resultAuthority === "server_authoritative"
      && ["complete", "partial"].includes(vertical.value.resultStatus)
      && SHA256.test(vertical.value.resultArtifactSha256 ?? "")
      && Number.isSafeInteger(vertical.value.transcriptBytes)
      && vertical.value.transcriptBytes > 0
      && vertical.value.modelId === runtimeLock?.model?.id
      && vertical.value.modelRevision === runtimeLock?.model?.revision
      && vertical.value.speakerResultRevision === 1
      && SHA256.test(vertical.value.speakerResultArtifactSha256 ?? "")
      && vertical.value.speakerResultSourceSha256
        === vertical.value.resultArtifactSha256
      && Number.isSafeInteger(vertical.value.speakerTurnCount)
      && vertical.value.speakerTurnCount > 0
      && Number.isSafeInteger(vertical.value.speakerCount)
      && vertical.value.speakerCount > 0
      && vertical.value.speakerCount <= 8
      && vertical.value.speakerCount <= vertical.value.speakerTurnCount
      && vertical.value.runtimeLockSha256 === sha256(runtimeLockBytes)
      && vertical.value.completedJobRetiredFromRecoverableQueue === true
      && vertical.value.historyOpenedVerifiedResult === true
      && vertical.value.historyLoadedSpeakerTranscript === true
      && vertical.value.historyRenderedSpeakerTranscript === true
      && vertical.value.status === "passed",
    "Meeting product vertical did not prove the result and History lifecycle.",
  );

  requireExactKeys(
    cancellation.value,
    CANCELLATION_KEYS,
    "Meeting cancellation evidence",
  );
  requireCondition(
    cancellation.value.schemaVersion === 1
      && cancellation.value.checkedHead === expectedHead
      && cancellation.value.profile === context.value.profile
      && cancellation.value.fixtureSha256 === context.value.fixtureSha256
      && /^job-[0-9a-f]{24}$/.test(cancellation.value.clientJobId ?? "")
      && cancellation.value.clientJobId !== vertical.value.clientJobId
      && cancellation.value.clientRoute === "serverBatch"
      && /^job-[0-9a-f]{32}$/.test(cancellation.value.serverJobId ?? "")
      && cancellation.value.observedRemoteServerProcessing === true
      && cancellation.value.observedAsrRunning === true
      && cancellation.value.cancelReturnedStatus === "cancelled"
      && Number.isSafeInteger(cancellation.value.remoteCancellationAcknowledgedAtMs)
      && cancellation.value.remoteCancellationAcknowledgedAtMs > 0
      && cancellation.value.remoteCancelled === true
      && cancellation.value.asrStageCancelled === true
      && cancellation.value.historyNotPublished === true
      && cancellation.value.status === "passed",
    "Meeting cancellation evidence did not prove in-flight cancellation.",
  );
  requireExactKeys(
    tunnelLedger.value,
    TUNNEL_LEDGER_KEYS,
    "Meeting tunnel process ledger",
  );
  if (Array.isArray(tunnelLedger.value.processes)) {
    for (const processEntry of tunnelLedger.value.processes) {
      requireExactKeys(
        processEntry,
        TUNNEL_PROCESS_KEYS,
        "Meeting tunnel process entry",
      );
    }
  }
  requireCondition(
    validTunnelLedger(tunnelLedger.value, expectedHead),
    "Meeting tunnel ledger did not prove two retired owned forwards.",
  );

  const cleanupText = cleanupLog.bytes.toString("utf8");
  const markerLines = cleanupText.split(/\r?\n/).filter((line) => (
    line.startsWith("REMOTE_RUNTIME_TIRON_")
  ));
  const markers = Object.fromEntries(markerLines.map((line) => {
    const separator = line.indexOf("=");
    return [line.slice(0, separator), line.slice(separator + 1)];
  }));
  requireCondition(
    markerLines.length === 2
      && Object.keys(markers).length === 2
      && markers.REMOTE_RUNTIME_TIRON_IMAGE_ID === preparation.value.imageId
      && markers.REMOTE_RUNTIME_TIRON_PREPARATION_RECEIPT_SHA256
        === plan.tironPreparation.receiptSha256
      && cleanupText.includes(`REMOTE_PRIVATE_SERVER_READY=${expectedHead}`)
      && cleanupText.split(/\r?\n/).filter((line) => (
        line === "REMOTE_GATE_CLEANUP=PASS"
      )).length === 1
      && !cleanupText.includes("REMOTE_GATE_CLEANUP=FAIL"),
    "Remote cleanup log does not bind the exact Tiron runtime and teardown.",
  );

  const teardownValue = teardown.value;
  requireExactKeys(teardownValue, TEARDOWN_KEYS, "Meeting teardown receipt");
  requireCondition(
    teardownValue.schemaVersion === 1
      && teardownValue.checkedHead === expectedHead
      && teardownValue.remoteCleanupPassed === true
      && teardownValue.localForwardAbsent === true
      && teardownValue.remainingOwnedProcesses === 0
      && teardownValue.ownedProcessCount === 3
      && teardownValue.remainingOwnedContainers === 0
      && teardownValue.remainingOwnedListeners === 0
      && teardownValue.remainingOwnedNetworks === 0
      && teardownValue.remoteCleanupLogSha256 === sha256(cleanupLog.bytes)
      && teardownValue.tunnelProcessLedgerSha256 === sha256(tunnelLedger.bytes)
      && teardownValue.status === "passed",
    "Meeting teardown receipt did not prove zero retained owners.",
  );

  return new Map([
    ["gb10.tiron-checked-image", sha256(preparation.bytes)],
    [
      "gb10.tiron-runtime-boundary",
      combinedEvidenceSha256(preparation.bytes, vertical.bytes),
    ],
    [
      "integrated.meeting-result-history",
      combinedEvidenceSha256(context.bytes, vertical.bytes),
    ],
    ["integrated.meeting-cancellation", sha256(cancellation.bytes)],
    [
      "integrated.teardown",
      combinedEvidenceSha256(teardown.bytes, cleanupLog.bytes, tunnelLedger.bytes),
    ],
  ]);
}
