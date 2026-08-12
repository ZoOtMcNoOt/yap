import assert from "node:assert/strict";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  hostedWindowsRuntimeEnvironment,
  HOSTED_WINDOWS_RUNTIME_PROFILES,
  resolveHostedWindowsRuntimeProfile,
  runHostedWindowsRuntimeCheck,
} from "../../../../verification/run-hosted-windows-runtime-check.mjs";

const contractRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(contractRoot, "..", "..", "..", "..");
const checkedHead = "a".repeat(40);

function processIsAlive(processId) {
  try {
    process.kill(processId, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") return false;
    throw error;
  }
}

function retainedPowerShellChildCommand(readyPath) {
  const escapedReadyPath = readyPath.replaceAll("'", "''");
  const rootProcessIdPath = `${readyPath}.root-pid`;
  const escapedRootProcessIdPath = rootProcessIdPath.replaceAll("'", "''");
  const childSource = [
    `$rootProcessId = [int] [IO.File]::ReadAllText('${escapedRootProcessIdPath}');`,
    `[IO.File]::WriteAllText('${escapedReadyPath}', [string] $PID);`,
    "while (Get-Process -Id $rootProcessId -ErrorAction SilentlyContinue) {",
    "Start-Sleep -Milliseconds 10;",
    "}",
    "Start-Sleep -Seconds 30",
  ].join(" ");
  const childEncodedCommand = Buffer.from(
    childSource,
    "utf16le",
  ).toString("base64");
  const rootSource = [
    `[IO.File]::WriteAllText('${escapedRootProcessIdPath}', [string] $PID);`,
    "$child = Start-Process",
    "-FilePath (Get-Command pwsh.exe).Source",
    `-ArgumentList '-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand','${childEncodedCommand}'`,
    "-WindowStyle Hidden",
    "-PassThru;",
    "$deadline = [DateTime]::UtcNow.AddSeconds(5);",
    `while (-not [IO.File]::Exists('${escapedReadyPath}')) {`,
    "if ([DateTime]::UtcNow -ge $deadline) {",
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

test("hosted Windows runtime profiles name only exact product runtime checks", () => {
  assert.deepEqual(
    Object.keys(HOSTED_WINDOWS_RUNTIME_PROFILES),
    [
      "server-connector",
      "authenticated-server-connector",
      "native-wdio",
    ],
  );
  assert.deepEqual(
    resolveHostedWindowsRuntimeProfile("server-connector").command,
    [
      "pwsh.exe",
      "-NoLogo",
      "-NoProfile",
      "-NonInteractive",
      "-File",
      path.join(repositoryRoot, "verification", "test-server-connector.ps1"),
    ],
  );
  assert.deepEqual(
    resolveHostedWindowsRuntimeProfile(
      "authenticated-server-connector",
    ).command,
    [
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
    ],
  );
  assert.deepEqual(
    resolveHostedWindowsRuntimeProfile("native-wdio").command,
    [
      "pnpm.cmd",
      "exec",
      "wdio",
      "run",
      "./tests/wdio.required.conf.ts",
    ],
  );
  assert.equal(
    resolveHostedWindowsRuntimeProfile("server-connector").naturalDescendantDrainMs,
    5_000,
  );
  assert.equal(
    resolveHostedWindowsRuntimeProfile("native-wdio").naturalDescendantDrainMs,
    30_000,
  );
  assert.throws(
    () => resolveHostedWindowsRuntimeProfile("compiler-build"),
    /profile must be/,
  );
});

test("authenticated connector compilation cannot consume bearer lifetime", () => {
  const source = readFileSync(
    path.join(
      repositoryRoot,
      "verification",
      "test-authenticated-server-connector.ps1",
    ),
    "utf8",
  );
  const testFilter = "'python_authenticated_server_accepts_signed_bearer'";
  const buildFilter = source.indexOf(testFilter);
  const buildOnly = source.indexOf("--no-run", buildFilter);
  const serverStart = source.indexOf("$Server = Start-Process");
  const executionFilter = source.indexOf(testFilter, serverStart);

  assert.ok(buildFilter >= 0, "the exact authenticated test build is missing");
  assert.ok(buildOnly > buildFilter, "the preflight must be build-only");
  assert.ok(
    buildOnly < serverStart,
    "the exact test binary must build before the server mints its bearer",
  );
  assert.ok(
    executionFilter > serverStart,
    "the exact authenticated tests must execute after the server starts",
  );
});

test("hosted Windows runtime children cannot inherit GitHub credentials", () => {
  const environment = hostedWindowsRuntimeEnvironment(checkedHead, {
    ACTIONS_ID_TOKEN_REQUEST_TOKEN: "id-token",
    ACTIONS_RUNTIME_TOKEN: "runtime-token",
    GH_ENTERPRISE_TOKEN: "enterprise-token",
    GH_TOKEN: "gh-token",
    GITHUB_ENTERPRISE_TOKEN: "github-enterprise-token",
    GITHUB_ENV: "environment-command-file",
    GITHUB_OUTPUT: "output-command-file",
    GITHUB_PATH: "path-command-file",
    GITHUB_STEP_SUMMARY: "summary-command-file",
    GITHUB_TOKEN: "github-token",
    SAFE_VALUE: "retained",
  });
  assert.equal(environment.SAFE_VALUE, "retained");
  assert.equal(environment.YAP_CHECKED_HEAD, checkedHead);
  for (const name of [
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
  ]) {
    assert.equal(environment[name], undefined);
  }
});

test("hosted Windows runtime wrapper requires complete empty-Job evidence", {
  skip: process.platform !== "win32",
}, async () => {
  const profiles = Object.freeze({
    fixture: Object.freeze({
      command: Object.freeze([process.execPath, "-e", "process.exit(0)"]),
      cwd: repositoryRoot,
      label: "Hosted successful-runtime fixture",
      logName: "fixture.log",
      naturalDescendantDrainMs: 5_000,
      timeoutMs: 15_000,
    }),
  });
  const environment = {
    ...process.env,
    GITHUB_ACTIONS: "true",
    GITHUB_TOKEN: "must-not-cross-the-boundary",
    RUNNER_OS: "Windows",
    RUNNER_TEMP: realpathSync.native(os.tmpdir()),
    YAP_CHECKED_HEAD: checkedHead,
    YAP_RUNNER_ENVIRONMENT: "github-hosted",
  };
  let invocation;
  let marker;
  const result = await runHostedWindowsRuntimeCheck({
    environment,
    executeCommand(options) {
      invocation = options;
      return Promise.resolve({
        evidenceSha256: "b".repeat(64),
        exitCode: 0,
        signal: null,
        terminationEvidence: {
          activeProcessCount: 0,
          activeProcessZeroObserved: true,
          assignedBeforeResume: true,
          cleanupProven: true,
          containment: "windows-job-object",
          rootExited: true,
          rootProcessId: 123,
          schemaVersion: 1,
          terminateRequested: false,
          terminationReason: "none",
        },
      });
    },
    profileName: "fixture",
    profiles,
    writeOutput(value) {
      marker = value;
    },
  });
  assert.equal(result.exitCode, 0);
  assert.equal(invocation.environment.GITHUB_TOKEN, undefined);
  assert.equal(invocation.environment.YAP_CHECKED_HEAD, checkedHead);
  assert.equal(invocation.maximumLogBytes, 16 * 1024 * 1024);
  assert.equal(invocation.naturalDescendantDrainMs, 5_000);
  assert.equal(existsSync(invocation.expectedLogDirectory), false);
  assert.equal(
    marker,
    `HOSTED_WINDOWS_RUNTIME_CHECK=passed:fixture:${"b".repeat(64)}`,
  );
});

test("hosted Windows runtime wrapper rejects and cleans a non-listening retained descendant", {
  skip: process.platform !== "win32",
}, async () => {
  const testRoot = mkdtempSync(path.join(
    realpathSync.native(os.tmpdir()),
    "yap-hosted-runtime-contract-",
  ));
  const readyPath = path.join(testRoot, "retained-child.pid");
  const profiles = Object.freeze({
    fixture: Object.freeze({
      command: Object.freeze(retainedPowerShellChildCommand(readyPath)),
      cwd: repositoryRoot,
      label: "Hosted retained-descendant fixture",
      logName: "fixture.log",
      naturalDescendantDrainMs: 5_000,
      timeoutMs: 15_000,
    }),
  });
  const environment = {
    ...process.env,
    ACTIONS_RUNTIME_TOKEN: "must-not-cross-the-boundary",
    GITHUB_ACTIONS: "true",
    RUNNER_OS: "Windows",
    RUNNER_TEMP: realpathSync.native(os.tmpdir()),
    YAP_CHECKED_HEAD: checkedHead,
    YAP_RUNNER_ENVIRONMENT: "github-hosted",
  };
  try {
    await assert.rejects(
      runHostedWindowsRuntimeCheck({
        environment,
        profileName: "fixture",
        profiles,
        writeOutput() {
          throw new Error("a failed runtime check must not emit a success marker");
        },
      }),
      (error) => {
        assert.equal(
          error.code,
          "INTEGRATED_GATE_COMMAND_RETAINED_DESCENDANT",
          error instanceof Error ? error.stack : String(error),
        );
        assert.equal(error.terminationEvidence.assignedBeforeResume, true);
        assert.equal(error.terminationEvidence.activeProcessZeroObserved, true);
        assert.equal(error.terminationEvidence.activeProcessCount, 0);
        assert.equal(error.terminationEvidence.cleanupProven, true);
        assert.ok(error.retainedProcessNames.includes("pwsh"));
        assert.doesNotMatch(
          error.message,
          /[A-Za-z]:\\|command|token|stdout|stderr|transcript/i,
        );
        return true;
      },
    );
    assert.equal(existsSync(readyPath), true);
    const childProcessId = Number.parseInt(readFileSync(readyPath, "utf8"), 10);
    assert.equal(processIsAlive(childProcessId), false);
  } finally {
    rmSync(testRoot, { recursive: true, force: true });
  }
});

test("the hosted runtime failure summary carries no private evidence", () => {
  const source = readFileSync(
    path.join(repositoryRoot, "verification", "run-hosted-windows-runtime-check.mjs"),
    "utf8",
  );
  const summary = source.slice(
    source.indexOf("function containmentSummary"),
    source.indexOf("function requireCompletedContainment"),
  );
  assert.notEqual(summary, "", "containmentSummary is missing");

  // The child's log is destroyed before the throw, so this string is the only
  // diagnostic that survives. It may only interpolate scalars off the result.
  const interpolated = [...summary.matchAll(/\$\{([^}]*)\}/g)].map(([, e]) => e.trim());
  assert.ok(interpolated.length > 0, "summary interpolates nothing");
  for (const expression of interpolated) {
    assert.match(
      expression,
      /^(result\?\.(exitCode|signal|evidenceSha256)|evidence\.[A-Za-z]+|SHA256\.test\(result\?\.evidenceSha256 \?\? ""\))( \?\? ("absent"|"null"))?$/,
      `summary interpolates ${expression}, which is not a known scalar field`,
    );
    assert.doesNotMatch(
      expression,
      /path|Path|cwd|log|Log|command|token|stdout|stderr|transcript/,
      `summary interpolates ${expression}, which can carry private evidence`,
    );
  }
});
