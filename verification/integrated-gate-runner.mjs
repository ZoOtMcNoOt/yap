import { spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  integratedGateCellDefinitionSha256,
  integratedGateManifestSha256,
  validateIntegratedGateManifest,
  validateIntegratedGateReceipt,
} from "./integrated-gate-receipt.mjs";
import {
  validateIntegratedPrivateEvidence,
  validateIntegratedPrivateEvidencePlan,
} from "./integrated-private-evidence.mjs";
import {
  INTEGRATED_GATE_BYTE_LIMITS,
  readBoundedJsonArtifact,
  serializeBoundedJson,
  sha256BoundedRegularFile,
} from "./integrated-gate-artifact-bounds.mjs";
import { executeBoundedCommand } from "./bounded-command-execution.mjs";
import {
  reserveGitHubGateAdmission,
  validateGitHubGateAdmission,
} from "./github-gate-admission.mjs";

const SHA40 = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const TOKEN = /^[0-9a-f]{64}$/;
const RUNNER_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));
const REPOSITORY_ROOT = path.resolve(RUNNER_DIRECTORY, "..");
const MANIFEST_PATH = path.join(
  RUNNER_DIRECTORY,
  "integrated-product-checkpoint-gate.json",
);
const LEGACY_MANIFEST_PATH = path.join(
  RUNNER_DIRECTORY,
  "integrated-preprocessing-language-routing-gate.json",
);
const IDENTITY_ACCESS_MANIFEST_PATH = path.join(
  RUNNER_DIRECTORY,
  "integrated-identity-access-gate.json",
);
const CANONICAL_MANIFEST_CONTRACTS = Object.freeze([
  Object.freeze({
    path: IDENTITY_ACCESS_MANIFEST_PATH,
    gateId: "integrated-identity-access",
  }),
  Object.freeze({
    path: MANIFEST_PATH,
    gateId: "integrated-product-checkpoint",
  }),
  Object.freeze({
    path: LEGACY_MANIFEST_PATH,
    gateId: "integrated-preprocessing-language-routing",
  }),
]);
const INTEGRATED_GATE_IDS = new Set([
  "integrated-identity-access",
  "integrated-product-checkpoint",
  "integrated-preprocessing-language-routing",
]);
const LEGACY_ADMISSION_AUTHORITY_ROOT = path.join(
  os.homedir(),
  ".yap-private-gate-admissions",
);
const LEGACY_ADMISSION_KEYS = new Set([
  "schemaVersion",
  "gateId",
  "checkedHead",
  "manifestPath",
  "manifestSha256",
  "privatePlanPath",
  "privatePlanSha256",
  "attempt",
  "attemptToken",
  "admittedAt",
  "runDirectory",
  "commandLogDirectory",
  "candidateReceiptPath",
]);
const IDENTITY_ADMISSION_KEYS = new Set([
  ...LEGACY_ADMISSION_KEYS,
  "reservationPath",
  "reservationSha256",
  "statusAuthority",
]);
const LEGACY_RESERVATION_KEYS = new Set([
  "schemaVersion",
  "gateId",
  "checkedHead",
  "manifestSha256",
  "evidenceRoot",
  "reservedAt",
]);

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function samePath(left, right) {
  const normalizedLeft = path.normalize(left);
  const normalizedRight = path.normalize(right);
  return process.platform === "win32"
    ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

export function integratedGateCommandEnvironment(checkedHead, source = process.env) {
  const environment = {};
  const credentialName =
    /^(?:GH_TOKEN|GITHUB_TOKEN|GH_ENTERPRISE_TOKEN|GITHUB_ENTERPRISE_TOKEN)$/i;
  for (const [name, value] of Object.entries(source)) {
    if (!credentialName.test(name)) environment[name] = value;
  }
  environment.YAP_CHECKED_HEAD = checkedHead;
  return environment;
}

function normalizedRealPath(candidate, label, expectedType) {
  requireCondition(path.isAbsolute(candidate), `${label} must be absolute.`);
  requireCondition(existsSync(candidate), `${label} does not exist.`);
  const item = lstatSync(candidate);
  requireCondition(!item.isSymbolicLink(), `${label} must not be a symbolic link.`);
  if (expectedType === "file") {
    requireCondition(item.isFile(), `${label} must be a regular file.`);
  } else {
    requireCondition(item.isDirectory(), `${label} must be a directory.`);
  }
  const normalized = path.normalize(candidate);
  const real = path.normalize(realpathSync.native(candidate));
  requireCondition(
    process.platform === "win32"
      ? normalized.toLowerCase() === real.toLowerCase()
      : normalized === real,
    `${label} must not resolve through a redirected parent.`,
  );
  return real;
}

function requireOutsideRepository(candidate, label) {
  const relative = path.relative(REPOSITORY_ROOT, candidate);
  requireCondition(
    relative !== "" && (relative.startsWith("..") || path.isAbsolute(relative)),
    `${label} must stay outside the repository.`,
  );
}

function readExactJson(candidate, label, maximumBytes) {
  const real = normalizedRealPath(path.resolve(candidate), label, "file");
  return readBoundedJsonArtifact(real, label, maximumBytes);
}

function git(args) {
  const result = spawnSync("git", args, {
    cwd: REPOSITORY_ROOT,
    encoding: "utf8",
    windowsHide: true,
  });
  requireCondition(
    result.status === 0,
    `Git ${args.join(" ")} failed: ${(result.stderr || result.stdout).trim()}`,
  );
  return result.stdout.trim();
}

export function assertExactCleanGitHead(expectedHead) {
  requireCondition(SHA40.test(expectedHead ?? ""), "Checked head must be one lowercase Git SHA.");
  requireCondition(git(["rev-parse", "HEAD"]) === expectedHead, "Repository head changed.");
  requireCondition(
    git(["status", "--porcelain=v1", "--untracked-files=normal"]) === "",
    "Repository working tree is not clean.",
  );
}

export function assertGateRunnerNodeRuntime(nodeVersion = process.versions.node) {
  const major = Number.parseInt(nodeVersion.split(".")[0] ?? "", 10);
  requireCondition(
    major === 24,
    `The integrated gate runner requires Node 24.x LTS; current runtime is v${nodeVersion}. `
      + "The admitted attempt has not started. Switch to the version in .node-version.",
  );
}

function writeExclusiveJson(candidate, value, label, maximumBytes) {
  const bytes = serializeBoundedJson(value, label, maximumBytes);
  writeFileSync(candidate, bytes, {
    flag: "wx",
    mode: 0o600,
  });
}

export function reserveIntegratedGateAttemptDirectory({
  evidenceRoot,
  gateId,
  checkedHead,
  manifestSha256,
  statusClient,
  reservationAuthorityRoot,
}) {
  requireCondition(SHA40.test(checkedHead ?? ""), "Checked head is invalid.");
  requireCondition(SHA256.test(manifestSha256 ?? ""), "Manifest identity is invalid.");
  requireCondition(
    INTEGRATED_GATE_IDS.has(gateId),
    "Gate id is invalid.",
  );
  const canonicalEvidenceRoot = normalizedRealPath(
    path.resolve(evidenceRoot),
    "Private gate root",
    "directory",
  );
  if (gateId !== "integrated-identity-access") {
    const authorityRoot = reservationAuthorityRoot === undefined
      ? canonicalLegacyAdmissionAuthorityRoot()
      : normalizedRealPath(
        path.resolve(reservationAuthorityRoot),
        "Legacy admission reservation authority",
        "directory",
      );
    requireOutsideRepository(authorityRoot, "Legacy admission reservation authority");
    writeExclusiveJson(
      legacyIntegratedGateReservationPath({
        authorityRoot,
        gateId,
        checkedHead,
        manifestSha256,
      }),
      {
        schemaVersion: 1,
        gateId,
        checkedHead,
        manifestSha256,
        evidenceRoot: canonicalEvidenceRoot,
        reservedAt: new Date().toISOString(),
      },
      "Legacy gate admission reservation",
      INTEGRATED_GATE_BYTE_LIMITS.runMarkerBytes,
    );
    const runDirectory = path.join(
      canonicalEvidenceRoot,
      `${gateId}-${checkedHead}-${manifestSha256.slice(0, 12)}`,
    );
    mkdirSync(runDirectory, { recursive: false, mode: 0o700 });
    return Object.freeze({
      runDirectory,
      reservedAt: new Date().toISOString(),
    });
  }
  const remoteReservation = reserveGitHubGateAdmission({
    gateId,
    checkedHead,
    manifestSha256,
    evidenceRoot: canonicalEvidenceRoot,
    reservedAt: new Date().toISOString(),
    nonce: randomBytes(32).toString("hex"),
    ...(statusClient ? { client: statusClient } : {}),
  });
  const runDirectory = path.join(
    canonicalEvidenceRoot,
    `${gateId}-${checkedHead}-${manifestSha256.slice(0, 12)}`,
  );
  mkdirSync(runDirectory, { recursive: false, mode: 0o700 });
  const reservationPath = path.join(runDirectory, "remote-admission.json");
  const reservation = {
    schemaVersion: 2,
    claim: remoteReservation.claim,
    statusAuthority: remoteReservation.statusAuthority,
  };
  const reservationBytes = serializeBoundedJson(
    reservation,
    "Gate admission reservation",
    INTEGRATED_GATE_BYTE_LIMITS.runMarkerBytes,
  );
  writeExclusiveJson(
    reservationPath,
    reservation,
    "Gate admission reservation",
    INTEGRATED_GATE_BYTE_LIMITS.runMarkerBytes,
  );
  return Object.freeze({
    runDirectory,
    reservationPath,
    reservationSha256: sha256(reservationBytes),
    reservedAt: remoteReservation.claim.reservedAt,
    statusAuthority: remoteReservation.statusAuthority,
  });
}

function canonicalLegacyAdmissionAuthorityRoot() {
  const home = normalizedRealPath(os.homedir(), "User home", "directory");
  const authorityRoot = path.join(
    home,
    path.basename(LEGACY_ADMISSION_AUTHORITY_ROOT),
  );
  if (!existsSync(authorityRoot)) {
    mkdirSync(authorityRoot, { recursive: false, mode: 0o700 });
  }
  return normalizedRealPath(
    authorityRoot,
    "Legacy admission reservation authority",
    "directory",
  );
}

function legacyIntegratedGateReservationPath({
  authorityRoot,
  gateId,
  checkedHead,
  manifestSha256,
}) {
  return path.join(
    authorityRoot,
    `${gateId}-${checkedHead}-${manifestSha256}.json`,
  );
}

export function validateLegacyIntegratedGateReservationValue(reservation) {
  requireCondition(
    reservation
      && typeof reservation === "object"
      && !Array.isArray(reservation)
      && Object.keys(reservation).length === LEGACY_RESERVATION_KEYS.size
      && Object.keys(reservation).every((key) => LEGACY_RESERVATION_KEYS.has(key)),
    "Legacy gate admission reservation fields differ from the frozen contract.",
  );
  requireCondition(
    reservation.schemaVersion === 1
      && INTEGRATED_GATE_IDS.has(reservation.gateId)
      && SHA40.test(reservation.checkedHead ?? "")
      && SHA256.test(reservation.manifestSha256 ?? "")
      && typeof reservation.evidenceRoot === "string"
      && reservation.evidenceRoot.length > 0
      && Number.isFinite(Date.parse(reservation.reservedAt)),
    "Legacy gate admission reservation is invalid.",
  );
  return reservation;
}

function assertLegacyIntegratedGateReservation(admission, runDirectory) {
  const reservationPath = legacyIntegratedGateReservationPath({
    authorityRoot: canonicalLegacyAdmissionAuthorityRoot(),
    gateId: admission.gateId,
    checkedHead: admission.checkedHead,
    manifestSha256: admission.manifestSha256,
  });
  const reservation = validateLegacyIntegratedGateReservationValue(
    readExactJson(
      reservationPath,
      "Legacy gate admission reservation",
      INTEGRATED_GATE_BYTE_LIMITS.runMarkerBytes,
    ).value,
  );
  requireCondition(
    reservation.gateId === admission.gateId
      && reservation.checkedHead === admission.checkedHead
      && reservation.manifestSha256 === admission.manifestSha256
      && samePath(reservation.evidenceRoot, path.dirname(runDirectory)),
    "Legacy gate admission reservation does not match the admitted attempt.",
  );
}

function assertIntegratedGateReservation(admission, runDirectory) {
  const reservationPath = normalizedRealPath(
    path.resolve(admission.reservationPath),
    "Gate admission reservation",
    "file",
  );
  requireCondition(
    samePath(reservationPath, path.join(runDirectory, "remote-admission.json")),
    "Gate admission reservation moved away from its run directory.",
  );
  const reservationFile = readExactJson(
    reservationPath,
    "Gate admission reservation",
    INTEGRATED_GATE_BYTE_LIMITS.runMarkerBytes,
  );
  const reservation = reservationFile.value;
  requireCondition(
    reservation
      && typeof reservation === "object"
      && !Array.isArray(reservation)
      && Object.keys(reservation).sort().join("\0")
        === [
          "claim",
          "schemaVersion",
          "statusAuthority",
        ].sort().join("\0"),
    "Gate admission reservation fields differ from the frozen contract.",
  );
  requireCondition(
    reservation.schemaVersion === 2
      && sha256(reservationFile.bytes) === admission.reservationSha256
      && reservation.claim.gateId === admission.gateId
      && reservation.claim.checkedHead === admission.checkedHead
      && reservation.claim.manifestSha256 === admission.manifestSha256
      && reservation.claim.reservedAt === admission.admittedAt
      && samePath(reservation.claim.evidenceRoot, path.dirname(runDirectory))
      && JSON.stringify(reservation.statusAuthority) === JSON.stringify(admission.statusAuthority),
    "Gate admission reservation does not match the admitted attempt.",
  );
  validateGitHubGateAdmission({
    claim: reservation.claim,
    expectedStatusAuthority: reservation.statusAuthority,
  });
}

function validateAdmission(value) {
  requireCondition(value && typeof value === "object" && !Array.isArray(value),
    "Gate admission must be an object.");
  requireCondition(
    INTEGRATED_GATE_IDS.has(value.gateId),
    "Gate admission has the wrong gate id.",
  );
  const admissionKeys = value.gateId === "integrated-identity-access"
    ? IDENTITY_ADMISSION_KEYS
    : LEGACY_ADMISSION_KEYS;
  const keys = Object.keys(value);
  requireCondition(
    keys.length === admissionKeys.size
      && keys.every((key) => admissionKeys.has(key)),
    "Gate admission fields differ from the frozen contract.",
  );
  requireCondition(value.schemaVersion === 1, "Gate admission schemaVersion must be 1.");
  requireCondition(SHA40.test(value.checkedHead ?? ""), "Gate admission head is invalid.");
  requireCondition(SHA256.test(value.manifestSha256 ?? ""), "Manifest identity is invalid.");
  requireCondition(SHA256.test(value.privatePlanSha256 ?? ""), "Private plan identity is invalid.");
  if (value.gateId === "integrated-identity-access") {
    requireCondition(SHA256.test(value.reservationSha256 ?? ""),
      "Reservation identity is invalid.");
    requireCondition(
      typeof value.reservationPath === "string"
        && value.statusAuthority
        && typeof value.statusAuthority === "object"
        && !Array.isArray(value.statusAuthority),
      "Remote reservation identity is invalid.",
    );
  }
  requireCondition(value.attempt === 1, "Only one admitted attempt is allowed.");
  requireCondition(TOKEN.test(value.attemptToken ?? ""), "Attempt token is invalid.");
  requireCondition(Number.isFinite(Date.parse(value.admittedAt)), "Admission timestamp is invalid.");
  return value;
}

function verifiedCommandLogDirectory(admission) {
  const runDirectory = normalizedRealPath(
    path.resolve(admission.runDirectory),
    "Gate run directory",
    "directory",
  );
  requireOutsideRepository(runDirectory, "Gate run directory");
  const commandLogDirectory = normalizedRealPath(
    path.join(runDirectory, "command-logs"),
    "Command log directory",
    "directory",
  );
  requireCondition(
    samePath(admission.commandLogDirectory, commandLogDirectory),
    "Command logs do not belong to the admitted run directory.",
  );
  return commandLogDirectory;
}

function verifiedAdmissionPaths(admissionFile, admission) {
  const runDirectory = normalizedRealPath(
    path.dirname(admissionFile.path),
    "Gate run directory",
    "directory",
  );
  requireOutsideRepository(runDirectory, "Gate run directory");
  requireCondition(
    samePath(admissionFile.path, path.join(runDirectory, "admission.json"))
      && samePath(admission.runDirectory, runDirectory),
    "Gate admission moved away from its run directory.",
  );
  const commandLogDirectory = verifiedCommandLogDirectory({
    ...admission,
    runDirectory,
  });
  const candidateReceiptPath = path.join(
    runDirectory,
    "candidate-receipt.json",
  );
  requireCondition(
    samePath(admission.candidateReceiptPath, candidateReceiptPath),
    "Candidate receipt does not belong to the admitted run directory.",
  );
  return Object.freeze({
    runDirectory,
    commandLogDirectory,
    candidateReceiptPath,
  });
}

export function loadIntegratedGateManifestSelection(manifestPath) {
  requireCondition(
    typeof manifestPath === "string" && manifestPath.length > 0,
    "An explicit integrated gate manifest is required.",
  );
  const selectedPath = normalizedRealPath(
    path.resolve(manifestPath),
    "Integrated gate manifest",
    "file",
  );
  const canonicalManifestContracts = CANONICAL_MANIFEST_CONTRACTS.map((contract) => ({
    gateId: contract.gateId,
    path: normalizedRealPath(
      contract.path,
      "Canonical integrated gate manifest",
      "file",
    ),
  }));
  const manifestContract = canonicalManifestContracts.find(
    ({ path: candidate }) => samePath(candidate, selectedPath),
  );
  requireCondition(
    manifestContract,
    "The runner accepts only a repository-owned integrated gate manifest.",
  );
  const manifestFile = readBoundedJsonArtifact(
    selectedPath,
    "Integrated gate manifest",
    INTEGRATED_GATE_BYTE_LIMITS.gateManifestBytes,
  );
  const manifest = validateIntegratedGateManifest(manifestFile.value);
  requireCondition(
    manifest.gateId === manifestContract.gateId,
    "The gate manifest path and behavior identity do not match.",
  );
  return Object.freeze({
    manifest,
    manifestFile,
    manifestSha256: integratedGateManifestSha256(manifestFile.bytes),
  });
}

export function assertIntegratedGateManifestMatchesAdmission(
  admission,
  manifestSelection,
) {
  requireCondition(
    typeof admission?.manifestPath === "string"
      && typeof manifestSelection?.manifestFile?.path === "string"
      && samePath(admission.manifestPath, manifestSelection.manifestFile.path),
    "Selected gate manifest does not match the admitted manifest.",
  );
  requireCondition(
    admission.gateId === manifestSelection.manifest.gateId,
    "Selected gate identity does not match the admitted gate.",
  );
  requireCondition(
    admission.manifestSha256 === manifestSelection.manifestSha256,
    "Selected gate manifest bytes do not match the admitted manifest.",
  );
}

function loadFrozenInputs({
  manifestPath,
  manifestSelection,
  privatePlanPath,
  expectedHead,
}) {
  const selectedManifest = manifestSelection
    ?? loadIntegratedGateManifestSelection(manifestPath);
  const privatePlanFile = readExactJson(
    privatePlanPath,
    "Private evidence plan",
    INTEGRATED_GATE_BYTE_LIMITS.privatePlanBytes,
  );
  requireOutsideRepository(privatePlanFile.path, "Private evidence plan");
  const privatePlan = validateIntegratedPrivateEvidencePlan(privatePlanFile.value, {
    expectedHead,
    repositoryRoot: REPOSITORY_ROOT,
  });
  return {
    manifest: selectedManifest.manifest,
    manifestFile: selectedManifest.manifestFile,
    manifestSha256: selectedManifest.manifestSha256,
    privatePlan,
    privatePlanFile,
  };
}

export function admitIntegratedGateAttempt({
  checkedHead,
  evidenceRoot,
  manifestPath,
  privatePlanPath,
}) {
  const manifestSelection = loadIntegratedGateManifestSelection(manifestPath);
  assertExactCleanGitHead(checkedHead);
  const root = normalizedRealPath(path.resolve(evidenceRoot), "Private gate root", "directory");
  requireOutsideRepository(root, "Private gate root");
  const frozen = loadFrozenInputs({
    manifestSelection,
    privatePlanPath,
    expectedHead: checkedHead,
  });
  validateIntegratedPrivateEvidencePlan(frozen.privatePlan, {
    expectedHead: checkedHead,
    repositoryRoot: REPOSITORY_ROOT,
    requireDestinationsAbsent: true,
  });

  const manifestSha256 = frozen.manifestSha256;
  const reservation = reserveIntegratedGateAttemptDirectory({
    evidenceRoot: root,
    gateId: frozen.manifest.gateId,
    checkedHead,
    manifestSha256,
  });
  const { runDirectory } = reservation;
  const commandLogDirectory = path.join(runDirectory, "command-logs");
  mkdirSync(commandLogDirectory, { recursive: false, mode: 0o700 });
  const admission = {
    schemaVersion: 1,
    gateId: frozen.manifest.gateId,
    checkedHead,
    manifestPath: frozen.manifestFile.path,
    manifestSha256,
    privatePlanPath: frozen.privatePlanFile.path,
    privatePlanSha256: sha256(frozen.privatePlanFile.bytes),
    attempt: 1,
    attemptToken: randomBytes(32).toString("hex"),
    admittedAt: reservation.reservedAt,
    runDirectory,
    commandLogDirectory,
    candidateReceiptPath: path.join(runDirectory, "candidate-receipt.json"),
    ...(frozen.manifest.gateId === "integrated-identity-access"
      ? {
        reservationPath: reservation.reservationPath,
        reservationSha256: reservation.reservationSha256,
        statusAuthority: reservation.statusAuthority,
      }
      : {}),
  };
  const admissionPath = path.join(runDirectory, "admission.json");
  writeExclusiveJson(
    admissionPath,
    admission,
    "Gate admission",
    INTEGRATED_GATE_BYTE_LIMITS.admissionBytes,
  );
  return Object.freeze({ admissionPath, ...admission });
}

export async function runCommandCell(
  cell,
  admission,
  { maximumLogBytes = INTEGRATED_GATE_BYTE_LIMITS.commandLogBytes } = {},
) {
  const cwd = path.resolve(REPOSITORY_ROOT, cell.cwd);
  const relative = path.relative(REPOSITORY_ROOT, cwd);
  requireCondition(
    relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative)),
    `Cell ${cell.id} escaped the repository.`,
  );
  const commandLogDirectory = verifiedCommandLogDirectory(admission);
  const logPath = path.join(commandLogDirectory, `${cell.id}.log`);
  const startedAt = new Date().toISOString();
  process.stdout.write(`[gate] ${cell.id}: running\n`);
  const commandResult = await executeBoundedCommand({
    command: cell.command,
    cwd,
    environment: integratedGateCommandEnvironment(admission.checkedHead),
    label: `Cell ${cell.id}`,
    logPath,
    expectedLogDirectory: commandLogDirectory,
    maximumLogBytes,
  });
  requireCondition(
    commandResult.exitCode === 0,
    `Cell ${cell.id} failed with code ${String(commandResult.exitCode)} `
      + `and signal ${String(commandResult.signal)}; inspect its bounded private log.`,
  );
  assertExactCleanGitHead(admission.checkedHead);
  const finishedAt = new Date().toISOString();
  process.stdout.write(`[gate] ${cell.id}: passed\n`);
  return {
    id: cell.id,
    executor: cell.executor,
    checkedHead: admission.checkedHead,
    definitionSha256: integratedGateCellDefinitionSha256(cell),
    evidenceSha256: commandResult.evidenceSha256,
    attempt: 1,
    status: "passed",
    startedAt,
    finishedAt,
  };
}

function portIsOpen(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port });
    const finish = (value) => {
      socket.destroy();
      resolve(value);
    };
    socket.setTimeout(750);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

async function assertNoRetainedLocalOwners() {
  requireCondition(!(await portIsOpen(18_765)), "Port 18765 still has a local listener.");
  if (process.platform !== "win32") return;
  const result = spawnSync("tasklist.exe", ["/FO", "CSV", "/NH"], {
    encoding: "utf8",
    windowsHide: true,
  });
  requireCondition(result.status === 0, "Could not inspect retained Windows processes.");
  requireCondition(
    !/^"(?:yap-desktop|msedgedriver)\.exe",/im.test(result.stdout),
    "A Yap desktop or WebDriver process remains after the candidate gate.",
  );
}

function privateCellReceipt(cell, evidenceSha256, admission, validatedAt) {
  requireCondition(SHA256.test(evidenceSha256 ?? ""),
    `Private evidence identity is missing for ${cell.id}.`);
  return {
    id: cell.id,
    executor: cell.executor,
    checkedHead: admission.checkedHead,
    definitionSha256: integratedGateCellDefinitionSha256(cell),
    evidenceSha256,
    attempt: 1,
    status: "passed",
    startedAt: admission.admittedAt,
    finishedAt: validatedAt,
  };
}

function nestedFailures(error) {
  return error instanceof AggregateError
    ? error.errors.flatMap((nested) => nestedFailures(nested))
    : [error];
}

export function integratedGateFailureRecord(admission, failure) {
  const causes = nestedFailures(failure);
  const typedCause = causes.find(
    (cause) => cause && typeof cause.code === "string",
  );
  const messages = causes.map(
    (cause) => cause instanceof Error ? cause.message : String(cause),
  );
  const message = [
    failure instanceof Error ? failure.message : String(failure),
    ...messages,
  ].filter((value, index, values) => value && values.indexOf(value) === index)
    .join(" Causes: ")
    .slice(0, 16_384);
  return {
    schemaVersion: 2,
    checkedHead: admission.checkedHead,
    failedAt: new Date().toISOString(),
    code: typedCause?.code ?? "INTEGRATED_GATE_FAILED",
    message,
  };
}

export async function completeIntegratedGateAttempt({
  admissionPath,
  attemptToken,
  manifestPath,
}) {
  const admissionFile = readExactJson(
    admissionPath,
    "Gate admission",
    INTEGRATED_GATE_BYTE_LIMITS.admissionBytes,
  );
  requireOutsideRepository(admissionFile.path, "Gate admission");
  const admission = validateAdmission(admissionFile.value);
  requireCondition(admission.attemptToken === attemptToken, "Attempt token does not match.");
  const manifestSelection = loadIntegratedGateManifestSelection(manifestPath);
  assertIntegratedGateManifestMatchesAdmission(admission, manifestSelection);
  const admittedPaths = verifiedAdmissionPaths(admissionFile, admission);
  if (admission.gateId === "integrated-identity-access") {
    assertIntegratedGateReservation(admission, admittedPaths.runDirectory);
  } else {
    assertLegacyIntegratedGateReservation(admission, admittedPaths.runDirectory);
  }
  const executionAdmission = Object.freeze({
    ...admission,
    ...admittedPaths,
  });
  for (const marker of ["running.json", "failed.json"]) {
    requireCondition(
      !existsSync(path.join(admittedPaths.runDirectory, marker)),
      "This checked-head attempt has already started or finished.",
    );
  }
  requireCondition(
    !existsSync(admittedPaths.candidateReceiptPath),
    "A candidate receipt already exists for this attempt.",
  );

  const frozen = loadFrozenInputs({
    manifestSelection,
    privatePlanPath: admission.privatePlanPath,
    expectedHead: admission.checkedHead,
  });
  requireCondition(
    integratedGateManifestSha256(frozen.manifestFile.bytes) === admission.manifestSha256,
    "Gate manifest changed after admission.",
  );
  requireCondition(
    sha256(frozen.privatePlanFile.bytes) === admission.privatePlanSha256,
    "Private evidence plan changed after admission.",
  );
  assertExactCleanGitHead(admission.checkedHead);
  assertGateRunnerNodeRuntime();
  writeExclusiveJson(
    path.join(admittedPaths.runDirectory, "running.json"),
    {
      schemaVersion: 1,
      checkedHead: admission.checkedHead,
      startedAt: new Date().toISOString(),
    },
    "Gate running marker",
    INTEGRATED_GATE_BYTE_LIMITS.runMarkerBytes,
  );

  const commandReceipts = new Map();
  try {
    for (const cell of frozen.manifest.candidateCells) {
      if (cell.executor === "command") {
        commandReceipts.set(
          cell.id,
          await runCommandCell(cell, executionAdmission),
        );
      }
    }
    assertExactCleanGitHead(admission.checkedHead);
    const privateEvidence = validateIntegratedPrivateEvidence(
      frozen.privatePlan,
      admission.checkedHead,
    );
    await assertNoRetainedLocalOwners();
    assertExactCleanGitHead(admission.checkedHead);
    const privateValidatedAt = new Date().toISOString();
    const children = frozen.manifest.candidateCells.map((cell) => {
      if (cell.executor === "command") return commandReceipts.get(cell.id);
      return privateCellReceipt(
        cell,
        privateEvidence.get(cell.id),
        admission,
        privateValidatedAt,
      );
    });
    requireCondition(children.every(Boolean), "Candidate receipt is missing a child.");
    const bindsAdmission = frozen.manifest.gateId === "integrated-identity-access";
    const admissionSha256 = sha256(admissionFile.bytes);
    const receipt = {
      schemaVersion: bindsAdmission ? 3 : 2,
      gateId: frozen.manifest.gateId,
      scope: "candidate",
      checkedHead: admission.checkedHead,
      candidateHead: admission.checkedHead,
      candidateReceiptSha256: null,
      manifestSha256: admission.manifestSha256,
      ...(bindsAdmission ? { admissionSha256 } : {}),
      status: "passed",
      startedAt: admission.admittedAt,
      finishedAt: new Date().toISOString(),
      children,
    };
    validateIntegratedGateReceipt({
      receipt,
      manifest: frozen.manifest,
      manifestSha256: admission.manifestSha256,
      expectedHead: admission.checkedHead,
      expectedAdmissionSha256: bindsAdmission ? admissionSha256 : null,
      expectedScope: "candidate",
    });
    writeExclusiveJson(
      admittedPaths.candidateReceiptPath,
      receipt,
      "Candidate receipt",
      INTEGRATED_GATE_BYTE_LIMITS.candidateReceiptBytes,
    );
    return Object.freeze({
      candidateReceiptPath: admittedPaths.candidateReceiptPath,
      checkedHead: admission.checkedHead,
      childCount: receipt.children.length,
      manifestSha256: admission.manifestSha256,
    });
  } catch (error) {
    let failure = error;
    try {
      await assertNoRetainedLocalOwners();
    } catch (cleanupError) {
      failure = new AggregateError(
        [error, cleanupError],
        "The candidate gate failed and local ownership was not fully released.",
      );
    }
    const failedPath = path.join(admittedPaths.runDirectory, "failed.json");
    if (!existsSync(failedPath)) {
      writeExclusiveJson(
        failedPath,
        integratedGateFailureRecord(admission, failure),
        "Gate failure marker",
        INTEGRATED_GATE_BYTE_LIMITS.runMarkerBytes,
      );
    }
    throw failure;
  }
}

export function validateCompletedIntegratedGateAttempt(admissionPath) {
  const admissionFile = readExactJson(
    admissionPath,
    "Gate admission",
    INTEGRATED_GATE_BYTE_LIMITS.admissionBytes,
  );
  requireOutsideRepository(admissionFile.path, "Gate admission");
  const admission = validateAdmission(admissionFile.value);
  const admittedPaths = verifiedAdmissionPaths(admissionFile, admission);
  if (admission.gateId === "integrated-identity-access") {
    assertIntegratedGateReservation(admission, admittedPaths.runDirectory);
  } else {
    assertLegacyIntegratedGateReservation(admission, admittedPaths.runDirectory);
  }
  const running = readExactJson(
    path.join(admittedPaths.runDirectory, "running.json"),
    "Gate running marker",
    INTEGRATED_GATE_BYTE_LIMITS.runMarkerBytes,
  );
  requireCondition(
    running.value.schemaVersion === 1
      && running.value.checkedHead === admission.checkedHead,
    "Gate running marker does not match its admission.",
  );
  requireCondition(
    !existsSync(path.join(admittedPaths.runDirectory, "failed.json")),
    "The admitted candidate attempt is failed.",
  );
  const frozen = loadFrozenInputs({
    manifestPath: admission.manifestPath,
    privatePlanPath: admission.privatePlanPath,
    expectedHead: admission.checkedHead,
  });
  requireCondition(
    integratedGateManifestSha256(frozen.manifestFile.bytes) === admission.manifestSha256
      && sha256(frozen.privatePlanFile.bytes) === admission.privatePlanSha256,
    "Completed gate inputs changed after admission.",
  );
  const receiptFile = readExactJson(
    admittedPaths.candidateReceiptPath,
    "Candidate receipt",
    INTEGRATED_GATE_BYTE_LIMITS.candidateReceiptBytes,
  );
  validateIntegratedGateReceipt({
    receipt: receiptFile.value,
    manifest: frozen.manifest,
    manifestSha256: admission.manifestSha256,
    expectedHead: admission.checkedHead,
    expectedCandidateHead: admission.checkedHead,
    expectedAdmissionSha256: receiptFile.value.schemaVersion === 3
      ? sha256(admissionFile.bytes)
      : null,
    expectedScope: "candidate",
  });
  const privateEvidence = validateIntegratedPrivateEvidence(
    frozen.privatePlan,
    admission.checkedHead,
  );
  for (const [index, cell] of frozen.manifest.candidateCells.entries()) {
    const child = receiptFile.value.children[index];
    const expectedEvidenceSha256 = cell.executor === "command"
      ? sha256BoundedRegularFile(
        normalizedRealPath(
          path.join(admittedPaths.commandLogDirectory, `${cell.id}.log`),
          `Command log ${cell.id}`,
          "file",
        ),
        `Command log ${cell.id}`,
        INTEGRATED_GATE_BYTE_LIMITS.commandLogBytes,
      ).sha256
      : privateEvidence.get(cell.id);
    requireCondition(
      child.evidenceSha256 === expectedEvidenceSha256,
      `Candidate child ${cell.id} no longer matches its admitted evidence.`,
    );
  }
  return Object.freeze({
    admission,
    candidateReceipt: receiptFile.value,
    candidateReceiptBytes: receiptFile.bytes,
    manifest: frozen.manifest,
    manifestSha256: admission.manifestSha256,
  });
}

function parseArguments(argv) {
  const [operation, ...rest] = argv;
  const values = new Map();
  for (let index = 0; index < rest.length; index += 2) {
    const name = rest[index];
    const value = rest[index + 1];
    requireCondition(
      name?.startsWith("--") && value !== undefined,
      "Runner arguments must be --name value pairs.",
    );
    requireCondition(!values.has(name.slice(2)), `Duplicate runner argument ${name}.`);
    values.set(name.slice(2), value);
  }
  return { operation, values };
}

export function parseIntegratedGateRunnerInvocation(argv) {
  const { operation, values } = parseArguments(argv);
  const requiredArguments = operation === "begin"
    ? ["checked-head", "evidence-root", "manifest", "private-plan"]
    : operation === "complete"
      ? ["admission", "attempt-token", "manifest"]
      : null;
  requireCondition(requiredArguments, "Operation must be begin or complete.");
  const hasExactArguments = values.size === requiredArguments.length
    && requiredArguments.every((name) => values.get(name));
  requireCondition(
    hasExactArguments,
    `${operation} requires exactly ${requiredArguments.map((name) => `--${name}`).join(", ")}.`,
  );
  if (operation === "begin") {
    return Object.freeze({
      operation,
      checkedHead: values.get("checked-head"),
      evidenceRoot: values.get("evidence-root"),
      manifestPath: values.get("manifest"),
      privatePlanPath: values.get("private-plan"),
    });
  }
  return Object.freeze({
    operation,
    admissionPath: values.get("admission"),
    attemptToken: values.get("attempt-token"),
    manifestPath: values.get("manifest"),
  });
}

async function runCli() {
  const invocation = parseIntegratedGateRunnerInvocation(process.argv.slice(2));
  if (invocation.operation === "begin") {
    const admission = admitIntegratedGateAttempt({
      checkedHead: invocation.checkedHead,
      evidenceRoot: invocation.evidenceRoot,
      manifestPath: invocation.manifestPath,
      privatePlanPath: invocation.privatePlanPath,
    });
    process.stdout.write(`${JSON.stringify(admission, null, 2)}\n`);
    return;
  }
  const result = await completeIntegratedGateAttempt({
    admissionPath: invocation.admissionPath,
    attemptToken: invocation.attemptToken,
    manifestPath: invocation.manifestPath,
  });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runCli().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
