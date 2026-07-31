import { spawnSync } from "node:child_process";
import {
  lstatSync,
  realpathSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS_POLICY_KEY =
  String.raw`HKLM\Software\Policies\Microsoft\VisualStudio\SQM`;
export const WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS_INSTALLATION_KEY =
  String.raw`HKLM\SOFTWARE\Wow6432Node\Microsoft\VSCommon\17.0\SQM`;

const moduleDirectory = path.dirname(fileURLToPath(import.meta.url));
const registryReaderPath = path.join(
  moduleDirectory,
  "read-windows-build-tools-optional-diagnostics-settings.ps1",
);
const WINDOWS_NT_SYSTEM_POWERSHELL =
  String.raw`\\?\GLOBALROOT\SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe`;
const WINDOWS_POWERSHELL_RELATIVE_PATH = path.win32.join(
  "System32",
  "WindowsPowerShell",
  "v1.0",
  "powershell.exe",
);
const SNAPSHOT_FIELDS = new Set([
  "schemaVersion",
  "registryView",
  "policy",
  "installation",
]);

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactFields(value, expected) {
  const fields = Object.keys(value);
  return fields.length === expected.size
    && fields.every((field) => expected.has(field));
}

function validateSetting(value, label) {
  requireCondition(isRecord(value), `Build Tools ${label} setting must be an object.`);
  if (value.state === "absent") {
    requireCondition(
      hasExactFields(value, new Set(["state"])),
      `Build Tools ${label} absent-setting fields differ from the contract.`,
    );
    return Object.freeze({ state: "absent" });
  }
  requireCondition(
    value.state === "present",
    `Build Tools ${label} state must be present or absent.`,
  );
  requireCondition(
    hasExactFields(value, new Set(["state", "kind", "value"])),
    `Build Tools ${label} present-setting fields differ from the contract.`,
  );
  requireCondition(
    value.kind === "DWord",
    `Build Tools ${label} OptIn must be a DWORD.`,
  );
  requireCondition(
    Number.isSafeInteger(value.value)
      && value.value >= 0
      && value.value <= 0xffff_ffff,
    `Build Tools ${label} DWORD must be an unsigned 32-bit integer.`,
  );
  return Object.freeze({
    state: "present",
    kind: "DWord",
    value: value.value,
  });
}

export function validateWindowsBuildToolsOptionalDiagnosticsSnapshot(value) {
  requireCondition(
    isRecord(value) && hasExactFields(value, SNAPSHOT_FIELDS),
    "Build Tools optional-diagnostics snapshot fields differ from the contract.",
  );
  requireCondition(
    value.schemaVersion === 1,
    "Build Tools optional-diagnostics snapshot schemaVersion must be 1.",
  );
  requireCondition(
    value.registryView === "Registry64",
    "Build Tools optional-diagnostics snapshot must use the 64-bit registry view.",
  );
  return Object.freeze({
    schemaVersion: 1,
    registryView: "Registry64",
    policy: validateSetting(value.policy, "policy"),
    installation: validateSetting(value.installation, "installation"),
  });
}

export function evaluateWindowsBuildToolsOptionalDiagnosticsOptOut({
  policyOptIn,
  installationOptIn,
}) {
  for (const [label, value] of [
    ["policy", policyOptIn],
    ["installation", installationOptIn],
  ]) {
    requireCondition(
      value === null || Number.isSafeInteger(value),
      `Visual Studio Build Tools ${label} OptIn must be a DWORD or absent.`,
    );
  }
  const source = policyOptIn !== null ? "policy" : "installation";
  const sourceKey = source === "policy"
    ? WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS_POLICY_KEY
    : WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS_INSTALLATION_KEY;
  const optIn = policyOptIn ?? installationOptIn;
  requireCondition(
    optIn !== null,
    "Visual Studio Build Tools optional-diagnostics configuration is missing. "
      + `Set ${WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS_INSTALLATION_KEY}\\OptIn `
      + "to DWORD 0 before release-gate admission. Required Microsoft diagnostics "
      + "are outside this setting.",
  );
  requireCondition(
    optIn === 0,
    `Visual Studio Build Tools optional diagnostics are enabled by the ${source} `
      + "OptIn DWORD. "
      + `Set ${sourceKey}\\OptIn to DWORD 0 before release-gate admission.`,
  );
  return { optIn, source };
}

function sameWindowsPath(left, right) {
  return path.win32.normalize(left).toLowerCase()
    === path.win32.normalize(right).toLowerCase();
}

export function resolveTrustedWindowsPowerShellExecutable() {
  const aliasMetadata = lstatSync(WINDOWS_NT_SYSTEM_POWERSHELL);
  requireCondition(
    aliasMetadata.isFile() && !aliasMetadata.isSymbolicLink(),
    "The Windows object-manager SystemRoot PowerShell alias is not a real file.",
  );
  const executable = path.win32.normalize(
    realpathSync.native(WINDOWS_NT_SYSTEM_POWERSHELL),
  );
  const executableMetadata = lstatSync(executable);
  requireCondition(
    executableMetadata.isFile() && !executableMetadata.isSymbolicLink(),
    "The trusted Windows PowerShell executable is not a real file.",
  );
  const systemRoot = path.win32.dirname(
    path.win32.dirname(
      path.win32.dirname(
        path.win32.dirname(executable),
      ),
    ),
  );
  requireCondition(
    sameWindowsPath(
      executable,
      path.win32.join(systemRoot, WINDOWS_POWERSHELL_RELATIVE_PATH),
    ),
    "The trusted Windows PowerShell executable is outside the OS SystemRoot.",
  );
  return Object.freeze({ executable, systemRoot });
}

function requireTrustedWindowsRootEnvironment(environment, systemRoot) {
  for (const name of ["SystemRoot", "WINDIR"]) {
    const value = environment[name];
    if (value === undefined) continue;
    requireCondition(
      typeof value === "string"
        && path.win32.isAbsolute(value)
        && sameWindowsPath(value, systemRoot),
      `${name} does not match the trusted Windows OS root.`,
    );
  }
}

function minimalWindowsEnvironment(environment, systemRoot) {
  return Object.fromEntries([
    ["SystemRoot", systemRoot],
    ["WINDIR", systemRoot],
    ...["TEMP", "TMP"].flatMap((name) => (
      typeof environment[name] === "string"
        ? [[name, environment[name]]]
        : []
    )),
  ]);
}

export function readWindowsBuildToolsOptionalDiagnosticsSnapshot({
  platform = process.platform,
  environment = process.env,
  run = spawnSync,
  resolvePowerShell = resolveTrustedWindowsPowerShellExecutable,
} = {}) {
  requireCondition(
    platform === "win32",
    "Build Tools optional-diagnostics registry settings are available only on Windows.",
  );
  const trustedPowerShell = resolvePowerShell();
  requireCondition(
    isRecord(trustedPowerShell)
      && typeof trustedPowerShell.executable === "string"
      && path.win32.isAbsolute(trustedPowerShell.executable)
      && typeof trustedPowerShell.systemRoot === "string"
      && path.win32.isAbsolute(trustedPowerShell.systemRoot),
    "Trusted Windows PowerShell resolution returned an invalid result.",
  );
  requireTrustedWindowsRootEnvironment(
    environment,
    trustedPowerShell.systemRoot,
  );
  const result = run(
    trustedPowerShell.executable,
    [
      "-NoLogo",
      "-NoProfile",
      "-NonInteractive",
      "-File",
      registryReaderPath,
    ],
    {
      encoding: "utf8",
      env: minimalWindowsEnvironment(environment, trustedPowerShell.systemRoot),
      maxBuffer: 64 * 1024,
      timeout: 20_000,
      windowsHide: true,
    },
  );
  if (result.error) {
    throw new Error(
      "Visual Studio Build Tools registry read failed before completion.",
      { cause: result.error },
    );
  }
  requireCondition(
    result.status === 0,
    "Visual Studio Build Tools registry read failed"
      + `${(result.stderr || result.stdout)?.trim()
        ? `: ${(result.stderr || result.stdout).trim().slice(0, 4_096)}`
        : "."}`,
  );
  let snapshot;
  try {
    snapshot = JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(
      "Visual Studio Build Tools registry reader returned invalid JSON.",
      { cause: error },
    );
  }
  return validateWindowsBuildToolsOptionalDiagnosticsSnapshot(snapshot);
}

function settingValue(setting) {
  return setting.state === "present" ? setting.value : null;
}

export function verifyWindowsBuildToolsOptionalDiagnosticsOptOut({
  platform = process.platform,
  environment = process.env,
  readSnapshot = () => readWindowsBuildToolsOptionalDiagnosticsSnapshot({
    platform,
    environment,
  }),
} = {}) {
  if (platform !== "win32") return { applicable: false };
  const snapshot = validateWindowsBuildToolsOptionalDiagnosticsSnapshot(
    readSnapshot(),
  );
  return {
    applicable: true,
    ...evaluateWindowsBuildToolsOptionalDiagnosticsOptOut({
      policyOptIn: settingValue(snapshot.policy),
      installationOptIn: settingValue(snapshot.installation),
    }),
  };
}

function main() {
  const result = verifyWindowsBuildToolsOptionalDiagnosticsOptOut();
  if (!result.applicable) {
    console.log("WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS=not-applicable");
    return;
  }
  console.log(
    `WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS=disabled:${result.source}`,
  );
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
