import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
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
  assertGateRunnerNodeRuntime,
  assertIntegratedGateManifestMatchesAdmission,
  completeIntegratedGateAttempt,
  integratedGateFailureRecord,
  loadIntegratedGateManifestSelection,
  parseIntegratedGateRunnerInvocation,
  runCommandCell,
  reserveIntegratedGateAttemptDirectory,
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
  return mkdtempSync(path.join(realpathSync.native(os.tmpdir()), prefix));
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
  "native.format",
  "native.clippy",
  "native.tests",
  "native.server-connector",
  "native.authenticated-server-connector",
  "native.windows-dependency-boundary",
  "native.dependency-audit",
  "desktop.dotnet-dependency-audit",
  "desktop.identity-broker",
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
  "hosted.ci.identity-broker",
  "hosted.ci.native-wdio",
  "hosted.ci.server",
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
  ...exactCommands,
  "native.authenticated-server-connector": [
    "pwsh.exe",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "./verification/test-authenticated-server-connector.ps1",
  ],
  "desktop.dotnet-dependency-audit": [
    "pwsh.exe",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "./verification/audit-dotnet-dependencies.ps1",
  ],
  "desktop.identity-broker": ["pnpm", "build:identity"],
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
    "--attempt-token",
    "f".repeat(64),
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
      completeArguments.filter((value, index) => ![5, 6].includes(index)),
    ),
    /complete requires exactly .*--manifest/,
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
    writeFileSync(
      admissionPath,
      `${JSON.stringify({
        schemaVersion: 1,
        gateId: phase6Admission.gateId,
        checkedHead,
        manifestPath: phase6Admission.manifestPath,
        manifestSha256: phase6Admission.manifestSha256,
        privatePlanPath: path.join(root, "private-plan.json"),
        privatePlanSha256: "1".repeat(64),
        attempt: 1,
        attemptToken: "f".repeat(64),
        admittedAt: startedAt,
        runDirectory: root,
        commandLogDirectory: path.join(root, "command-logs"),
        candidateReceiptPath: path.join(root, "candidate-receipt.json"),
      }, null, 2)}\n`,
    );
    await assert.rejects(
      completeIntegratedGateAttempt({
        admissionPath,
        attemptToken: "f".repeat(64),
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

test("integrated gate reservation authority rejects same-root and cross-root retries", () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-attempt-");
  const otherRoot = createCanonicalTemporaryDirectory("yap-gate-attempt-other-");
  const reservationAuthorityRoot =
    createCanonicalTemporaryDirectory("yap-gate-attempt-authority-");
  try {
    const input = {
      evidenceRoot: root,
      gateId: manifest.gateId,
      checkedHead,
      manifestSha256,
      reservationAuthorityRoot,
    };
    const first = reserveIntegratedGateAttemptDirectory(input);
    assert.ok(first.startsWith(root));
    assert.throws(() => reserveIntegratedGateAttemptDirectory(input));
    assert.throws(() => reserveIntegratedGateAttemptDirectory({
      ...input,
      evidenceRoot: otherRoot,
    }));
  } finally {
    rmSync(root, { recursive: true, force: true });
    rmSync(otherRoot, { recursive: true, force: true });
    rmSync(reservationAuthorityRoot, { recursive: true, force: true });
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

test("integrated gate terminates a command whose output exceeds its bounded log", async () => {
  const root = createCanonicalTemporaryDirectory("yap-gate-command-output-");
  const commandLogDirectory = path.join(root, "command-logs");
  mkdirSync(commandLogDirectory);
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
    assert.equal(failureRecord.schemaVersion, 2);
    assert.equal(
      failureRecord.code,
      "INTEGRATED_GATE_COMMAND_OUTPUT_LIMIT_EXCEEDED",
    );
    assert.match(failureRecord.message, /1024-byte command-log limit/);
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
  const remoteCleanupLogPath = path.join(root, `${checkedHead}-remote-cleanup.log`);
  const teardownPath = path.join(integratedRoot, "teardown.json");
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
    schemaVersion: 1,
    checkedHead,
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
    },
  };
  try {
    validateIntegratedPrivateEvidencePlan(plan, {
      expectedHead: checkedHead,
      repositoryRoot: repoRoot,
      requireDestinationsAbsent: true,
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
        schemaVersion: 1,
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
        status: "passed",
      }, null, 2)}\n`,
    );

    const evidence = validateIntegratedPrivateEvidence(plan, checkedHead);
    assert.equal(evidence.size, 12);
    const preparedFailurePath = `${preparedPath}.failure.json`;
    writeFileSync(preparedFailurePath, '{"status":"failed"}\n');
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead),
      /cannot retain prepared-audio failure evidence/,
    );
    rmSync(preparedFailurePath);
    const verticalPath = path.join(integratedRoot, "native-vertical-slice.json");
    const vertical = JSON.parse(readFileSync(verticalPath, "utf8"));
    const lidExecution = vertical.languagePreflightExecution;
    delete vertical.languagePreflightExecution;
    writeFileSync(verticalPath, `${JSON.stringify(vertical, null, 2)}\n`);
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead),
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
      () => validateIntegratedPrivateEvidence(plan, checkedHead),
      /did not use the frozen prepared images/,
    );
    writeFileSync(remoteCleanupLogPath, remoteCleanupLog);
    gb10.runtimeImages["cohere-vllm"].imageId = `sha256:${"f".repeat(64)}`;
    delete gb10.evidenceSha256;
    gb10.evidenceSha256 = sha256(JSON.stringify(stableValue(gb10)));
    writeFileSync(gb10Path, `${JSON.stringify(gb10, null, 2)}\n`);
    assert.throws(
      () => validateIntegratedPrivateEvidence(plan, checkedHead),
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
      () => validateIntegratedPrivateEvidence(plan, checkedHead),
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
    assert.throws(() => validateIntegratedPrivateEvidence(plan, checkedHead));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("connected teardown receipt derives cleanup state and refuses retained owners", async () => {
  const root = createCanonicalTemporaryDirectory("yap-connected-teardown-");
  const logPath = path.join(root, "remote.log");
  const tunnelLedgerPath = path.join(root, "tunnel-process-ledger.json");
  const output = path.join(root, "teardown.json");
  try {
    writeFileSync(
      logPath,
      `REMOTE_PRIVATE_SERVER_READY=${checkedHead}\nREMOTE_GATE_CLEANUP=PASS\n`,
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
    const receipt = await createConnectedServerTeardownReceipt({
      checkedHead,
      remoteCleanupLog: logPath,
      tunnelProcessLedger: tunnelLedgerPath,
      output,
      remoteServerProcessId: 123_455,
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
