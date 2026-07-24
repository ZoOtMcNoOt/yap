import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  reserveIntegratedGateAttemptDirectory,
} from "../../../../verification/integrated-gate-runner.mjs";
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
  "integrated-preprocessing-language-routing-gate.json",
);
const manifestBytes = readFileSync(manifestPath);
const manifest = validateIntegratedGateManifest(JSON.parse(manifestBytes.toString("utf8")));
const manifestSha256 = integratedGateManifestSha256(manifestBytes);
const checkedHead = "a".repeat(40);
const startedAt = "2026-07-23T12:00:00.000Z";
const finishedAt = "2026-07-23T13:00:00.000Z";
const sha256 = (value) => createHash("sha256").update(value).digest("hex");

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
  "frontend.accessibility-and-workflows": ["pnpm", "test:e2e"],
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
};

function createReceipt(scope) {
  const cells = scope === "candidate" ? manifest.candidateCells : manifest.hostedClosureCells;
  return {
    schemaVersion: 2,
    gateId: manifest.gateId,
    scope,
    checkedHead,
    candidateHead: checkedHead,
    candidateReceiptSha256: scope === "candidate" ? null : "e".repeat(64),
    manifestSha256,
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
  assert.deepEqual(manifest.candidateCells.map(({ id }) => id), candidateIds);
  assert.deepEqual(manifest.hostedClosureCells.map(({ id }) => id), hostedClosureIds);
  const commandCells = Object.fromEntries(
    manifest.candidateCells
      .filter(({ executor }) => executor === "command")
      .map(({ id, command }) => [id, command]),
  );
  assert.deepEqual(commandCells, exactCommands);
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

test("integrated gate reserves one deterministic attempt and refuses a retry", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-gate-attempt-"));
  try {
    const input = {
      evidenceRoot: root,
      gateId: manifest.gateId,
      checkedHead,
      manifestSha256,
    };
    const first = reserveIntegratedGateAttemptDirectory(input);
    assert.ok(first.startsWith(root));
    assert.throws(() => reserveIntegratedGateAttemptDirectory(input));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("integrated private evidence is derived from concrete checked-head artifacts", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-private-evidence-"));
  const targetRoot = path.join(root, `${checkedHead}-target`);
  const integratedRoot = path.join(root, `${checkedHead}-integrated`);
  const preparedPath = path.join(targetRoot, "local-stream-short-boundaries.json");
  const gb10Path = path.join(root, `${checkedHead}-resident-provider-lifecycle.json`);
  const remoteCleanupLogPath = path.join(root, `${checkedHead}-remote-cleanup.log`);
  const teardownPath = path.join(integratedRoot, "teardown.json");
  const suiteSha256 = "1".repeat(64);
  const plan = {
    schemaVersion: 1,
    checkedHead,
    targetClient: {
      evidenceDirectory: targetRoot,
      preparedAudioEvidenceFile: preparedPath,
      preparedAudioSuiteSha256: suiteSha256,
    },
    gb10: { lifecycleEvidenceFile: gb10Path },
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
      logicalProcessorBudget: os.cpus().length,
      allCasesPassed: true,
      cases: durations.map((durationMs) => ({
        durationMs,
        durationSamples: durationMs * 16,
        expectedFrames: durationMs / 10,
        acceptedFrames: durationMs / 10,
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
        schemaVersion: 2,
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
        status: "passed",
      }, null, 2)}\n`,
    );
    const remoteCleanupLog = Buffer.from(
      `REMOTE_PRIVATE_SERVER_READY=${checkedHead}\nREMOTE_GATE_CLEANUP=PASS\n`,
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
    prepared.cases[0].droppedFrames = 1;
    writeFileSync(preparedPath, `${JSON.stringify(prepared, null, 2)}\n`);
    assert.throws(() => validateIntegratedPrivateEvidence(plan, checkedHead));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("connected teardown receipt derives cleanup state and refuses retained owners", async () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-connected-teardown-"));
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
});

test("documentation-only hosted lineage exposes both sides of a source-to-docs move", () => {
  const source = readFileSync(
    path.join(repoRoot, "verification", "integrated-hosted-closure.mjs"),
    "utf8",
  );
  assert.match(source, /"diff",\s*"--no-renames",\s*"--name-only"/);
});
