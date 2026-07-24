import { execFile, spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  closeSync,
  existsSync,
  fstatSync,
  lstatSync,
  openSync,
  realpathSync,
  writeSync,
} from "node:fs";
import path from "node:path";

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function samePath(left, right) {
  const normalizedLeft = path.normalize(left);
  const normalizedRight = path.normalize(right);
  return process.platform === "win32"
    ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight;
}

function openVerifiedCommandLog(logPath, expectedLogDirectory) {
  requireCondition(
    path.isAbsolute(logPath) && path.isAbsolute(expectedLogDirectory),
    "Command log paths must be absolute.",
  );
  const normalizedDirectory = path.normalize(expectedLogDirectory);
  const directoryMetadata = lstatSync(normalizedDirectory);
  requireCondition(
    directoryMetadata.isDirectory() && !directoryMetadata.isSymbolicLink(),
    "Command log directory must be a real directory.",
  );
  const realDirectory = path.normalize(
    realpathSync.native(normalizedDirectory),
  );
  requireCondition(
    samePath(normalizedDirectory, realDirectory),
    "Command log directory must not resolve through a redirected parent.",
  );
  const normalizedLogPath = path.normalize(logPath);
  requireCondition(
    samePath(path.dirname(normalizedLogPath), realDirectory),
    "Command log escaped its verified private directory.",
  );

  const descriptor = openSync(normalizedLogPath, "wx", 0o600);
  try {
    const descriptorMetadata = fstatSync(descriptor);
    const pathMetadata = lstatSync(normalizedLogPath);
    const realLogPath = path.normalize(realpathSync.native(normalizedLogPath));
    requireCondition(
      descriptorMetadata.isFile()
        && pathMetadata.isFile()
        && !pathMetadata.isSymbolicLink()
        && descriptorMetadata.dev === pathMetadata.dev
        && descriptorMetadata.ino === pathMetadata.ino
        && samePath(realLogPath, normalizedLogPath)
        && samePath(path.dirname(realLogPath), realDirectory),
      "Command log identity changed before execution.",
    );
    return descriptor;
  } catch (error) {
    closeSync(descriptor);
    throw error;
  }
}

function windowsCommandLine(command) {
  return command.map((token) => {
    requireCondition(
      !/[\r\n"&|<>^%]/.test(token),
      `Command token contains an unsupported Windows shell character: ${token}`,
    );
    return /\s/.test(token) ? `"${token}"` : token;
  }).join(" ");
}

function resolveWindowsCommand(executable, cwd) {
  const localCandidate = path.resolve(cwd, executable);
  const candidates = executable.includes("/") || executable.includes("\\")
    ? [localCandidate]
    : spawnSync("where.exe", [executable], {
      cwd,
      encoding: "utf8",
      maxBuffer: 64 * 1024,
      windowsHide: true,
    }).stdout?.split(/\r?\n/).filter(Boolean) ?? [];
  const resolved = candidates.find((candidate) => (
    [".bat", ".cmd", ".com", ".exe"].includes(path.extname(candidate).toLowerCase())
      && existsSync(candidate)
      && lstatSync(candidate).isFile()
  ));
  requireCondition(resolved, `Windows could not resolve command ${executable}.`);
  return path.normalize(resolved);
}

function commandProcess(command, cwd) {
  const [executable, ...args] = command;
  if (process.platform !== "win32") return { executable, args, cwd };
  const resolved = resolveWindowsCommand(executable, cwd);
  if (![".bat", ".cmd"].includes(path.extname(resolved).toLowerCase())) {
    return { executable: resolved, args, cwd };
  }
  return {
    executable: process.env.ComSpec || "cmd.exe",
    args: ["/d", "/s", "/c", windowsCommandLine(["call", resolved, ...args])],
    cwd,
  };
}

export class BoundedCommandOutputLimitError extends Error {
  constructor(label, maximumBytes, observedBytes) {
    super(
      `${label} exceeded its ${maximumBytes}-byte command-log limit `
      + `(observed at least ${observedBytes} bytes); process-tree termination was requested.`,
    );
    this.name = "BoundedCommandOutputLimitError";
    this.code = "INTEGRATED_GATE_COMMAND_OUTPUT_LIMIT_EXCEEDED";
    this.maximumBytes = maximumBytes;
    this.observedBytes = observedBytes;
  }
}

const WINDOWS_PROCESS_SNAPSHOT_COMMAND = [
  "$ErrorActionPreference='Stop'",
  "$rows=Get-Process | ForEach-Object {",
  "  [pscustomobject]@{ProcessId=$_.Id;ParentProcessId=$_.Parent.Id}",
  "}",
  "$rows | ConvertTo-Json -Compress",
].join("; ");

function windowsProcessSnapshot() {
  return new Promise((resolve, reject) => {
    execFile(
      "powershell.exe",
      [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        WINDOWS_PROCESS_SNAPSHOT_COMMAND,
      ],
      {
        encoding: "utf8",
        maxBuffer: 4 * 1024 * 1024,
        timeout: 5_000,
        windowsHide: true,
      },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(
            `Windows process-tree snapshot failed: ${
              (stderr || error.message || "unknown error").trim()
            }`,
            { cause: error },
          ));
          return;
        }
        try {
          resolve(JSON.parse(stdout));
        } catch (parseError) {
          reject(new Error(
            "Windows process-tree snapshot returned invalid JSON.",
            { cause: parseError },
          ));
        }
      },
    );
  });
}

async function windowsDescendantProcessIds(rootProcessId) {
  const parsed = await windowsProcessSnapshot();
  const rows = (Array.isArray(parsed) ? parsed : [parsed]).filter((row) => (
    Number.isSafeInteger(row?.ProcessId)
      && row.ProcessId > 0
      && Number.isSafeInteger(row?.ParentProcessId)
      && row.ParentProcessId >= 0
  ));
  const children = new Map();
  for (const row of rows) {
    const existing = children.get(row.ParentProcessId) ?? [];
    existing.push(row.ProcessId);
    children.set(row.ParentProcessId, existing);
  }
  const descendants = [];
  const seen = new Set([rootProcessId]);
  const visit = (processId) => {
    for (const childProcessId of children.get(processId) ?? []) {
      if (seen.has(childProcessId)) continue;
      seen.add(childProcessId);
      visit(childProcessId);
      descendants.push(childProcessId);
    }
  };
  visit(rootProcessId);
  return descendants;
}

function forceKill(processId) {
  try {
    process.kill(processId, "SIGKILL");
  } catch (error) {
    if (error?.code !== "ESRCH") throw error;
  }
}

async function terminateProcessTree(child) {
  if (!Number.isSafeInteger(child.pid) || child.pid <= 0) return [];
  if (process.platform === "win32") {
    const descendants = await windowsDescendantProcessIds(child.pid);
    forceKill(child.pid);
    for (const processId of descendants) forceKill(processId);
    return [child.pid, ...descendants];
  }
  try {
    process.kill(-child.pid, "SIGKILL");
  } catch {
    try {
      child.kill("SIGKILL");
    } catch {
      // The process group may already be gone.
    }
  }
  return [child.pid];
}

function writeAll(descriptor, bytes) {
  let offset = 0;
  while (offset < bytes.length) {
    const bytesWritten = writeSync(
      descriptor,
      bytes,
      offset,
      bytes.length - offset,
    );
    requireCondition(bytesWritten > 0, "Command log write made no progress.");
    offset += bytesWritten;
  }
}

export function executeBoundedCommand({
  command,
  cwd,
  environment,
  label,
  logPath,
  expectedLogDirectory,
  maximumLogBytes,
}) {
  requireCondition(
    Number.isSafeInteger(maximumLogBytes) && maximumLogBytes > 0,
    "Command-log byte limit must be one positive safe integer.",
  );
  const logDescriptor = openVerifiedCommandLog(
    logPath,
    expectedLogDirectory,
  );
  let invocation;
  try {
    invocation = commandProcess(command, cwd);
  } catch (error) {
    closeSync(logDescriptor);
    throw error;
  }

  return new Promise((resolve, reject) => {
    const digest = createHash("sha256");
    let byteLength = 0;
    let terminalError = null;
    let terminationPromise = Promise.resolve();
    let settled = false;
    let child;

    const settle = (error, result) => {
      if (settled) return;
      settled = true;
      closeSync(logDescriptor);
      if (error) reject(error);
      else resolve(result);
    };
    const requestTermination = (error) => {
      if (terminalError) return;
      terminalError = error;
      terminationPromise = terminateProcessTree(child)
        .then((terminatedProcessIds) => {
          error.terminatedProcessIds = terminatedProcessIds;
        })
        .catch((terminationError) => {
          terminalError = new AggregateError(
            [error, terminationError],
            `${label} failed and its process tree could not be fully terminated.`,
          );
          try {
            child.kill("SIGKILL");
          } catch {
            // Preserve both the command failure and tree-termination failure.
          }
        });
    };
    const settleAfterTermination = (error, result) => {
      terminationPromise.then(
        () => settle(terminalError ?? error, result),
        (terminationError) => settle(terminationError),
      );
    };
    const capture = (chunk) => {
      if (terminalError) return;
      try {
        const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
        const observedBytes = byteLength + bytes.length;
        const acceptedLength = Math.min(
          bytes.length,
          maximumLogBytes - byteLength,
        );
        if (acceptedLength > 0) {
          const accepted = bytes.subarray(0, acceptedLength);
          writeAll(logDescriptor, accepted);
          digest.update(accepted);
          byteLength += acceptedLength;
        }
        if (observedBytes > maximumLogBytes) {
          requestTermination(new BoundedCommandOutputLimitError(
            label,
            maximumLogBytes,
            observedBytes,
          ));
        }
      } catch (error) {
        const failure = new Error(
          `${label} command log could not be written safely.`,
          { cause: error },
        );
        failure.code = "INTEGRATED_GATE_COMMAND_LOG_WRITE_FAILED";
        requestTermination(failure);
      }
    };

    try {
      child = spawn(invocation.executable, invocation.args, {
        cwd: invocation.cwd,
        detached: process.platform !== "win32",
        env: environment,
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      });
    } catch (error) {
      settle(error);
      return;
    }
    child.stdout.on("data", capture);
    child.stderr.on("data", capture);
    child.once("error", (error) => settleAfterTermination(error));
    child.once("close", (exitCode, signal) => {
      if (terminalError) {
        settleAfterTermination(terminalError);
        return;
      }
      settle(null, {
        evidenceSha256: digest.digest("hex"),
        exitCode,
        signal,
      });
    });
  });
}
