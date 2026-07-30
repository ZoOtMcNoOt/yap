import {
  lstatSync,
  mkdtempSync,
  realpathSync,
  rmSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { executeBoundedCommand } from "./bounded-command-execution.mjs";
import { INTEGRATED_GATE_BYTE_LIMITS } from "./integrated-gate-artifact-bounds.mjs";
import { protectAndVerifyPrivateDirectory } from "./private-gate-artifacts.mjs";

const SHA40 = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const moduleDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(moduleDirectory, "..");
const desktopRoot = path.join(repositoryRoot, "desktop");
const forbiddenChildEnvironmentNames = new Set([
  "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
  "ACTIONS_RUNTIME_TOKEN",
  "GH_ENTERPRISE_TOKEN",
  "GH_TOKEN",
  "GITHUB_ENTERPRISE_TOKEN",
  "GITHUB_ENV",
  "GITHUB_OUTPUT",
  "GITHUB_PATH",
  "GITHUB_STEP_SUMMARY",
  "GITHUB_TOKEN",
]);

export const HOSTED_WINDOWS_RUNTIME_PROFILES = Object.freeze({
  "server-connector": Object.freeze({
    command: Object.freeze([
      "pwsh.exe",
      "-NoLogo",
      "-NoProfile",
      "-NonInteractive",
      "-File",
      path.join(repositoryRoot, "verification", "test-server-connector.ps1"),
    ]),
    cwd: repositoryRoot,
    label: "Hosted server-connector runtime",
    logName: "server-connector.log",
    timeoutMs: 15 * 60 * 1_000,
  }),
  "authenticated-server-connector": Object.freeze({
    command: Object.freeze([
      "pwsh.exe",
      "-NoLogo",
      "-NoProfile",
      "-NonInteractive",
      "-File",
      path.join(
        repositoryRoot,
        "verification",
        "test-authenticated-server-connector.ps1",
      ),
    ]),
    cwd: repositoryRoot,
    label: "Hosted authenticated server-connector runtime",
    logName: "authenticated-server-connector.log",
    timeoutMs: 15 * 60 * 1_000,
  }),
  "native-wdio": Object.freeze({
    command: Object.freeze([
      "pnpm.cmd",
      "exec",
      "wdio",
      "run",
      "./tests/wdio.required.conf.ts",
    ]),
    cwd: desktopRoot,
    label: "Hosted native WDIO runtime",
    logName: "native-wdio.log",
    timeoutMs: 30 * 60 * 1_000,
  }),
});

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

function verifiedRealDirectory(candidate, label) {
  requireCondition(
    typeof candidate === "string" && path.isAbsolute(candidate),
    `${label} must be one absolute path.`,
  );
  const normalized = path.normalize(candidate);
  const metadata = lstatSync(normalized);
  const real = path.normalize(realpathSync.native(normalized));
  requireCondition(
    metadata.isDirectory()
      && !metadata.isSymbolicLink()
      && samePath(normalized, real),
    `${label} must be one real directory.`,
  );
  return real;
}

function requireOutsideRepository(candidate, label) {
  const relative = path.relative(repositoryRoot, candidate);
  requireCondition(
    relative !== ""
      && (relative.startsWith("..") || path.isAbsolute(relative)),
    `${label} must remain outside the repository.`,
  );
}

function validateProfile(profile, profileName) {
  requireCondition(
    profile
      && Array.isArray(profile.command)
      && profile.command.length > 0
      && profile.command.every(
        (token) => typeof token === "string" && token.length > 0,
      )
      && typeof profile.cwd === "string"
      && path.isAbsolute(profile.cwd)
      && typeof profile.label === "string"
      && profile.label.length > 0
      && typeof profile.logName === "string"
      && /^[a-z0-9-]+\.log$/.test(profile.logName)
      && Number.isSafeInteger(profile.timeoutMs)
      && profile.timeoutMs > 0,
    `Hosted Windows runtime profile ${profileName} is invalid.`,
  );
  return profile;
}

export function resolveHostedWindowsRuntimeProfile(
  profileName,
  profiles = HOSTED_WINDOWS_RUNTIME_PROFILES,
) {
  requireCondition(
    typeof profileName === "string" && Object.hasOwn(profiles, profileName),
    "Hosted Windows runtime profile must be server-connector, "
      + "authenticated-server-connector, or native-wdio.",
  );
  return validateProfile(profiles[profileName], profileName);
}

export function hostedWindowsRuntimeEnvironment(
  checkedHead,
  source = process.env,
) {
  requireCondition(
    SHA40.test(checkedHead ?? ""),
    "Hosted Windows runtime checks require one exact lowercase checked-head SHA.",
  );
  const environment = {};
  for (const [name, value] of Object.entries(source)) {
    if (!forbiddenChildEnvironmentNames.has(name.toUpperCase())) {
      environment[name] = value;
    }
  }
  environment.YAP_CHECKED_HEAD = checkedHead;
  return environment;
}

function requireHostedWindowsBoundary(platform, environment) {
  requireCondition(
    platform === "win32",
    "Hosted Windows runtime checks require Windows.",
  );
  requireCondition(
    environment.GITHUB_ACTIONS === "true"
      && environment.RUNNER_OS === "Windows"
      && environment.YAP_RUNNER_ENVIRONMENT === "github-hosted",
    "Hosted Windows runtime checks require a disposable GitHub-hosted Windows runner.",
  );
  requireCondition(
    SHA40.test(environment.YAP_CHECKED_HEAD ?? ""),
    "YAP_CHECKED_HEAD must be the exact lowercase reviewed head SHA.",
  );
}

function requireCompletedContainment(result, profileName) {
  const evidence = result?.terminationEvidence;
  requireCondition(
    result?.exitCode === 0
      && result.signal === null
      && SHA256.test(result.evidenceSha256 ?? ""),
    `Hosted Windows runtime profile ${profileName} exited unsuccessfully.`,
  );
  requireCondition(
    evidence?.schemaVersion === 1
      && evidence.containment === "windows-job-object"
      && Number.isSafeInteger(evidence.rootProcessId)
      && evidence.rootProcessId > 0
      && evidence.assignedBeforeResume === true
      && evidence.terminationReason === "none"
      && evidence.terminateRequested === false
      && evidence.rootExited === true
      && evidence.activeProcessZeroObserved === true
      && evidence.activeProcessCount === 0
      && evidence.cleanupProven === true,
    `Hosted Windows runtime profile ${profileName} did not prove an empty owned Job.`,
  );
}

function attachCleanupFailure(primaryError, cleanupError) {
  const error = primaryError instanceof Error
    ? primaryError
    : new Error(String(primaryError));
  Object.defineProperty(error, "privateLogCleanupFailure", {
    configurable: false,
    enumerable: false,
    value: cleanupError,
    writable: false,
  });
  return error;
}

export async function runHostedWindowsRuntimeCheck({
  profileName,
  platform = process.platform,
  environment = process.env,
  profiles = HOSTED_WINDOWS_RUNTIME_PROFILES,
  executeCommand = executeBoundedCommand,
  writeOutput = (message) => console.log(message),
} = {}) {
  requireHostedWindowsBoundary(platform, environment);
  const profile = resolveHostedWindowsRuntimeProfile(profileName, profiles);
  const runnerTemp = verifiedRealDirectory(
    environment.RUNNER_TEMP,
    "GitHub runner temporary directory",
  );
  requireOutsideRepository(runnerTemp, "GitHub runner temporary directory");
  const createdRunDirectory = mkdtempSync(
    path.join(runnerTemp, "yap-hosted-runtime-"),
  );
  let runDirectory;
  try {
    runDirectory = protectAndVerifyPrivateDirectory(createdRunDirectory);
  } catch (error) {
    try {
      rmSync(createdRunDirectory, { recursive: true, force: true });
    } catch (cleanupError) {
      throw attachCleanupFailure(error, cleanupError);
    }
    throw error;
  }

  let result;
  let runtimeFailure = null;
  try {
    result = await executeCommand({
      command: [...profile.command],
      cwd: verifiedRealDirectory(profile.cwd, `${profileName} working directory`),
      environment: hostedWindowsRuntimeEnvironment(
        environment.YAP_CHECKED_HEAD,
        environment,
      ),
      label: profile.label,
      logPath: path.join(runDirectory, profile.logName),
      expectedLogDirectory: runDirectory,
      maximumLogBytes: INTEGRATED_GATE_BYTE_LIMITS.commandLogBytes,
      timeoutMs: profile.timeoutMs,
    });
    requireCompletedContainment(result, profileName);
  } catch (error) {
    runtimeFailure = error;
  } finally {
    try {
      rmSync(runDirectory, { recursive: true, force: true });
    } catch (cleanupError) {
      runtimeFailure = runtimeFailure === null
        ? cleanupError
        : attachCleanupFailure(runtimeFailure, cleanupError);
    }
  }
  if (runtimeFailure !== null) throw runtimeFailure;
  writeOutput(
    `HOSTED_WINDOWS_RUNTIME_CHECK=passed:${profileName}:${result.evidenceSha256}`,
  );
  return result;
}

async function main() {
  requireCondition(
    process.argv.length === 3,
    "Usage: node verification/run-hosted-windows-runtime-check.mjs <profile>",
  );
  await runHostedWindowsRuntimeCheck({ profileName: process.argv[2] });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
