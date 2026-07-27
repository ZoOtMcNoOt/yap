import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  closeSync,
  existsSync,
  lstatSync,
  realpathSync,
} from "node:fs";
import path from "node:path";
import {
  BoundedCommandOutputLimitError,
  openVerifiedCommandLog,
  writeAll,
} from "./bounded-command-log.mjs";
import {
  cleanupUnprovenError,
  preservePrimaryError,
  windowsTerminationEvidence,
} from "./windows-command-job-errors.mjs";
import {
  cleanupWindowsSupervisorFiles,
  createWindowsSupervisorInvocation,
} from "./windows-command-job-protocol.mjs";
import {
  startWindowsSupervisorTerminationWatchdog,
} from "./windows-command-supervisor-watchdog.mjs";
import {
  interpretWindowsCommandResult,
} from "./windows-command-result.mjs";

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
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

async function terminateProcessTree(child) {
  if (!Number.isSafeInteger(child.pid) || child.pid <= 0) return [];
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
  let windowsProtocol = null;
  try {
    invocation = commandProcess(command, cwd);
    if (process.platform === "win32") {
      windowsProtocol = createWindowsSupervisorInvocation(
        invocation,
        path.normalize(realpathSync.native(expectedLogDirectory)),
        environment,
      );
      invocation = windowsProtocol.invocation;
    }
  } catch (error) {
    closeSync(logDescriptor);
    cleanupWindowsSupervisorFiles(windowsProtocol);
    throw error;
  }

  return new Promise((resolve, reject) => {
    const digest = createHash("sha256");
    let byteLength = 0;
    let terminalError = null;
    let terminationPromise = Promise.resolve();
    let cancelWindowsWatchdog = () => {};
    let settled = false;
    let child;

    const settle = (error, result) => {
      if (settled) return;
      settled = true;
      cancelWindowsWatchdog();
      let finalError = error;
      try {
        cleanupWindowsSupervisorFiles(windowsProtocol);
      } catch (cleanupError) {
        if (finalError) {
          finalError = preservePrimaryError(
            finalError,
            cleanupError,
            finalError.terminationEvidence,
          );
        } else {
          finalError = cleanupError;
        }
      }
      closeSync(logDescriptor);
      if (finalError) reject(finalError);
      else resolve(result);
    };
    const requestTermination = (error) => {
      if (terminalError) return;
      terminalError = error;
      if (process.platform === "win32") {
        try {
          child.stdin.end("T\n");
        } catch {
          // Missing proof is handled when the supervisor settles or times out.
        }
        cancelWindowsWatchdog = startWindowsSupervisorTerminationWatchdog({
          supervisor: child,
          onLateClose: () => {
            try {
              cleanupWindowsSupervisorFiles(windowsProtocol);
            } catch {
              // The promise already reported cleanup as unverified.
            }
          },
          onUnproven: (watchdogFailure) => {
            const terminationFailure = cleanupUnprovenError(
              label,
              watchdogFailure,
            );
            settle(preservePrimaryError(
              terminalError,
              terminationFailure,
              {
                schemaVersion: 1,
                containment: "windows-job-object",
                rootProcessId: null,
                assignedBeforeResume: false,
                terminationReason: "cleanup-unproven",
                terminateRequested: true,
                rootExited: false,
                activeProcessCount: null,
                activeProcessZeroObserved: false,
                cleanupProven: false,
              },
            ));
          },
        });
        return;
      }
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
        stdio: [process.platform === "win32" ? "pipe" : "ignore", "pipe", "pipe"],
        windowsHide: true,
      });
    } catch (error) {
      settle(error);
      return;
    }
    child.stdin?.on("error", () => {
      // A closed control pipe is reflected by missing or unproven status.
    });
    if (process.platform === "win32") {
      try {
        child.stdin.write(windowsProtocol.environmentPrelude);
      } catch (error) {
        requestTermination(error);
      }
    }
    child.stdout.on("data", capture);
    child.stderr.on("data", capture);
    child.once("error", (error) => {
      if (process.platform === "win32") requestTermination(error);
      else settleAfterTermination(error);
    });
    child.once("close", (exitCode, signal) => {
      if (process.platform === "win32") {
        if (settled) return;
        const interpreted = interpretWindowsCommandResult({
          exitCode,
          label,
          primaryError: terminalError,
          protocol: windowsProtocol,
          signal,
        });
        if (interpreted.error) {
          settle(interpreted.error);
          return;
        }
        settle(null, {
          evidenceSha256: digest.digest("hex"),
          exitCode: interpreted.status.targetExitCode,
          signal: null,
          terminationEvidence: windowsTerminationEvidence(
            interpreted.status,
            "none",
          ),
        });
        return;
      }
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

export { BoundedCommandOutputLimitError };
