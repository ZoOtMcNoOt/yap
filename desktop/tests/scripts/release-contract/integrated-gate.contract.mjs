import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
  symlinkSync,
  truncateSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

import {
  admitIntegratedGateAttempt,
  assertGateRunnerNodeRuntime,
  assertIntegratedGateManifestMatchesAdmission,
  completeIntegratedGateAttempt,
  integratedGateFailureRecord,
  integratedGateCommandEnvironment,
  integratedGateCommandLogSha256,
  loadIntegratedGateManifestSelection,
  parseIntegratedGateRunnerInvocation,
  runCommandCell,
  reserveIntegratedGateAttemptDirectory,
  validateLegacyIntegratedGateReservationValue,
  verifyIdentityAccessAdmissionPrerequisites,
} from "../../../../verification/integrated-gate-runner.mjs";
import {
  INTEGRATED_GATE_BYTE_LIMITS,
} from "../../../../verification/integrated-gate-artifact-bounds.mjs";
import {
  integratedGateCellDefinitionSha256,
  integratedGateManifestSha256,
  validateIntegratedGateManifest,
  validateIntegratedGateReceipt,
} from "../../../../verification/integrated-gate-receipt.mjs";
import {
  buildHostedClosureReceipt,
  selectHostedClosureEvidence,
} from "../../../../verification/integrated-hosted-closure.mjs";
import {
  validateIntegratedPrivateEvidence,
  validateIntegratedPrivateEvidencePlan,
} from "../../../../verification/integrated-private-evidence.mjs";
import {
  createConnectedServerTeardownReceipt,
} from "../../../../verification/write-connected-server-teardown-receipt.mjs";
import {
  GITHUB_ADMISSION_AUTHORITY_HOST,
  GITHUB_ADMISSION_REPOSITORY,
  GITHUB_ADMISSION_REPOSITORY_ID,
  githubApiArguments,
} from "../../../../verification/github-gate-admission.mjs";
import {
  assertPrivateDirectory,
  assertPrivateFile,
  protectAndVerifyPrivateDirectory,
  protectAndVerifyPrivateFile,
  readExactPrivateFile,
  writeExclusivePrivateFile,
} from "../../../../verification/private-gate-artifacts.mjs";

const contractRoot = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(contractRoot, "..", "..", "..", "..");
const manifestPath = path.join(
  repoRoot,
  "verification",
  "integrated-product-checkpoint-gate.json",
);
const manifestBytes = readFileSync(manifestPath);
const manifest = validateIntegratedGateManifest(JSON.parse(manifestBytes.toString("utf8")));
const manifestSha256 = integratedGateManifestSha256(manifestBytes);
const identityManifestPath = path.join(
  repoRoot,
  "verification",
  "integrated-identity-access-gate.json",
);
const identityManifestBytes = readFileSync(identityManifestPath);
const identityManifest = validateIntegratedGateManifest(
  JSON.parse(identityManifestBytes.toString("utf8")),
);
const phase6ManifestPath = path.join(
  repoRoot,
  "verification",
  "integrated-preprocessing-language-routing-gate.json",
);
const phase6ManifestBytes = readFileSync(phase6ManifestPath);
const phase6Manifest = validateIntegratedGateManifest(
  JSON.parse(phase6ManifestBytes.toString("utf8")),
);
const checkedHead = "a".repeat(40);
const startedAt = "2026-07-23T12:00:00.000Z";
const finishedAt = "2026-07-23T13:00:00.000Z";
const sha256 = (value) => createHash("sha256").update(value).digest("hex");

function createCanonicalTemporaryDirectory(prefix) {
  return protectAndVerifyPrivateDirectory(
    mkdtempSync(path.join(realpathSync.native(os.tmpdir()), prefix)),
  );
}

function protectPrivateFixtureTree(root) {
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const candidate = path.join(root, entry.name);
    if (entry.isDirectory()) {
      protectAndVerifyPrivateDirectory(candidate);
      protectPrivateFixtureTree(candidate);
    } else if (entry.isFile()) {
      protectAndVerifyPrivateFile(candidate);
    } else {
      throw new Error(`Private fixture tree contains an unsupported item: ${candidate}`);
    }
  }
}

function createGateStatusClient({ competingStatusWins = false } = {}) {
  const statuses = [];
  const repositoryId = 42;
  const repositoryFullName = "example/yap";
  function value(id, body) {
    return {
      id,
      state: body.state,
      context: body.context,
      description: body.description,
      created_at: `2026-07-23T12:00:0${id}.000Z`,
      url: `https://api.github.invalid/statuses/${id}`,
      creator: { id: 7, login: "gate-publisher" },
    };
  }
  return {
    authorityHost: GITHUB_ADMISSION_AUTHORITY_HOST,
    repositoryId,
    repositoryFullName,
    statuses,
    listStatuses() {
      return [...statuses].sort((left, right) => right.id - left.id);
    },
    createStatus(_head, body) {
      if (competingStatusWins && statuses.length === 0) {
        statuses.push(value(1, body));
      }
      const created = value(statuses.length + 1, body);
      statuses.push(created);
      return created;
    },
  };
}

function processIsAlive(processId) {
  try {
    process.kill(processId, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") return false;
    throw error;
  }
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

const candidateIds = [
  "frontend.node-runtime",
  "frontend.dependencies",
  "frontend.dependency-audit",
  "frontend.release-contracts",
  "frontend.provenance",
  "frontend.unit",
  "frontend.production-build",
  "frontend.chromium-runtime",
  "frontend.browser-workflows",
  "native.format",
  "native.clippy",
  "native.tests",
  "native.server-connector",
  "native.windows-dependency-boundary",
  "native.dependency-audit",
  "desktop.wdio-build",
  "desktop.required-wdio",
  "server.python-3.12",
  "server.lint",
  "target-client.native-resource-and-restart",
  "target-client.prepared-audio-boundaries",
  "target-client.rendered-ui-and-microphone",
  "target-client.teardown",
  "gb10.provider-duration-and-concurrency",
  "gb10.provider-cancellation-and-recovery",
  "gb10.provider-resource-bounds",
  "gb10.provider-teardown",
  "integrated.desktop-private-server",
  "integrated.tunnel-interruption-recovery",
  "integrated.authoritative-history-result",
  "integrated.teardown",
];
const identityCandidateIds = [
  "frontend.node-runtime",
  "frontend.dependencies",
  "frontend.dependency-audit",
  "frontend.release-contracts",
  "frontend.provenance",
  "frontend.unit",
  "frontend.production-build",
  "frontend.chromium-runtime",
  "frontend.browser-workflows",
  "windows.build-tools-optional-diagnostics-disabled",
  "server.python-3.12",
  "server.lint",
  "server.mock-oidc-owner-flow",
  "target-client.native-resource-and-restart",
  "target-client.prepared-audio-boundaries",
  "target-client.rendered-ui-and-microphone",
  "target-client.teardown",
  "gb10.provider-duration-and-concurrency",
  "gb10.provider-cancellation-and-recovery",
  "gb10.provider-resource-bounds",
  "gb10.provider-teardown",
  "integrated.desktop-private-server",
  "integrated.tunnel-interruption-recovery",
  "integrated.authoritative-history-result",
  "integrated.teardown",
];
const phase6CandidateIds = [
  "frontend.node-runtime",
  "frontend.dependencies",
  "frontend.dependency-audit",
  "frontend.release-contracts",
  "frontend.provenance",
  "frontend.unit",
  "frontend.production-build",
  "frontend.chromium-runtime",
  "frontend.accessibility-and-workflows",
  "native.format",
  "native.clippy",
  "native.tests",
  "native.server-connector",
  "native.windows-dependency-boundary",
  "native.dependency-audit",
  "desktop.wdio-build",
  "desktop.required-wdio",
  "server.python-3.12",
  "target-client.native-resource-and-restart",
  "target-client.prepared-audio-boundaries",
  "target-client.rendered-ui-and-microphone",
  "target-client.teardown",
  "gb10.provider-duration-and-concurrency",
  "gb10.provider-cancellation-and-recovery",
  "gb10.provider-resource-bounds",
  "gb10.provider-teardown",
  "integrated.desktop-private-server",
  "integrated.tunnel-interruption-recovery",
  "integrated.authoritative-history-result",
  "integrated.teardown",
];
const hostedClosureIds = [
  "hosted.ci.frontend",
  "hosted.ci.rust",
  "hosted.ci.native-wdio",
  "hosted.ci.server",
  "hosted.codeql.rust",
  "hosted.codeql.actions",
  "hosted.codeql.javascript-typescript",
  "hosted.codeql.python",
  "hosted.nsis.disposable-windows",
];
const identityHostedClosureIds = [
  "hosted.ci.frontend",
  "hosted.ci.rust",
  "hosted.ci.native-wdio",
  "hosted.ci.server",
  "hosted.ci.mock-oidc",
  "hosted.codeql.rust",
  "hosted.codeql.actions",
  "hosted.codeql.javascript-typescript",
  "hosted.codeql.python",
  "hosted.nsis.disposable-windows",
];
const exactCommands = {
  "frontend.node-runtime": ["node", "./tests/scripts/assert-node24.mjs"],
  "frontend.dependencies": ["corepack", "pnpm@11.7.0", "install", "--frozen-lockfile"],
  "frontend.dependency-audit": ["pnpm", "audit:dependencies"],
  "frontend.release-contracts": ["pnpm", "test:release-contract"],
  "frontend.provenance": [
    "node",
    "./tests/scripts/assert-third-party-provenance.mjs",
    "--require-reviewed",
    "--verify-upstream",
  ],
  "frontend.unit": ["pnpm", "test"],
  "frontend.production-build": ["pnpm", "build"],
  "frontend.chromium-runtime": ["pnpm", "exec", "playwright", "install", "chromium"],
  "frontend.browser-workflows": ["pnpm", "test:e2e"],
  "native.format": ["cargo", "fmt", "--all", "--check"],
  "native.clippy": ["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"],
  "native.tests": ["cargo", "test", "--locked"],
  "native.server-connector": [
    "pwsh.exe",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "./verification/test-server-connector.ps1",
  ],
  "native.windows-dependency-boundary": [
    "pwsh.exe",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "./verification/test-windows-rust-dependency-boundary.ps1",
  ],
  "native.dependency-audit": [
    "pwsh.exe",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "./verification/audit-windows-rust-dependencies.ps1",
  ],
  "desktop.wdio-build": ["pnpm", "test:desktop:build"],
  "desktop.required-wdio": ["pnpm", "exec", "wdio", "run", "./tests/wdio.required.conf.ts"],
  "server.python-3.12": [
    "pwsh.exe",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "./verification/test-portable-python-server.ps1",
  ],
  "server.lint": ["uv", "run", "--locked", "ruff", "check", "."],
};
const identityExactCommands = {
  ...Object.fromEntries(
    Object.entries(exactCommands).filter(([id]) => (
      !id.startsWith("native.") && !id.startsWith("desktop.")
    )),
  ),
  "windows.build-tools-optional-diagnostics-disabled": [
    "node",
    "verification/verify-windows-build-tools-optional-diagnostics-opt-out.mjs",
  ],
  "frontend.dependencies": [
    "corepack",
    "pnpm@11.7.0",
    "install",
    "--frozen-lockfile",
    "--force",
    "--no-optimistic-repeat-install",
    "--package-import-method=copy",
  ],
  "server.lint": [
    "uv",
    "run",
    "--locked",
    "ruff",
    "check",
    ".",
    "../infra/yap-server-node/owned-process-supervisor.py",
  ],
};

function createReceipt(
  scope,
  {
    gateManifest = manifest,
    gateManifestSha256 = manifestSha256,
    admissionSha256 = null,
  } = {},
) {
  const cells = scope === "candidate"
    ? gateManifest.candidateCells
    : gateManifest.hostedClosureCells;
  const bindsAdmission = gateManifest.gateId === "integrated-identity-access";
  return {
    schemaVersion: bindsAdmission ? 3 : 2,
    gateId: gateManifest.gateId,
    scope,
    checkedHead,
    candidateHead: checkedHead,
    candidateReceiptSha256: scope === "candidate" ? null : "e".repeat(64),
    manifestSha256: gateManifestSha256,
    ...(bindsAdmission ? { admissionSha256 } : {}),
    status: "passed",
    startedAt,
    finishedAt,
    children: cells.map((cell) => ({
      id: cell.id,
      executor: cell.executor,
      checkedHead,
      definitionSha256: integratedGateCellDefinitionSha256(cell),
      evidenceSha256: "b".repeat(64),
      attempt: 1,
      status: "passed",
      startedAt,
      finishedAt,
    })),
  };
}

test("integrated gate freezes the complete candidate and hosted child inventories", () => {
  assert.equal(manifest.gateId, "integrated-product-checkpoint");
  assert.deepEqual(manifest.candidateCells.map(({ id }) => id), candidateIds);
  assert.deepEqual(manifest.hostedClosureCells.map(({ id }) => id), hostedClosureIds);
  const commandCells = Object.fromEntries(
    manifest.candidateCells
      .filter(({ executor }) => executor === "command")
      .map(({ id, command }) => [id, command]),
  );
  assert.deepEqual(commandCells, exactCommands);
});

test("identity and access gate freezes its complete behavior inventory", () => {
  assert.equal(identityManifest.gateId, "integrated-identity-access");
  assert.deepEqual(
    identityManifest.candidateCells.map(({ id }) => id),
    identityCandidateIds,
  );
  assert.deepEqual(
    identityManifest.hostedClosureCells.map(({ id }) => id),
    identityHostedClosureIds,
  );
  const commandCells = Object.fromEntries(
    identityManifest.candidateCells
      .filter(({ executor }) => executor === "command")
      .map(({ id, command }) => [id, command]),
  );
  assert.deepEqual(commandCells, identityExactCommands);
});

test("identity and access gate keeps native toolchain work on disposable hosted Windows", () => {
  const candidateIds = new Set(
    identityManifest.candidateCells.map(({ id }) => id),
  );
  for (const nativeId of [
    "native.format",
    "native.clippy",
    "native.tests",
    "native.server-connector",
    "native.authenticated-server-connector",
    "native.windows-dependency-boundary",
    "native.dependency-audit",
    "desktop.wdio-build",
    "desktop.required-wdio",
  ]) {
    assert.equal(
      candidateIds.has(nativeId),
      false,
      `${nativeId} must execute only through the hosted Windows closure`,
    );
  }
  assert.ok(
    candidateIds.has("windows.build-tools-optional-diagnostics-disabled"),
    "the local Windows optional-diagnostics prerequisite must remain in the candidate gate",
  );
  assert.ok(
    identityHostedClosureIds.includes("hosted.ci.rust"),
    "the hosted closure must retain exact Rust and connector evidence",
  );
  assert.ok(
    identityHostedClosureIds.includes("hosted.ci.native-wdio"),
    "the hosted closure must retain exact native UI evidence",
  );
});

test("identity admission delegates to the bounded optional-diagnostics verifier", () => {
  const calls = [];
  const environment = {
    SystemRoot: String.raw`C:\Windows`,
    PATH: process.env.PATH,
    GH_TOKEN: "removed by the verifier's process boundary",
  };
  verifyIdentityAccessAdmissionPrerequisites({
    checkedHead,
    platform: "win32",
    environment,
    verifyOptionalDiagnostics(options) {
      calls.push(options);
      return { applicable: true, optIn: 0, source: "installation" };
    },
  });
  assert.deepEqual(calls, [{ platform: "win32", environment }]);
});

test("identity admission rejects unsupported runners and invalid prerequisite results", () => {
  assert.throws(
    () => verifyIdentityAccessAdmissionPrerequisites({
      checkedHead,
      platform: "linux",
    }),
    /must be admitted from its exact Windows runner/,
  );
  assert.throws(
    () => verifyIdentityAccessAdmissionPrerequisites({
      checkedHead,
      platform: "win32",
      verifyOptionalDiagnostics() {
        throw new Error("registry unavailable");
      },
    }),
    /failed before admission; no attempt was reserved: registry unavailable/,
  );
  assert.throws(
    () => verifyIdentityAccessAdmissionPrerequisites({
      checkedHead,
      platform: "win32",
      verifyOptionalDiagnostics: () => ({ applicable: false }),
    }),
    /returned an invalid result; no attempt was reserved/,
  );
});

test("identity and access gate binds mock OIDC candidate and hosted closure", () => {
  assert.deepEqual(
    identityManifest.candidateCells.find(
      ({ id }) => id === "server.mock-oidc-owner-flow",
    ),
    {
      id: "server.mock-oidc-owner-flow",
      executor: "private-receipt",
      receiptContract: "mock-oidc-owner-flow-v1",
    },
  );
  assert.deepEqual(
    identityManifest.hostedClosureCells.find(
      ({ id }) => id === "hosted.ci.mock-oidc",
    ),
    {
      id: "hosted.ci.mock-oidc",
      executor: "github-check",
      workflow: "CI",
      job: "mock-oidc",
    },
  );
});

test("mock OIDC hosted closure executes Linux lifecycle tests without skips", () => {
  const workflow = readFileSync(
    path.join(repoRoot, ".github", "workflows", "ci.yml"),
    "utf8",
  );
  assert.match(
    workflow,
    /name: Run required Linux owned-process lifecycle tests without skips/,
  );
  assert.match(workflow, /YAP_REQUIRE_LINUX_LIFECYCLE_TESTS: "1"/);
  for (const moduleName of [
    "tests.infra.test_owned_process_group_behavior",
    "tests.infra.test_owned_process_supervisor",
    "tests.infra.test_resident_provider_lifecycle_gate",
    "tests.infra.test_private_container_loopback_proxy",
    "tests.infra.test_private_container_loopback_proxy_behavior",
  ]) {
    assert.match(workflow, new RegExp(moduleName.replaceAll(".", String.raw`\.`)));
  }
});

test("identity and access receipts bind the canonical admission", () => {
  const admissionSha256 = "9".repeat(64);
  const identityManifestSha256 =
    integratedGateManifestSha256(identityManifestBytes);
  const receipt = createReceipt("candidate", {
    gateManifest: identityManifest,
    gateManifestSha256: identityManifestSha256,
    admissionSha256,
  });
  assert.doesNotThrow(() => validateIntegratedGateReceipt({
    receipt,
    manifest: identityManifest,
    manifestSha256: identityManifestSha256,
    expectedHead: checkedHead,
    expectedAdmissionSha256: admissionSha256,
    expectedScope: "candidate",
  }));
  assert.throws(() => validateIntegratedGateReceipt({
    receipt,
    manifest: identityManifest,
    manifestSha256: identityManifestSha256,
    expectedHead: checkedHead,
    expectedAdmissionSha256: "8".repeat(64),
    expectedScope: "candidate",
  }), /admission identity does not match/);

  const hosted = buildHostedClosureReceipt({
    manifest: identityManifest,
    manifestSha256: identityManifestSha256,
    checkedHead,
    candidateHead: checkedHead,
    candidateReceiptSha256: "e".repeat(64),
    admissionSha256,
    selected: identityManifest.hostedClosureCells.map((cell, index) => ({
      cell,
      run: {
        databaseId: 20_000 + index,
        headSha: checkedHead,
        workflowName: cell.workflow,
        attempt: 1,
        status: "completed",
        conclusion: "success",
        createdAt: startedAt,
        updatedAt: finishedAt,
        url: `https://example.invalid/run/${index}`,
      },
      job: {
        databaseId: 30_000 + index,
        name: cell.job,
        status: "completed",
        conclusion: "success",
        startedAt,
        completedAt: finishedAt,
        url: `https://example.invalid/job/${index}`,
      },
    })),
  });
  assert.doesNotThrow(() => validateIntegratedGateReceipt({
    receipt: hosted,
    manifest: identityManifest,
    manifestSha256: identityManifestSha256,
    expectedHead: checkedHead,
    expectedCandidateHead: checkedHead,
    expectedCandidateReceiptSha256: "e".repeat(64),
    expectedAdmissionSha256: admissionSha256,
    expectedScope: "hosted-closure",
  }));
});

test("historical Phase 6 gate identity and bytes remain frozen", () => {
  assert.equal(phase6Manifest.gateId, "integrated-preprocessing-language-routing");
  assert.deepEqual(
    phase6Manifest.candidateCells.map(({ id }) => id),
    phase6CandidateIds,
  );
  assert.equal(
    integratedGateManifestSha256(phase6ManifestBytes),
    "46832f4605a92262917c0afbdeef9608270f9c56cd25a553ab6c6a5e5f7fdb52",
  );
});

test("runner manifest selection preserves each canonical gate identity and child set", () => {
  const identitySelection = loadIntegratedGateManifestSelection(identityManifestPath);
  const productSelection = loadIntegratedGateManifestSelection(manifestPath);
  const phase6Selection = loadIntegratedGateManifestSelection(phase6ManifestPath);

  assert.equal(identitySelection.manifest.gateId, "integrated-identity-access");
  assert.deepEqual(
    identitySelection.manifest.candidateCells.map(({ id }) => id),
    identityCandidateIds,
  );
  assert.equal(
    identitySelection.manifestSha256,
    integratedGateManifestSha256(identityManifestBytes),
  );
  assert.equal(productSelection.manifest.gateId, "integrated-product-checkpoint");
  assert.deepEqual(
    productSelection.manifest.candidateCells.map(({ id }) => id),
    candidateIds,
  );
  assert.equal(productSelection.manifestSha256, manifestSha256);
  assert.equal(
    phase6Selection.manifest.gateId,
    "integrated-preprocessing-language-routing",
  );
  assert.deepEqual(
    phase6Selection.manifest.candidateCells.map(({ id }) => id),
    phase6CandidateIds,
  );
  assert.equal(
    phase6Selection.manifestSha256,
    "46832f4605a92262917c0afbdeef9608270f9c56cd25a553ab6c6a5e5f7fdb52",
  );
});

test("active command cells freeze finite wall-clock deadlines without rewriting history", () => {
  assert.equal(identityManifest.schemaVersion, 2);
  const commandCells = identityManifest.candidateCells.filter(
    ({ executor }) => executor === "command",
  );
  assert.ok(commandCells.length > 0);
  assert.ok(commandCells.every(({ timeoutMs }) => (
    Number.isSafeInteger(timeoutMs)
      && timeoutMs >= 1_000
      && timeoutMs <= 7_200_000
  )));
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(phase6Manifest.schemaVersion, 1);

  for (const timeoutMs of [undefined, 0, 999, 1.5, 7_200_001]) {
    const mutated = structuredClone(identityManifest);
    if (timeoutMs === undefined) delete mutated.candidateCells[0].timeoutMs;
    else mutated.candidateCells[0].timeoutMs = timeoutMs;
    assert.throws(
      () => validateIntegratedGateManifest(mutated),
      /wall-clock timeout|unsupported fields/,
    );
  }

  const changed = structuredClone(identityManifest.candidateCells[0]);
  changed.timeoutMs += 1;
  assert.notEqual(
    integratedGateCellDefinitionSha256(identityManifest.candidateCells[0]),
    integratedGateCellDefinitionSha256(changed),
  );
});

test("runner requires an explicit canonical manifest and rejects cross-gate completion", async () => {
  const beginArguments = [
    "begin",
    "--checked-head",
    checkedHead,
    "--evidence-root",
    "private-root",
    "--manifest",
    manifestPath,
    "--private-plan",
    "private-plan.json",
  ];
  const completeArguments = [
    "complete",
    "--admission",
    "admission.json",
    "--manifest",
    manifestPath,
  ];
  assert.equal(
    parseIntegratedGateRunnerInvocation(beginArguments).manifestPath,
    manifestPath,
  );
  assert.equal(
    parseIntegratedGateRunnerInvocation(completeArguments).manifestPath,
    manifestPath,
  );
  assert.throws(
    () => parseIntegratedGateRunnerInvocation(
      beginArguments.filter((value, index) => ![5, 6].includes(index)),
    ),
    /begin requires exactly .*--manifest/,
  );
  assert.throws(
    () => parseIntegratedGateRunnerInvocation(
      completeArguments.filter((value, index) => ![3, 4].includes(index)),
    ),
    /complete requires exactly .*--manifest/,
  );
  assert.throws(
    () => parseIntegratedGateRunnerInvocation([
      ...completeArguments,
      "--attempt-token",
      "f".repeat(64),
    ]),
    /complete requires exactly/,
  );

  const productSelection = loadIntegratedGateManifestSelection(manifestPath);
  const phase6Selection = loadIntegratedGateManifestSelection(phase6ManifestPath);
  const phase6Admission = {
    gateId: phase6Selection.manifest.gateId,
    manifestPath: phase6Selection.manifestFile.path,
    manifestSha256: phase6Selection.manifestSha256,
  };
  assert.doesNotThrow(
    () => assertIntegratedGateManifestMatchesAdmission(
      phase6Admission,
      phase6Selection,
    ),
  );
  assert.throws(
    () => assertIntegratedGateManifestMatchesAdmission(
      phase6Admission,
      productSelection,
    ),
    /does not match the admitted manifest/,
  );
  assert.throws(
    () => assertIntegratedGateManifestMatchesAdmission(
      {
        ...phase6Admission,
        gateId: productSelection.manifest.gateId,
      },
      phase6Selection,
    ),
    /identity does not match the admitted gate/,
  );
  assert.throws(
    () => assertIntegratedGateManifestMatchesAdmission(
      {
        ...phase6Admission,
        manifestSha256: "0".repeat(64),
      },
      phase6Selection,
    ),
    /bytes do not match the admitted manifest/,
  );

  const root = createCanonicalTemporaryDirectory("yap-invalid-gate-manifest-");
  try {
    const copiedManifest = path.join(root, "copied-gate.json");
    writeFileSync(copiedManifest, manifestBytes);
    assert.throws(
      () => loadIntegratedGateManifestSelection(copiedManifest),
      /accepts only a repository-owned integrated gate manifest/,
    );
    const admissionPath = path.join(root, "admission.json");
    protectAndVerifyPrivateDirectory(root);
    writeExclusivePrivateFile(
      admissionPath,
      Buffer.from(`${JSON.stringify({
        schemaVersion: 2,
        gateId: phase6Admission.gateId,
        checkedHead,
        manifestPath: phase6Admission.manifestPath,
        manifestSha256: phase6Admission.manifestSha256,
        privatePlanPath: path.join(root, "private-plan.json"),
        privatePlanSha256: "1".repeat(64),
        attempt: 1,
        attemptCapabilitySha256: "f".repeat(64),
        admittedAt: startedAt,
        runDirectory: root,
        commandLogDirectory: path.join(root, "command-logs"),
        candidateReceiptPath: path.join(root, "candidate-receipt.json"),
      }, null, 2)}\n`),
    );
    await assert.rejects(
      completeIntegratedGateAttempt({
        admissionPath,
        manifestPath,
      }),
      /does not match the admitted manifest/,
    );
    assert.equal(existsSync(path.join(root, "running.json")), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("integrated gate runbooks select their exact manifest for begin and complete", () => {
  const contracts = [
    {
      runbook: "integrated-identity-access-gate.md",
      manifestArgument:
        ".\\verification\\integrated-identity-access-gate.json",
    },
    {
      runbook: "integrated-product-checkpoint-gate.md",
      manifestArgument:
        ".\\verification\\integrated-product-checkpoint-gate.json",
    },
    {
      runbook: "integrated-preprocessing-language-routing-gate.md",
      manifestArgument:
        ".\\verification\\integrated-preprocessing-language-routing-gate.json",
    },
  ];
  for (const contract of contracts) {
    const runbook = readFileSync(
      path.join(repoRoot, "docs", "runbooks", contract.runbook),
      "utf8",
    );
    assert.doesNotMatch(runbook, /--attempt-token|<admitted-token>/);
    const runnerCommands = runbook
      .split("```powershell")
      .slice(1)
      .map((block) => block.split("```")[0])
      .filter((block) => block.includes("integrated-gate-runner.mjs"));
    assert.equal(runnerCommands.length, 2);
    for (const operation of ["begin", "complete"]) {
      const command = runnerCommands.find(
        (block) => block.includes(`integrated-gate-runner.mjs ${operation}`),
      );
      assert.ok(command, `${contract.runbook} must document ${operation}`);
      assert.ok(
        command.includes(`--manifest ${contract.manifestArgument}`),
        `${contract.runbook} ${operation} must select ${contract.manifestArgument}`,
      );
    }
  }
});

test("integrated runbooks protect admission inputs and bind the remote helper set", () => {
  const identityRunbook = readFileSync(
    path.join(repoRoot, "docs", "runbooks", "integrated-identity-access-gate.md"),
    "utf8",
  );
  const preprocessingRunbook = readFileSync(
    path.join(
      repoRoot,
      "docs",
      "runbooks",
      "integrated-preprocessing-language-routing-gate.md",
    ),
    "utf8",
  );
  const productRunbook = readFileSync(
    path.join(repoRoot, "docs", "runbooks", "integrated-product-checkpoint-gate.md"),
    "utf8",
  );
  for (const [label, runbook] of [
    ["identity", identityRunbook],
    ["preprocessing", preprocessingRunbook],
    ["product checkpoint", productRunbook],
  ]) {
    assert.match(
      runbook,
      /private-gate-artifacts\.ps1/,
      `${label} runbook must name the private-artifact protection helper`,
    );
  }
  for (const operation of [
    "protect-directory",
    "verify-directory",
    "protect-file",
    "verify-file",
  ]) {
    assert.match(identityRunbook, new RegExp(`-Operation ${operation}`));
    assert.match(preprocessingRunbook, new RegExp(`-Operation ${operation}`));
  }
  assert.match(identityRunbook, /"remoteHelperSetSha256"/);
  assert.match(identityRunbook, /REMOTE_HELPER_SET_SHA256=<sha256>/);
  assert.match(identityRunbook, /--remote-helper-set-sha256/);
});

test("checked private-server runbook pins system OpenSSH and protects its inputs", () => {
  const runbook = readFileSync(
    path.join(repoRoot, "docs", "runbooks", "yap-server-node-setup.md"),
    "utf8",
  );
  assert.doesNotMatch(runbook, /Get-Command ssh\.exe/);
  assert.match(runbook, /System32\\OpenSSH\\ssh\.exe/);
  assert.match(runbook, /private-gate-artifacts\.ps1/);
  assert.match(runbook, /-Operation protect-directory/);
  assert.match(runbook, /-Operation protect-ssh-file/);
  assert.match(runbook, /-Operation verify-ssh-file/);
});

test("private-artifact verification pins the system PowerShell host", () => {
  const source = readFileSync(
    path.join(repoRoot, "verification", "private-gate-artifacts.mjs"),
    "utf8",
  );
  assert.match(source, /"System32",\s*"WindowsPowerShell",\s*"v1\.0",\s*"powershell\.exe"/);
  assert.doesNotMatch(source, /where\.exe|pwsh\.exe/);
});

test("integrated gate accepts exact one-attempt receipts for both scopes", () => {
  for (const scope of ["candidate", "hosted-closure"]) {
    const result = validateIntegratedGateReceipt({
      receipt: createReceipt(scope),
      manifest,
      manifestSha256,
      expectedHead: checkedHead,
      expectedCandidateReceiptSha256: scope === "candidate" ? null : "e".repeat(64),
      expectedScope: scope,
    });
    assert.equal(result.checkedHead, checkedHead);
    assert.equal(result.scope, scope);
  }
});

test("integrated gate rejects omissions, extras, stale definitions, retries, and failures", () => {
  const mutations = [
    (receipt) => receipt.children.pop(),
    (receipt) => receipt.children.push({ ...receipt.children.at(-1), id: "unexpected.child" }),
    (receipt) => { receipt.children[0].definitionSha256 = "c".repeat(64); },
    (receipt) => { receipt.children[0].attempt = 2; },
    (receipt) => { receipt.children[0].status = "failed"; },
    (receipt) => { receipt.children[0].checkedHead = "d".repeat(40); },
    (receipt) => { receipt.candidateHead = "d".repeat(40); },
    (receipt) => { receipt.candidateReceiptSha256 = "f".repeat(64); },
  ];
  for (const mutate of mutations) {
    const receipt = structuredClone(createReceipt("candidate"));
    mutate(receipt);
    assert.throws(() => validateIntegratedGateReceipt({
      receipt,
      manifest,
      manifestSha256,
      expectedHead: checkedHead,
      expectedCandidateReceiptSha256: null,
      expectedScope: "candidate",
    }));
  }
});

test("checked-head WDIO builds require a clean tree before and after compilation", () => {
  const source = readFileSync(
    path.join(repoRoot, "desktop", "tests", "scripts", "tauri-wdio-build.mjs"),
    "utf8",
  );
  assert.match(source, /assertCleanCheckedHead\(checkedHead, "before"\)/);
  assert.match(source, /assertCleanCheckedHead\(checkedHead, "after"\)/);
  assert.match(source, /"status", "--porcelain=v1", "--untracked-files=normal"/);
  assert.ok(
    source.lastIndexOf("await rm(generated, { force: true });")
      < source.indexOf('assertCleanCheckedHead(checkedHead, "after")'),
    "generated WDIO capability must be removed before the post-build clean-tree check",
  );
});

test("connected gate records a real five-window AmberNet preflight", () => {
  const source = readFileSync(
    path.join(repoRoot, "desktop", "tests", "wdio", "private-server-asr.gate.spec.js"),
    "utf8",
  );
  assert.match(
    source,
    /expect\(await invoke\("wdio_build_git_sha"\)\)\.toBe\(checkedHead\)/,
  );
  assert.match(source, /runLanguagePreflightExecution\(/);
  assert.match(source, /fetch\(`http:\/\/\$\{tunnelHost\}:\$\{tunnelPort\}\/v1\/lid\/preflight`/);
  assert.match(source, /expect\(result\.observations\)\.toHaveLength/);
  assert.match(source, /languagePreflightExecution,/);
  assert.match(source, /schemaVersion: 3,/);
});

test("target-client runbook carries prepared-audio identity into the UI gate", () => {
  const runbook = readFileSync(
    path.join(repoRoot, "docs", "runbooks", "target-client-language-routing-qualification.md"),
    "utf8",
  );
  assert.match(runbook, /YAP_TARGET_CLIENT_PREPARED_AUDIO_EVIDENCE_FILE/);
  assert.match(runbook, /YAP_TARGET_CLIENT_PREPARED_AUDIO_SUITE_SHA256/);
});

test("portable Python gate rejects project and uv.lock drift", () => {
  const source = readFileSync(
    path.join(repoRoot, "verification", "exact-python-runtime.psm1"),
    "utf8",
  );
  assert.match(source, /'--offline'\s*'--locked'\s*'--exact'/);
  assert.doesNotMatch(source, /'--frozen'/);
});

test("identity gate prequalifies the non-login connected uv executor", () => {
  const runbook = readFileSync(
    path.join(repoRoot, "docs", "runbooks", "integrated-identity-access-gate.md"),
    "utf8",
  );
  assert.match(runbook, /non-login SSH shape/);
  assert.match(
    runbook,
    /absolute `YAP_UV_EXECUTABLE` plus\s+its byte length, SHA-256/,
  );
  assert.match(runbook, /checked-uv-executor\.py` as `YAP_UV_BINARY`/);
  assert.match(runbook, /seals that exact\s+in-memory image\s+against mutation/);

  const helperRelativePath = "infra/yap-server-node/checked-uv-executor.py";
  const helperPath = path.join(repoRoot, helperRelativePath);
  const helper = readFileSync(
    helperPath,
    "utf8",
  );
  assert.match(helper, /YAP_UV_EXECUTABLE_SHA256/);
  assert.match(helper, /YAP_UV_EXECUTABLE_SIZE_BYTES/);
  assert.match(helper, /MAX_EXECUTABLE_BYTES/);
  assert.match(helper, /source_stat\.st_size != expected_size_bytes/);
  assert.match(helper, /remaining = expected_size_bytes/);
  assert.match(helper, /os\.O_NOFOLLOW/);
  assert.match(helper, /os\.memfd_create/);
  assert.match(helper, /fcntl\.F_ADD_SEALS/);
  assert.match(helper, /os\.execve\(memfd/);
  const indexEntry = execFileSync(
    "git",
    ["-C", repoRoot, "ls-files", "--stage", "--", helperRelativePath],
    { encoding: "utf8" },
  ).trim();
  assert.match(indexEntry, /^100755 [0-9a-f]{40} 0\t/);
});

test("identity gate prequalifies its fixed GB10 control parent", () => {
  const runbook = readFileSync(
    path.join(repoRoot, "docs", "runbooks", "integrated-identity-access-gate.md"),
    "utf8",
  );
  const fixedControllerPolicy = runbook.match(
    /The next\s+admitted GB10 receipt controller[\s\S]*?sticky-directory exception\./,
  )?.[0];
  assert.ok(fixedControllerPolicy);
  assert.match(
    fixedControllerPolicy,
    /validate that every real directory\s+component/,
  );
  assert.match(
    fixedControllerPolicy,
    /fixed `\/srv\/yap-server\/private\/\.\.\.` chain/,
  );
  assert.match(
    fixedControllerPolicy,
    /owned by root or\s+the admitted remote account \(`admin`\)/,
  );
  assert.match(fixedControllerPolicy, /is not redirected/);
  assert.match(fixedControllerPolicy, /has no\s+group\/world write access/);
  assert.match(
    fixedControllerPolicy,
    /mode `0700` on the\s+receipt parent and per-head child and mode `0600` on the receipt/,
  );
  const genericHarnessPolicy = runbook.match(
    /For this reusable cross-platform\s+harness,[\s\S]*?creates any file:/,
  )?.[0];
  assert.ok(genericHarnessPolicy);
  assert.match(
    genericHarnessPolicy,
    /distinct from the stricter fixed GB10 receipt-controller path/,
  );
  assert.match(
    genericHarnessPolicy,
    /shared-writable\s+ancestor is accepted only when its sticky-bit and ownership protect the child/,
  );
  assert.match(runbook, /fixed GB10 controller parent/);
  assert.match(runbook, /non-redirected directory[\s\S]*mode `0700`/);
  assert.match(runbook, /planned per-head child must remain absent/);
  assert.match(runbook, /no-owner GB10 preflight/);
  assert.match(runbook, /repeat the ancestor and fixed-parent\s+validation immediately before/);
  assert.match(runbook, /non-recursive direct-child creation/);
  assert.match(runbook, /complete checked-head transient-unit\s+family/);
  assert.match(runbook, /bounded-command log must use no-overwrite creation/);
  assert.match(runbook, /protected\s+private-file policy on success and failure/);
});

test("identity gate prequalifies uv in the admitted mock-OIDC environment", () => {
  const runbook = readFileSync(
    path.join(repoRoot, "docs", "runbooks", "integrated-identity-access-gate.md"),
    "utf8",
  );
  const consumedAdmission = runbook.match(
    /Exact head `dece4265e052d775d2d11f1883cd8cc4b2b25191`[\s\S]*?Do not retry, complete, or relabel\s+this head\./,
  )?.[0];
  assert.ok(consumedAdmission);
  assert.match(
    consumedAdmission,
    /failed before the locked `uv sync` command or owner flow because\s+non-interactive SSH did not put the reviewed absolute `uv` executable's parent\s+on `PATH`\./,
  );
  assert.match(
    consumedAdmission,
    /The executable remained available at its authenticated private path,\s+but portable PowerShell could not resolve the bare command name\./,
  );
  assert.match(
    consumedAdmission,
    /Readback\s+proved that the mode-`0700` per-head receipt directory existed, the receipt\s+remained absent, and no owner flow started\./,
  );
  assert.doesNotMatch(consumedAdmission, /\/home\//);

  const executorPolicy = runbook.match(
    /For the fixed GB10 mock-OIDC controller,[\s\S]*?A resolution\s+mismatch is a pre-admission failure\./,
  )?.[0];
  assert.ok(executorPolicy);
  assert.match(
    executorPolicy,
    /For the fixed GB10 mock-OIDC controller, do not rely on a login shell to extend\s+`PATH`\./,
  );
  assert.match(
    executorPolicy,
    /Before reservation and again immediately before admitted use,\s+authenticate every real directory component from the filesystem anchor through\s+the selected absolute `uv` parent as canonical, non-redirected, owned by root\s+or `admin`, and not group\/world writable\./,
  );
  assert.match(
    executorPolicy,
    /Then authenticate the `uv` path as one\s+canonical, regular, single-link, `admin`-owned executable with no group\/world\s+write bit and with the reviewed SHA-256, size, and version\./,
  );
  assert.match(
    executorPolicy,
    /In the same\s+non-interactive SSH command environment used by the admitted controller, make\s+that exact executable resolvable inside the pinned portable PowerShell process\s+and prove that `Get-Command uv` returns the authenticated absolute path\./,
  );
  assert.match(
    executorPolicy,
    /The\s+no-owner preflight must exercise this exact controller invocation, not a login\s+shell or an environment assembled by a different diagnostic\./,
  );
});

test("gate admission pins GitHub.com and the canonical repository", () => {
  const previousHost = process.env.GH_HOST;
  try {
    process.env.GH_HOST = "example.invalid";
    assert.deepEqual(
      githubApiArguments(["repos/mcnatg1/yap"]),
      [
        "api",
        "--hostname",
        "github.com",
        "-H",
        "Accept: application/vnd.github+json",
        "repos/mcnatg1/yap",
      ],
    );
    assert.equal(GITHUB_ADMISSION_AUTHORITY_HOST, "github.com");
    assert.equal(GITHUB_ADMISSION_REPOSITORY, "mcnatg1/yap");
    assert.equal(GITHUB_ADMISSION_REPOSITORY_ID, 1278708785);
    const source = readFileSync(
      path.join(repoRoot, "verification", "github-gate-admission.mjs"),
      "utf8",
    );
    assert.match(source, /GH_PROMPT_DISABLED:\s*"1"/);
    assert.match(source, /dedicated nonempty GH_TOKEN/);
    assert.doesNotMatch(source, /remote", "get-url"/);
    const hostedSource = readFileSync(
      path.join(repoRoot, "verification", "integrated-hosted-closure.mjs"),
      "utf8",
    );
    assert.match(hostedSource, /GITHUB_ADMISSION_AUTHORITY_HOST/);
    assert.match(hostedSource, /GITHUB_ADMISSION_REPOSITORY/);
    assert.match(hostedSource, /"--repo"/);
    assert.match(hostedSource, /GH_PROMPT_DISABLED:\s*"1"/);
  } finally {
    if (previousHost === undefined) delete process.env.GH_HOST;
    else process.env.GH_HOST = previousHost;
  }
});

test("integrated gate command cells never inherit GitHub credentials", () => {
  assert.deepEqual(
    integratedGateCommandEnvironment(checkedHead, {
      PATH: "safe-path",
      GH_TOKEN: "secret",
      github_token: "secret",
      GH_ENTERPRISE_TOKEN: "secret",
      GITHUB_ENTERPRISE_TOKEN: "secret",
    }),
    {
      PATH: "safe-path",
      YAP_CHECKED_HEAD: checkedHead,
    },
  );
});

test("historical gates retain their local deterministic reservation boundary", () => {
  const root = createCanonicalTemporaryDirectory("yap-legacy-gate-attempt-");
  const authority =
    createCanonicalTemporaryDirectory("yap-legacy-gate-authority-");
  try {
    for (const [gateId, gateManifestSha256] of [
      [manifest.gateId, manifestSha256],
      [
        phase6Manifest.gateId,
        integratedGateManifestSha256(phase6ManifestBytes),
      ],
    ]) {
      const input = {
        evidenceRoot: root,
        gateId,
        checkedHead,
        manifestSha256: gateManifestSha256,
        reservationAuthorityRoot: authority,
      };
      const first = reserveIntegratedGateAttemptDirectory(input);
      assert.ok(first.runDirectory.startsWith(root));
      assert.equal(first.statusAuthority, undefined);
      assert.throws(() => reserveIntegratedGateAttemptDirectory(input));
    }
  } finally {
    rmSync(root, { recursive: true, force: true });
    rmSync(authority, { recursive: true, force: true });
  }
});

test("historical gate reservations retain their exact frozen schema", () => {
  const reservation = {
    schemaVersion: 1,
    gateId: manifest.gateId,
    checkedHead,
    manifestSha256,
    evidenceRoot: "C:\\private-evidence",
    reservedAt: startedAt,
  };
  assert.doesNotThrow(
    () => validateLegacyIntegratedGateReservationValue(reservation),
  );
  assert.throws(
    () => validateLegacyIntegratedGateReservationValue({
      ...reservation,
      unexpected: true,
    }),
    /fields differ from the frozen contract/,
  );
});

test("integrated gate reservation authority rejects same-root and cross-root retries", () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-attempt-");
  const otherRoot = createCanonicalTemporaryDirectory("yap-gate-attempt-other-");
  const statusClient = createGateStatusClient();
  const previousUserProfile = process.env.USERPROFILE;
  try {
    const input = {
      evidenceRoot: root,
      gateId: identityManifest.gateId,
      checkedHead,
      manifestSha256: integratedGateManifestSha256(identityManifestBytes),
      statusClient,
    };
    const first = reserveIntegratedGateAttemptDirectory(input);
    assert.ok(first.runDirectory.startsWith(root));
    assert.throws(() => reserveIntegratedGateAttemptDirectory(input));
    rmSync(first.runDirectory, { recursive: true, force: true });
    process.env.USERPROFILE = otherRoot;
    assert.throws(() => reserveIntegratedGateAttemptDirectory({
      ...input,
      evidenceRoot: otherRoot,
    }));
  } finally {
    if (previousUserProfile === undefined) delete process.env.USERPROFILE;
    else process.env.USERPROFILE = previousUserProfile;
    rmSync(root, { recursive: true, force: true });
    rmSync(otherRoot, { recursive: true, force: true });
  }
});

test("integrated gate admits only the oldest remote status in a reservation race", () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-attempt-race-");
  try {
    assert.throws(
      () => reserveIntegratedGateAttemptDirectory({
        evidenceRoot: root,
        gateId: identityManifest.gateId,
        checkedHead,
        manifestSha256: integratedGateManifestSha256(identityManifestBytes),
        statusClient: createGateStatusClient({ competingStatusWins: true }),
      }),
      /different GitHub gate admission won/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("identity admission returns no capability and stores only its protected digest", () => {
  const root = createCanonicalTemporaryDirectory("yap-identity-admission-");
  const repositoryHead = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repoRoot,
    encoding: "utf8",
  }).trim();
  const privatePlanPath = path.join(root, "private-plan.json");
  const runtimePreparation = Object.fromEntries(
    ["cohere-vllm", "nemotron-nemo", "language-detection"].map((runtime, index) => {
      const receiptFile = path.join(root, `${runtime}-preparation.json`);
      const receiptBytes = Buffer.from(`${JSON.stringify({
        schemaVersion: 1,
        checkedHead: repositoryHead,
        runtime,
        dockerfileSha256: "d".repeat(64),
        image: `yap-${runtime}:checked-head-${repositoryHead}`,
        imageId: `sha256:${String(index + 1).repeat(64)}`,
        architecture: "arm64",
        baseDigest: `sha256:${"e".repeat(64)}`,
      })}\n`);
      writeExclusivePrivateFile(receiptFile, receiptBytes);
      return [runtime, {
        receiptFile,
        receiptSha256: sha256(receiptBytes),
      }];
    }),
  );
  const privatePlanBytes = Buffer.from(`${JSON.stringify({
    schemaVersion: 2,
    checkedHead: repositoryHead,
    mockOidc: {
      receiptFile: path.join(root, "mock-oidc-owner-flow.json"),
    },
    targetClient: {
      evidenceDirectory: path.join(root, "target-client"),
      preparedAudioEvidenceFile: path.join(
        root,
        "target-client",
        "local-stream-short-boundaries.json",
      ),
      preparedAudioSuiteSha256: "1".repeat(64),
    },
    gb10: {
      lifecycleEvidenceFile: path.join(root, "resident-provider-lifecycle.json"),
      runtimePreparation,
    },
    integrated: {
      evidenceDirectory: path.join(root, "connected-server"),
      remoteCleanupLogFile: path.join(root, "remote-cleanup.log"),
      teardownEvidenceFile: path.join(root, "connected-server", "teardown.json"),
      remoteHelperSetSha256: "2".repeat(64),
    },
  })}\n`);
  writeExclusivePrivateFile(privatePlanPath, privatePlanBytes);
  const statusClient = createGateStatusClient();
  const rejectedStatusClient = createGateStatusClient();

  try {
    assert.throws(
      () => admitIntegratedGateAttempt({
        checkedHead: repositoryHead,
        evidenceRoot: root,
        manifestPath: identityManifestPath,
        privatePlanPath,
        statusClient: rejectedStatusClient,
        verifyAdmissionPrerequisites() {
          throw new Error("Windows optional-diagnostics prerequisite rejected");
        },
      }),
      /Windows optional-diagnostics prerequisite rejected/,
    );
    assert.equal(
      rejectedStatusClient.statuses.length,
      0,
      "a failed prerequisite must not reserve remote admission status",
    );
    const prerequisiteHeads = [];
    const admitted = admitIntegratedGateAttempt({
      checkedHead: repositoryHead,
      evidenceRoot: root,
      manifestPath: identityManifestPath,
      privatePlanPath,
      statusClient,
      verifyAdmissionPrerequisites({ checkedHead: prerequisiteHead }) {
        prerequisiteHeads.push(prerequisiteHead);
        assert.equal(statusClient.statuses.length, 0);
      },
    });
    assert.deepEqual(prerequisiteHeads, [repositoryHead]);
    assert.deepEqual(Object.keys(admitted).sort(), [
      "admissionPath",
      "candidateReceiptPath",
      "checkedHead",
      "gateId",
    ]);
    assertPrivateFile(admitted.admissionPath);
    const admission = JSON.parse(readFileSync(admitted.admissionPath, "utf8"));
    const capabilityPath = path.join(admission.runDirectory, "attempt.capability");
    const capability = readExactPrivateFile(capabilityPath, 32);
    try {
      assert.equal(sha256(capability), admission.attemptCapabilitySha256);
    } finally {
      capability.fill(0);
    }
    assert.equal("attemptToken" in admission, false);
    assert.equal("attemptCapability" in admission, false);
    assert.equal(JSON.stringify(admitted).includes(admission.attemptCapabilitySha256), false);
    assert.equal(statusClient.statuses.length, 1);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("integrated gate rejects a wrong runner runtime before consuming the attempt", () => {
  assert.doesNotThrow(() => assertGateRunnerNodeRuntime("24.14.0"));
  assert.throws(
    () => assertGateRunnerNodeRuntime("26.3.1"),
    /attempt has not started/,
  );
  const runnerSource = readFileSync(
    path.join(repoRoot, "verification", "integrated-gate-runner.mjs"),
    "utf8",
  );
  const runtimePreflightIndex = runnerSource.indexOf("assertGateRunnerNodeRuntime();");
  const runningMarkerIndex = runnerSource.indexOf(
    'path.join(admittedPaths.runDirectory, "running.json")',
  );
  assert.notEqual(runtimePreflightIndex, -1, "the runner runtime preflight must exist");
  assert.notEqual(runningMarkerIndex, -1, "the attempt marker write must exist");
  assert.ok(
    runtimePreflightIndex < runningMarkerIndex,
    "the runner runtime preflight must precede the attempt marker",
  );
});

test("private gate artifacts use verified private directories and exclusive files", () => {
  const root = createCanonicalTemporaryDirectory("yap-private-artifact-");
  const capabilityPath = path.join(root, "attempt.capability");
  const capability = Buffer.alloc(32, 0x5a);
  try {
    assert.equal(assertPrivateDirectory(root), root);
    writeExclusivePrivateFile(capabilityPath, capability);
    assert.equal(assertPrivateFile(capabilityPath), capabilityPath);
    assert.deepEqual(readExactPrivateFile(capabilityPath, 32), capability);
    assert.throws(
      () => writeExclusivePrivateFile(capabilityPath, Buffer.alloc(32)),
      /EEXIST|exist/i,
    );
    assert.throws(
      () => readExactPrivateFile(capabilityPath, 31),
      /exactly 31 bytes/,
    );
  } finally {
    capability.fill(0);
    rmSync(root, { recursive: true, force: true });
  }
});

test("completed command-log hashing reasserts the private-file boundary", () => {
  const root = createCanonicalTemporaryDirectory("yap-private-command-log-");
  const commandLog = path.join(root, "command.log");
  try {
    writeExclusivePrivateFile(commandLog, Buffer.from("bounded output\n"));
    assert.equal(
      integratedGateCommandLogSha256(commandLog, "Command log fixture"),
      sha256("bounded output\n"),
    );
    if (process.platform === "win32") {
      execFileSync(
        path.join(process.env.SystemRoot, "System32", "icacls.exe"),
        [commandLog, "/grant", "*S-1-5-32-545:F"],
        { windowsHide: true, stdio: "ignore" },
      );
    } else {
      chmodSync(commandLog, 0o644);
    }
    assert.throws(
      () => integratedGateCommandLogSha256(commandLog, "Command log fixture"),
      /private gate file|DACL|mode 600/i,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("Windows atomic private-file producer publishes the validator DACL", {
  skip: process.platform !== "win32",
}, () => {
  const root = createCanonicalTemporaryDirectory("yap-private-powershell-output-");
  const destination = path.join(root, "receipt.json");
  const modulePath = path.join(
    repoRoot,
    "verification",
    "private-file-output.psm1",
  );
  const quotePowerShell = (value) => value.replaceAll("'", "''");
  try {
    execFileSync(
      "pwsh.exe",
      [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        `Import-Module '${quotePowerShell(modulePath)}' -Force; `
          + `Write-NewPrivateFileAtomically `
          + `-DestinationPath '${quotePowerShell(destination)}' `
          + "-Content ([Text.Encoding]::UTF8.GetBytes('{\"passed\":true}'))",
      ],
      { windowsHide: true, stdio: "pipe" },
    );
    assert.equal(assertPrivateFile(destination), destination);
    assert.equal(readFileSync(destination, "utf8"), '{"passed":true}');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("Windows private artifact protection removes broad access rules", {
  skip: process.platform !== "win32",
}, () => {
  const root = mkdtempSync(path.join(
    realpathSync.native(os.tmpdir()),
    "yap-private-artifact-dacl-",
  ));
  const privateFile = path.join(root, "private-evidence.json");
  try {
    execFileSync(
      path.join(process.env.SystemRoot, "System32", "icacls.exe"),
      [root, "/grant", "*S-1-5-32-545:(OI)(CI)F"],
      { windowsHide: true, stdio: "ignore" },
    );
    writeFileSync(privateFile, "{}\n");
    assert.equal(protectAndVerifyPrivateDirectory(root), root);
    assert.equal(protectAndVerifyPrivateFile(privateFile), privateFile);
    assert.equal(assertPrivateDirectory(root), root);
    assert.equal(assertPrivateFile(privateFile), privateFile);
    execFileSync(
      path.join(process.env.SystemRoot, "System32", "icacls.exe"),
      [privateFile, "/grant", "*S-1-5-32-545:F"],
      { windowsHide: true, stdio: "ignore" },
    );
    assert.throws(
      () => assertPrivateFile(privateFile),
      /private gate file|DACL/i,
    );
    assert.equal(protectAndVerifyPrivateFile(privateFile), privateFile);
    assert.equal(assertPrivateFile(privateFile), privateFile);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("integrated gate failure records retain only sanitized command termination evidence", () => {
  const failure = new Error("synthetic retained descendant");
  failure.code = "INTEGRATED_GATE_COMMAND_RETAINED_DESCENDANT";
  failure.rootExitCode = 0;
  failure.terminationEvidence = {
    schemaVersion: 1,
    containment: "windows-job-object",
    rootProcessId: 42,
    assignedBeforeResume: true,
    terminationReason: "retained-descendant",
    terminateRequested: true,
    rootExited: true,
    activeProcessCount: 0,
    activeProcessZeroObserved: true,
    cleanupProven: true,
    privateSupervisorNonce: "must-not-persist",
  };

  const record = integratedGateFailureRecord({ checkedHead }, failure);

  assert.equal(record.schemaVersion, 3);
  assert.deepEqual(record.commandTermination, {
    schemaVersion: 1,
    targetExitCode: 0,
    containment: "windows-job-object",
    assignedBeforeResume: true,
    terminationReason: "retained-descendant",
    terminateRequested: true,
    rootExited: true,
    activeProcessCount: 0,
    activeProcessZeroObserved: true,
    cleanupProven: true,
  });
  assert.doesNotMatch(JSON.stringify(record), /must-not-persist/);
  assert.equal(Object.hasOwn(record.commandTermination, "rootProcessId"), false);

  failure.terminationEvidence.cleanupProven = "not-a-boolean";
  assert.equal(
    integratedGateFailureRecord({ checkedHead }, failure).commandTermination,
    null,
  );
  failure.terminationEvidence = {
    schemaVersion: 1,
    containment: "windows-job-object",
    rootProcessId: 42,
    assignedBeforeResume: true,
    terminationReason: "retained-descendant",
    terminateRequested: true,
    rootExited: true,
    activeProcessCount: 0,
    activeProcessZeroObserved: true,
    cleanupProven: true,
  };

  const conflictingFailure = new Error("synthetic output overflow");
  conflictingFailure.code = "INTEGRATED_GATE_COMMAND_OUTPUT_LIMIT_EXCEEDED";
  conflictingFailure.terminationEvidence = {
    ...failure.terminationEvidence,
    cleanupProven: true,
    terminationReason: "retained-descendant",
  };
  assert.equal(
    integratedGateFailureRecord(
      { checkedHead },
      new AggregateError([conflictingFailure, failure]),
    ).commandTermination,
    null,
  );

  const timeoutFailure = new Error("synthetic command timeout");
  timeoutFailure.code = "INTEGRATED_GATE_COMMAND_TIMEOUT";
  timeoutFailure.terminationEvidence = {
    ...failure.terminationEvidence,
    terminationReason: "timeout",
  };
  assert.equal(
    integratedGateFailureRecord(
      { checkedHead },
      timeoutFailure,
    ).commandTermination.terminationReason,
    "timeout",
  );
});

test("integrated gate records proven cleanup for a clean nonzero command exit", {
  skip: process.platform !== "win32",
}, async () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-command-nonzero-");
  const commandLogDirectory = path.join(root, "command-logs");
  mkdirSync(commandLogDirectory);
  protectAndVerifyPrivateDirectory(commandLogDirectory);
  const cell = {
    id: "bounded.command-nonzero",
    executor: "command",
    cwd: ".",
    command: [process.execPath, "-e", "process.exit(23)"],
  };
  const admission = {
    checkedHead,
    runDirectory: root,
    commandLogDirectory,
  };
  try {
    await assert.rejects(
      runCommandCell(cell, admission, { maximumLogBytes: 1_024 }),
      (error) => {
        assert.equal(error.code, "INTEGRATED_GATE_COMMAND_EXITED_NONZERO");
        assert.equal(error.rootExitCode, 23);
        assert.equal(error.terminationEvidence.terminationReason, "none");
        assert.equal(error.terminationEvidence.cleanupProven, true);

        const record = integratedGateFailureRecord(admission, error);
        assert.equal(record.code, error.code);
        assert.deepEqual(record.commandTermination, {
          schemaVersion: 1,
          targetExitCode: 23,
          containment: "windows-job-object",
          assignedBeforeResume: true,
          terminationReason: "none",
          terminateRequested: false,
          rootExited: true,
          activeProcessCount: 0,
          activeProcessZeroObserved: true,
          cleanupProven: true,
        });
        assert.equal(Object.hasOwn(record.commandTermination, "rootProcessId"), false);
        return true;
      },
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("integrated gate terminates a command whose output exceeds its bounded log", async () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-command-output-");
  const commandLogDirectory = path.join(root, "command-logs");
  mkdirSync(commandLogDirectory);
  protectAndVerifyPrivateDirectory(commandLogDirectory);
  const maximumLogBytes = 1_024;
  const readyPath = path.join(root, "grandchild-ready");
  const escapedReadyPath = JSON.stringify(readyPath);
  const grandchildSource = Buffer.from(
    `require("node:fs").writeFileSync(${escapedReadyPath},String(process.pid));`
      + "setTimeout(process.exit,10000,0);",
  ).toString("base64");
  const commandSource = [
    'const{spawn}=require("node:child_process");',
    'const{existsSync}=require("node:fs");',
    `const source=Buffer.from("${grandchildSource}","base64").toString("utf8");`,
    'spawn(process.execPath,["-e",source],{stdio:"ignore"});',
    `const ready=${escapedReadyPath};`,
    `const overflow=()=>process.stdout.write(Buffer.alloc(${maximumLogBytes + 1},120));`,
    "const wait=()=>existsSync(ready)?overflow():setTimeout(wait,10);wait();",
    "setTimeout(process.exit,15000,0);",
  ].join("");
  const cell = {
    id: "bounded.command-output",
    executor: "command",
    cwd: ".",
    command: [
      process.execPath,
      "-e",
      commandSource,
    ],
  };
  const admission = {
    checkedHead,
    runDirectory: root,
    commandLogDirectory,
  };
  const started = Date.now();
  let boundedFailure;
  try {
    await assert.rejects(
      runCommandCell(cell, admission, { maximumLogBytes }),
      (error) => {
        boundedFailure = error;
        assert.equal(error.code, "INTEGRATED_GATE_COMMAND_OUTPUT_LIMIT_EXCEEDED");
        assert.equal(error.maximumBytes, maximumLogBytes);
        assert.ok(error.observedBytes > maximumLogBytes);
        assert.deepEqual(error.terminationEvidence, {
          schemaVersion: 1,
          containment: "windows-job-object",
          rootProcessId: error.terminationEvidence?.rootProcessId,
          assignedBeforeResume: true,
          terminationReason: "output-limit",
          terminateRequested: true,
          rootExited: true,
          activeProcessCount: 0,
          activeProcessZeroObserved: true,
          cleanupProven: true,
        });
        assert.ok(
          Number.isSafeInteger(error.terminationEvidence.rootProcessId)
            && error.terminationEvidence.rootProcessId > 0,
        );
        return true;
      },
    );
    assert.ok(
      Date.now() - started < 10_000,
      "the command process tree must terminate well before its delayed natural exit; "
        + `termination targets: ${JSON.stringify(boundedFailure?.terminatedProcessIds)}`,
    );
    assert.equal(
      statSync(path.join(commandLogDirectory, `${cell.id}.log`)).size,
      maximumLogBytes,
    );
    const failureRecord = integratedGateFailureRecord(admission, boundedFailure);
    assert.equal(failureRecord.schemaVersion, 3);
    assert.equal(
      failureRecord.code,
      "INTEGRATED_GATE_COMMAND_OUTPUT_LIMIT_EXCEEDED",
    );
    assert.match(failureRecord.message, /1024-byte command-log limit/);
    assert.deepEqual(failureRecord.commandTermination, {
      schemaVersion: 1,
      targetExitCode: null,
      containment: boundedFailure.terminationEvidence.containment,
      assignedBeforeResume: boundedFailure.terminationEvidence.assignedBeforeResume,
      terminationReason: boundedFailure.terminationEvidence.terminationReason,
      terminateRequested: boundedFailure.terminationEvidence.terminateRequested,
      rootExited: boundedFailure.terminationEvidence.rootExited,
      activeProcessCount: boundedFailure.terminationEvidence.activeProcessCount,
      activeProcessZeroObserved:
        boundedFailure.terminationEvidence.activeProcessZeroObserved,
      cleanupProven: boundedFailure.terminationEvidence.cleanupProven,
    });
    assert.deepEqual(
      Object.keys(failureRecord).sort(),
      [
        "checkedHead",
        "code",
        "commandTermination",
        "failedAt",
        "message",
        "schemaVersion",
      ],
    );
    const grandchildProcessId = Number.parseInt(readFileSync(readyPath, "utf8"), 10);
    assert.ok(Number.isSafeInteger(grandchildProcessId) && grandchildProcessId > 0);
    assert.equal(
      processIsAlive(grandchildProcessId),
      false,
      "the ready command grandchild must be gone when bounded cleanup settles",
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("command cells reject a redirected log destination before execution", async () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-log-path-");
  const runDirectory = path.join(root, "admitted");
  const commandLogDirectory = path.join(runDirectory, "command-logs");
  const redirectedDirectory = path.join(root, "redirected");
  const markerPath = path.join(root, "command-ran");
  mkdirSync(runDirectory);
  mkdirSync(commandLogDirectory);
  mkdirSync(redirectedDirectory);
  protectAndVerifyPrivateDirectory(runDirectory);
  protectAndVerifyPrivateDirectory(commandLogDirectory);
  protectAndVerifyPrivateDirectory(redirectedDirectory);
  try {
    await assert.rejects(
      runCommandCell(
        {
          id: "redirected.command-log",
          executor: "command",
          cwd: ".",
          command: [
            process.execPath,
            "-e",
            `require("node:fs").writeFileSync(${JSON.stringify(markerPath)},"ran")`,
          ],
        },
        {
          checkedHead,
          runDirectory,
          commandLogDirectory: redirectedDirectory,
        },
      ),
      /do not belong to the admitted run directory/,
    );
    assert.equal(existsSync(markerPath), false);
    assert.equal(
      existsSync(path.join(redirectedDirectory, "redirected.command-log.log")),
      false,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("command cells reject a junction-swapped log directory before execution", async () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-log-junction-");
  const runDirectory = path.join(root, "admitted");
  const commandLogDirectory = path.join(runDirectory, "command-logs");
  const redirectedDirectory = path.join(root, "redirected");
  const markerPath = path.join(root, "command-ran");
  mkdirSync(runDirectory);
  mkdirSync(redirectedDirectory);
  protectAndVerifyPrivateDirectory(runDirectory);
  protectAndVerifyPrivateDirectory(redirectedDirectory);
  symlinkSync(
    redirectedDirectory,
    commandLogDirectory,
    process.platform === "win32" ? "junction" : "dir",
  );
  try {
    await assert.rejects(
      runCommandCell(
        {
          id: "junction.command-log",
          executor: "command",
          cwd: ".",
          command: [
            process.execPath,
            "-e",
            `require("node:fs").writeFileSync(${JSON.stringify(markerPath)},"ran")`,
          ],
        },
        {
          checkedHead,
          runDirectory,
          commandLogDirectory,
        },
      ),
      /symbolic link|redirected parent/,
    );
    assert.equal(existsSync(markerPath), false);
    assert.equal(
      existsSync(path.join(redirectedDirectory, "junction.command-log.log")),
      false,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("integrated private evidence is derived from concrete checked-head artifacts", () => {
  const root = createCanonicalTemporaryDirectory("yap-private-evidence-");
  const targetRoot = path.join(root, `${checkedHead}-target`);
  const integratedRoot = path.join(root, `${checkedHead}-integrated`);
  const preparedPath = path.join(targetRoot, "local-stream-short-boundaries.json");
  const gb10Path = path.join(root, `${checkedHead}-resident-provider-lifecycle.json`);
  const mockOidcReceiptPath = path.join(root, `${checkedHead}-mock-oidc-owner-flow.json`);
  const remoteCleanupLogPath = path.join(root, `${checkedHead}-remote-cleanup.log`);
  const teardownPath = path.join(integratedRoot, "teardown.json");
  const remoteHelperSetSha256 = "b".repeat(64);
  const suiteSha256 = "1".repeat(64);
  const runtimeImageIds = {
    "cohere-vllm": `sha256:${"a".repeat(64)}`,
    "nemotron-nemo": `sha256:${"b".repeat(64)}`,
    "language-detection": `sha256:${"c".repeat(64)}`,
  };
  const runtimePreparation = Object.fromEntries(
    ["cohere-vllm", "nemotron-nemo", "language-detection"].map((runtime) => {
      const receiptFile = path.join(root, `${runtime}-preparation.json`);
      const receiptBytes = Buffer.from(`${JSON.stringify({
        schemaVersion: 1,
        checkedHead,
        runtime,
        dockerfileSha256: "d".repeat(64),
        image: `yap-${runtime}:checked-head-${checkedHead}`,
        imageId: runtimeImageIds[runtime],
        architecture: "arm64",
        baseDigest: `sha256:${"e".repeat(64)}`,
      })}\n`);
      writeFileSync(receiptFile, receiptBytes);
      return [runtime, {
        receiptFile,
        receiptSha256: sha256(receiptBytes),
      }];
    }),
  );
  const plan = {
    schemaVersion: 2,
    checkedHead,
    mockOidc: { receiptFile: mockOidcReceiptPath },
    targetClient: {
      evidenceDirectory: targetRoot,
      preparedAudioEvidenceFile: preparedPath,
      preparedAudioSuiteSha256: suiteSha256,
    },
    gb10: { lifecycleEvidenceFile: gb10Path, runtimePreparation },
    integrated: {
      evidenceDirectory: integratedRoot,
      remoteCleanupLogFile: remoteCleanupLogPath,
      teardownEvidenceFile: teardownPath,
      remoteHelperSetSha256,
    },
  };
  protectPrivateFixtureTree(root);
  try {
    const legacyPlan = {
      ...plan,
      schemaVersion: 1,
      integrated: { ...plan.integrated },
    };
    delete legacyPlan.mockOidc;
    delete legacyPlan.integrated.remoteHelperSetSha256;
    validateIntegratedPrivateEvidencePlan(legacyPlan, {
      expectedHead: checkedHead,
      repositoryRoot: repoRoot,
      requireDestinationsAbsent: true,
    });
    assert.throws(
      () => validateIntegratedPrivateEvidencePlan(legacyPlan, {
        expectedHead: checkedHead,
        repositoryRoot: repoRoot,
        requireDestinationsAbsent: true,
        requireMockOidc: true,
      }),
      /requires a schemaVersion 2 mock OIDC receipt/,
    );
    validateIntegratedPrivateEvidencePlan(plan, {
      expectedHead: checkedHead,
      repositoryRoot: repoRoot,
      requireDestinationsAbsent: true,
      requireMockOidc: true,
    });
    mkdirSync(targetRoot);
    const logBytes = Buffer.from("bounded native profile passed\n");
    const profile = {
      schemaVersion: 5,
      audioFixtureSha256: "2".repeat(64),
      logicalProcessorBudget: os.cpus().length,
      localAsrThreads: 2,
      combinedRealTimeGatePassed: true,
      paced: { pacedGatePassed: true },
      sustained: {
        requestedCycles: 12,
        completedCycles: 12,
        allCyclesPassed: true,
        privateByteGrowthLimit: 64 * 1024 * 1024,
        memoryPlateauGatePassed: true,
        sustainedGatePassed: true,
      },
    };
    const profileBytes = Buffer.from(`${JSON.stringify(profile, null, 2)}\n`);
    writeFileSync(path.join(targetRoot, "resident-language-routing-profile.json"), profileBytes);
    writeFileSync(path.join(targetRoot, "native-resource-gate.log"), logBytes);
    writeFileSync(
      path.join(targetRoot, "resource-gate-context.json"),
      `${JSON.stringify({
        schemaVersion: 4,
        status: "passed",
        checkedHead,
        processorName: os.cpus()[0].model.trim(),
        processorConstraint: null,
        logicalProcessors: os.cpus().length,
        logicalProcessorBudget: os.cpus().length,
        sessionCycles: 12,
        nativeTimeoutSeconds: 1_200,
        boundary: "desktop-prepared-audio-frame-to-final-resource-profile",
        networkBoundary: "direct-local-runtime-with-no-server-client",
        exclusions: [
          "physical-microphone",
          "rendered-ui",
          "server-transport",
          "energy",
          "thermal",
        ],
        modelsDirectoryRecorded: false,
        audioFixturePathRecorded: false,
        audioFixtureSha256: profile.audioFixtureSha256,
        profileSha256: sha256(profileBytes),
        logSha256: sha256(logBytes),
      }, null, 2)}\n`,
    );
    const durations = [250, 500, 750, 1_000, 1_120, 2_000, 5_000, 10_000, 30_000];
    const prepared = {
      schemaVersion: 2,
      checkedHead,
      suiteSha256,
      planSha256: "3".repeat(64),
      modelArtifactLockSha256: "4".repeat(64),
      qualificationProfile: "short-boundaries",
      measurementBoundary: "desktop-prepared-audio-frame-to-final",
      adapterDrainTargetMs: 6_000,
      adapterDrainTimeoutMs: 12_000,
      logicalProcessorBudget: os.cpus().length,
      allCasesPassed: true,
      cases: durations.map((durationMs) => ({
        durationMs,
        durationSamples: durationMs * 16,
        expectedFrames: durationMs / 10,
        acceptedFrames: durationMs / 10,
        adapterDrainMs: 1_000,
        adapterDrainTargetMet: true,
        adapterStatus: "drained",
        droppedFrames: 0,
        processedAudioSamples: durationMs * 16,
        streamStatus: "completed",
        passed: true,
        languageDegraded: false,
        transcriptionUnavailable: false,
        expectedText: durationMs >= 1_000,
        textSeen: durationMs >= 1_000,
      })),
    };
    const preparedBytes = Buffer.from(`${JSON.stringify(prepared, null, 2)}\n`);
    writeFileSync(preparedPath, preparedBytes);
    const renderedRoot = path.join(targetRoot, "rendered-ui-and-microphone");
    mkdirSync(renderedRoot);
    const rendered = {
      schemaVersion: 4,
      buildGitSha: checkedHead,
      preparedAudioEvidenceSha256: sha256(preparedBytes),
      route: "localFallback",
      targetClientGate: true,
      transcriptTextRecorded: false,
      restartCancellation: { cycleCount: 4, finalStatus: "idle" },
    };
    const renderedBytes = Buffer.from(`${JSON.stringify(rendered, null, 2)}\n`);
    writeFileSync(path.join(renderedRoot, "rendered-ui-evidence.json"), renderedBytes);
    writeFileSync(
      path.join(renderedRoot, "rendered-ui-context.json"),
      `${JSON.stringify({
        schemaVersion: 4,
        status: "passed",
        checkedHead,
        preparedAudioSuiteSha256: suiteSha256,
        preparedAudioEvidenceSha256: sha256(preparedBytes),
        evidenceSha256: sha256(renderedBytes),
        serverBoundary: "isolated-profile-with-no-loopback-server-listener",
        transcriptTextRecorded: false,
      }, null, 2)}\n`,
    );

    const gb10Children = [
      "nemo/active-capacity",
      "nemo/cancellation",
      "nemo/duration-batch",
      "nemo/duration-finalized",
      "nemo/language-contract",
      "nemo/long-windows",
      "nemo/readiness",
      "nemo/resource-load",
      "nemo/resources",
      "nemo/short-tail",
      "vllm/cancellation",
      "vllm/duration-batch",
      "vllm/pcm-capacity",
      "vllm/readiness",
      "vllm/resource-load",
      "vllm/resources",
      "vllm/short-tail",
      "vllm/slot-capacity",
    ];
    const gb10 = {
      schemaVersion: 1,
      checkedHead,
      hardwareProfile: "dgx-spark-gb10",
      executionShape: "sequential-resident-providers",
      runtimeImages: {
        "cohere-vllm": {
          imageId: runtimeImageIds["cohere-vllm"],
          preparationReceiptSha256: runtimePreparation["cohere-vllm"].receiptSha256,
        },
        "nemotron-nemo": {
          imageId: runtimeImageIds["nemotron-nemo"],
          preparationReceiptSha256: runtimePreparation["nemotron-nemo"].receiptSha256,
        },
      },
      durationSuite: { sha256: "5".repeat(64), planSha256: "6".repeat(64) },
      hostBoundary: {
        listenerStateUnchanged: true,
        firewallObservationUnchanged: true,
        serviceUnitsUnchanged: true,
        remainingProviderContainers: 0,
        remainingProviderRuntimeProcesses: 0,
        remainingProviderNetworks: 0,
      },
      childEvidence: Object.fromEntries(gb10Children.map((name) => [name, "7".repeat(64)])),
      passed: true,
    };
    gb10.evidenceSha256 = sha256(JSON.stringify(stableValue(gb10)));
    writeFileSync(gb10Path, `${JSON.stringify(gb10, null, 2)}\n`);

    mkdirSync(integratedRoot);
    writeFileSync(
      path.join(integratedRoot, "gate-context.json"),
      `${JSON.stringify({
        schemaVersion: 1,
        checkedHead,
        fixtureLicense: "CC-BY-4.0",
        fixtureSha256: "8".repeat(64),
        serverOrigin: "http://127.0.0.1:18765",
        status: "started",
      }, null, 2)}\n`,
    );
    writeFileSync(
      path.join(integratedRoot, "native-vertical-slice.json"),
      `${JSON.stringify({
        schemaVersion: 3,
        checkedHead,
        fixtureSha256: "8".repeat(64),
        clientRoute: "serverBatch",
        serverOrigin: "http://127.0.0.1:18765",
        resultAuthority: "server_authoritative",
        durablePreprocessingManifestVerified: true,
        completedJobRetiredFromRecoverableQueue: true,
        tunnelInterruptionState: "retrying",
        tunnelRestoredState: "ready",
        immutableJobSurvivedTunnelInterruption: true,
        historyOpenedVerifiedResult: true,
        languagePreflightExecution: {
          componentId: "ambernet-batch-language-preflight",
          modelId: "nvidia/nemo/langid_ambernet",
          modelRevision: "1.12.0",
          observationCount: 5,
          policyRevision: "ambernet-stratified-five-region-v1",
          requestIdSha256: "9".repeat(64),
          resultStatus: "suggestion",
          runtimeCpuOnly: true,
          runtimePythonVersion: "3.12.13",
          sourcePcmSha256: "a".repeat(64),
        },
        status: "passed",
      }, null, 2)}\n`,
    );
    const remoteCleanupLog = Buffer.from(
      [
        `REMOTE_RUNTIME_COHERE_VLLM_IMAGE_ID=${runtimeImageIds["cohere-vllm"]}`,
        `REMOTE_RUNTIME_COHERE_VLLM_PREPARATION_RECEIPT_SHA256=${runtimePreparation["cohere-vllm"].receiptSha256}`,
        `REMOTE_RUNTIME_LANGUAGE_DETECTION_IMAGE_ID=${runtimeImageIds["language-detection"]}`,
        `REMOTE_RUNTIME_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256=${runtimePreparation["language-detection"].receiptSha256}`,
        `REMOTE_HELPER_SET_SHA256=${remoteHelperSetSha256}`,
        `REMOTE_PRIVATE_SERVER_READY=${checkedHead}`,
        "REMOTE_GATE_CLEANUP=PASS",
        "",
      ].join("\n"),
    );
    writeFileSync(remoteCleanupLogPath, remoteCleanupLog);
    const tunnelProcessLedger = Buffer.from(`${JSON.stringify({
      schemaVersion: 1,
      checkedHead,
      startedProcessCount: 2,
      exitedProcessCount: 2,
      processes: [
        {
          pid: 1001,
          startedAt: "2026-07-23T12:10:00.000Z",
          exitedAt: "2026-07-23T12:20:00.000Z",
        },
        {
          pid: 1002,
          startedAt: "2026-07-23T12:21:00.000Z",
          exitedAt: "2026-07-23T12:30:00.000Z",
        },
      ],
      status: "passed",
    }, null, 2)}\n`);
    writeFileSync(
      path.join(integratedRoot, "tunnel-process-ledger.json"),
      tunnelProcessLedger,
    );
    writeFileSync(
      teardownPath,
      `${JSON.stringify({
        schemaVersion: 2,
        checkedHead,
        remoteCleanupPassed: true,
        localForwardAbsent: true,
        remainingOwnedProcesses: 0,
        ownedProcessCount: 3,
        remainingOwnedContainers: 0,
        remainingOwnedListeners: 0,
        remainingOwnedNetworks: 0,
        remoteCleanupLogSha256: sha256(remoteCleanupLog),
        tunnelProcessLedgerSha256: sha256(tunnelProcessLedger),
        remoteHelperSetSha256,
        status: "passed",
      }, null, 2)}\n`,
    );

    const mockOidcReceipt = {
      schemaVersion: 1,
      receiptContract: "mock-oidc-owner-flow-v1",
      checkedHead,
      lockedImageDigest:
        "sha256:f625692f5bf84939f3d0af4931f2c0f038dca84c4f1bac1171710d544181f97f",
      validatorSources: {
        oidcAccessTokensSha256: sha256(readFileSync(path.join(
          repoRoot,
          "server",
          "src",
          "yap_server",
          "auth",
          "oidc_access_tokens.py",
        ))),
        oidcMetadataSha256: sha256(readFileSync(path.join(
          repoRoot,
          "server",
          "src",
          "yap_server",
          "auth",
          "oidc_metadata.py",
        ))),
      },
      ownerFlowSha256: sha256(readFileSync(path.join(
        repoRoot,
        "verification",
        "mock-oidc-owner-flow.py",
      ))),
      teardown: {
        childProcessesStopped: true,
        containerAbsent: true,
        networkAbsent: true,
        loopbackPortReleased: true,
        stateDirectoryRemoved: true,
        cancellationHandlerRemoved: true,
        remainingContainers: 0,
        remainingNetworks: 0,
        status: "passed",
      },
      status: "passed",
    };
    const mockOidcReceiptBytes = Buffer.from(
      `${JSON.stringify(mockOidcReceipt, null, 2)}\n`,
    );
    writeFileSync(mockOidcReceiptPath, mockOidcReceiptBytes);
    protectPrivateFixtureTree(root);

    const evidence = validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot);
    assert.equal(evidence.size, 13);
    assert.equal(
      evidence.get("server.mock-oidc-owner-flow"),
      sha256(mockOidcReceiptBytes),
    );
    if (process.platform === "win32") {
      execFileSync(
        path.join(process.env.SystemRoot, "System32", "icacls.exe"),
        [mockOidcReceiptPath, "/grant", "*S-1-5-32-545:F"],
        { windowsHide: true, stdio: "ignore" },
      );
    } else {
      chmodSync(mockOidcReceiptPath, 0o644);
    }
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
      /private gate file|DACL|mode 600/i,
    );
    protectAndVerifyPrivateFile(mockOidcReceiptPath);
    mockOidcReceipt.ownerFlowSha256 = "f".repeat(64);
    writeFileSync(
      mockOidcReceiptPath,
      `${JSON.stringify(mockOidcReceipt, null, 2)}\n`,
    );
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
      /source identities do not match/,
    );
    mockOidcReceipt.ownerFlowSha256 = sha256(readFileSync(path.join(
      repoRoot,
      "verification",
      "mock-oidc-owner-flow.py",
    )));
    mockOidcReceipt.teardown.containerAbsent = false;
    writeFileSync(
      mockOidcReceiptPath,
      `${JSON.stringify(mockOidcReceipt, null, 2)}\n`,
    );
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
      /did not prove verified teardown/,
    );
    mockOidcReceipt.teardown.containerAbsent = true;
    mockOidcReceipt.privatePath = "must-not-be-admitted";
    writeFileSync(
      mockOidcReceiptPath,
      `${JSON.stringify(mockOidcReceipt, null, 2)}\n`,
    );
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
      /fields differ from the frozen contract/,
    );
    delete mockOidcReceipt.privatePath;
    truncateSync(mockOidcReceiptPath, 4_097);
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
      (error) => {
        assert.equal(error.code, "INTEGRATED_GATE_ARTIFACT_LIMIT_EXCEEDED");
        assert.equal(error.maximumBytes, 4_096);
        return true;
      },
    );
    writeFileSync(mockOidcReceiptPath, mockOidcReceiptBytes);
    const preparedFailurePath = `${preparedPath}.failure.json`;
    writeFileSync(preparedFailurePath, '{"status":"failed"}\n');
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
      /cannot retain prepared-audio failure evidence/,
    );
    rmSync(preparedFailurePath);
    const verticalPath = path.join(integratedRoot, "native-vertical-slice.json");
    const vertical = JSON.parse(readFileSync(verticalPath, "utf8"));
    const lidExecution = vertical.languagePreflightExecution;
    delete vertical.languagePreflightExecution;
    writeFileSync(verticalPath, `${JSON.stringify(vertical, null, 2)}\n`);
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
      /did not prove ASR and LID execution/,
    );
    vertical.languagePreflightExecution = lidExecution;
    writeFileSync(verticalPath, `${JSON.stringify(vertical, null, 2)}\n`);
    writeFileSync(
      remoteCleanupLogPath,
      Buffer.concat([
        remoteCleanupLog,
        Buffer.from(
          `REMOTE_RUNTIME_COHERE_VLLM_IMAGE_ID=${runtimeImageIds["cohere-vllm"]}\n`,
        ),
      ]),
    );
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
      /did not use the frozen prepared images/,
    );
    writeFileSync(remoteCleanupLogPath, remoteCleanupLog);
    gb10.runtimeImages["cohere-vllm"].imageId = `sha256:${"f".repeat(64)}`;
    delete gb10.evidenceSha256;
    gb10.evidenceSha256 = sha256(JSON.stringify(stableValue(gb10)));
    writeFileSync(gb10Path, `${JSON.stringify(gb10, null, 2)}\n`);
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
      /not bound to the frozen runtime preparation/,
    );
    gb10.runtimeImages["cohere-vllm"].imageId = runtimeImageIds["cohere-vllm"];
    delete gb10.evidenceSha256;
    gb10.evidenceSha256 = sha256(JSON.stringify(stableValue(gb10)));
    writeFileSync(gb10Path, `${JSON.stringify(gb10, null, 2)}\n`);
    const cohereReceipt = runtimePreparation["cohere-vllm"].receiptFile;
    const cohereReceiptBytes = readFileSync(cohereReceipt);
    writeFileSync(cohereReceipt, Buffer.concat([cohereReceiptBytes, Buffer.from(" ")]));
    assert.throws(
      () => validateIntegratedPrivateEvidencePlan(plan, {
        expectedHead: checkedHead,
        repositoryRoot: repoRoot,
      }),
      /does not match the frozen plan/,
    );
    writeFileSync(cohereReceipt, cohereReceiptBytes);
    truncateSync(
      preparedPath,
      INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes + 1,
    );
    assert.equal(
      statSync(preparedPath).size,
      INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes + 1,
    );
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
      (error) => {
        assert.equal(error.code, "INTEGRATED_GATE_ARTIFACT_LIMIT_EXCEEDED");
        assert.equal(
          error.maximumBytes,
          INTEGRATED_GATE_BYTE_LIMITS.privateJsonEvidenceBytes,
        );
        return true;
      },
    );
    writeFileSync(preparedPath, preparedBytes);
    prepared.cases[0].droppedFrames = 1;
    writeFileSync(preparedPath, `${JSON.stringify(prepared, null, 2)}\n`);
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead, repoRoot),
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("connected teardown receipt derives cleanup state and refuses retained owners", async () => {
  const root = createCanonicalTemporaryDirectory("yap-connected-teardown-");
  const logPath = path.join(root, "remote.log");
  const tunnelLedgerPath = path.join(root, "tunnel-process-ledger.json");
  const output = path.join(root, "teardown.json");
  const remoteHelperSetSha256 = "c".repeat(64);
  try {
    writeFileSync(
      logPath,
      `REMOTE_HELPER_SET_SHA256=${remoteHelperSetSha256}\n`
        + `REMOTE_PRIVATE_SERVER_READY=${checkedHead}\n`
        + "REMOTE_GATE_CLEANUP=PASS\n",
    );
    writeFileSync(
      tunnelLedgerPath,
      `${JSON.stringify({
        schemaVersion: 1,
        checkedHead,
        startedProcessCount: 2,
        exitedProcessCount: 2,
        processes: [
          {
            pid: 123_456,
            startedAt: "2026-07-23T12:10:00.000Z",
            exitedAt: "2026-07-23T12:20:00.000Z",
          },
          {
            pid: 123_457,
            startedAt: "2026-07-23T12:21:00.000Z",
            exitedAt: "2026-07-23T12:30:00.000Z",
          },
        ],
        status: "passed",
      }, null, 2)}\n`,
    );
    protectAndVerifyPrivateFile(logPath);
    protectAndVerifyPrivateFile(tunnelLedgerPath);
    const receipt = await createConnectedServerTeardownReceipt({
      checkedHead,
      remoteCleanupLog: logPath,
      tunnelProcessLedger: tunnelLedgerPath,
      output,
      remoteServerProcessId: 123_455,
      remoteHelperSetSha256,
      processProbe: () => false,
      portProbe: async () => false,
    });
    assert.equal(receipt.status, "passed");
    await assert.rejects(
      createConnectedServerTeardownReceipt({
        checkedHead,
        remoteCleanupLog: logPath,
        tunnelProcessLedger: tunnelLedgerPath,
        output: path.join(root, "retained.json"),
        remoteServerProcessId: 123_455,
        remoteHelperSetSha256,
        processProbe: () => true,
        portProbe: async () => false,
      }),
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("hosted closure derives exact checked-head jobs and rejects rerun-only evidence", () => {
  const runsByWorkflow = new Map();
  const jobsByRun = new Map();
  const workflows = [...new Set(manifest.hostedClosureCells.map(({ workflow }) => workflow))];
  workflows.forEach((workflow, index) => {
    const databaseId = 10_000 + index;
    runsByWorkflow.set(workflow, [{
      databaseId,
      headSha: checkedHead,
      workflowName: workflow,
      status: "completed",
      conclusion: "success",
      attempt: 1,
      createdAt: startedAt,
      updatedAt: finishedAt,
      url: `https://example.invalid/run/${databaseId}`,
    }]);
    jobsByRun.set(
      databaseId,
      manifest.hostedClosureCells
        .filter((cell) => cell.workflow === workflow)
        .map((cell, jobIndex) => ({
          databaseId: databaseId * 100 + jobIndex,
          name: cell.job,
          status: "completed",
          conclusion: "success",
          startedAt,
          completedAt: finishedAt,
          url: `https://example.invalid/job/${databaseId}/${jobIndex}`,
        })),
    );
  });
  const selected = selectHostedClosureEvidence({
    cells: manifest.hostedClosureCells,
    checkedHead,
    runsByWorkflow,
    jobsByRun,
  });
  const receipt = buildHostedClosureReceipt({
    manifest,
    manifestSha256,
    checkedHead,
    candidateHead: checkedHead,
    candidateReceiptSha256: "e".repeat(64),
    selected,
  });
  assert.equal(
    validateIntegratedGateReceipt({
      receipt,
      manifest,
      manifestSha256,
      expectedHead: checkedHead,
      expectedCandidateHead: checkedHead,
      expectedCandidateReceiptSha256: "e".repeat(64),
      expectedScope: "hosted-closure",
    }).childCount,
    hostedClosureIds.length,
  );
  const rerunOnly = structuredClone([...runsByWorkflow.get("CI")]);
  rerunOnly[0].attempt = 2;
  const mutatedRuns = new Map(runsByWorkflow);
  mutatedRuns.set("CI", rerunOnly);
  assert.throws(() => selectHostedClosureEvidence({
    cells: manifest.hostedClosureCells,
    checkedHead,
    runsByWorkflow: mutatedRuns,
    jobsByRun,
  }));
  const olderFailure = {
    ...runsByWorkflow.get("CI")[0],
    databaseId: 9_999,
    conclusion: "failure",
    createdAt: "2026-07-23T11:00:00.000Z",
    updatedAt: "2026-07-23T11:30:00.000Z",
    url: "https://example.invalid/run/9999",
  };
  const independentlyRetriedRuns = new Map(runsByWorkflow);
  independentlyRetriedRuns.set("CI", [
    runsByWorkflow.get("CI")[0],
    olderFailure,
  ]);
  assert.throws(
    () => selectHostedClosureEvidence({
      cells: manifest.hostedClosureCells,
      checkedHead,
      runsByWorkflow: independentlyRetriedRuns,
      jobsByRun,
    }),
    /exact-head run is ambiguous/i,
  );
});

test("documentation-only hosted lineage exposes both sides of a source-to-docs move", () => {
  const source = readFileSync(
    path.join(repoRoot, "verification", "integrated-hosted-closure.mjs"),
    "utf8",
  );
  assert.match(source, /"diff",\s*"--no-renames",\s*"--name-only"/);
});
