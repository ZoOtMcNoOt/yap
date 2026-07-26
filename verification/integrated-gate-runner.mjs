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
const INTEGRATED_GATE_IDS = new Set([
  "integrated-product-checkpoint",
  "integrated-preprocessing-language-routing",
]);
const ADMISSION_KEYS = new Set([
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
}) {
  requireCondition(SHA40.test(checkedHead ?? ""), "Checked head is invalid.");
  requireCondition(SHA256.test(manifestSha256 ?? ""), "Manifest identity is invalid.");
  requireCondition(
    INTEGRATED_GATE_IDS.has(gateId),
    "Gate id is invalid.",
  );
  const runDirectory = path.join(
    evidenceRoot,
    `${gateId}-${checkedHead}-${manifestSha256.slice(0, 12)}`,
  );
  mkdirSync(runDirectory, { recursive: false, mode: 0o700 });
  return runDirectory;
}

function validateAdmission(value) {
  requireCondition(value && typeof value === "object" && !Array.isArray(value),
    "Gate admission must be an object.");
  const keys = Object.keys(value);
  requireCondition(
    keys.length === ADMISSION_KEYS.size
      && keys.every((key) => ADMISSION_KEYS.has(key)),
    "Gate admission fields differ from the frozen contract.",
  );
  requireCondition(value.schemaVersion === 1, "Gate admission schemaVersion must be 1.");
  requireCondition(
    INTEGRATED_GATE_IDS.has(value.gateId),
    "Gate admission has the wrong gate id.",
  );
  requireCondition(SHA40.test(value.checkedHead ?? ""), "Gate admission head is invalid.");
  requireCondition(SHA256.test(value.manifestSha256 ?? ""), "Manifest identity is invalid.");
  requireCondition(SHA256.test(value.privatePlanSha256 ?? ""), "Private plan identity is invalid.");
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

function loadFrozenInputs({ manifestPath, privatePlanPath, expectedHead }) {
  const manifestFile = readExactJson(
    manifestPath,
    "Integrated gate manifest",
    INTEGRATED_GATE_BYTE_LIMITS.gateManifestBytes,
  );
  const canonicalManifestContracts = [
    [MANIFEST_PATH, "integrated-product-checkpoint"],
    [LEGACY_MANIFEST_PATH, "integrated-preprocessing-language-routing"],
  ].map(([candidate, gateId]) => ({
    gateId,
    path: normalizedRealPath(
      candidate,
      "Canonical integrated gate manifest",
      "file",
    ).toLowerCase(),
  }));
  const manifestContract = canonicalManifestContracts.find(
    ({ path: candidate }) => candidate === manifestFile.path.toLowerCase(),
  );
  requireCondition(
    manifestContract,
    "The runner accepts only a repository-owned integrated gate manifest.",
  );
  const manifest = validateIntegratedGateManifest(manifestFile.value);
  requireCondition(
    manifest.gateId === manifestContract.gateId,
    "The gate manifest path and behavior identity do not match.",
  );
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
    manifest,
    manifestFile,
    privatePlan,
    privatePlanFile,
  };
}

export function admitIntegratedGateAttempt({
  checkedHead,
  evidenceRoot,
  manifestPath = MANIFEST_PATH,
  privatePlanPath,
}) {
  assertExactCleanGitHead(checkedHead);
  const root = normalizedRealPath(path.resolve(evidenceRoot), "Private gate root", "directory");
  requireOutsideRepository(root, "Private gate root");
  const frozen = loadFrozenInputs({
    manifestPath,
    privatePlanPath,
    expectedHead: checkedHead,
  });
  validateIntegratedPrivateEvidencePlan(frozen.privatePlan, {
    expectedHead: checkedHead,
    repositoryRoot: REPOSITORY_ROOT,
    requireDestinationsAbsent: true,
  });

  const manifestSha256 = integratedGateManifestSha256(frozen.manifestFile.bytes);
  const runDirectory = reserveIntegratedGateAttemptDirectory({
    evidenceRoot: root,
    gateId: frozen.manifest.gateId,
    checkedHead,
    manifestSha256,
  });
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
    admittedAt: new Date().toISOString(),
    runDirectory,
    commandLogDirectory,
    candidateReceiptPath: path.join(runDirectory, "candidate-receipt.json"),
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
    environment: { ...process.env, YAP_CHECKED_HEAD: admission.checkedHead },
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
}) {
  const admissionFile = readExactJson(
    admissionPath,
    "Gate admission",
    INTEGRATED_GATE_BYTE_LIMITS.admissionBytes,
  );
  requireOutsideRepository(admissionFile.path, "Gate admission");
  const admission = validateAdmission(admissionFile.value);
  requireCondition(admission.attemptToken === attemptToken, "Attempt token does not match.");
  const admittedPaths = verifiedAdmissionPaths(admissionFile, admission);
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
    manifestPath: admission.manifestPath,
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
    const receipt = {
      schemaVersion: 2,
      gateId: frozen.manifest.gateId,
      scope: "candidate",
      checkedHead: admission.checkedHead,
      candidateHead: admission.checkedHead,
      candidateReceiptSha256: null,
      manifestSha256: admission.manifestSha256,
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

async function runCli() {
  const { operation, values } = parseArguments(process.argv.slice(2));
  if (operation === "begin") {
    const checkedHead = values.get("checked-head");
    const evidenceRoot = values.get("evidence-root");
    const privatePlanPath = values.get("private-plan");
    requireCondition(checkedHead && evidenceRoot && privatePlanPath,
      "begin requires --checked-head, --evidence-root, and --private-plan.");
    const admission = admitIntegratedGateAttempt({
      checkedHead,
      evidenceRoot,
      privatePlanPath,
    });
    process.stdout.write(`${JSON.stringify(admission, null, 2)}\n`);
    return;
  }
  requireCondition(operation === "complete", "Operation must be begin or complete.");
  const admissionPath = values.get("admission");
  const attemptToken = values.get("attempt-token");
  requireCondition(admissionPath && attemptToken,
    "complete requires --admission and --attempt-token.");
  const result = await completeIntegratedGateAttempt({ admissionPath, attemptToken });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runCli().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
