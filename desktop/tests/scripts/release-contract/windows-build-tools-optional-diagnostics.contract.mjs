import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  evaluateWindowsBuildToolsOptionalDiagnosticsOptOut,
  readWindowsBuildToolsOptionalDiagnosticsSnapshot,
  resolveTrustedWindowsPowerShellExecutable,
  validateWindowsBuildToolsOptionalDiagnosticsSnapshot,
  verifyWindowsBuildToolsOptionalDiagnosticsOptOut,
  WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS_INSTALLATION_KEY,
  WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS_POLICY_KEY,
} from "../../../../verification/verify-windows-build-tools-optional-diagnostics-opt-out.mjs";

const contractRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(contractRoot, "..", "..", "..", "..");

function optionalDiagnosticsSnapshot({ policy = null, installation = 0 } = {}) {
  const setting = (value) => value === null
    ? { state: "absent" }
    : { state: "present", kind: "DWord", value };
  return {
    schemaVersion: 1,
    registryView: "Registry64",
    policy: setting(policy),
    installation: setting(installation),
  };
}

function trustedPowerShellFixture() {
  const systemRoot = String.raw`C:\Windows`;
  return {
    executable: path.win32.join(
      systemRoot,
      "System32",
      "WindowsPowerShell",
      "v1.0",
      "powershell.exe",
    ),
    systemRoot,
  };
}

test("Windows Build Tools optional-diagnostics snapshot accepts only the bounded schema", () => {
  assert.deepEqual(
    validateWindowsBuildToolsOptionalDiagnosticsSnapshot(optionalDiagnosticsSnapshot()),
    optionalDiagnosticsSnapshot(),
  );
  assert.throws(
    () => validateWindowsBuildToolsOptionalDiagnosticsSnapshot({
      ...optionalDiagnosticsSnapshot(),
      policy: { state: "present", kind: "String", value: 0 },
    }),
    /policy.*DWORD/i,
  );
  assert.throws(
    () => validateWindowsBuildToolsOptionalDiagnosticsSnapshot({
      ...optionalDiagnosticsSnapshot(),
      unexpected: true,
    }),
    /fields differ/,
  );
  assert.throws(
    () => validateWindowsBuildToolsOptionalDiagnosticsSnapshot({
      ...optionalDiagnosticsSnapshot(),
      installation: { state: "absent", value: 0 },
    }),
    /installation.*fields differ/i,
  );
});

test("Windows Build Tools policy overrides the installation setting", () => {
  assert.deepEqual(
    evaluateWindowsBuildToolsOptionalDiagnosticsOptOut({
      policyOptIn: 0,
      installationOptIn: 1,
    }),
    { optIn: 0, source: "policy" },
  );
  assert.throws(
    () => evaluateWindowsBuildToolsOptionalDiagnosticsOptOut({
      policyOptIn: 1,
      installationOptIn: 0,
    }),
    /enabled by the policy/,
  );
});

test("Windows Build Tools installation setting must explicitly opt out", () => {
  assert.deepEqual(
    evaluateWindowsBuildToolsOptionalDiagnosticsOptOut({
      policyOptIn: null,
      installationOptIn: 0,
    }),
    { optIn: 0, source: "installation" },
  );
  assert.throws(
    () => evaluateWindowsBuildToolsOptionalDiagnosticsOptOut({
      policyOptIn: null,
      installationOptIn: 1,
    }),
    /enabled by the installation/,
  );
  assert.throws(
    () => evaluateWindowsBuildToolsOptionalDiagnosticsOptOut({
      policyOptIn: null,
      installationOptIn: null,
    }),
    /configuration is missing/,
  );
  assert.throws(
    () => evaluateWindowsBuildToolsOptionalDiagnosticsOptOut({
      policyOptIn: undefined,
      installationOptIn: 0,
    }),
    /policy OptIn must be a DWORD or absent/,
  );
});

test("Windows Build Tools registry reader pins the inbox API helper", () => {
  const trustedPowerShell = trustedPowerShellFixture();
  const systemRoot = trustedPowerShell.systemRoot;
  const calls = [];
  const snapshot = optionalDiagnosticsSnapshot();
  assert.deepEqual(
    readWindowsBuildToolsOptionalDiagnosticsSnapshot({
      platform: "win32",
      environment: {
        SystemRoot: systemRoot,
        TEMP: path.resolve(systemRoot, "Temp"),
        GH_TOKEN: "must-not-cross-the-boundary",
      },
      resolvePowerShell: () => trustedPowerShell,
      run(executable, args, options) {
        calls.push({ executable, args, options });
        return {
          error: null,
          status: 0,
          stdout: `${JSON.stringify(snapshot)}\r\n`,
          stderr: "",
        };
      },
    }),
    snapshot,
  );
  assert.equal(calls.length, 1);
  assert.equal(
    calls[0].executable,
    trustedPowerShell.executable,
  );
  assert.deepEqual(calls[0].args, [
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-File",
    path.join(
      repositoryRoot,
      "verification",
      "read-windows-build-tools-optional-diagnostics-settings.ps1",
    ),
  ]);
  assert.equal(calls[0].options.windowsHide, true);
  assert.equal(calls[0].options.env.GH_TOKEN, undefined);
  assert.equal(calls[0].options.env.SystemRoot, systemRoot);
  assert.equal(calls[0].options.env.WINDIR, systemRoot);
});

test("Windows Build Tools registry reader rejects an alternate SystemRoot before launch", () => {
  const trustedPowerShell = trustedPowerShellFixture();
  const alternateRoot = path.win32.join(
    path.win32.parse(trustedPowerShell.systemRoot).root,
    "untrusted-windows-root",
  );
  let launches = 0;
  assert.throws(
    () => readWindowsBuildToolsOptionalDiagnosticsSnapshot({
      platform: "win32",
      environment: {
        SystemRoot: alternateRoot,
        WINDIR: trustedPowerShell.systemRoot,
      },
      resolvePowerShell: () => trustedPowerShell,
      run() {
        launches += 1;
        throw new Error("the untrusted helper must never launch");
      },
    }),
    /SystemRoot does not match the trusted Windows OS root/,
  );
  assert.equal(launches, 0);
});

test("Windows Build Tools registry access failures cannot fall back", () => {
  const trustedPowerShell = trustedPowerShellFixture();
  const systemRoot = trustedPowerShell.systemRoot;
  assert.throws(
    () => readWindowsBuildToolsOptionalDiagnosticsSnapshot({
      platform: "win32",
      environment: { SystemRoot: systemRoot },
      resolvePowerShell: () => trustedPowerShell,
      run: () => ({
        error: null,
        status: 1,
        stdout: "",
        stderr: "UnauthorizedAccessException: policy read denied",
      }),
    }),
    /registry read failed.*access denied|registry read failed.*policy read denied/i,
  );
  assert.throws(
    () => readWindowsBuildToolsOptionalDiagnosticsSnapshot({
      platform: "win32",
      environment: { SystemRoot: systemRoot },
      resolvePowerShell: () => trustedPowerShell,
      run: () => ({
        error: null,
        status: 0,
        stdout: "{not-json}",
        stderr: "",
      }),
    }),
    /invalid JSON/,
  );
});

test("Windows Build Tools helper resolves through the kernel SystemRoot alias", {
  skip: process.platform !== "win32",
}, () => {
  const trustedPowerShell = resolveTrustedWindowsPowerShellExecutable();
  assert.equal(path.win32.isAbsolute(trustedPowerShell.executable), true);
  assert.equal(path.win32.isAbsolute(trustedPowerShell.systemRoot), true);
  assert.equal(
    path.win32.normalize(trustedPowerShell.executable).toLowerCase(),
    path.win32.join(
      trustedPowerShell.systemRoot,
      "System32",
      "WindowsPowerShell",
      "v1.0",
      "powershell.exe",
    ).toLowerCase(),
  );
});

test("Windows Build Tools verification evaluates one structured snapshot", () => {
  const reads = [];
  const result = verifyWindowsBuildToolsOptionalDiagnosticsOptOut({
    platform: "win32",
    readSnapshot() {
      reads.push("snapshot");
      return optionalDiagnosticsSnapshot();
    },
  });
  assert.deepEqual(reads, ["snapshot"]);
  assert.deepEqual(result, {
    applicable: true,
    optIn: 0,
    source: "installation",
  });
});

test("Windows Build Tools verification is not applicable off Windows", () => {
  assert.deepEqual(
    verifyWindowsBuildToolsOptionalDiagnosticsOptOut({
      platform: "linux",
      readSnapshot() {
        throw new Error("registry must not be queried");
      },
    }),
    { applicable: false },
  );
});

test("Windows Build Tools helper uses the 64-bit read-only registry API", () => {
  const source = readFileSync(
    path.join(
      repositoryRoot,
      "verification",
      "read-windows-build-tools-optional-diagnostics-settings.ps1",
    ),
    "utf8",
  );
  assert.match(source, /^#requires -Version 5\.1\r?$/im);
  assert.match(source, /^#requires -PSEdition Desktop\r?$/im);
  assert.match(source, /RegistryKey\]::OpenBaseKey/);
  assert.match(source, /RegistryView\]::Registry64/);
  assert.match(source, /\.OpenSubKey\(/);
  assert.match(source, /\.GetValueKind\(/);
  assert.doesNotMatch(source, /SetValue|CreateSubKey|reg(?:\.exe)?\s+(?:add|delete)/i);
});

test("documented Build Tools registry locations remain exact", () => {
  assert.equal(
    WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS_POLICY_KEY,
    String.raw`HKLM\Software\Policies\Microsoft\VisualStudio\SQM`,
  );
  assert.equal(
    WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS_INSTALLATION_KEY,
    String.raw`HKLM\SOFTWARE\Wow6432Node\Microsoft\VSCommon\17.0\SQM`,
  );
});
