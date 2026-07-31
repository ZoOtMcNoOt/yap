import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  realpathSync,
} from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  INTEGRATED_GATE_BYTE_LIMITS,
  readBoundedJsonArtifact,
  readBoundedRegularFile,
  serializeBoundedJson,
} from "./integrated-gate-artifact-bounds.mjs";
import {
  assertPrivateDirectory,
  assertPrivateFile,
  writeExclusivePrivateFile,
} from "./private-gate-artifacts.mjs";

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
  remoteHelperSetSha256,
  processProbe = processExists,
  portProbe = portIsOpen,
}) {
  requireCondition(SHA40.test(checkedHead ?? ""),
    "Checked head must be one lowercase Git SHA.");
  requireCondition(
    Number.isSafeInteger(remoteServerProcessId) && remoteServerProcessId > 0,
    "The directly launched remote-server SSH process id is required.",
  );
  requireCondition(
    remoteHelperSetSha256 === undefined || /^[0-9a-f]{64}$/.test(remoteHelperSetSha256),
    "Remote helper-set identity must be one lowercase SHA-256 when supplied.",
  );
  const logCandidate = path.resolve(remoteCleanupLog);
  requireOutsideRepository(logCandidate, "Remote cleanup log");
  assertPrivateFile(logCandidate);
  const logArtifact = readBoundedRegularFile(
    logCandidate,
    "Remote cleanup log",
    INTEGRATED_GATE_BYTE_LIMITS.privateLogEvidenceBytes,
  );
  const logPath = logArtifact.path;
  requireOutsideRepository(logPath, "Remote cleanup log");
  const tunnelLedgerCandidate = path.resolve(tunnelProcessLedger);
  requireOutsideRepository(tunnelLedgerCandidate, "Tunnel process ledger");
  assertPrivateFile(tunnelLedgerCandidate);
  const tunnelLedgerArtifact = readBoundedJsonArtifact(
    tunnelLedgerCandidate,
    "Tunnel process ledger",
    INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes,
  );
  const tunnelLedgerPath = tunnelLedgerArtifact.path;
  requireOutsideRepository(tunnelLedgerPath, "Tunnel process ledger");
  requireCondition(path.isAbsolute(output), "Teardown receipt path must be absolute.");
  requireOutsideRepository(path.resolve(output), "Teardown receipt");
  requireCondition(!existsSync(output), "Teardown receipt destination must be new.");
  const outputParent = realDirectory(path.dirname(output), "Teardown receipt parent");
  requireCondition(
    outputParent.toLowerCase() === path.normalize(path.dirname(output)).toLowerCase(),
    "Teardown receipt parent must not redirect elsewhere.",
  );
  assertPrivateDirectory(outputParent);

  const logBytes = logArtifact.bytes;
  const logText = logBytes.toString("utf8");
  const tunnelLedgerBytes = tunnelLedgerArtifact.bytes;
  const tunnelLedger = tunnelLedgerArtifact.value;
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
  const helperSetLines = logText
    .split(/\r?\n/)
    .filter((line) => line.startsWith("REMOTE_HELPER_SET_SHA256="));
  requireCondition(
    cleanupLines.length === 1
      && cleanupLines[0] === "REMOTE_GATE_CLEANUP=PASS"
      && (
        remoteHelperSetSha256 === undefined
        || (
          helperSetLines.length === 1
          && helperSetLines[0] === `REMOTE_HELPER_SET_SHA256=${remoteHelperSetSha256}`
        )
      )
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
    schemaVersion: remoteHelperSetSha256 === undefined ? 1 : 2,
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
    ...(remoteHelperSetSha256 === undefined ? {} : { remoteHelperSetSha256 }),
    status: "passed",
  };
  const receiptBytes = serializeBoundedJson(
    receipt,
    "Connected-server teardown receipt",
    INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes,
  );
  writeExclusivePrivateFile(output, receiptBytes);
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
  const remoteHelperSetSha256 = values.get("remote-helper-set-sha256");
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
    ...(remoteHelperSetSha256 ? { remoteHelperSetSha256 } : {}),
  });
  process.stdout.write("CONNECTED_SERVER_TEARDOWN_RECEIPT=PASS\n");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runCli().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
