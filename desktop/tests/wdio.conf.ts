import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertRecordingRootEmpty,
  listRecordingArtifacts,
} from "./wdio/recording-artifact-ownership.js";
import {
  attachWdioRunIsolation,
  createWdioRunIsolation,
  removePrivateRunRootWhenReleased,
  resetPrivateRecordingRoot,
} from "./wdio/wdio-run-isolation.js";

const binaryName = process.platform === "win32" ? "yap-desktop.exe" : "yap-desktop";
const testsRoot = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(testsRoot, "..");
const appBinaryPath =
  process.env.APP_BINARY ?? path.join(desktopRoot, "src-tauri", "target", "debug", binaryName);
const isolation = process.env.WDIO_WORKER_ID
  ? attachWdioRunIsolation()
  : createWdioRunIsolation();
class WdioRunIsolationCleanupService {
  async onComplete() {
    await new Promise((resolve) => setTimeout(resolve, 100));
    await removePrivateRunRootWhenReleased(isolation);
    console.info(`[WDIO run isolation] removedRunRoot=${isolation.runRoot}`);
  }
}

export const config = {
  bail: 0,
  baseUrl: "http://localhost:4445",
  capabilities: [
    {
      browserName: "tauri",
      "tauri:options": {
        application: appBinaryPath,
      },
    },
  ],
  connectionRetryCount: 1,
  connectionRetryTimeout: 120_000,
  framework: "mocha",
  logLevel: "info",
  maxInstances: 1,
  mochaOpts: {
    timeout: 60_000,
    ui: "bdd",
  },
  outputDir: path.join(testsRoot, "results", "wdio"),
  reporters: ["spec"],
  runner: "local",
  exclude: [path.join(testsRoot, "wdio", "private-server-asr.gate.spec.js")],
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
    [WdioRunIsolationCleanupService, {}],
  ],
  specs: [path.join(testsRoot, "wdio", "**", "*.spec.js")],
  waitforTimeout: 10_000,
  onPrepare() {
    assertRecordingRootEmpty(isolation.recordingRoot);
    console.info(`[WDIO run isolation] runRoot=${isolation.runRoot}`);
    console.info(`[WDIO run isolation] recordingRoot=${isolation.recordingRoot}`);
    console.info(`[WDIO run isolation] webviewRoot=${isolation.webviewRoot}`);
  },
  async afterTest(_test, _context, result) {
    if (result.error) {
      const safeName = result.error.message.replace(/[^a-z0-9]+/gi, "-").slice(0, 80);
      const screenshotPath = path.join(
        testsRoot,
        "results",
        "wdio",
        `failure-${Date.now()}-${safeName}.png`,
      );
      mkdirSync(path.dirname(screenshotPath), { recursive: true });
      await browser.saveScreenshot(screenshotPath);
    }
    const artifacts = listRecordingArtifacts(isolation.recordingRoot);
    if (artifacts.length > 0) {
      const removed = await resetPrivateRecordingRoot(isolation);
      throw new Error(
        `WDIO test leaked private recording artifacts; removed from the isolated root: ${removed.join(", ")}`,
      );
    }
    assertRecordingRootEmpty(isolation.recordingRoot);
    console.info("[WDIO run isolation] afterTest recordingRoot=empty");
  },
  async onComplete() {
    const artifacts = listRecordingArtifacts(isolation.recordingRoot);
    let leakageError;
    if (artifacts.length > 0) {
      const removed = await resetPrivateRecordingRoot(isolation);
      leakageError = new Error(
        `WDIO run left private recording artifacts; removed before final cleanup: ${removed.join(", ")}`,
      );
    }
    assertRecordingRootEmpty(isolation.recordingRoot);
    console.info("[WDIO run isolation] pre-shutdown recordingRoot=empty");
    if (leakageError) throw leakageError;
  },
};
