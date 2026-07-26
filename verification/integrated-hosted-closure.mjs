import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertExactCleanGitHead,
  validateCompletedIntegratedGateAttempt,
} from "./integrated-gate-runner.mjs";
import {
  integratedGateCellDefinitionSha256,
  validateIntegratedGateReceipt,
} from "./integrated-gate-receipt.mjs";

const SHA40 = /^[0-9a-f]{40}$/;
const RUNNER_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));
const REPOSITORY_ROOT = path.resolve(RUNNER_DIRECTORY, "..");

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
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

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function requireOutsideRepository(candidate, label) {
  const relative = path.relative(REPOSITORY_ROOT, candidate);
  requireCondition(
    relative !== "" && (relative.startsWith("..") || path.isAbsolute(relative)),
    `${label} must stay outside the repository.`,
  );
}

function gh(args) {
  const result = spawnSync("gh", args, {
    cwd: REPOSITORY_ROOT,
    encoding: "utf8",
    maxBuffer: 50 * 1024 * 1024,
    windowsHide: true,
  });
  requireCondition(
    result.status === 0,
    `GitHub CLI ${args.join(" ")} failed: ${(result.stderr || result.stdout).trim()}`,
  );
  return result.stdout;
}

function git(args, { allowFailure = false } = {}) {
  const result = spawnSync("git", args, {
    cwd: REPOSITORY_ROOT,
    encoding: "utf8",
    windowsHide: true,
  });
  if (!allowFailure) {
    requireCondition(
      result.status === 0,
      `Git ${args.join(" ")} failed: ${(result.stderr || result.stdout).trim()}`,
    );
  }
  return result;
}

export function assertCandidateToHostedLineage(candidateHead, hostedHead) {
  requireCondition(SHA40.test(candidateHead ?? ""), "Candidate head is invalid.");
  requireCondition(SHA40.test(hostedHead ?? ""), "Hosted head is invalid.");
  if (candidateHead === hostedHead) return Object.freeze({ documentationOnly: false });
  const ancestor = git(
    ["merge-base", "--is-ancestor", candidateHead, hostedHead],
    { allowFailure: true },
  );
  requireCondition(
    ancestor.status === 0,
    "Hosted head is not a descendant of the checked candidate.",
  );
  const changed = git([
    "diff",
    "--no-renames",
    "--name-only",
    "--diff-filter=ACDMRTUXB",
    `${candidateHead}..${hostedHead}`,
  ]).stdout.trim().split(/\r?\n/).filter(Boolean);
  requireCondition(
    changed.length > 0 && changed.every((candidate) => candidate.startsWith("docs/")),
    "Only documentation evidence reconciliation may follow the checked candidate.",
  );
  return Object.freeze({ documentationOnly: true, changed });
}

function listWorkflowRuns(workflow, checkedHead) {
  return JSON.parse(gh([
    "run",
    "list",
    "--workflow",
    workflow,
    "--commit",
    checkedHead,
    "--limit",
    "100",
    "--json",
    "databaseId,headSha,workflowName,status,conclusion,attempt,createdAt,updatedAt,url",
  ]));
}

function readRunJobs(databaseId) {
  return JSON.parse(gh([
    "run",
    "view",
    String(databaseId),
    "--json",
    "jobs",
  ])).jobs;
}

export function selectHostedClosureEvidence({
  cells,
  checkedHead,
  runsByWorkflow,
  jobsByRun,
}) {
  requireCondition(SHA40.test(checkedHead ?? ""), "Hosted closure head is invalid.");
  const selected = [];
  for (const cell of cells) {
    const runs = runsByWorkflow.get(cell.workflow) ?? [];
    const exactRuns = runs.filter((run) => (
      run.workflowName === cell.workflow
      && run.headSha === checkedHead
    )).sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt));
    const independentById = new Map();
    for (const run of exactRuns) {
      if (!independentById.has(run.databaseId)) {
        independentById.set(run.databaseId, run);
      }
    }
    const independentRuns = [...independentById.values()];
    requireCondition(
      independentRuns.length >= 1,
      `Hosted workflow ${cell.workflow} has no run for ${checkedHead}.`,
    );
    requireCondition(
      independentRuns.length === 1,
      `Hosted workflow ${cell.workflow} exact-head run is ambiguous: `
        + `found ${independentRuns.length} independent runs for ${checkedHead}.`,
    );
    const run = independentRuns[0];
    requireCondition(
      run.status === "completed" && run.conclusion === "success" && run.attempt === 1,
      `The newest ${cell.workflow} run for ${checkedHead} is not first-attempt green.`,
    );
    const jobs = jobsByRun.get(run.databaseId) ?? [];
    const matches = jobs.filter((job) => (
      job.name === cell.job
      && job.status === "completed"
      && job.conclusion === "success"
    ));
    requireCondition(
      matches.length === 1,
      `Hosted job ${cell.workflow} / ${cell.job} is missing, duplicated, or not green.`,
    );
    const job = matches[0];
    requireCondition(
      Number.isFinite(Date.parse(job.startedAt))
        && Number.isFinite(Date.parse(job.completedAt))
        && Date.parse(job.completedAt) >= Date.parse(job.startedAt),
      `Hosted job ${cell.id} has invalid timestamps.`,
    );
    selected.push({
      cell,
      run: {
        databaseId: run.databaseId,
        headSha: run.headSha,
        workflowName: run.workflowName,
        attempt: run.attempt,
        status: run.status,
        conclusion: run.conclusion,
        createdAt: run.createdAt,
        updatedAt: run.updatedAt,
        url: run.url,
      },
      job: {
        databaseId: job.databaseId,
        name: job.name,
        status: job.status,
        conclusion: job.conclusion,
        startedAt: job.startedAt,
        completedAt: job.completedAt,
        url: job.url,
      },
    });
  }
  return selected;
}

export function buildHostedClosureReceipt({
  manifest,
  manifestSha256,
  checkedHead,
  candidateHead,
  candidateReceiptSha256,
  admissionSha256,
  selected,
}) {
  requireCondition(
    selected.length === manifest.hostedClosureCells.length,
    "Hosted closure selection is incomplete.",
  );
  const startedAt = selected
    .map(({ job }) => job.startedAt)
    .sort((left, right) => Date.parse(left) - Date.parse(right))[0];
  const finishedAt = selected
    .map(({ job }) => job.completedAt)
    .sort((left, right) => Date.parse(right) - Date.parse(left))[0];
  return {
    schemaVersion: manifest.gateId === "integrated-identity-access" ? 3 : 2,
    gateId: manifest.gateId,
    scope: "hosted-closure",
    checkedHead,
    candidateHead,
    candidateReceiptSha256,
    manifestSha256,
    ...(manifest.gateId === "integrated-identity-access"
      ? { admissionSha256 }
      : {}),
    status: "passed",
    startedAt,
    finishedAt,
    children: selected.map(({ cell, run, job }) => ({
      id: cell.id,
      executor: cell.executor,
      checkedHead,
      definitionSha256: integratedGateCellDefinitionSha256(cell),
      evidenceSha256: sha256(JSON.stringify(stableValue({ run, job }))),
      attempt: 1,
      status: "passed",
      startedAt: job.startedAt,
      finishedAt: job.completedAt,
    })),
  };
}

export function collectHostedClosureEvidence(manifest, checkedHead) {
  const workflows = [...new Set(manifest.hostedClosureCells.map(({ workflow }) => workflow))];
  const runsByWorkflow = new Map(
    workflows.map((workflow) => [workflow, listWorkflowRuns(workflow, checkedHead)]),
  );
  const runIds = new Set();
  for (const runs of runsByWorkflow.values()) {
    for (const run of runs) {
      if (
        run.headSha === checkedHead
        && run.status === "completed"
        && run.conclusion === "success"
        && run.attempt === 1
      ) {
        runIds.add(run.databaseId);
      }
    }
  }
  const jobsByRun = new Map([...runIds].map((runId) => [runId, readRunJobs(runId)]));
  return selectHostedClosureEvidence({
    cells: manifest.hostedClosureCells,
    checkedHead,
    runsByWorkflow,
    jobsByRun,
  });
}

export function writeHostedClosureReceipt({
  checkedHead,
  candidateAdmissionPath,
  output,
}) {
  assertExactCleanGitHead(checkedHead);
  const completedCandidate = validateCompletedIntegratedGateAttempt(
    candidateAdmissionPath,
  );
  const { manifest, manifestSha256 } = completedCandidate;
  const candidateHead = completedCandidate.admission.checkedHead;
  const candidateReceiptSha256 = sha256(completedCandidate.candidateReceiptBytes);
  const admissionSha256 = completedCandidate.candidateReceipt.admissionSha256 ?? null;
  const lineage = assertCandidateToHostedLineage(candidateHead, checkedHead);

  requireCondition(path.isAbsolute(output), "Hosted receipt path must be absolute.");
  requireOutsideRepository(path.resolve(output), "Hosted receipt");
  requireCondition(!existsSync(output), "Hosted receipt destination must be new.");
  const parent = path.dirname(output);
  requireCondition(
    existsSync(parent)
      && statSync(parent).isDirectory()
      && !lstatSync(parent).isSymbolicLink()
      && path.normalize(realpathSync.native(parent)).toLowerCase()
        === path.normalize(parent).toLowerCase(),
    "Hosted receipt parent must be an existing real directory.",
  );

  const selected = collectHostedClosureEvidence(manifest, checkedHead);
  assertExactCleanGitHead(checkedHead);
  const receipt = buildHostedClosureReceipt({
    manifest,
    manifestSha256,
    checkedHead,
    candidateHead,
    candidateReceiptSha256,
    admissionSha256,
    selected,
  });
  validateIntegratedGateReceipt({
    receipt,
    manifest,
    manifestSha256,
    expectedHead: checkedHead,
    expectedCandidateHead: candidateHead,
    expectedCandidateReceiptSha256: candidateReceiptSha256,
    expectedAdmissionSha256: admissionSha256,
    expectedScope: "hosted-closure",
  });
  writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
  return Object.freeze({
    checkedHead,
    candidateHead,
    candidateReceiptSha256,
    childCount: receipt.children.length,
    documentationOnlyDescendant: lineage.documentationOnly,
    manifestSha256,
    output,
  });
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

function runCli() {
  const values = parseArguments(process.argv.slice(2));
  const checkedHead = values.get("checked-head");
  const candidateAdmissionPath = values.get("candidate-admission");
  const output = values.get("output");
  requireCondition(checkedHead && candidateAdmissionPath && output,
    "--checked-head, --candidate-admission, and --output are required.");
  const result = writeHostedClosureReceipt({
    checkedHead,
    candidateAdmissionPath,
    output,
  });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    runCli();
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
