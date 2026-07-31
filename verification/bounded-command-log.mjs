import {
  closeSync,
  fstatSync,
  lstatSync,
  openSync,
  realpathSync,
  writeSync,
} from "node:fs";
import path from "node:path";
import {
  assertPrivateDirectory,
  protectAndVerifyPrivateFile,
} from "./private-gate-artifacts.mjs";

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

export function openVerifiedCommandLog(logPath, expectedLogDirectory) {
  requireCondition(
    path.isAbsolute(logPath) && path.isAbsolute(expectedLogDirectory),
    "Command log paths must be absolute.",
  );
  const normalizedDirectory = assertPrivateDirectory(
    path.normalize(expectedLogDirectory),
  );
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
    protectAndVerifyPrivateFile(normalizedLogPath);
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

export function writeAll(descriptor, bytes) {
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
