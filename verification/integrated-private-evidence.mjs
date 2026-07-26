import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  realpathSync,
  statSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";

import { validateTargetClientNativeResourceEvidence } from "../desktop/tests/wdio/target-client-native-resource-evidence.js";
import { validateTargetClientPreparedAudioEvidence } from "../desktop/tests/wdio/target-client-prepared-audio-evidence.js";
import {
  INTEGRATED_GATE_BYTE_LIMITS,
  readBoundedJsonArtifact,
  readBoundedRegularFile,
} from "./integrated-gate-artifact-bounds.mjs";

const SHA40 = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const IMAGE_DIGEST = /^sha256:[0-9a-f]{64}$/;
const MOCK_OIDC_RECEIPT_MAX_BYTES = 4 * 1024;
const PRIVATE_PLAN_V1_KEYS = new Set([
  "schemaVersion",
  "checkedHead",
  "targetClient",
  "gb10",
  "integrated",
]);
const PRIVATE_PLAN_V2_KEYS = new Set([
  ...PRIVATE_PLAN_V1_KEYS,
  "mockOidc",
]);
const RUNTIME_PREPARATION_IDS = new Set([
  "cohere-vllm",
  "nemotron-nemo",
  "language-detection",
]);
const GB10_CHILDREN = new Set([
  "nemo/active-capacity",
  "nemo/cancellation",
  "nemo/duration-batch",
  "nemo/duration-finalized",
  "nemo/language-contract",
  "nemo/long-windows",
  "nemo/readiness",
  "nemo/resource-load",
  "nemo/resources",
  "nemo/short-tail",
  "vllm/cancellation",
  "vllm/duration-batch",
  "vllm/pcm-capacity",
  "vllm/readiness",
  "vllm/resource-load",
  "vllm/resources",
  "vllm/short-tail",
  "vllm/slot-capacity",
]);

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function requireExactKeys(value, allowed, label) {
  const keys = Object.keys(value);
  const extra = keys.filter((key) => !allowed.has(key));
  const missing = [...allowed].filter((key) => !keys.includes(key));
  requireCondition(
    extra.length === 0 && missing.length === 0,
    `${label} fields differ from the frozen contract.`,
  );
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, stableValue(value[key])]),
    );
  }
  return value;
}

function canonicalEvidenceSha256(value) {
  return sha256(JSON.stringify(stableValue(value)));
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

function requireOutsideRepository(candidate, repositoryRoot, label) {
  requireCondition(path.isAbsolute(candidate), `${label} must be absolute.`);
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
    `${label} must stay beneath its private evidence root.`,
  );
}

function requireRealParent(candidate, label) {
  const parent = path.dirname(candidate);
  requireCondition(
    existsSync(parent)
      && statSync(parent).isDirectory()
      && !lstatSync(parent).isSymbolicLink()
      && path.normalize(realpathSync.native(parent)).toLowerCase()
        === path.normalize(parent).toLowerCase(),
    `${label} parent must be an existing real directory.`,
  );
}

function readRealBytesFile(candidate, label) {
  return readBoundedRegularFile(
    candidate,
    label,
    INTEGRATED_GATE_BYTE_LIMITS.privateLogEvidenceBytes,
  ).bytes;
}

function readRealFile(candidate, label) {
  return readBoundedJsonArtifact(
    candidate,
    label,
    INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes,
  );
}

function requireRealDirectory(candidate, label) {
  requireCondition(
    existsSync(candidate)
      && statSync(candidate).isDirectory()
      && !lstatSync(candidate).isSymbolicLink()
      && path.normalize(realpathSync.native(candidate)).toLowerCase()
        === path.normalize(candidate).toLowerCase(),
    `${label} must be an existing real directory.`,
  );
}

function readRuntimePreparation(plan, runtime, expectedHead) {
  const preparation = plan.gb10.runtimePreparation[runtime];
  const receipt = readBoundedJsonArtifact(
    preparation.receiptFile,
    `${runtime} preparation receipt`,
    INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes,
  );
  const value = receipt.value;
  requireExactKeys(
    value,
    new Set([
      "schemaVersion",
      "checkedHead",
      "runtime",
      "dockerfileSha256",
      "image",
      "imageId",
      "architecture",
      "baseDigest",
    ]),
    `${runtime} preparation receipt`,
  );
  requireCondition(
    value.schemaVersion === 1
      && value.checkedHead === expectedHead
      && value.runtime === runtime
      && SHA256.test(value.dockerfileSha256 ?? "")
      && typeof value.image === "string"
      && value.image.endsWith(`:checked-head-${expectedHead}`)
      && /^sha256:[0-9a-f]{64}$/.test(value.imageId ?? "")
      && value.architecture === "arm64"
      && /^sha256:[0-9a-f]{64}$/.test(value.baseDigest ?? "")
      && sha256(receipt.bytes) === preparation.receiptSha256,
    `${runtime} preparation receipt does not match the frozen plan.`,
  );
  return receipt;
}

export function validateIntegratedPrivateEvidencePlan(
  plan,
  {
    expectedHead,
    repositoryRoot,
    requireDestinationsAbsent = false,
    requireMockOidc = false,
  },
) {
  requireCondition(plan && typeof plan === "object" && !Array.isArray(plan),
    "Private evidence plan must be an object.");
  requireCondition(
    plan.schemaVersion === 1 || plan.schemaVersion === 2,
    "Private evidence plan schemaVersion must be 1 or 2.",
  );
  requireExactKeys(
    plan,
    plan.schemaVersion === 2 ? PRIVATE_PLAN_V2_KEYS : PRIVATE_PLAN_V1_KEYS,
    "Private evidence plan",
  );
  requireCondition(
    !requireMockOidc || plan.schemaVersion === 2,
    "This gate requires a schemaVersion 2 mock OIDC receipt.",
  );
  requireCondition(SHA40.test(expectedHead ?? "") && plan.checkedHead === expectedHead,
    "Private evidence plan head does not match.");
  if (plan.schemaVersion === 2) {
    requireCondition(
      plan.mockOidc
        && typeof plan.mockOidc === "object"
        && !Array.isArray(plan.mockOidc),
      "Mock OIDC private plan must be an object.",
    );
    requireExactKeys(
      plan.mockOidc,
      new Set(["receiptFile"]),
      "Mock OIDC private plan",
    );
  }
  requireExactKeys(
    plan.targetClient,
    new Set(["evidenceDirectory", "preparedAudioEvidenceFile", "preparedAudioSuiteSha256"]),
    "Target-client private plan",
  );
  requireExactKeys(
    plan.gb10,
    new Set(["lifecycleEvidenceFile", "runtimePreparation"]),
    "GB10 private plan",
  );
  requireCondition(
    plan.gb10.runtimePreparation
      && typeof plan.gb10.runtimePreparation === "object"
      && !Array.isArray(plan.gb10.runtimePreparation),
    "Runtime preparation plan must be an object.",
  );
  requireExactKeys(
    plan.gb10.runtimePreparation,
    RUNTIME_PREPARATION_IDS,
    "Runtime preparation plan",
  );
  for (const runtime of RUNTIME_PREPARATION_IDS) {
    const preparation = plan.gb10.runtimePreparation[runtime];
    requireCondition(
      preparation && typeof preparation === "object" && !Array.isArray(preparation),
      `${runtime} preparation plan must be an object.`,
    );
    requireExactKeys(
      preparation,
      new Set(["receiptFile", "receiptSha256"]),
      `${runtime} preparation plan`,
    );
    requireCondition(
      typeof preparation.receiptFile === "string",
      `${runtime} preparation receipt must be a path.`,
    );
    requireOutsideRepository(
      preparation.receiptFile,
      repositoryRoot,
      `${runtime} preparation receipt`,
    );
    requireCondition(
      SHA256.test(preparation.receiptSha256 ?? ""),
      `${runtime} preparation receipt identity is invalid.`,
    );
    readRuntimePreparation(plan, runtime, expectedHead);
  }
  requireExactKeys(
    plan.integrated,
    new Set(["evidenceDirectory", "remoteCleanupLogFile", "teardownEvidenceFile"]),
    "Integrated private plan",
  );
  const paths = [
    ...(plan.schemaVersion === 2
      ? [["Mock OIDC receipt file", plan.mockOidc.receiptFile]]
      : []),
    ["Target-client evidence directory", plan.targetClient.evidenceDirectory],
    ["Prepared-audio evidence file", plan.targetClient.preparedAudioEvidenceFile],
    [
      "Prepared-audio failure evidence file",
      `${plan.targetClient.preparedAudioEvidenceFile}.failure.json`,
    ],
    ["GB10 lifecycle evidence file", plan.gb10.lifecycleEvidenceFile],
    ["Integrated evidence directory", plan.integrated.evidenceDirectory],
    ["Integrated remote cleanup log", plan.integrated.remoteCleanupLogFile],
    ["Integrated teardown evidence file", plan.integrated.teardownEvidenceFile],
  ];
  for (const [label, candidate] of paths) {
    requireCondition(typeof candidate === "string", `${label} must be a path.`);
    requireOutsideRepository(candidate, repositoryRoot, label);
  }
  for (const [label, candidate] of [
    ...(plan.schemaVersion === 2
      ? [["Mock OIDC receipt file", plan.mockOidc.receiptFile]]
      : []),
    ["Target-client evidence directory", plan.targetClient.evidenceDirectory],
    ["GB10 lifecycle evidence file", plan.gb10.lifecycleEvidenceFile],
    ["Integrated evidence directory", plan.integrated.evidenceDirectory],
    ["Integrated remote cleanup log", plan.integrated.remoteCleanupLogFile],
  ]) {
    requireRealParent(candidate, label);
  }
  requireContained(
    plan.targetClient.preparedAudioEvidenceFile,
    plan.targetClient.evidenceDirectory,
    "Prepared-audio evidence file",
  );
  requireContained(
    `${plan.targetClient.preparedAudioEvidenceFile}.failure.json`,
    plan.targetClient.evidenceDirectory,
    "Prepared-audio failure evidence file",
  );
  requireContained(
    plan.integrated.teardownEvidenceFile,
    plan.integrated.evidenceDirectory,
    "Integrated teardown evidence file",
  );
  requireCondition(
    path.normalize(plan.targetClient.evidenceDirectory).toLowerCase()
      !== path.normalize(plan.integrated.evidenceDirectory).toLowerCase(),
    "Target-client and integrated evidence need distinct roots.",
  );
  requireCondition(
    SHA256.test(plan.targetClient.preparedAudioSuiteSha256 ?? ""),
    "Prepared-audio suite identity is invalid.",
  );
  if (requireDestinationsAbsent) {
    for (const [label, candidate] of paths) {
      requireCondition(!existsSync(candidate), `${label} must be new when the attempt is admitted.`);
    }
  }
  return plan;
}

function validateMockOidcEvidence(plan, expectedHead, repositoryRoot) {
  requireCondition(
    plan.schemaVersion === 2,
    "Mock OIDC evidence requires a schemaVersion 2 private plan.",
  );
  requireCondition(
    typeof repositoryRoot === "string" && path.isAbsolute(repositoryRoot),
    "Mock OIDC evidence requires an absolute repository root.",
  );
  const receipt = readBoundedJsonArtifact(
    plan.mockOidc.receiptFile,
    "Mock OIDC owner-flow receipt",
    MOCK_OIDC_RECEIPT_MAX_BYTES,
  );
  const value = receipt.value;
  requireExactKeys(
    value,
    new Set([
      "schemaVersion",
      "receiptContract",
      "checkedHead",
      "lockedImageDigest",
      "validatorSources",
      "ownerFlowSha256",
      "teardown",
      "status",
    ]),
    "Mock OIDC owner-flow receipt",
  );
  requireCondition(
    value.validatorSources
      && typeof value.validatorSources === "object"
      && !Array.isArray(value.validatorSources),
    "Mock OIDC validator sources must be an object.",
  );
  requireExactKeys(
    value.validatorSources,
    new Set(["oidcAccessTokensSha256", "oidcMetadataSha256"]),
    "Mock OIDC validator sources",
  );
  requireCondition(
    value.teardown
      && typeof value.teardown === "object"
      && !Array.isArray(value.teardown),
    "Mock OIDC teardown receipt must be an object.",
  );
  requireExactKeys(
    value.teardown,
    new Set([
      "childProcessesStopped",
      "containerAbsent",
      "networkAbsent",
      "loopbackPortReleased",
      "stateDirectoryRemoved",
      "cancellationHandlerRemoved",
      "remainingContainers",
      "remainingNetworks",
      "status",
    ]),
    "Mock OIDC teardown receipt",
  );
  requireCondition(
    value.schemaVersion === 1
      && value.receiptContract === "mock-oidc-owner-flow-v1"
      && value.checkedHead === expectedHead
      && IMAGE_DIGEST.test(value.lockedImageDigest ?? "")
      && SHA256.test(value.validatorSources.oidcAccessTokensSha256 ?? "")
      && SHA256.test(value.validatorSources.oidcMetadataSha256 ?? "")
      && SHA256.test(value.ownerFlowSha256 ?? "")
      && value.status === "passed",
    "Mock OIDC owner-flow receipt did not pass its checked-head contract.",
  );
  requireCondition(
    value.teardown.childProcessesStopped === true
      && value.teardown.containerAbsent === true
      && value.teardown.networkAbsent === true
      && value.teardown.loopbackPortReleased === true
      && value.teardown.stateDirectoryRemoved === true
      && value.teardown.cancellationHandlerRemoved === true
      && value.teardown.remainingContainers === 0
      && value.teardown.remainingNetworks === 0
      && value.teardown.status === "passed",
    "Mock OIDC owner-flow receipt did not prove verified teardown.",
  );

  const repository = path.resolve(repositoryRoot);
  const lock = readBoundedJsonArtifact(
    path.join(repository, "verification", "mock-oidc-provider.lock.json"),
    "Mock OIDC provider lock",
    INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes,
  );
  requireCondition(
    lock.value.schemaVersion === 1
      && lock.value.manifestDigest === value.lockedImageDigest
      && lock.value.reference
        === `ghcr.io/navikt/mock-oauth2-server:5.0.2@${value.lockedImageDigest}`,
    "Mock OIDC receipt does not match the locked provider image.",
  );
  const accessTokens = readBoundedRegularFile(
    path.join(
      repository,
      "server",
      "src",
      "yap_server",
      "auth",
      "oidc_access_tokens.py",
    ),
    "OIDC access-token validator source",
    INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes,
  );
  const metadata = readBoundedRegularFile(
    path.join(
      repository,
      "server",
      "src",
      "yap_server",
      "auth",
      "oidc_metadata.py",
    ),
    "OIDC metadata owner source",
    INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes,
  );
  const ownerFlow = readBoundedRegularFile(
    path.join(repository, "verification", "mock-oidc-owner-flow.py"),
    "Mock OIDC owner-flow source",
    INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes,
  );
  requireCondition(
    value.validatorSources.oidcAccessTokensSha256 === sha256(accessTokens.bytes)
      && value.validatorSources.oidcMetadataSha256 === sha256(metadata.bytes)
      && value.ownerFlowSha256 === sha256(ownerFlow.bytes),
    "Mock OIDC receipt source identities do not match the exact checkout.",
  );
  return new Map([
    ["server.mock-oidc-owner-flow", sha256(receipt.bytes)],
  ]);
}

function validateTargetClientEvidence(plan, expectedHead) {
  const root = plan.targetClient.evidenceDirectory;
  requireRealDirectory(root, "Target-client evidence directory");
  const resource = readRealFile(path.join(root, "resource-gate-context.json"), "Native resource context");
  const profile = readRealFile(path.join(root, "resident-language-routing-profile.json"), "Native resource profile");
  const logPath = path.join(root, "native-resource-gate.log");
  const log = { bytes: readRealBytesFile(logPath, "Native resource log") };
  const processors = os.cpus();
  validateTargetClientNativeResourceEvidence(resource.value, profile.value, {
    checkedHead: expectedHead,
    logicalProcessors: processors.length,
    processorName: processors[0]?.model.trim(),
  });
  requireCondition(sha256(profile.bytes) === resource.value.profileSha256,
    "Native resource profile changed after validation.");
  requireCondition(sha256(log.bytes) === resource.value.logSha256,
    "Native resource log changed after validation.");

  const preparedPath = plan.targetClient.preparedAudioEvidenceFile;
  requireContained(preparedPath, root, "Prepared-audio evidence file");
  requireCondition(
    !existsSync(`${preparedPath}.failure.json`),
    "A successful target-client run cannot retain prepared-audio failure evidence.",
  );
  const prepared = readRealFile(preparedPath, "Prepared-audio evidence");
  validateTargetClientPreparedAudioEvidence(prepared.value, {
    checkedHead: expectedHead,
    logicalProcessors: processors.length,
    suiteSha256: plan.targetClient.preparedAudioSuiteSha256,
  });

  const renderedRoot = path.join(root, "rendered-ui-and-microphone");
  requireRealDirectory(renderedRoot, "Rendered target-client evidence directory");
  const context = readRealFile(path.join(renderedRoot, "rendered-ui-context.json"), "Rendered UI context");
  const rendered = readRealFile(path.join(renderedRoot, "rendered-ui-evidence.json"), "Rendered UI evidence");
  requireCondition(
    context.value.schemaVersion === 4
      && context.value.status === "passed"
      && context.value.checkedHead === expectedHead
      && context.value.preparedAudioSuiteSha256 === plan.targetClient.preparedAudioSuiteSha256
      && context.value.preparedAudioEvidenceSha256 === sha256(prepared.bytes)
      && context.value.evidenceSha256 === sha256(rendered.bytes)
      && context.value.serverBoundary === "isolated-profile-with-no-loopback-server-listener"
      && context.value.transcriptTextRecorded === false,
    "Rendered UI context did not pass its checked-head private contract.",
  );
  requireCondition(
    rendered.value.schemaVersion === 4
      && rendered.value.buildGitSha === expectedHead
      && rendered.value.preparedAudioEvidenceSha256 === sha256(prepared.bytes)
      && rendered.value.route === "localFallback"
      && rendered.value.targetClientGate === true
      && rendered.value.transcriptTextRecorded === false
      && rendered.value.restartCancellation?.cycleCount === 4
      && rendered.value.restartCancellation?.finalStatus === "idle",
    "Rendered UI evidence did not pass its checked-head contract.",
  );
  requireCondition(
    !existsSync(path.join(renderedRoot, "live-recordings")),
    "Target-client teardown retained its recording directory.",
  );

  return new Map([
    [
      "target-client.native-resource-and-restart",
      combinedEvidenceSha256(resource.bytes, profile.bytes, log.bytes),
    ],
    ["target-client.prepared-audio-boundaries", sha256(prepared.bytes)],
    [
      "target-client.rendered-ui-and-microphone",
      combinedEvidenceSha256(context.bytes, rendered.bytes),
    ],
    ["target-client.teardown", sha256(context.bytes)],
  ]);
}

function validateGb10Evidence(plan, expectedHead) {
  const evidence = readRealFile(plan.gb10.lifecycleEvidenceFile, "GB10 lifecycle evidence");
  const value = evidence.value;
  const unhashed = { ...value };
  delete unhashed.evidenceSha256;
  requireCondition(
    value.schemaVersion === 1
      && value.checkedHead === expectedHead
      && value.hardwareProfile === "dgx-spark-gb10"
      && value.executionShape === "sequential-resident-providers"
      && value.passed === true
      && SHA256.test(value.evidenceSha256 ?? "")
      && value.evidenceSha256 === canonicalEvidenceSha256(unhashed),
    "GB10 lifecycle aggregate did not pass its checked-head contract.",
  );
  requireCondition(
    value.hostBoundary?.listenerStateUnchanged === true
      && value.hostBoundary?.firewallObservationUnchanged === true
      && value.hostBoundary?.serviceUnitsUnchanged === true
      && value.hostBoundary?.remainingProviderContainers === 0
      && value.hostBoundary?.remainingProviderRuntimeProcesses === 0
      && value.hostBoundary?.remainingProviderNetworks === 0,
    "GB10 lifecycle aggregate did not prove exact host teardown.",
  );
  requireCondition(
    value.durationSuite
      && SHA256.test(value.durationSuite.sha256 ?? "")
      && SHA256.test(value.durationSuite.planSha256 ?? ""),
    "GB10 lifecycle aggregate has an invalid duration-suite identity.",
  );
  requireCondition(
    value.runtimeImages
      && Object.keys(value.runtimeImages).length === 2
      && ["cohere-vllm", "nemotron-nemo"].every((runtime) => {
        const receipt = readRuntimePreparation(plan, runtime, expectedHead);
        return value.runtimeImages[runtime]?.imageId === receipt.value.imageId
          && value.runtimeImages[runtime]?.preparationReceiptSha256
            === plan.gb10.runtimePreparation[runtime].receiptSha256;
      }),
    "GB10 lifecycle aggregate is not bound to the frozen runtime preparation.",
  );
  requireCondition(
    value.childEvidence
      && Object.keys(value.childEvidence).length === GB10_CHILDREN.size
      && Object.entries(value.childEvidence).every(
        ([key, hash]) => GB10_CHILDREN.has(key) && SHA256.test(hash),
      ),
    "GB10 lifecycle aggregate has an incomplete child set.",
  );
  const evidenceSha256 = sha256(evidence.bytes);
  return new Map([
    ["gb10.provider-duration-and-concurrency", evidenceSha256],
    ["gb10.provider-cancellation-and-recovery", evidenceSha256],
    ["gb10.provider-resource-bounds", evidenceSha256],
    ["gb10.provider-teardown", evidenceSha256],
  ]);
}

function validateIntegratedEvidence(plan, expectedHead) {
  const root = plan.integrated.evidenceDirectory;
  requireRealDirectory(root, "Integrated desktop/private-server evidence directory");
  const context = readRealFile(path.join(root, "gate-context.json"), "Integrated gate context");
  const vertical = readRealFile(path.join(root, "native-vertical-slice.json"), "Integrated vertical slice");
  const tunnelLedger = readRealFile(
    path.join(root, "tunnel-process-ledger.json"),
    "Integrated tunnel process ledger",
  );
  const teardown = readRealFile(plan.integrated.teardownEvidenceFile, "Integrated teardown evidence");
  const cleanupLogBytes = readRealBytesFile(
    plan.integrated.remoteCleanupLogFile,
    "Integrated remote cleanup log",
  );
  const cleanupLogText = cleanupLogBytes.toString("utf8");
  const cleanupLines = cleanupLogText
    .split(/\r?\n/)
    .filter((line) => line.startsWith("REMOTE_GATE_CLEANUP="));
  const runtimeMarkerLines = cleanupLogText
    .split(/\r?\n/)
    .filter((line) => line.startsWith("REMOTE_RUNTIME_"));
  const runtimeLines = Object.fromEntries(
    runtimeMarkerLines.map((line) => {
      const separator = line.indexOf("=");
      return [line.slice(0, separator), line.slice(separator + 1)];
    }),
  );
  const coherePreparation = readRuntimePreparation(
    plan,
    "cohere-vllm",
    expectedHead,
  );
  const lidPreparation = readRuntimePreparation(
    plan,
    "language-detection",
    expectedHead,
  );
  requireCondition(
    context.value.schemaVersion === 1
      && context.value.checkedHead === expectedHead
      && context.value.status === "started"
      && context.value.fixtureLicense === "CC-BY-4.0"
      && SHA256.test(context.value.fixtureSha256 ?? "")
      && context.value.serverOrigin === "http://127.0.0.1:18765",
    "Integrated gate context is invalid.",
  );
  requireCondition(
    vertical.value.schemaVersion === 3
      && vertical.value.checkedHead === expectedHead
      && vertical.value.fixtureSha256 === context.value.fixtureSha256
      && vertical.value.clientRoute === "serverBatch"
      && vertical.value.serverOrigin === context.value.serverOrigin
      && vertical.value.resultAuthority === "server_authoritative"
      && vertical.value.durablePreprocessingManifestVerified === true
      && vertical.value.completedJobRetiredFromRecoverableQueue === true
      && vertical.value.tunnelInterruptionState === "retrying"
      && vertical.value.tunnelRestoredState === "ready"
      && vertical.value.immutableJobSurvivedTunnelInterruption === true
      && vertical.value.historyOpenedVerifiedResult === true
      && vertical.value.languagePreflightExecution?.componentId
        === "ambernet-batch-language-preflight"
      && vertical.value.languagePreflightExecution?.modelId
        === "nvidia/nemo/langid_ambernet"
      && vertical.value.languagePreflightExecution?.modelRevision === "1.12.0"
      && vertical.value.languagePreflightExecution?.runtimePythonVersion === "3.12.13"
      && vertical.value.languagePreflightExecution?.runtimeCpuOnly === true
      && vertical.value.languagePreflightExecution?.policyRevision
        === "ambernet-stratified-five-region-v1"
      && vertical.value.languagePreflightExecution?.observationCount === 5
      && ["manual", "suggestion"].includes(
        vertical.value.languagePreflightExecution?.resultStatus,
      )
      && SHA256.test(
        vertical.value.languagePreflightExecution?.requestIdSha256 ?? "",
      )
      && SHA256.test(
        vertical.value.languagePreflightExecution?.sourcePcmSha256 ?? "",
      )
      && vertical.value.status === "passed",
    "Integrated desktop/private-server evidence did not prove ASR and LID execution.",
  );
  requireCondition(
    tunnelLedger.value.schemaVersion === 1
      && tunnelLedger.value.checkedHead === expectedHead
      && tunnelLedger.value.startedProcessCount === 2
      && tunnelLedger.value.exitedProcessCount === 2
      && tunnelLedger.value.status === "passed"
      && Array.isArray(tunnelLedger.value.processes)
      && tunnelLedger.value.processes.length === 2
      && new Set(tunnelLedger.value.processes.map(({ pid }) => pid)).size === 2
      && tunnelLedger.value.processes.every(({ pid, startedAt, exitedAt }) => (
        Number.isSafeInteger(pid)
        && pid > 0
        && Number.isFinite(Date.parse(startedAt))
        && Number.isFinite(Date.parse(exitedAt))
        && Date.parse(exitedAt) >= Date.parse(startedAt)
      )),
    "Integrated tunnel process ledger did not prove two retired owned forwards.",
  );
  requireCondition(
    runtimeLines.REMOTE_RUNTIME_COHERE_VLLM_IMAGE_ID
      === coherePreparation.value.imageId
      && runtimeLines.REMOTE_RUNTIME_COHERE_VLLM_PREPARATION_RECEIPT_SHA256
        === plan.gb10.runtimePreparation["cohere-vllm"].receiptSha256
      && runtimeLines.REMOTE_RUNTIME_LANGUAGE_DETECTION_IMAGE_ID
        === lidPreparation.value.imageId
      && runtimeLines.REMOTE_RUNTIME_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256
        === plan.gb10.runtimePreparation["language-detection"].receiptSha256
      && runtimeMarkerLines.length === 4
      && Object.keys(runtimeLines).length === 4,
    "Integrated server runtime did not use the frozen prepared images.",
  );
  requireCondition(
    teardown.value.schemaVersion === 1
      && teardown.value.checkedHead === expectedHead
      && teardown.value.remoteCleanupPassed === true
      && teardown.value.localForwardAbsent === true
      && teardown.value.remainingOwnedProcesses === 0
      && teardown.value.ownedProcessCount === 3
      && teardown.value.remainingOwnedContainers === 0
      && teardown.value.remainingOwnedListeners === 0
      && teardown.value.remainingOwnedNetworks === 0
      && SHA256.test(teardown.value.remoteCleanupLogSha256 ?? "")
      && teardown.value.remoteCleanupLogSha256 === sha256(cleanupLogBytes)
      && teardown.value.tunnelProcessLedgerSha256 === sha256(tunnelLedger.bytes)
      && teardown.value.status === "passed",
    "Integrated desktop/private-server teardown evidence did not pass.",
  );
  requireCondition(
    cleanupLines.length === 1
      && cleanupLines[0] === "REMOTE_GATE_CLEANUP=PASS"
      && cleanupLogText.includes(`REMOTE_PRIVATE_SERVER_READY=${expectedHead}`)
      && !cleanupLogText.includes("REMOTE_GATE_CLEANUP=FAIL"),
    "Integrated remote cleanup log did not prove exact checked-head teardown.",
  );
  const verticalSha256 = combinedEvidenceSha256(context.bytes, vertical.bytes);
  const teardownSha256 = combinedEvidenceSha256(
    teardown.bytes,
    cleanupLogBytes,
    tunnelLedger.bytes,
  );
  return new Map([
    ["integrated.desktop-private-server", verticalSha256],
    ["integrated.tunnel-interruption-recovery", verticalSha256],
    ["integrated.authoritative-history-result", verticalSha256],
    ["integrated.teardown", teardownSha256],
  ]);
}

export function validateIntegratedPrivateEvidence(
  plan,
  expectedHead,
  repositoryRoot,
) {
  const maps = [
    ...(plan.schemaVersion === 2
      ? [validateMockOidcEvidence(plan, expectedHead, repositoryRoot)]
      : []),
    validateTargetClientEvidence(plan, expectedHead),
    validateGb10Evidence(plan, expectedHead),
    validateIntegratedEvidence(plan, expectedHead),
  ];
  const evidence = new Map();
  for (const map of maps) {
    for (const [id, digest] of map) {
      requireCondition(!evidence.has(id), `Duplicate private evidence child ${id}.`);
      evidence.set(id, digest);
    }
  }
  return evidence;
}
