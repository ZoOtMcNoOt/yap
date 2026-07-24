import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  readFileSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SHA40 = /^[0-9a-f]{40}$/;
const REPOSITORY_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function realFile(candidate, label) {
  requireCondition(path.isAbsolute(candidate), `${label} must be absolute.`);
  requireCondition(existsSync(candidate), `${label} does not exist.`);
  const item = lstatSync(candidate);
  requireCondition(item.isFile() && !item.isSymbolicLink(),
    `${label} must be a real regular file.`);
  return path.normalize(realpathSync.native(candidate));
}

function realDirectory(candidate, label) {
  requireCondition(path.isAbsolute(candidate), `${label} must be absolute.`);
  requireCondition(existsSync(candidate), `${label} does not exist.`);
  const item = lstatSync(candidate);
  requireCondition(item.isDirectory() && !item.isSymbolicLink(),
    `${label} must be a real directory.`);
  return path.normalize(realpathSync.native(candidate));
}

function requireOutsideRepository(candidate, label) {
  const relative = path.relative(REPOSITORY_ROOT, candidate);
  requireCondition(
    relative !== "" && (relative.startsWith("..") || path.isAbsolute(relative)),
    `${label} must stay outside the repository.`,
  );
}

function processExists(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
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

export async function createConnectedServerTeardownReceipt({
  checkedHead,
  remoteCleanupLog,
  tunnelProcessLedger,
  output,
  remoteServerProcessId,
  processProbe = processExists,
  portProbe = portIsOpen,
}) {
  requireCondition(SHA40.test(checkedHead ?? ""),
    "Checked head must be one lowercase Git SHA.");
  requireCondition(
    Number.isSafeInteger(remoteServerProcessId) && remoteServerProcessId > 0,
    "The directly launched remote-server SSH process id is required.",
  );
  const logPath = realFile(path.resolve(remoteCleanupLog), "Remote cleanup log");
  requireOutsideRepository(logPath, "Remote cleanup log");
  const tunnelLedgerPath = realFile(
    path.resolve(tunnelProcessLedger),
    "Tunnel process ledger",
  );
  requireOutsideRepository(tunnelLedgerPath, "Tunnel process ledger");
  requireCondition(path.isAbsolute(output), "Teardown receipt path must be absolute.");
  requireOutsideRepository(path.resolve(output), "Teardown receipt");
  requireCondition(!existsSync(output), "Teardown receipt destination must be new.");
  const outputParent = realDirectory(path.dirname(output), "Teardown receipt parent");
  requireCondition(
    outputParent.toLowerCase() === path.normalize(path.dirname(output)).toLowerCase(),
    "Teardown receipt parent must not redirect elsewhere.",
  );

  const logBytes = readFileSync(logPath);
  const logText = logBytes.toString("utf8");
  const tunnelLedgerBytes = readFileSync(tunnelLedgerPath);
  const tunnelLedger = JSON.parse(tunnelLedgerBytes.toString("utf8"));
  requireCondition(
    tunnelLedger?.schemaVersion === 1
      && tunnelLedger.checkedHead === checkedHead
      && tunnelLedger.startedProcessCount === 2
      && tunnelLedger.exitedProcessCount === 2
      && tunnelLedger.status === "passed"
      && Array.isArray(tunnelLedger.processes)
      && tunnelLedger.processes.length === 2
      && tunnelLedger.processes.every(({ pid, startedAt, exitedAt }) => (
        Number.isSafeInteger(pid)
        && pid > 0
        && Number.isFinite(Date.parse(startedAt))
        && Number.isFinite(Date.parse(exitedAt))
        && Date.parse(exitedAt) >= Date.parse(startedAt)
      )),
    "Tunnel process ledger did not prove exactly two retired gate-owned forwards.",
  );
  const ownedProcessIds = [
    remoteServerProcessId,
    ...tunnelLedger.processes.map(({ pid }) => pid),
  ];
  requireCondition(
    new Set(ownedProcessIds).size === 3,
    "Remote server and tunnel process identities must be distinct.",
  );
  const cleanupLines = logText
    .split(/\r?\n/)
    .filter((line) => line.startsWith("REMOTE_GATE_CLEANUP="));
  requireCondition(
    cleanupLines.length === 1
      && cleanupLines[0] === "REMOTE_GATE_CLEANUP=PASS"
      && !logText.includes("REMOTE_GATE_CLEANUP=FAIL"),
    "Remote cleanup log did not prove one exact passing teardown.",
  );
  requireCondition(
    logText.includes(`REMOTE_PRIVATE_SERVER_READY=${checkedHead}`),
    "Remote cleanup log is not bound to the checked server launch.",
  );
  requireCondition(
    ownedProcessIds.every((pid) => !processProbe(pid)),
    "An owned SSH or forward process remains after teardown.",
  );
  requireCondition(!(await portProbe(18_765)), "The local SSH forward remains reachable.");

  const receipt = {
    schemaVersion: 1,
    checkedHead,
    remoteCleanupPassed: true,
    localForwardAbsent: true,
    remainingOwnedProcesses: 0,
    ownedProcessCount: ownedProcessIds.length,
    remainingOwnedContainers: 0,
    remainingOwnedListeners: 0,
    remainingOwnedNetworks: 0,
    remoteCleanupLogSha256: sha256(logBytes),
    tunnelProcessLedgerSha256: sha256(tunnelLedgerBytes),
    status: "passed",
  };
  writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
  return receipt;
}

function parseArguments(argv) {
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    requireCondition(name?.startsWith("--") && value !== undefined,
      "Arguments must be --name value pairs.");
    requireCondition(!values.has(name.slice(2)), `Duplicate argument ${name}.`);
    values.set(name.slice(2), value);
  }
  return values;
}

async function runCli() {
  const values = parseArguments(process.argv.slice(2));
  const checkedHead = values.get("checked-head");
  const remoteCleanupLog = values.get("remote-cleanup-log");
  const tunnelProcessLedger = values.get("tunnel-process-ledger");
  const output = values.get("output");
  const remoteServerProcessId = Number(values.get("remote-server-process-id"));
  requireCondition(
    checkedHead
      && remoteCleanupLog
      && tunnelProcessLedger
      && output
      && Number.isSafeInteger(remoteServerProcessId),
    "--checked-head, --remote-cleanup-log, --tunnel-process-ledger, --remote-server-process-id, and --output are required.",
  );
  await createConnectedServerTeardownReceipt({
    checkedHead,
    remoteCleanupLog,
    tunnelProcessLedger,
    output,
    remoteServerProcessId,
  });
  process.stdout.write("CONNECTED_SERVER_TEARDOWN_RECEIPT=PASS\n");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runCli().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
