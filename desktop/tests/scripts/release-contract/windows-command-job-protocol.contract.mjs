import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  BoundedCommandTimeoutError,
  BoundedCommandOutputLimitError,
} from "../../../../verification/bounded-command-execution.mjs";
import {
  cleanupUnprovenError,
  preservePrimaryError,
} from "../../../../verification/windows-command-job-errors.mjs";
import {
  cleanupWindowsSupervisorFiles,
  createWindowsSupervisorInvocation,
} from "../../../../verification/windows-command-job-protocol.mjs";
import {
  readWindowsSupervisorStatus,
} from "../../../../verification/windows-command-job-status.mjs";
import {
  interpretWindowsCommandResult,
} from "../../../../verification/windows-command-result.mjs";

const contractRoot = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(contractRoot, "..", "..", "..", "..");

function createCanonicalTemporaryDirectory(prefix) {
  return mkdtempSync(path.join(realpathSync.native(os.tmpdir()), prefix));
}

test("Windows Job status rejects completed cleanup without assignment or accounting zero", () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-job-status-");
  const supervisorIdentitySha256 = "a".repeat(64);
  const environmentSha256 = "e".repeat(64);
  const launchNonce = "b".repeat(64);
  const launchSpecSha256 = "c".repeat(64);
  const statusPath = path.join(root, "status.json");
  const protocol = {
    expectedLogDirectory: root,
    environmentSha256,
    launchNonce,
    launchSpecPath: path.join(root, "unused-launch.json"),
    launchSpecSha256,
    statusPath,
    supervisorIdentitySha256,
  };
  const status = {
    schemaVersion: 2,
    containment: "windows-job-object",
    environmentSha256,
    supervisorIdentitySha256,
    launchNonce,
    launchSpecSha256,
    outcome: "completed",
    rootProcessId: 1234,
    assignedBeforeResume: false,
    targetExitCode: 0,
    terminationRequested: false,
    rootExited: true,
    activeProcessCount: 0,
    activeProcessZeroObserved: true,
    cleanupProven: true,
    retainedDescendantDetected: false,
    retainedProcessNames: [],
    elapsedMilliseconds: 10,
    nativeErrorCode: null,
  };
  try {
    writeFileSync(statusPath, `${JSON.stringify(status)}\n`, { flag: "wx" });
    assert.throws(
      () => readWindowsSupervisorStatus(protocol),
      /cleanup was claimed without complete Job evidence/,
    );
    rmSync(statusPath);
    status.assignedBeforeResume = true;
    status.activeProcessZeroObserved = false;
    writeFileSync(statusPath, `${JSON.stringify(status)}\n`, { flag: "wx" });
    assert.throws(
      () => readWindowsSupervisorStatus(protocol),
      /cleanup was claimed without complete Job evidence/,
    );
    rmSync(statusPath);
    status.outcome = "supervisor-failure";
    status.targetExitCode = null;
    status.terminationRequested = true;
    status.activeProcessZeroObserved = true;
    status.retainedDescendantDetected = true;
    status.retainedProcessNames = ["pwsh"];
    status.nativeErrorCode = 5;
    writeFileSync(statusPath, `${JSON.stringify(status)}\n`, { flag: "wx" });
    const interpreted = interpretWindowsCommandResult({
      exitCode: 0,
      label: "Retained-descendant termination fixture",
      primaryError: null,
      protocol,
      signal: null,
    });
    assert.equal(
      interpreted.error.code,
      "INTEGRATED_GATE_COMMAND_SUPERVISOR_FAILED",
    );
    assert.equal(interpreted.error.nativeErrorCode, 5);
    assert.equal(interpreted.error.terminationEvidence.cleanupProven, true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("Windows Job status accepts proven pre-assignment supervisor cleanup", () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-preassignment-status-");
  const statusPath = path.join(root, "status.json");
  const protocol = {
    expectedLogDirectory: root,
    environmentSha256: "e".repeat(64),
    launchNonce: "b".repeat(64),
    launchSpecPath: path.join(root, "unused-launch.json"),
    launchSpecSha256: "c".repeat(64),
    statusPath,
    supervisorIdentitySha256: "a".repeat(64),
  };
  const status = {
    schemaVersion: 2,
    containment: "windows-job-object",
    environmentSha256: protocol.environmentSha256,
    supervisorIdentitySha256: protocol.supervisorIdentitySha256,
    launchNonce: protocol.launchNonce,
    launchSpecSha256: protocol.launchSpecSha256,
    outcome: "supervisor-failure",
    rootProcessId: 0,
    assignedBeforeResume: false,
    targetExitCode: null,
    terminationRequested: true,
    rootExited: false,
    activeProcessCount: 0,
    activeProcessZeroObserved: false,
    cleanupProven: true,
    retainedDescendantDetected: false,
    retainedProcessNames: [],
    elapsedMilliseconds: 10,
    nativeErrorCode: 5,
  };
  try {
    writeFileSync(statusPath, `${JSON.stringify(status)}\n`, { flag: "wx" });
    assert.deepEqual(readWindowsSupervisorStatus(protocol), status);
    rmSync(statusPath);
    protocol.launchNonce = "d".repeat(64);
    writeFileSync(statusPath, `${JSON.stringify(status)}\n`, { flag: "wx" });
    assert.throws(
      () => readWindowsSupervisorStatus(protocol),
      /status values differed from its contract/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("retained-descendant status remains authoritative over a racing timeout", () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-timeout-retained-status-");
  const statusPath = path.join(root, "status.json");
  const protocol = {
    expectedLogDirectory: root,
    environmentSha256: "e".repeat(64),
    launchNonce: "b".repeat(64),
    launchSpecPath: path.join(root, "unused-launch.json"),
    launchSpecSha256: "c".repeat(64),
    statusPath,
    supervisorIdentitySha256: "a".repeat(64),
  };
  const status = {
    schemaVersion: 2,
    containment: "windows-job-object",
    environmentSha256: protocol.environmentSha256,
    supervisorIdentitySha256: protocol.supervisorIdentitySha256,
    launchNonce: protocol.launchNonce,
    launchSpecSha256: protocol.launchSpecSha256,
    outcome: "retained-descendant",
    rootProcessId: 1234,
    assignedBeforeResume: true,
    targetExitCode: 0,
    terminationRequested: true,
    rootExited: true,
    activeProcessCount: 0,
    activeProcessZeroObserved: true,
    cleanupProven: true,
    retainedDescendantDetected: true,
    retainedProcessNames: ["pwsh"],
    elapsedMilliseconds: 5_010,
    nativeErrorCode: null,
  };
  try {
    writeFileSync(statusPath, `${JSON.stringify(status)}\n`, { flag: "wx" });
    const interpreted = interpretWindowsCommandResult({
      exitCode: 0,
      label: "Timeout/retained-descendant race fixture",
      primaryError: new BoundedCommandTimeoutError(
        "Timeout/retained-descendant race fixture",
        5_000,
      ),
      protocol,
      signal: null,
    });
    assert.equal(
      interpreted.error.code,
      "INTEGRATED_GATE_COMMAND_RETAINED_DESCENDANT",
    );
    assert.equal(
      interpreted.error.terminationEvidence.terminationReason,
      "retained-descendant",
    );
    assert.deepEqual(interpreted.error.retainedProcessNames, ["pwsh"]);
    assert.match(interpreted.error.message, /\(pwsh\)/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("unproven Windows cleanup preserves the typed output-limit error", () => {
  const primary = new BoundedCommandOutputLimitError(
    "Protocol fixture",
    1_024,
    1_025,
  );
  const cleanupFailure = cleanupUnprovenError(
    "Protocol fixture",
    new Error("control channel closed"),
  );
  const evidence = {
    schemaVersion: 1,
    containment: "windows-job-object",
    rootProcessId: null,
    assignedBeforeResume: false,
    terminationReason: "cleanup-unproven",
    terminateRequested: true,
    rootExited: false,
    activeProcessCount: null,
    activeProcessZeroObserved: false,
    cleanupProven: false,
  };
  const result = preservePrimaryError(primary, cleanupFailure, evidence);
  assert.equal(result, primary);
  assert.equal(result.code, "INTEGRATED_GATE_COMMAND_OUTPUT_LIMIT_EXCEEDED");
  assert.equal(result.maximumBytes, 1_024);
  assert.equal(result.observedBytes, 1_025);
  assert.equal(result.primaryError, primary);
  assert.equal(
    result.terminationFailure.code,
    "INTEGRATED_GATE_COMMAND_TERMINATION_UNVERIFIED",
  );
  assert.deepEqual(result.terminationEvidence, evidence);
  assert.equal(Object.keys(result).includes("primaryError"), false);
});

test("Windows supervisor cleanup attempts both private files", () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-job-cleanup-");
  const blockedLaunchPath = path.join(root, "launch-directory");
  const statusPath = path.join(root, "status.json");
  try {
    mkdirSync(blockedLaunchPath);
    writeFileSync(statusPath, "{}\n");
    assert.throws(
      () => cleanupWindowsSupervisorFiles({
        launchSpecPath: blockedLaunchPath,
        statusPath,
      }),
      /private files could not all be removed/,
    );
    assert.equal(existsSync(statusPath), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("Windows Job supervisor rejects a changed launch specification", {
  skip: process.platform !== "win32",
}, () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-job-launch-spec-");
  const markerPath = path.join(root, "target-ran");
  let protocol;
  try {
    protocol = createWindowsSupervisorInvocation(
      {
        executable: process.execPath,
        args: [
          "-e",
          `require("node:fs").writeFileSync(${JSON.stringify(markerPath)},"ran")`,
        ],
        cwd: repoRoot,
      },
      root,
      process.env,
    );
    appendFileSync(protocol.launchSpecPath, " ");
    const result = spawnSync(
      protocol.invocation.executable,
      protocol.invocation.args,
      {
        cwd: protocol.invocation.cwd,
        encoding: "utf8",
        env: process.env,
        input: protocol.environmentPrelude,
        maxBuffer: 64 * 1024,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      },
    );
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /launch specification changed before execution/);
    assert.equal(existsSync(markerPath), false);
    assert.equal(existsSync(protocol.statusPath), false);
  } finally {
    cleanupWindowsSupervisorFiles(protocol);
    rmSync(root, { recursive: true, force: true });
  }
});

test("Windows Job supervisor rejects changed source before the target runs", {
  skip: process.platform !== "win32",
}, () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-job-source-");
  const markerPath = path.join(root, "target-ran");
  let protocol;
  try {
    protocol = createWindowsSupervisorInvocation(
      {
        executable: process.execPath,
        args: [
          "-e",
          `require("node:fs").writeFileSync(${JSON.stringify(markerPath)},"ran")`,
        ],
        cwd: repoRoot,
      },
      root,
      process.env,
    );
    const encodedIndex = protocol.invocation.args.indexOf("-EncodedCommand") + 1;
    const decoded = Buffer.from(
      protocol.invocation.args[encodedIndex],
      "base64",
    ).toString("utf16le");
    const parameterMatch = decoded.match(
      /\$parameterBytes=\[Convert\]::FromBase64String\('([^']+)'\)/,
    );
    assert.ok(parameterMatch);
    const parameters = JSON.parse(
      Buffer.from(parameterMatch[1], "base64").toString("utf8"),
    );
    assert.equal(
      parameters.ExpectedCSharpSourceSha256,
      protocol.csharpSourceSha256,
    );
    parameters.ExpectedCSharpSourceSha256 = "d".repeat(64);
    const changedParametersBase64 = Buffer.from(
      JSON.stringify(parameters),
      "utf8",
    ).toString("base64");
    protocol.invocation.args[encodedIndex] = Buffer.from(
      decoded.replace(parameterMatch[1], changedParametersBase64),
      "utf16le",
    ).toString("base64");
    const result = spawnSync(
      protocol.invocation.executable,
      protocol.invocation.args,
      {
        cwd: protocol.invocation.cwd,
        encoding: "utf8",
        env: process.env,
        input: protocol.environmentPrelude,
        maxBuffer: 64 * 1024,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      },
    );
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /source changed before compilation/);
    assert.equal(existsSync(markerPath), false);
    assert.equal(existsSync(protocol.statusPath), false);
  } finally {
    cleanupWindowsSupervisorFiles(protocol);
    rmSync(root, { recursive: true, force: true });
  }
});
