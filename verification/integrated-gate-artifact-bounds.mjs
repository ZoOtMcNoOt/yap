import { createHash } from "node:crypto";
import {
  closeSync,
  existsSync,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
  realpathSync,
} from "node:fs";
import path from "node:path";

const READ_CHUNK_BYTES = 64 * 1024;

export const INTEGRATED_GATE_BYTE_LIMITS = Object.freeze({
  admissionBytes: 256 * 1024,
  candidateReceiptBytes: 1024 * 1024,
  commandLogBytes: 16 * 1024 * 1024,
  gateManifestBytes: 1024 * 1024,
  privateJsonEvidenceBytes: 1024 * 1024,
  privateLogEvidenceBytes: 8 * 1024 * 1024,
  privatePlanBytes: 1024 * 1024,
  runMarkerBytes: 64 * 1024,
});

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function samePath(left, right) {
  return process.platform === "win32"
    ? left.toLowerCase() === right.toLowerCase()
    : left === right;
}

function displayByteCount(value) {
  return value <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(value) : value.toString();
}

export class IntegratedGateArtifactLimitError extends Error {
  constructor(label, maximumBytes, observedBytes) {
    super(
      `${label} exceeds its ${maximumBytes}-byte limit `
      + `(observed ${String(observedBytes)} bytes).`,
    );
    this.name = "IntegratedGateArtifactLimitError";
    this.code = "INTEGRATED_GATE_ARTIFACT_LIMIT_EXCEEDED";
    this.artifactLabel = label;
    this.maximumBytes = maximumBytes;
    this.observedBytes = observedBytes;
  }
}

function requireMaximumBytes(maximumBytes) {
  requireCondition(
    Number.isSafeInteger(maximumBytes) && maximumBytes > 0,
    "Artifact byte limit must be one positive safe integer.",
  );
}

function requireWithinLimit(label, maximumBytes, observedBytes) {
  if (observedBytes > BigInt(maximumBytes)) {
    throw new IntegratedGateArtifactLimitError(
      label,
      maximumBytes,
      displayByteCount(observedBytes),
    );
  }
}

function stableOpenedFile(candidate, label, maximumBytes, consume) {
  requireMaximumBytes(maximumBytes);
  const resolved = path.resolve(candidate);
  requireCondition(existsSync(resolved), `${label} does not exist.`);
  const pathMetadata = lstatSync(resolved, { bigint: true });
  requireCondition(
    pathMetadata.isFile() && !pathMetadata.isSymbolicLink(),
    `${label} must be a real regular file.`,
  );
  requireWithinLimit(label, maximumBytes, pathMetadata.size);

  const real = path.normalize(realpathSync.native(resolved));
  requireCondition(
    samePath(path.normalize(resolved), real),
    `${label} must not resolve through a redirected parent.`,
  );

  const descriptor = openSync(real, "r");
  try {
    const before = fstatSync(descriptor, { bigint: true });
    requireCondition(before.isFile(), `${label} must remain a regular file.`);
    requireWithinLimit(label, maximumBytes, before.size);
    requireCondition(
      before.dev === pathMetadata.dev && before.ino === pathMetadata.ino,
      `${label} changed while it was opened.`,
    );

    const buffer = Buffer.allocUnsafe(
      Math.min(READ_CHUNK_BYTES, maximumBytes + 1),
    );
    let byteLength = 0;
    while (true) {
      const bytesRead = readSync(descriptor, buffer, 0, buffer.length, null);
      if (bytesRead === 0) break;
      const nextLength = byteLength + bytesRead;
      if (nextLength > maximumBytes) {
        throw new IntegratedGateArtifactLimitError(
          label,
          maximumBytes,
          nextLength,
        );
      }
      consume(buffer.subarray(0, bytesRead));
      byteLength = nextLength;
    }

    const after = fstatSync(descriptor, { bigint: true });
    requireCondition(
      after.size === before.size
        && after.mtimeNs === before.mtimeNs
        && after.ctimeNs === before.ctimeNs
        && BigInt(byteLength) === before.size,
      `${label} changed while it was read.`,
    );
    return { byteLength, path: real };
  } finally {
    closeSync(descriptor);
  }
}

export function readBoundedRegularFile(candidate, label, maximumBytes) {
  const chunks = [];
  const result = stableOpenedFile(
    candidate,
    label,
    maximumBytes,
    (chunk) => chunks.push(Buffer.from(chunk)),
  );
  return {
    ...result,
    bytes: Buffer.concat(chunks, result.byteLength),
  };
}

export function readBoundedJsonArtifact(candidate, label, maximumBytes) {
  const artifact = readBoundedRegularFile(candidate, label, maximumBytes);
  try {
    return {
      ...artifact,
      value: JSON.parse(artifact.bytes.toString("utf8")),
    };
  } catch (error) {
    throw new SyntaxError(
      `${label} is not valid JSON: ${error instanceof Error ? error.message : String(error)}`,
      { cause: error },
    );
  }
}

export function sha256BoundedRegularFile(candidate, label, maximumBytes) {
  const digest = createHash("sha256");
  const result = stableOpenedFile(
    candidate,
    label,
    maximumBytes,
    (chunk) => digest.update(chunk),
  );
  return {
    ...result,
    sha256: digest.digest("hex"),
  };
}

export function serializeBoundedJson(value, label, maximumBytes) {
  requireMaximumBytes(maximumBytes);
  const bytes = Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf8");
  requireWithinLimit(label, maximumBytes, BigInt(bytes.length));
  return bytes;
}
