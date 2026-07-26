import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  INTEGRATED_GATE_BYTE_LIMITS,
  readBoundedJsonArtifact,
} from "./integrated-gate-artifact-bounds.mjs";

const SHA40 = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const CELL_ID = /^[a-z0-9]+(?:[.-][a-z0-9]+)*$/;
const RECEIPT_SCOPES = Object.freeze({
  candidate: "candidateCells",
  "hosted-closure": "hostedClosureCells",
});
const INTEGRATED_GATE_IDS = new Set([
  "integrated-identity-access",
  "integrated-product-checkpoint",
  "integrated-preprocessing-language-routing",
]);
const MANIFEST_KEYS = new Set([
  "schemaVersion",
  "gateId",
  "candidateCells",
  "hostedClosureCells",
]);
const RECEIPT_KEYS_V2 = new Set([
  "schemaVersion",
  "gateId",
  "scope",
  "checkedHead",
  "candidateHead",
  "candidateReceiptSha256",
  "manifestSha256",
  "status",
  "startedAt",
  "finishedAt",
  "children",
]);
const RECEIPT_KEYS_V3 = new Set([
  ...RECEIPT_KEYS_V2,
  "admissionSha256",
]);
const CHILD_KEYS = new Set([
  "id",
  "executor",
  "checkedHead",
  "definitionSha256",
  "evidenceSha256",
  "attempt",
  "status",
  "startedAt",
  "finishedAt",
]);

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function requireExactKeys(value, allowed, label) {
  const extra = Object.keys(value).filter((key) => !allowed.has(key));
  requireCondition(extra.length === 0, `${label} contains unsupported fields: ${extra.join(", ")}.`);
}

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, stableValue(value[key])]),
    );
  }
  return value;
}

function stableJson(value) {
  return JSON.stringify(stableValue(value));
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function validTimestamp(value) {
  return typeof value === "string"
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(value)
    && Number.isFinite(Date.parse(value));
}

function validateCell(cell, seen) {
  requireCondition(cell && typeof cell === "object" && !Array.isArray(cell),
    "Every gate cell must be an object.");
  requireCondition(CELL_ID.test(cell.id ?? ""), `Invalid gate cell id: ${String(cell.id)}.`);
  requireCondition(!seen.has(cell.id), `Duplicate gate cell id: ${cell.id}.`);
  seen.add(cell.id);

  if (cell.executor === "command") {
    requireExactKeys(cell, new Set(["id", "executor", "cwd", "command"]), `Cell ${cell.id}`);
    requireCondition(
      typeof cell.cwd === "string"
        && cell.cwd.length > 0
        && !path.isAbsolute(cell.cwd)
        && !cell.cwd.split(/[\\/]/).includes(".."),
      `Cell ${cell.id} has an unsafe working directory.`,
    );
    requireCondition(
      Array.isArray(cell.command)
        && cell.command.length > 0
        && cell.command.length <= 32
        && cell.command.every((part) => typeof part === "string" && part.length > 0),
      `Cell ${cell.id} has an invalid command.`,
    );
  } else if (cell.executor === "private-receipt") {
    requireExactKeys(cell, new Set(["id", "executor", "receiptContract"]), `Cell ${cell.id}`);
    requireCondition(
      CELL_ID.test(cell.receiptContract ?? ""),
      `Cell ${cell.id} has an invalid private receipt contract.`,
    );
  } else if (cell.executor === "github-check") {
    requireExactKeys(cell, new Set(["id", "executor", "workflow", "job"]), `Cell ${cell.id}`);
    requireCondition(
      typeof cell.workflow === "string" && cell.workflow.length > 0
        && typeof cell.job === "string" && cell.job.length > 0,
      `Cell ${cell.id} has an invalid hosted check identity.`,
    );
  } else {
    throw new Error(`Cell ${cell.id} has unsupported executor ${String(cell.executor)}.`);
  }
}

export function validateIntegratedGateManifest(manifest) {
  requireCondition(manifest && typeof manifest === "object" && !Array.isArray(manifest),
    "Integrated gate manifest must be an object.");
  requireExactKeys(manifest, MANIFEST_KEYS, "Integrated gate manifest");
  requireCondition(manifest.schemaVersion === 1, "Integrated gate manifest schemaVersion must be 1.");
  requireCondition(
    INTEGRATED_GATE_IDS.has(manifest.gateId),
    "Integrated gate manifest has the wrong gate id.",
  );
  requireCondition(
    Array.isArray(manifest.candidateCells) && manifest.candidateCells.length > 0,
    "Integrated gate manifest needs candidate cells.",
  );
  requireCondition(
    Array.isArray(manifest.hostedClosureCells) && manifest.hostedClosureCells.length > 0,
    "Integrated gate manifest needs hosted-closure cells.",
  );
  const seen = new Set();
  for (const cell of [...manifest.candidateCells, ...manifest.hostedClosureCells]) {
    validateCell(cell, seen);
  }
  return manifest;
}

export function integratedGateManifestSha256(bytes) {
  return sha256(bytes);
}

export function integratedGateCellDefinitionSha256(cell) {
  return sha256(stableJson(cell));
}

export function validateIntegratedGateReceipt({
  receipt,
  manifest,
  manifestSha256,
  expectedHead,
  expectedCandidateHead = expectedHead,
  expectedCandidateReceiptSha256 = null,
  expectedAdmissionSha256 = null,
  expectedScope,
}) {
  validateIntegratedGateManifest(manifest);
  requireCondition(receipt && typeof receipt === "object" && !Array.isArray(receipt),
    "Integrated gate receipt must be an object.");
  requireCondition(
    receipt.schemaVersion === 2 || receipt.schemaVersion === 3,
    "Integrated gate receipt schemaVersion must be 2 or 3.",
  );
  requireExactKeys(
    receipt,
    receipt.schemaVersion === 3 ? RECEIPT_KEYS_V3 : RECEIPT_KEYS_V2,
    "Integrated gate receipt",
  );
  requireCondition(
    manifest.gateId !== "integrated-identity-access" || receipt.schemaVersion === 3,
    "Identity and access receipts must bind their admission.",
  );
  if (receipt.schemaVersion === 3) {
    requireCondition(
      SHA256.test(expectedAdmissionSha256 ?? "")
        && receipt.admissionSha256 === expectedAdmissionSha256,
      "Integrated gate receipt admission identity does not match.",
    );
  }
  requireCondition(receipt.gateId === manifest.gateId, "Integrated gate receipt has the wrong gate id.");
  requireCondition(RECEIPT_SCOPES[expectedScope], "Integrated gate receipt scope is unsupported.");
  requireCondition(receipt.scope === expectedScope, "Integrated gate receipt has the wrong scope.");
  requireCondition(SHA40.test(expectedHead ?? ""), "Expected checked head must be a lowercase Git SHA.");
  requireCondition(receipt.checkedHead === expectedHead, "Integrated gate receipt head does not match.");
  requireCondition(
    SHA40.test(expectedCandidateHead ?? "") && receipt.candidateHead === expectedCandidateHead,
    "Integrated gate receipt candidate head does not match.",
  );
  if (expectedScope === "candidate") {
    requireCondition(
      receipt.candidateHead === receipt.checkedHead
        && expectedCandidateReceiptSha256 === null
        && receipt.candidateReceiptSha256 === null,
      "Candidate receipt cannot refer to a predecessor receipt.",
    );
  } else {
    requireCondition(
      SHA256.test(expectedCandidateReceiptSha256 ?? "")
        && receipt.candidateReceiptSha256 === expectedCandidateReceiptSha256,
      "Hosted closure is not bound to the candidate receipt.",
    );
  }
  requireCondition(
    SHA256.test(manifestSha256 ?? "") && receipt.manifestSha256 === manifestSha256,
    "Integrated gate receipt manifest identity does not match.",
  );
  requireCondition(receipt.status === "passed", "Integrated gate receipt did not pass.");
  requireCondition(
    validTimestamp(receipt.startedAt) && validTimestamp(receipt.finishedAt)
      && Date.parse(receipt.finishedAt) >= Date.parse(receipt.startedAt),
    "Integrated gate receipt timestamps are invalid.",
  );

  const expectedCells = manifest[RECEIPT_SCOPES[expectedScope]];
  requireCondition(
    Array.isArray(receipt.children) && receipt.children.length === expectedCells.length,
    `Integrated gate receipt must contain exactly ${expectedCells.length} children.`,
  );
  receipt.children.forEach((child, index) => {
    const expected = expectedCells[index];
    requireCondition(child && typeof child === "object" && !Array.isArray(child),
      `Integrated gate child ${index + 1} must be an object.`);
    requireExactKeys(child, CHILD_KEYS, `Integrated gate child ${index + 1}`);
    requireCondition(child.id === expected.id, `Integrated gate child ${index + 1} is out of order.`);
    requireCondition(child.executor === expected.executor, `Integrated gate child ${child.id} executor changed.`);
    requireCondition(child.checkedHead === expectedHead, `Integrated gate child ${child.id} head changed.`);
    requireCondition(
      child.definitionSha256 === integratedGateCellDefinitionSha256(expected),
      `Integrated gate child ${child.id} definition changed.`,
    );
    requireCondition(SHA256.test(child.evidenceSha256 ?? ""),
      `Integrated gate child ${child.id} evidence identity is invalid.`);
    requireCondition(child.attempt === 1, `Integrated gate child ${child.id} was not the one admitted attempt.`);
    requireCondition(child.status === "passed", `Integrated gate child ${child.id} did not pass.`);
    requireCondition(
      validTimestamp(child.startedAt) && validTimestamp(child.finishedAt)
        && Date.parse(child.finishedAt) >= Date.parse(child.startedAt)
        && Date.parse(child.startedAt) >= Date.parse(receipt.startedAt)
        && Date.parse(child.finishedAt) <= Date.parse(receipt.finishedAt),
      `Integrated gate child ${child.id} timestamps are invalid.`,
    );
  });
  return Object.freeze({
    candidateHead: receipt.candidateHead,
    checkedHead: receipt.checkedHead,
    childCount: receipt.children.length,
    admissionSha256: receipt.admissionSha256 ?? null,
    manifestSha256: receipt.manifestSha256,
    scope: receipt.scope,
  });
}

function parseArguments(argv) {
  const [operation, ...rest] = argv;
  const values = new Map();
  for (let index = 0; index < rest.length; index += 2) {
    const name = rest[index];
    const value = rest[index + 1];
    if (!name?.startsWith("--") || value === undefined) {
      throw new Error("Gate receipt arguments must be --name value pairs.");
    }
    values.set(name.slice(2), value);
  }
  return { operation, values };
}

function runCli() {
  const { operation, values } = parseArguments(process.argv.slice(2));
  const manifestPath = values.get("manifest");
  requireCondition(manifestPath, "--manifest is required.");
  const manifestArtifact = readBoundedJsonArtifact(
    manifestPath,
    "Integrated gate manifest",
    INTEGRATED_GATE_BYTE_LIMITS.gateManifestBytes,
  );
  const manifest = validateIntegratedGateManifest(manifestArtifact.value);
  const manifestSha256 = integratedGateManifestSha256(manifestArtifact.bytes);
  if (operation === "manifest") {
    process.stdout.write(`${JSON.stringify({
      candidateCells: manifest.candidateCells.map(({ id }) => id),
      gateId: manifest.gateId,
      hostedClosureCells: manifest.hostedClosureCells.map(({ id }) => id),
      manifestSha256,
      schemaVersion: manifest.schemaVersion,
    }, null, 2)}\n`);
    return;
  }
  requireCondition(operation === "validate", "Operation must be manifest or validate.");
  const receiptPath = values.get("receipt");
  const expectedHead = values.get("checked-head");
  const expectedCandidateHead = values.get("candidate-head") ?? expectedHead;
  const expectedCandidateReceiptSha256 =
    values.get("candidate-receipt-sha256") ?? null;
  const expectedAdmissionSha256 = values.get("admission-sha256") ?? null;
  const expectedScope = values.get("scope");
  requireCondition(receiptPath, "--receipt is required.");
  const receipt = readBoundedJsonArtifact(
    receiptPath,
    "Integrated gate receipt",
    INTEGRATED_GATE_BYTE_LIMITS.candidateReceiptBytes,
  );
  const result = validateIntegratedGateReceipt({
    receipt: receipt.value,
    manifest,
    manifestSha256,
    expectedHead,
    expectedCandidateHead,
    expectedCandidateReceiptSha256,
    expectedAdmissionSha256,
    expectedScope,
  });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runCli();
}
