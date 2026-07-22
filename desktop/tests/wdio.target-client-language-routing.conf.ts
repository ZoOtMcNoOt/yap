import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertRecordingRootEmpty,
  listRecordingArtifacts,
} from "./wdio/recording-artifact-ownership.js";
import {
  requireAbsoluteWindowsPath,
  sameWindowsPath,
} from "./wdio/windows-path-safety.js";
import { validateTargetClientPowerThermalEvidence } from "./wdio/target-client-power-thermal-evidence.js";

// Cohesion note: preflight and finalization intentionally share one captured
// path/hash identity so the private evidence transaction cannot change owners.
const binaryName = "yap-desktop.exe";
const testsRoot = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(testsRoot, "..");
const repoRoot = path.resolve(desktopRoot, "..");
const worker = Boolean(process.env.WDIO_WORKER_ID);
const checkedHead = process.env.YAP_CHECKED_HEAD ?? "";
const stimulusSha256 = process.env.YAP_TARGET_CLIENT_STIMULUS_SHA256 ?? "";
const stimulusLicense = process.env.YAP_TARGET_CLIENT_STIMULUS_LICENSE ?? "";
const evidenceRoot = requireAbsoluteWindowsPath(
  process.env.YAP_TARGET_CLIENT_EVIDENCE_DIR,
  "Target-client evidence root",
);
const modelsRoot = requireAbsoluteWindowsPath(
  process.env.YAP_MODELS_DIR,
  "Target-client models root",
);
const appBinaryPath = requireAbsoluteWindowsPath(
  process.env.APP_BINARY,
  "Target-client release binary",
);
const powerThermalEvidencePath = requireAbsoluteWindowsPath(
  process.env.YAP_TARGET_CLIENT_POWER_THERMAL_EVIDENCE_FILE,
  "Target-client power/thermal evidence file",
);
const activeCaptureMs = parseActiveCaptureDuration(process.env.YAP_HARDWARE_ACTIVE_CAPTURE_MS);
const runRoot = path.join(evidenceRoot, "rendered-ui-and-microphone");
const appDataRoot = path.join(runRoot, "app-data");
const recordingRoot = path.join(runRoot, "live-recordings");
const webviewRoot = path.join(runRoot, "webview2");
const outputDirectory = path.join(runRoot, "wdio");
const uiEvidenceFile = path.join(runRoot, "rendered-ui-evidence.json");
const uiContextFile = path.join(runRoot, "rendered-ui-context.json");
const powerThermalSummaryFile = path.join(runRoot, "power-thermal-evidence.json");
let appBinarySha256 = "";
let validatedPowerThermalEvidence;

function parseActiveCaptureDuration(raw: string | undefined): number {
  if (!raw || !/^[1-9][0-9]*$/.test(raw)) {
    throw new Error("YAP_HARDWARE_ACTIVE_CAPTURE_MS must be an integer of at least 900000.");
  }
  const value = Number.parseInt(raw, 10);
  if (!Number.isSafeInteger(value) || value < 900_000 || value > 1_800_000) {
    throw new Error("YAP_HARDWARE_ACTIVE_CAPTURE_MS must be between 900000 and 1800000.");
  }
  return value;
}

function requireStimulusIdentity() {
  if (!/^[0-9a-f]{64}$/.test(stimulusSha256)) {
    throw new Error("YAP_TARGET_CLIENT_STIMULUS_SHA256 must identify the physical audio stimulus.");
  }
  if (!/^[A-Za-z0-9.+-]{2,64}$/.test(stimulusLicense)) {
    throw new Error("YAP_TARGET_CLIENT_STIMULUS_LICENSE must be a bounded license identifier.");
  }
}

function requireCleanCheckedHead() {
  if (!/^[0-9a-f]{40}$/.test(checkedHead)) {
    throw new Error("YAP_CHECKED_HEAD must be the exact lowercase candidate SHA.");
  }
  const actualHead = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repoRoot,
    encoding: "utf8",
  }).trim();
  if (actualHead !== checkedHead) {
    throw new Error("YAP_CHECKED_HEAD does not match the checked-out repository HEAD.");
  }
  const status = execFileSync(
    "git",
    ["status", "--porcelain=v1", "--untracked-files=normal"],
    { cwd: repoRoot, encoding: "utf8" },
  ).trim();
  if (status) throw new Error("The target-client UI gate requires a clean checked head.");
}

function requireOfflineBoundary() {
  const script = String.raw`
$gateways = @(
  [Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
    Where-Object {
      $_.OperationalStatus -eq [Net.NetworkInformation.OperationalStatus]::Up -and
      $_.NetworkInterfaceType -ne [Net.NetworkInformation.NetworkInterfaceType]::Loopback -and
      $_.NetworkInterfaceType -ne [Net.NetworkInformation.NetworkInterfaceType]::Tunnel -and
      @($_.GetIPProperties().GatewayAddresses | Where-Object {
        -not $_.Address.Equals([Net.IPAddress]::Any) -and
        -not $_.Address.Equals([Net.IPAddress]::IPv6Any)
      }).Count -gt 0
    } |
    ForEach-Object { $_.Name }
)
if ($gateways.Count -gt 0) {
  [Console]::Error.WriteLine(($gateways -join ', '))
  exit 1
}
`;
  try {
    execFileSync(
      "pwsh.exe",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    );
  } catch (error) {
    const stderr = typeof error === "object" && error && "stderr" in error
      ? String(error.stderr).trim()
      : "unknown interface";
    throw new Error(`The target-client UI gate requires an offline host: ${stderr}.`);
  }
}

function requireRealDirectory(candidate: string, label: string) {
  if (!existsSync(candidate) || !statSync(candidate).isDirectory()) {
    throw new Error(`${label} must be an existing directory.`);
  }
  if (lstatSync(candidate).isSymbolicLink()) {
    throw new Error(`${label} must not be a symbolic link.`);
  }
  if (!sameWindowsPath(realpathSync.native(candidate), candidate)) {
    throw new Error(`${label} must not resolve through a redirect.`);
  }
}

function requireRealFile(candidate: string, label: string) {
  if (!existsSync(candidate) || !statSync(candidate).isFile()) {
    throw new Error(`${label} must be an existing file.`);
  }
  if (lstatSync(candidate).isSymbolicLink()) {
    throw new Error(`${label} must not be a symbolic link.`);
  }
  if (!sameWindowsPath(realpathSync.native(candidate), candidate)) {
    throw new Error(`${label} must not resolve through a redirect.`);
  }
}

function requireOutsideRepository(candidate: string, label: string) {
  const relative = path.relative(repoRoot, candidate);
  if (relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))) {
    throw new Error(`${label} must stay outside the repository.`);
  }
}

function requireInsideEvidenceRoot(candidate: string, label: string) {
  const relative = path.relative(evidenceRoot, candidate);
  if (
    relative === ""
    || relative === ".."
    || relative.startsWith(`..${path.sep}`)
    || path.isAbsolute(relative)
  ) {
    throw new Error(`${label} must stay beneath the protected target-client evidence root.`);
  }
}

function requireReleaseBinary() {
  const expected = path.join(desktopRoot, "src-tauri", "target", "release", binaryName);
  if (!sameWindowsPath(appBinaryPath, expected)) {
    throw new Error("APP_BINARY must be the exact checked-head release-mode WDIO binary.");
  }
  if (!existsSync(appBinaryPath) || !statSync(appBinaryPath).isFile()) {
    throw new Error("The target-client release-mode WDIO binary is missing.");
  }
  if (lstatSync(appBinaryPath).isSymbolicLink()) {
    throw new Error("The target-client release binary must not be a symbolic link.");
  }
}

function requireNativeResourceEvidence() {
  const contextPath = path.join(evidenceRoot, "resource-gate-context.json");
  const profilePath = path.join(evidenceRoot, "resident-language-routing-profile.json");
  if (!existsSync(contextPath) || !existsSync(profilePath)) {
    throw new Error("The rendered-UI gate requires the completed native resource gate first.");
  }
  const context = JSON.parse(readFileSync(contextPath, "utf8"));
  if (context.status !== "passed" || context.checkedHead !== checkedHead) {
    throw new Error("Native resource evidence does not belong to this checked head.");
  }
  const processors = os.cpus();
  if (
    processors.length !== context.logicalProcessors
    || processors[0]?.model.trim() !== context.processorName
    || !context.processorName.includes(context.expectedProcessorToken)
  ) {
    throw new Error("Native resource evidence does not belong to this target machine.");
  }
  const profileSha256 = createHash("sha256")
    .update(readFileSync(profilePath))
    .digest("hex");
  if (profileSha256 !== context.profileSha256) {
    throw new Error("Native resource evidence changed after publication.");
  }
}

function createPrivateRunDirectories() {
  if (!worker) {
    if (existsSync(runRoot)) {
      throw new Error("The target-client rendered-UI evidence path must be new.");
    }
    mkdirSync(runRoot);
    for (const directory of [appDataRoot, recordingRoot, webviewRoot, outputDirectory]) {
      mkdirSync(directory);
    }
    writeFileSync(
      path.join(appDataRoot, "primary-language.json"),
      `${JSON.stringify({ schemaVersion: 1, languageBcp47: "en-US" }, null, 2)}\n`,
      { encoding: "utf8", flag: "wx" },
    );
    writeFileSync(
      uiContextFile,
      `${JSON.stringify({
        schemaVersion: 1,
        status: "started",
        activeCaptureMs,
        appBinarySha256,
        checkedHead,
        powerThermalEvidenceSha256: createHash("sha256")
          .update(readFileSync(powerThermalEvidencePath))
          .digest("hex"),
        stimulusLicense,
        stimulusSha256,
        transcriptTextRecorded: false,
      }, null, 2)}\n`,
      { encoding: "utf8", flag: "wx" },
    );
    writeFileSync(
      powerThermalSummaryFile,
      `${JSON.stringify(validatedPowerThermalEvidence, null, 2)}\n`,
      { encoding: "utf8", flag: "wx" },
    );
  }
  for (const directory of [runRoot, appDataRoot, recordingRoot, webviewRoot, outputDirectory]) {
    requireRealDirectory(directory, "Target-client gate directory");
  }
}

function assertNoRetainedModelSnapshots() {
  const expectedModelDirectories = [
    path.join(modelsRoot, "nemotron-3.5-asr-streaming-0.6b-1120ms-int8"),
    path.join(modelsRoot, "silero-vad", "sha256-9e2449e1087496d8"),
    path.join(modelsRoot, "ambernet-lid", "sha256-ef1006c763780354"),
  ];
  const retained = expectedModelDirectories.flatMap((directory) => {
    if (!existsSync(directory)) return [`missing:${directory}`];
    return readdirSync(directory).filter((name) => name.startsWith(".yap-model-load-"));
  });
  if (retained.length > 0) {
    throw new Error(`The target-client gate retained model snapshots: ${retained.join(", ")}`);
  }
}

requireCleanCheckedHead();
requireOfflineBoundary();
requireStimulusIdentity();
requireOutsideRepository(evidenceRoot, "Target-client evidence");
requireOutsideRepository(modelsRoot, "Target-client models");
requireOutsideRepository(powerThermalEvidencePath, "Target-client power/thermal evidence");
requireInsideEvidenceRoot(powerThermalEvidencePath, "Target-client power/thermal evidence");
requireRealDirectory(evidenceRoot, "Target-client evidence root");
requireRealDirectory(modelsRoot, "Target-client models root");
requireRealFile(powerThermalEvidencePath, "Target-client power/thermal evidence");
requireReleaseBinary();
requireNativeResourceEvidence();
appBinarySha256 = createHash("sha256").update(readFileSync(appBinaryPath)).digest("hex");
validatedPowerThermalEvidence = validateTargetClientPowerThermalEvidence(
  JSON.parse(readFileSync(powerThermalEvidencePath, "utf8")),
  {
    appBinarySha256,
    checkedHead,
    processorName: os.cpus()[0]?.model.trim(),
    stimulusSha256,
  },
);
createPrivateRunDirectories();

process.env.YAP_APP_DATA_DIR = appDataRoot;
process.env.YAP_LIVE_RECORDINGS_DIR = recordingRoot;
process.env.WEBVIEW2_USER_DATA_FOLDER = webviewRoot;
process.env.YAP_TARGET_CLIENT_LANGUAGE_ROUTING_GATE = "1";
process.env.YAP_TARGET_CLIENT_UI_EVIDENCE_FILE = uiEvidenceFile;

export const config = {
  bail: 1,
  baseUrl: "http://localhost:4445",
  capabilities: [
    {
      browserName: "tauri",
      "tauri:options": { application: appBinaryPath },
    },
  ],
  connectionRetryCount: 1,
  connectionRetryTimeout: 120_000,
  framework: "mocha",
  logLevel: "info",
  maxInstances: 1,
  mochaOpts: {
    forbidOnly: true,
    forbidPending: true,
    timeout: activeCaptureMs + 180_000,
    ui: "bdd",
  },
  outputDir: outputDirectory,
  reporters: ["spec"],
  runner: "local",
  services: [
    [
      "@wdio/tauri-service",
      {
        appBinaryPath,
        backendLogLevel: "info",
        captureBackendLogs: true,
        captureFrontendLogs: true,
        driverProvider: "embedded",
        embeddedPort: 4445,
        frontendLogLevel: "warn",
      },
    ],
  ],
  specs: [path.join(testsRoot, "wdio", "live-overlay.hardware.spec.js")],
  waitforTimeout: 20_000,
  onPrepare() {
    assertRecordingRootEmpty(recordingRoot);
  },
  async afterTest(_test: unknown, _context: unknown, result: { error?: Error }) {
    if (result.error) {
      const safeName = result.error.message.replace(/[^a-z0-9]+/gi, "-").slice(0, 80);
      await browser.saveScreenshot(path.join(outputDirectory, `failure-${Date.now()}-${safeName}.png`));
    }
    assertRecordingRootEmpty(recordingRoot);
  },
  onComplete() {
    const artifacts = listRecordingArtifacts(recordingRoot);
    rmSync(recordingRoot, { force: true, recursive: true });
    requireOfflineBoundary();
    assertNoRetainedModelSnapshots();
    if (artifacts.length > 0) {
      throw new Error(
        `The target-client UI gate retained private recording artifacts before cleanup: ${artifacts.join(", ")}`,
      );
    }
    if (!existsSync(uiEvidenceFile)) {
      throw new Error("The target-client UI gate did not publish aggregate evidence.");
    }
    const evidenceBytes = readFileSync(uiEvidenceFile);
    const evidence = JSON.parse(evidenceBytes.toString("utf8"));
    if (
      evidence.schemaVersion !== 1
      || evidence.activeCaptureMs !== activeCaptureMs
      || evidence.route !== "localFallback"
      || evidence.stimulusLicense !== stimulusLicense
      || evidence.stimulusSha256 !== stimulusSha256
      || evidence.targetClientGate !== true
      || evidence.transcriptTextRecorded !== false
      || !Array.isArray(evidence.languageRoutingEnabledLocales)
      || evidence.languageRoutingEnabledLocales.length < 2
      || !Array.isArray(evidence.lifecycleStatuses)
      || !evidence.lifecycleStatuses.includes("speaking")
      || evidence.restartCancellation?.cycleCount !== 4
      || evidence.restartCancellation?.finalStatus !== "idle"
      || !Number.isFinite(evidence.renderedUiResponsiveness?.p95DelayMs)
      || evidence.renderedUiResponsiveness.p95DelayMs > 50
      || !Number.isFinite(evidence.renderedUiResponsiveness?.maximumDelayMs)
      || evidence.renderedUiResponsiveness.maximumDelayMs > 250
    ) {
      throw new Error("The target-client UI aggregate did not satisfy its frozen contract.");
    }
    const context = JSON.parse(readFileSync(uiContextFile, "utf8"));
    const finalBinarySha256 = createHash("sha256").update(readFileSync(appBinaryPath)).digest("hex");
    if (finalBinarySha256 !== context.appBinarySha256) {
      throw new Error("The target-client release binary changed during qualification.");
    }
    const finalPowerThermalEvidenceSha256 = createHash("sha256")
      .update(readFileSync(powerThermalEvidencePath))
      .digest("hex");
    if (finalPowerThermalEvidenceSha256 !== context.powerThermalEvidenceSha256) {
      throw new Error("The power/thermal evidence changed during qualification.");
    }
    const powerThermalSummarySha256 = createHash("sha256")
      .update(readFileSync(powerThermalSummaryFile))
      .digest("hex");
    writeFileSync(
      uiContextFile,
      `${JSON.stringify({
        ...context,
        evidenceSha256: createHash("sha256").update(evidenceBytes).digest("hex"),
        powerThermalSummarySha256,
        status: "passed",
      }, null, 2)}\n`,
      { encoding: "utf8" },
    );
  },
};
