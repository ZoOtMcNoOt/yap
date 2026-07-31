import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  executeBoundedCommand,
} from "../../../../verification/bounded-command-execution.mjs";
import {
  protectAndVerifyPrivateDirectory,
} from "../../../../verification/private-gate-artifacts.mjs";

const contractRoot = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(contractRoot, "..", "..", "..", "..");
const sha256 = (value) => createHash("sha256").update(value).digest("hex");

function createCanonicalTemporaryDirectory(prefix) {
  return protectAndVerifyPrivateDirectory(
    mkdtempSync(path.join(realpathSync.native(os.tmpdir()), prefix)),
  );
}

function createProtectedDirectory(parent, name) {
  const directory = path.join(parent, name);
  mkdirSync(directory);
  return protectAndVerifyPrivateDirectory(directory);
}

function processIsAlive(processId) {
  try {
    process.kill(processId, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") return false;
    throw error;
  }
}

function ownedPowerShellChildCommand(readyPath, childSource) {
  const escapedReadyPath = readyPath.replaceAll("'", "''");
  const escapedRootProcessIdPath = `${readyPath}.root-pid`.replaceAll("'", "''");
  const ownedChildSource = [
    `$rootProcessId = [int] [IO.File]::ReadAllText('${escapedRootProcessIdPath}');`,
    `[IO.File]::WriteAllText('${escapedReadyPath}', [string] $PID);`,
    "while (Get-Process -Id $rootProcessId -ErrorAction SilentlyContinue) {",
    "Start-Sleep -Milliseconds 10;",
    "}",
    childSource,
  ].join(" ");
  const childEncodedCommand = Buffer.from(
    ownedChildSource,
    "utf16le",
  ).toString("base64");
  const rootSource = [
    `[IO.File]::WriteAllText('${escapedRootProcessIdPath}', [string] $PID);`,
    "$child = Start-Process",
    "-FilePath (Get-Command pwsh.exe).Source",
    `-ArgumentList '-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand','${childEncodedCommand}'`,
    "-WindowStyle Hidden",
    "-PassThru;",
    "$readyDeadline = [DateTime]::UtcNow.AddSeconds(5);",
    `while (-not [IO.File]::Exists('${escapedReadyPath}')) {`,
    "if ([DateTime]::UtcNow -ge $readyDeadline) {",
    "Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue;",
    "exit 97;",
    "}",
    "Start-Sleep -Milliseconds 10;",
    "}",
    "exit 0",
  ].join(" ");
  return [
    "pwsh.exe",
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-EncodedCommand",
    Buffer.from(rootSource, "utf16le").toString("base64"),
  ];
}

test("bounded Windows commands allow owned descendants to drain naturally", {
  skip: process.platform !== "win32",
}, async () => {
  const root = createCanonicalTemporaryDirectory(
    "yap-gate-natural-descendant-drain-",
  );
  const commandLogDirectory = createProtectedDirectory(root, "command-logs");
  const readyPath = path.join(root, "child-ready");
  const completionPath = path.join(root, "child-completed");
  const escapedCompletionPath = completionPath.replaceAll("'", "''");
  try {
    const result = await executeBoundedCommand({
      command: ownedPowerShellChildCommand(
        readyPath,
        "Start-Sleep -Milliseconds 3000;"
          + ` [IO.File]::WriteAllText('${escapedCompletionPath}', 'completed')`,
      ),
      cwd: repoRoot,
      environment: process.env,
      label: "Natural-descendant-drain fixture",
      logPath: path.join(commandLogDirectory, "natural-descendant-drain.log"),
      expectedLogDirectory: commandLogDirectory,
      maximumLogBytes: 1_024,
      timeoutMs: 15_000,
    });
    assert.equal(result.exitCode, 0);
    assert.equal(result.terminationEvidence.terminationReason, "none");
    assert.equal(result.terminationEvidence.terminateRequested, false);
    assert.equal(result.terminationEvidence.activeProcessZeroObserved, true);
    assert.equal(result.terminationEvidence.activeProcessCount, 0);
    assert.equal(result.terminationEvidence.cleanupProven, true);
    const elapsedMilliseconds = Date.now() - statSync(readyPath).mtimeMs;
    assert.ok(
      elapsedMilliseconds < 12_000,
      "naturally draining descendants must settle within the focused contract bound",
    );
    assert.ok(
      elapsedMilliseconds >= 2_000,
      "the fixture must cross the former two-second drain boundary",
    );
    const childProcessId = Number.parseInt(readFileSync(readyPath, "utf8"), 10);
    assert.equal(readFileSync(completionPath, "utf8"), "completed");
    assert.equal(processIsAlive(childProcessId), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("bounded Windows commands reject and clean retained descendants", {
  skip: process.platform !== "win32",
}, async () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-retained-descendant-");
  const commandLogDirectory = createProtectedDirectory(root, "command-logs");
  const readyPath = path.join(root, "grandchild-ready");
  try {
    await assert.rejects(
      executeBoundedCommand({
        command: ownedPowerShellChildCommand(
          readyPath,
          "Start-Sleep -Seconds 30",
        ),
        cwd: repoRoot,
        environment: process.env,
        label: "Retained-descendant fixture",
        logPath: path.join(commandLogDirectory, "retained-descendant.log"),
        expectedLogDirectory: commandLogDirectory,
        maximumLogBytes: 1_024,
        timeoutMs: 15_000,
      }),
      (error) => {
        assert.equal(error.code, "INTEGRATED_GATE_COMMAND_RETAINED_DESCENDANT");
        assert.equal(error.rootExitCode, 0);
        assert.equal(
          error.terminationEvidence.terminationReason,
          "retained-descendant",
        );
        assert.equal(error.terminationEvidence.activeProcessZeroObserved, true);
        assert.equal(error.terminationEvidence.activeProcessCount, 0);
        assert.equal(error.terminationEvidence.cleanupProven, true);
        return true;
      },
    );
    assert.ok(
      Date.now() - statSync(readyPath).mtimeMs < 10_000,
      "retained descendants must be removed promptly after they become active",
    );
    const grandchildProcessId = Number.parseInt(readFileSync(readyPath, "utf8"), 10);
    assert.equal(processIsAlive(grandchildProcessId), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("nested bounded Windows commands retain independent Job ownership", {
  skip: process.platform !== "win32",
}, async () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-nested-command-");
  const outerLogDirectory = createProtectedDirectory(root, "outer-command-logs");
  const innerLogDirectory = createProtectedDirectory(root, "inner-command-logs");
  const readyPath = path.join(root, "inner-grandchild-ready");
  const resultPath = path.join(root, "inner-result.json");
  const maximumLogBytes = 1_024;
  const grandchildSource = Buffer.from(
    `require("node:fs").writeFileSync(${JSON.stringify(readyPath)},String(process.pid));`
      + "setTimeout(process.exit,30000,0);",
  ).toString("base64");
  const overflowingSource = [
    'const{spawn}=require("node:child_process");',
    'const{existsSync}=require("node:fs");',
    `const source=Buffer.from("${grandchildSource}","base64").toString("utf8");`,
    'spawn(process.execPath,["-e",source],{stdio:"ignore"});',
    `const ready=${JSON.stringify(readyPath)};`,
    `const overflow=()=>process.stdout.write(Buffer.alloc(${maximumLogBytes + 1},120));`,
    "const wait=()=>existsSync(ready)?overflow():setTimeout(wait,10);wait();",
    "setTimeout(process.exit,30000,0);",
  ].join("");
  const boundedCommandModuleUrl = pathToFileURL(path.join(
    repoRoot,
    "verification",
    "bounded-command-execution.mjs",
  )).href;
  const driverPath = path.join(root, "nested-command-driver.mjs");
  writeFileSync(driverPath, [
    `import { writeFileSync } from "node:fs";`,
    `import { executeBoundedCommand } from ${JSON.stringify(boundedCommandModuleUrl)};`,
    "try {",
    "  await executeBoundedCommand({",
    `    command: [process.execPath, "-e", ${JSON.stringify(overflowingSource)}],`,
    `    cwd: ${JSON.stringify(repoRoot)},`,
    "    environment: process.env,",
    '    label: "Nested bounded command",',
    `    logPath: ${JSON.stringify(path.join(innerLogDirectory, "inner.log"))},`,
    `    expectedLogDirectory: ${JSON.stringify(innerLogDirectory)},`,
    `    maximumLogBytes: ${maximumLogBytes},`,
    "    timeoutMs: 15_000,",
    "  });",
    `  writeFileSync(${JSON.stringify(resultPath)}, JSON.stringify({ unexpectedSuccess: true }));`,
    "  process.exitCode = 1;",
    "} catch (error) {",
    `  writeFileSync(${JSON.stringify(resultPath)}, JSON.stringify({`,
    "    code: error.code,",
    "    maximumBytes: error.maximumBytes,",
    "    observedBytes: error.observedBytes,",
    "    terminationEvidence: error.terminationEvidence,",
    "  }));",
    "  process.exitCode = error.code === "
      + '"INTEGRATED_GATE_COMMAND_OUTPUT_LIMIT_EXCEEDED" ? 0 : 1;',
    "}",
    "",
  ].join("\n"));
  try {
    const outerResult = await executeBoundedCommand({
      command: [process.execPath, driverPath],
      cwd: repoRoot,
      environment: process.env,
      label: "Outer bounded command",
      logPath: path.join(outerLogDirectory, "outer.log"),
      expectedLogDirectory: outerLogDirectory,
      maximumLogBytes: 64 * 1024,
      timeoutMs: 30_000,
    });
    assert.equal(outerResult.exitCode, 0);
    assert.equal(outerResult.terminationEvidence.assignedBeforeResume, true);
    assert.equal(outerResult.terminationEvidence.activeProcessZeroObserved, true);
    assert.equal(outerResult.terminationEvidence.cleanupProven, true);

    const innerResult = JSON.parse(readFileSync(resultPath, "utf8"));
    assert.equal(
      innerResult.code,
      "INTEGRATED_GATE_COMMAND_OUTPUT_LIMIT_EXCEEDED",
    );
    assert.equal(innerResult.maximumBytes, maximumLogBytes);
    assert.ok(innerResult.observedBytes > maximumLogBytes);
    assert.equal(innerResult.terminationEvidence.assignedBeforeResume, true);
    assert.equal(
      innerResult.terminationEvidence.activeProcessZeroObserved,
      true,
    );
    assert.equal(innerResult.terminationEvidence.activeProcessCount, 0);
    assert.equal(innerResult.terminationEvidence.cleanupProven, true);
    assert.notEqual(
      innerResult.terminationEvidence.rootProcessId,
      outerResult.terminationEvidence.rootProcessId,
    );
    const grandchildProcessId = Number.parseInt(readFileSync(readyPath, "utf8"), 10);
    assert.equal(processIsAlive(grandchildProcessId), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("bounded Windows commands preserve batch arguments, environment, bytes, and exit code", {
  skip: process.platform !== "win32",
}, async () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-batch-command-");
  const commandLogDirectory = createProtectedDirectory(root, "command-logs");
  const commandPath = path.join(root, "command-fixture.cmd");
  writeFileSync(
    commandPath,
    [
      "@echo off",
      'if not "%YAP_BOUNDED_COMMAND_FIXTURE%"=="environment value" exit /b 41',
      'if not "%~1"=="argument value" exit /b 42',
      "if defined PSExecutionPolicyPreference exit /b 43",
      "if defined PSModulePath exit /b 44",
      "<nul set /p =exact-output",
      "exit /b 37",
      "",
    ].join("\r\n"),
  );
  try {
    const environment = {
      ...process.env,
      YAP_BOUNDED_COMMAND_FIXTURE: "environment value",
    };
    delete environment.PSExecutionPolicyPreference;
    delete environment.PSModulePath;
    const result = await executeBoundedCommand({
      command: [commandPath, "argument value"],
      cwd: repoRoot,
      environment,
      label: "Batch command fixture",
      logPath: path.join(commandLogDirectory, "batch-command.log"),
      expectedLogDirectory: commandLogDirectory,
      maximumLogBytes: 1_024,
      timeoutMs: 15_000,
    });
    assert.equal(result.exitCode, 37);
    assert.equal(result.signal, null);
    assert.equal(result.evidenceSha256, sha256("exact-output"));
    assert.equal(
      readFileSync(path.join(commandLogDirectory, "batch-command.log"), "utf8"),
      "exact-output",
    );
    assert.equal(result.terminationEvidence.assignedBeforeResume, true);
    assert.equal(result.terminationEvidence.terminationReason, "none");
    assert.equal(result.terminationEvidence.terminateRequested, false);
    assert.equal(result.terminationEvidence.activeProcessZeroObserved, true);
    assert.equal(result.terminationEvidence.activeProcessCount, 0);
    assert.equal(result.terminationEvidence.cleanupProven, true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("bounded Windows commands enforce their wall-clock deadline and clean descendants", {
  skip: process.platform !== "win32",
}, async () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-command-timeout-");
  const commandLogDirectory = createProtectedDirectory(root, "command-logs");
  const readyPath = path.join(root, "timeout-child-ready");
  const childSource = Buffer.from(
    `require("node:fs").writeFileSync(${JSON.stringify(readyPath)},String(process.pid));`
      + "setTimeout(process.exit,30000,0);",
  ).toString("base64");
  const commandSource = [
    'const{spawn}=require("node:child_process");',
    `const source=Buffer.from("${childSource}","base64").toString("utf8");`,
    'spawn(process.execPath,["-e",source],{stdio:"ignore"});',
    "setTimeout(process.exit,30000,0);",
  ].join("");
  const started = Date.now();
  try {
    await assert.rejects(
      executeBoundedCommand({
        command: [process.execPath, "-e", commandSource],
        cwd: repoRoot,
        environment: process.env,
        label: "Wall-clock timeout fixture",
        logPath: path.join(commandLogDirectory, "timeout.log"),
        expectedLogDirectory: commandLogDirectory,
        maximumLogBytes: 1_024,
        timeoutMs: 9_000,
      }),
      (error) => {
        assert.equal(error.code, "INTEGRATED_GATE_COMMAND_TIMEOUT");
        assert.equal(error.timeoutMs, 9_000);
        assert.equal(error.terminationEvidence.terminationReason, "timeout");
        assert.equal(error.terminationEvidence.terminateRequested, true);
        assert.equal(error.terminationEvidence.activeProcessZeroObserved, true);
        assert.equal(error.terminationEvidence.activeProcessCount, 0);
        assert.equal(error.terminationEvidence.cleanupProven, true);
        return true;
      },
    );
    assert.ok(
      Date.now() - started < 20_000,
      "the deadline must settle the owned Job before the fixture exits naturally",
    );
    const childProcessId = Number.parseInt(readFileSync(readyPath, "utf8"), 10);
    assert.equal(processIsAlive(childProcessId), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
