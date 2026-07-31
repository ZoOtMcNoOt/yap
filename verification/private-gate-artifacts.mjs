import { spawnSync } from "node:child_process";
import {
  chmodSync,
  closeSync,
  existsSync,
  fchmodSync,
  fstatSync,
  fsyncSync,
  lstatSync,
  openSync,
  readFileSync,
  realpathSync,
  statSync,
  unlinkSync,
  writeSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const moduleDirectory = path.dirname(fileURLToPath(import.meta.url));
const windowsAclHelper = path.join(
  moduleDirectory,
  "private-gate-artifacts.ps1",
);

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

function verifiedRealItem(candidate, kind, label) {
  requireCondition(path.isAbsolute(candidate), `${label} must be absolute.`);
  const normalized = path.normalize(candidate);
  const metadata = lstatSync(normalized);
  const real = path.normalize(realpathSync.native(normalized));
  requireCondition(
    (kind === "directory" ? metadata.isDirectory() : metadata.isFile())
      && !metadata.isSymbolicLink()
      && samePath(normalized, real),
    `${label} must be one real ${kind}.`,
  );
  return Object.freeze({ metadata, path: real });
}

function minimalWindowsEnvironment() {
  return Object.fromEntries(
    [
      "SystemRoot",
      "WINDIR",
      "TEMP",
      "TMP",
    ].flatMap((name) => (
      typeof process.env[name] === "string"
        ? [[name, process.env[name]]]
        : []
    )),
  );
}

function resolvePowerShell() {
  const systemRoot = process.env.SystemRoot ?? process.env.WINDIR;
  requireCondition(systemRoot, "Windows system root is unavailable.");
  return verifiedRealItem(
    path.join(
      systemRoot,
      "System32",
      "WindowsPowerShell",
      "v1.0",
      "powershell.exe",
    ),
    "file",
    "Windows system PowerShell executable",
  ).path;
}

function invokeWindowsAclHelper(operation, candidate, expectedPolicy) {
  const helper = verifiedRealItem(
    windowsAclHelper,
    "file",
    "Private gate ACL helper",
  ).path;
  const result = spawnSync(
    resolvePowerShell(),
    [
      "-NoLogo",
      "-NoProfile",
      "-NonInteractive",
      "-File",
      helper,
      "-Operation",
      operation,
      "-LiteralPath",
      candidate,
    ],
    {
      encoding: "utf8",
      env: minimalWindowsEnvironment(),
      maxBuffer: 64 * 1024,
      windowsHide: true,
    },
  );
  requireCondition(
    result.status === 0,
    `Private gate Windows DACL ${operation} failed: ${
      (result.stderr || result.stdout).trim().slice(0, 4_096)
    }`,
  );
  const value = JSON.parse(result.stdout);
  requireCondition(
    value.schemaVersion === 1
      && samePath(value.path, candidate)
      && value.policy === expectedPolicy
      && value.protectedDacl === true
      && value.explicitRuleCount === 3,
    "Private gate Windows DACL verification returned an invalid result.",
  );
}

function verifyPosixPermissions(candidate, kind) {
  requireCondition(
    typeof process.getuid === "function",
    "Private gate POSIX ownership cannot be verified.",
  );
  const metadata = statSync(candidate);
  const expectedMode = kind === "directory" ? 0o700 : 0o600;
  requireCondition(
    metadata.uid === process.getuid()
      && (metadata.mode & 0o777) === expectedMode,
    `Private gate ${kind} must be owned by the current user with mode ${
      expectedMode.toString(8)
    }.`,
  );
}

function protectOrVerifyPrivateItem(
  candidate,
  kind,
  protect,
  windowsPolicy = "gate",
) {
  const verified = verifiedRealItem(
    path.normalize(candidate),
    kind,
    `Private gate ${kind}`,
  );
  if (kind === "file") {
    requireCondition(
      verified.metadata.nlink === 1,
      "Private gate file must not be hard-linked.",
    );
  }
  if (process.platform === "win32") {
    const operationKind = windowsPolicy === "openssh"
      ? "ssh-file"
      : kind;
    if (protect) {
      invokeWindowsAclHelper(
        `protect-${operationKind}`,
        verified.path,
        windowsPolicy,
      );
    } else {
      invokeWindowsAclHelper(
        `verify-${operationKind}`,
        verified.path,
        windowsPolicy,
      );
    }
  } else {
    if (protect) chmodSync(verified.path, kind === "directory" ? 0o700 : 0o600);
    verifyPosixPermissions(verified.path, kind);
  }
  verifiedRealItem(verified.path, kind, `Private gate ${kind}`);
  return verified.path;
}

export function protectAndVerifyPrivateDirectory(candidate) {
  return protectOrVerifyPrivateItem(candidate, "directory", true);
}

export function assertPrivateDirectory(candidate) {
  return protectOrVerifyPrivateItem(candidate, "directory", false);
}

export function protectAndVerifyPrivateFile(candidate) {
  return protectOrVerifyPrivateItem(candidate, "file", true);
}

export function assertPrivateFile(candidate) {
  return protectOrVerifyPrivateItem(candidate, "file", false);
}

export function protectAndVerifyPrivateSshFile(candidate) {
  return protectOrVerifyPrivateItem(candidate, "file", true, "openssh");
}

export function assertPrivateSshFile(candidate) {
  return protectOrVerifyPrivateItem(candidate, "file", false, "openssh");
}

export function writeExclusivePrivateFile(candidate, bytes) {
  requireCondition(
    Buffer.isBuffer(bytes) || bytes instanceof Uint8Array,
    "Private gate file bytes must be one bounded byte array.",
  );
  const normalized = path.normalize(candidate);
  const parent = assertPrivateDirectory(path.dirname(normalized));
  requireCondition(
    samePath(parent, path.dirname(normalized)),
    "Private gate file escaped its protected parent.",
  );
  let descriptor = null;
  let owned = false;
  try {
    descriptor = openSync(normalized, "wx", 0o600);
    owned = true;
    if (process.platform !== "win32") fchmodSync(descriptor, 0o600);
    protectAndVerifyPrivateFile(normalized);
    const descriptorMetadata = fstatSync(descriptor);
    const pathMetadata = statSync(normalized);
    requireCondition(
      descriptorMetadata.isFile()
        && descriptorMetadata.dev === pathMetadata.dev
        && descriptorMetadata.ino === pathMetadata.ino
        && descriptorMetadata.nlink === 1,
      "Private gate file identity changed before publication.",
    );
    let offset = 0;
    while (offset < bytes.length) {
      const count = writeSync(
        descriptor,
        bytes,
        offset,
        bytes.length - offset,
      );
      requireCondition(count > 0, "Private gate file write made no progress.");
      offset += count;
    }
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = null;
    assertPrivateFile(normalized);
    return normalized;
  } catch (error) {
    if (descriptor !== null) {
      try {
        closeSync(descriptor);
      } catch {
        // Preserve the publication failure.
      }
    }
    if (owned && existsSync(normalized)) {
      try {
        unlinkSync(normalized);
      } catch {
        // The caller still receives the original fail-closed publication error.
      }
    }
    throw error;
  }
}

export function readExactPrivateFile(candidate, expectedBytes) {
  requireCondition(
    Number.isSafeInteger(expectedBytes) && expectedBytes >= 0,
    "Expected private file byte length must be one nonnegative safe integer.",
  );
  const verified = assertPrivateFile(path.normalize(candidate));
  const metadata = statSync(verified);
  requireCondition(
    metadata.size === expectedBytes,
    `Private gate file must contain exactly ${expectedBytes} bytes.`,
  );
  const bytes = readFileSync(verified);
  requireCondition(
    bytes.length === expectedBytes,
    "Private gate file changed while it was read.",
  );
  assertPrivateFile(verified);
  return bytes;
}
