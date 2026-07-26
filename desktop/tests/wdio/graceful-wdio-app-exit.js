import { execFile } from "node:child_process";
import process from "node:process";
import { setTimeout as delay } from "node:timers/promises";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

async function findWdioAppProcessId(browserInstance) {
  const webdriverPort = Number(browserInstance.options.port ?? 4445);
  if (!Number.isInteger(webdriverPort)) {
    throw new Error(
      `Cannot identify the WDIO app from WebDriver port ${browserInstance.options.port}.`,
    );
  }
  const { stdout } = await execFileAsync("netstat.exe", ["-ano", "-p", "tcp"], {
    timeout: 5_000,
    windowsHide: true,
  });
  const listenerPattern = new RegExp(
    `^\\s*TCP\\s+\\S+:${webdriverPort}\\s+\\S+\\s+LISTENING\\s+(\\d+)\\s*$`,
    "mi",
  );
  const processId = Number(stdout.match(listenerPattern)?.[1]);
  if (!Number.isInteger(processId) || processId <= 0) {
    throw new Error(`No WDIO app is listening on port ${webdriverPort}.`);
  }
  return processId;
}

function isProcessAlive(processId) {
  try {
    process.kill(processId, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") return false;
    throw error;
  }
}

async function waitForProcessExit(processId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isProcessAlive(processId)) return;
    await delay(50);
  }
  throw new Error(
    `Production tray quit left WDIO app process ${processId} alive after ${timeoutMs}ms.`,
  );
}

export async function gracefullyExitWdioApp(
  browserInstance = globalThis.browser,
  { timeoutMs = 10_000 } = {},
) {
  const processId = await findWdioAppProcessId(browserInstance);
  let bridgeClosedDuringQuit = false;
  try {
    await browserInstance.tauri.execute(({ core }) =>
      core.invoke("wdio_dispatch_tray_action", { action: "quit" }));
  } catch (error) {
    bridgeClosedDuringQuit = true;
    console.info(`WDIO bridge closed during production tray quit: ${String(error)}`);
  }

  await waitForProcessExit(processId, timeoutMs);
  browserInstance.sessionId = undefined;
  return { bridgeClosedDuringQuit, processId };
}
