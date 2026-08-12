import assert from "node:assert/strict";
import { access } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { assertReviewedActionPins } from "./action-policy.mjs";
import {
  discoveredWorkflowPaths,
  normalizedRunBody,
  readRepoFile,
  readWorkflow,
  repoRoot,
  workflowSteps,
} from "./workflow-access.mjs";
import {
  exactCacheKeys,
  pnpmStoreBindingScriptPath,
  reviewedActions,
  workflowPaths,
} from "./workflow-policy.mjs";

function assertNoRunnerContextInJobEnvironment(value, location) {
  const text = String(value);
  if (text.includes("${{")) {
    assert.doesNotMatch(
      text,
      /\brunner\b/i,
      `${location} uses runner context before runner assignment`,
    );
  }
}

test("release contract has an explicit package command outside Vitest discovery", async () => {
  const packageJson = JSON.parse(await readRepoFile("desktop/package.json"));
  assert.equal(
    packageJson.scripts["test:release-contract"],
    "pnpm check:node && node --test ./tests/scripts/release-evidence.contract.mjs",
  );
  assert.doesNotMatch(packageJson.scripts["test:release-contract"], /\.test\.[cm]?[jt]s/);
  await assert.rejects(
    access(path.join(repoRoot, "desktop/tests/scripts/release-evidence.test.mjs")),
    /ENOENT/,
  );
});

test("required native WDIO executes every deterministic spec with Mocha runtime guards", async () => {
  const ci = await readWorkflow(".github/workflows/ci.yml");
  const { job, steps } = workflowSteps(ci, "native-wdio");
  const { config } = await import("../../wdio.required.conf.ts");
  const { config: hardwareConfig } = await import("../../wdio.hardware.conf.ts");

  assert.deepEqual(
    config.specs.map((spec) => path.basename(spec)),
    ["smoke.spec.js", "live-overlay.spec.js", "tray-actions.spec.js"],
  );
  assert.equal(config.bail, 1);
  assert.notEqual(config.logLevel, "trace");
  assert.equal(config.mochaOpts.forbidOnly, true);
  assert.equal(config.mochaOpts.forbidPending, true);
  assert.deepEqual(
    hardwareConfig.specs.map((spec) => path.basename(spec)),
    ["live-overlay.hardware.spec.js"],
  );
  assert.equal(hardwareConfig.mochaOpts.forbidOnly, true);
  assert.equal(job["runs-on"], "windows-latest");
  assert.equal(job.env.RUST_TARGET, "x86_64-pc-windows-msvc");
  assert.equal(
    job.env.YAP_CHECKED_HEAD,
    "${{ github.event.pull_request.head.sha || github.sha }}",
  );
  assert.equal(job.env.YAP_RUNNER_ENVIRONMENT, undefined);
  assert.ok(steps.some((step) => step.run === "pnpm test:desktop:build"));
  const runtimeStep = steps.find(
    (step) => step.name === "Run required hardware-independent WDIO specs",
  );
  assert.equal(
    runtimeStep?.env?.YAP_RUNNER_ENVIRONMENT,
    "${{ runner.environment }}",
  );
  assert.equal(runtimeStep?.["working-directory"], "${{ github.workspace }}");
  assert.equal(
    normalizedRunBody(runtimeStep?.run),
    "node ./verification/run-hosted-windows-runtime-check.mjs native-wdio",
  );
  const smokeSource = await readRepoFile("desktop/tests/wdio/smoke.spec.js");
  assert.match(smokeSource, /process\.env\.YAP_CHECKED_HEAD/);
  assert.match(smokeSource, /core\.invoke\("wdio_build_git_sha"\)/);
  assert.match(smokeSource, /\.toBe\(expectedBuildGitSha\)/);
  assert.ok(
    steps.some(
      (step) => step.uses === reviewedActions.uploadArtifact && step.if === "failure()",
    ),
    "native WDIO failure artifacts must use the reviewed upload-artifact v7.0.1 pin",
  );
  await assert.rejects(
    access(path.join(repoRoot, "desktop/tests/wdio/required-spec-policy.mjs")),
    /ENOENT/,
  );
});

test("CI and smoke workflows run the explicit release contract on supported triggers", async () => {
  const ci = await readWorkflow(".github/workflows/ci.yml");
  const smoke = await readWorkflow(".github/workflows/nsis-smoke.yml");
  const frontendSteps = workflowSteps(ci, "frontend").steps;
  const smokeSteps = workflowSteps(smoke, "nsis-bundle-smoke").steps;

  assert.ok(frontendSteps.some((step) => step.run === "pnpm test:release-contract"));
  assert.ok(smokeSteps.some((step) => step.run === "pnpm test:release-contract"));
  assert.equal(smoke.on.workflow_dispatch, null);
  assert.ok(smoke.on.schedule);
  assert.equal(smoke.on.release, undefined);
});

test("CI workflow token defaults to read-only repository contents", async () => {
  const ci = await readWorkflow(".github/workflows/ci.yml");
  assert.deepEqual(
    ci.permissions,
    { contents: "read" },
    "CI must declare only top-level contents: read permissions",
  );
});

test("every exact-head CI closure job verifies its own checked-out commit", async () => {
  const ci = await readWorkflow(".github/workflows/ci.yml");
  const gate = JSON.parse(
    await readRepoFile("verification/integrated-identity-access-gate.json"),
  );
  const expectedHead = "${{ github.event.pull_request.head.sha || github.sha }}";
  const windowsPowerShell = "C:\\Program Files\\PowerShell\\7\\pwsh.exe";
  const windowsShellHost = "C:\\Windows\\System32\\cmd.exe";
  const windowsShell = (
    `${windowsShellHost} /d /s /c ""${windowsPowerShell}" `
    + '-NoLogo -NoProfile -NonInteractive -Command - < "{0}""'
  );
  const windowsShellSeparator = windowsShell.indexOf(" ");
  assert.equal(windowsShell.slice(0, windowsShellSeparator), windowsShellHost);
  assert.equal(
    windowsShell.slice(windowsShellSeparator + 1),
    `/d /s /c ""${windowsPowerShell}" `
      + '-NoLogo -NoProfile -NonInteractive -Command - < "{0}""',
  );
  const linuxPowerShell = "/opt/microsoft/powershell/7/pwsh";
  const linuxShell = (
    `${linuxPowerShell} -NoLogo -NoProfile -NonInteractive -File {0}`
  );
  const jobContracts = [
    {
      closureJob: "frontend",
      gitCommandName: "git.exe",
      powerShellExecutable: windowsPowerShell,
      shell: windowsShell,
      expectedRunnerOs: "Windows",
      jobName: "frontend",
      runsOn: "windows-latest",
    },
    {
      closureJob: "rust",
      gitCommandName: "git.exe",
      powerShellExecutable: windowsPowerShell,
      shell: windowsShell,
      expectedRunnerOs: "Windows",
      jobName: "rust",
      runsOn: "windows-latest",
    },
    {
      closureJob: "Native WDIO smoke (required, no hardware)",
      gitCommandName: "git.exe",
      powerShellExecutable: windowsPowerShell,
      shell: windowsShell,
      expectedRunnerOs: "Windows",
      jobName: "native-wdio",
      runsOn: "windows-latest",
    },
    {
      closureJob: "server",
      gitCommandName: "git.exe",
      powerShellExecutable: windowsPowerShell,
      shell: windowsShell,
      expectedRunnerOs: "Windows",
      jobName: "server",
      runsOn: "windows-latest",
    },
    {
      closureJob: "mock-oidc",
      gitCommandName: "git",
      powerShellExecutable: linuxPowerShell,
      shell: linuxShell,
      expectedRunnerOs: "Linux",
      jobName: "mock-oidc",
      runsOn: "ubuntu-latest",
    },
  ];
  assert.deepEqual(
    gate.hostedClosureCells
      .filter((cell) => cell.workflow === "CI")
      .map((cell) => cell.job),
    jobContracts.map(({ closureJob }) => closureJob),
  );

  for (const contract of jobContracts) {
    const { job, steps } = workflowSteps(ci, contract.jobName);
    assert.equal(job["runs-on"], contract.runsOn);
    const checkout = steps.find(
      (step) => (
        typeof step.uses === "string"
          && step.uses.startsWith("actions/checkout@")
      ),
    );
    assert.equal(checkout?.with?.ref, expectedHead);
    assert.equal(checkout?.with?.["persist-credentials"], false);

    const initial = steps.find(
      (step) => step.name === "Verify exact GitHub-hosted checkout",
    );
    const final = steps.find(
      (step) => (
        step.name === "Verify exact GitHub-hosted checkout remained unchanged"
      ),
    );
    assert.ok(initial, `${contract.jobName} is missing its Initial checkout guard`);
    assert.equal(initial.id, "exact_head_checkout");
    assert.equal(initial.shell, contract.shell);
    assert.equal(initial["working-directory"], "${{ github.workspace }}");
    assert.match(
      initial.run,
      /\.\/verification\/initialize-github-hosted-checkout-proof\.ps1/,
    );
    assert.match(
      initial.run,
      new RegExp(`-ExpectedRunnerOs ${contract.expectedRunnerOs}`),
    );
    assert.match(
      initial.run,
      new RegExp(`-GitCommandName ${contract.gitCommandName}(?:\\s|$)`),
    );
    assert.ok(
      initial.run.includes(
        `-ExpectedPowerShellExecutable '${contract.powerShellExecutable}'`,
      ),
    );
    assert.match(
      initial.run,
      /-RunnerEnvironment '\$\{\{ runner\.environment \}\}'/,
    );
    assert.match(initial.run, /-OutputFile \$env:GITHUB_OUTPUT/);
    assert.ok(initial.run.includes(`-ExpectedHead '${expectedHead}'`));

    assert.ok(final, `${contract.jobName} is missing its Final checkout guard`);
    assert.equal(final.shell, contract.shell);
    assert.equal(final["working-directory"], "${{ github.workspace }}");
    assert.doesNotMatch(
      final.run,
      /\.\/verification\/(?:initialize|verify)-github-hosted-checkout/,
    );
    assert.doesNotMatch(final.run, /\bGet-Command\b/);
    assert.match(
      final.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.guard_source_base64 \}\}/,
    );
    assert.match(
      final.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.guard_sha256 \}\}/,
    );
    assert.match(
      final.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.git_executable_base64 \}\}/,
    );
    assert.match(
      final.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.git_sha256 \}\}/,
    );
    assert.match(
      final.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.powershell_executable_base64 \}\}/,
    );
    assert.match(
      final.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.powershell_sha256 \}\}/,
    );
    assert.match(
      final.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.repository_root_base64 \}\}/,
    );
    assert.match(
      final.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.tracked_manifest_sha256 \}\}/,
    );
    assert.match(
      final.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.git_index_sha256 \}\}/,
    );
    assert.match(final.run, /\[Environment\]::ProcessPath/);
    assert.match(final.run, /admitted PowerShell host changed/);
    assert.match(final.run, /\[ScriptBlock\]::Create/);
    assert.match(final.run, /-VerificationStage Final/);
    assert.match(
      final.run,
      new RegExp(`-ExpectedRunnerOs ${contract.expectedRunnerOs}`),
    );
    assert.match(
      final.run,
      /-RunnerEnvironment '\$\{\{ runner\.environment \}\}'/,
    );
    assert.ok(final.run.includes(`-ExpectedHead '${expectedHead}'`));
    assert.ok(steps.indexOf(checkout) < steps.indexOf(initial));
    assert.ok(steps.indexOf(initial) < steps.indexOf(final));
  }

  const mockOidcSteps = workflowSteps(ci, "mock-oidc").steps;
  const linuxModeRegression = mockOidcSteps.find(
    (step) => step.name === "Prove Linux executable-bit drift fails closed",
  );
  assert.equal(linuxModeRegression?.["working-directory"], "desktop");
  assert.equal(
    normalizedRunBody(linuxModeRegression?.run),
    "node --test "
      + '--test-name-pattern "real Git executable-bit drift" '
      + "tests/scripts/release-contract/github-hosted-checkout.contract.mjs",
  );
});

test("reviewed workflow inventory covers every workflow YAML file", async () => {
  assert.deepEqual(
    await discoveredWorkflowPaths(),
    [...workflowPaths].sort(),
    "every workflow file must be added to the reviewed action and cache policy inventory",
  );
});

test("runner context is evaluated only after a workflow job has a runner", async () => {
  for (const workflowPath of workflowPaths) {
    const workflow = await readWorkflow(workflowPath);
    for (const [jobName, job] of Object.entries(workflow.jobs ?? {})) {
      for (const [environmentName, value] of Object.entries(job.env ?? {})) {
        assertNoRunnerContextInJobEnvironment(
          value,
          `${workflowPath} ${jobName}.env.${environmentName}`,
        );
      }
    }
  }
});

test("job-level runner guard rejects direct, indexed, and nested references", () => {
  for (const value of [
    "${{ runner.environment }}",
    "${{ runner['environment'] }}",
    "${{ format('{0}', runner.environment) }}",
    "${{ format('{{{0}}}', runner.environment) }}",
    "${{ toJson(runner) }}",
  ]) {
    assert.throws(
      () => assertNoRunnerContextInJobEnvironment(value, "synthetic.env.VALUE"),
      /uses runner context before runner assignment/,
    );
  }
  assert.doesNotThrow(
    () => assertNoRunnerContextInJobEnvironment(
      "prefix-${{ github.sha }}",
      "synthetic.env.VALUE",
    ),
  );
});

test("all CI, smoke, and release actions use exact reviewed commit pins", async () => {
  for (const workflowPath of workflowPaths) {
    assertReviewedActionPins(await readWorkflow(workflowPath), workflowPath);
  }
});

test("server CI uses the reviewed exact uv environment and lock-bound cache", async () => {
  const ci = await readWorkflow(".github/workflows/ci.yml");
  const { steps } = workflowSteps(ci, "server");
  const setupUv = steps.find((step) => step.uses === reviewedActions.setupUv);
  const populateCache = steps.find(
    (step) => step.name === "Populate the exact server dependency cache",
  );

  assert.ok(setupUv, "server CI must use the reviewed setup-uv action revision");
  assert.deepEqual(setupUv.with, {
    version: "0.11.21",
    "enable-cache": true,
    "cache-dependency-glob": "server/uv.lock",
  });
  assert.ok(populateCache, "server CI must populate the exact dependency cache");
  assert.equal(populateCache["working-directory"], "server");
  assert.equal(
    normalizedRunBody(populateCache.run),
    "uv sync --locked --exact --extra evaluation --extra test --python (Get-Command python.exe).Source --no-python-downloads",
  );
});

test("server orchestrator CI owns the locked Linux lifecycle closure", async () => {
  const ci = await readWorkflow(".github/workflows/ci.yml");
  const { job, steps } = workflowSteps(ci, "server-orchestrator");
  const checkout = steps.find((step) => step.uses === reviewedActions.checkout);
  const setupRust = steps.find((step) => step.uses === reviewedActions.setupRust);
  const restore = steps.find((step) => step.uses === reviewedActions.cacheRestore);
  const initialGuard = steps.find(
    (step) => step.name === "Verify exact GitHub-hosted checkout",
  );
  const finalGuard = steps.find(
    (step) => step.name === "Verify exact GitHub-hosted checkout remained unchanged",
  );

  assert.equal(job.name, "Server orchestrator (Linux lifecycle)");
  assert.equal(job["runs-on"], "ubuntu-latest");
  assert.equal(job["timeout-minutes"], 15);
  assert.equal(job.defaults?.run?.shell, "pwsh");
  assert.deepEqual(checkout?.with, {
    "persist-credentials": false,
    ref: "${{ github.event.pull_request.head.sha || github.sha }}",
  });
  assert.deepEqual(setupRust?.with, {
    toolchain: "1.96.0",
    components: "clippy, rustfmt",
  });
  assert.equal(restore?.with?.key, exactCacheKeys.serverOrchestratorCargo);
  assert.match(initialGuard?.run ?? "", /-ExpectedRunnerOs Linux/);
  assert.match(finalGuard?.run ?? "", /-ExpectedRunnerOs Linux/);

  const exactCommands = new Map(
    steps
      .filter((step) => step.name && step.run)
      .map((step) => [step.name, normalizedRunBody(step.run)]),
  );
  assert.equal(
    exactCommands.get("Check server-orchestrator formatting"),
    "cargo fmt --all --check",
  );
  assert.equal(
    exactCommands.get("Lint every server-orchestrator target"),
    "cargo clippy --locked --all-targets --all-features -- -D warnings",
  );
  assert.equal(
    exactCommands.get("Run default server-orchestrator contracts"),
    "cargo test --locked",
  );
  assert.equal(
    exactCommands.get("Run Linux child lifecycle contracts"),
    "cargo test --locked --features test-fixture --test supervised_service -- --test-threads=1",
  );
  assert.equal(
    exactCommands.get("Verify service installer and systemd boundary contracts"),
    [
      "bash -n infra/yap-server-node/install-provider-supervisor-service.sh",
      "bash -n infra/yap-server-node/install-agent-admission-service.sh",
      "cd server",
      "PYTHONPATH=src python3 -m unittest \\",
      "  tests.agents.test_agent_admission_client \\",
      "  tests.infra.test_agent_admission_service \\",
      "  tests.infra.test_provider_supervisor_service",
    ].join("\n"),
  );
  assert.doesNotMatch(
    steps.map((step) => String(step.run ?? "")).join("\n"),
    /\bdocker\b/i,
  );
});

test("Rust connector CI populates a cold locked environment before contained runtimes", async () => {
  const ci = await readWorkflow(".github/workflows/ci.yml");
  const { job, steps } = workflowSteps(ci, "rust");
  const populateEnvironment = steps.find(
    (step) => (
      step.name === "Populate exact server dependencies for connector runtimes"
    ),
  );
  const serverConnector = steps.find(
    (step) => step.name === "Run exact server connector integration",
  );
  const authenticatedConnector = steps.find(
    (step) => step.name === "Run exact authenticated connector integration",
  );

  assert.equal(
    job.env.YAP_CHECKED_HEAD,
    "${{ github.event.pull_request.head.sha || github.sha }}",
  );
  assert.equal(job.env.YAP_RUNNER_ENVIRONMENT, undefined);
  assert.equal(
    serverConnector?.env?.YAP_RUNNER_ENVIRONMENT,
    "${{ runner.environment }}",
  );
  assert.equal(
    authenticatedConnector?.env?.YAP_RUNNER_ENVIRONMENT,
    "${{ runner.environment }}",
  );
  assert.ok(populateEnvironment);
  assert.equal(populateEnvironment["working-directory"], "server");
  assert.equal(
    normalizedRunBody(populateEnvironment.run),
    "uv sync --locked --exact --python (Get-Command python.exe).Source --no-python-downloads",
  );
  assert.equal(serverConnector["working-directory"], "${{ github.workspace }}");
  assert.equal(
    normalizedRunBody(serverConnector.run),
    "node ./verification/run-hosted-windows-runtime-check.mjs server-connector",
  );
  assert.equal(
    authenticatedConnector["working-directory"],
    "${{ github.workspace }}",
  );
  assert.equal(
    normalizedRunBody(authenticatedConnector.run),
    "node ./verification/run-hosted-windows-runtime-check.mjs authenticated-server-connector",
  );
  assert.ok(
    steps.indexOf(populateEnvironment) < steps.indexOf(serverConnector),
    "the online lock population must precede the connector's offline sync",
  );
  assert.ok(
    steps.indexOf(serverConnector) < steps.indexOf(authenticatedConnector),
    "connector runtime checks must remain independently observable",
  );
});

test("mock OIDC CI is the reviewed pinned Linux Docker closure", async () => {
  const ci = await readWorkflow(".github/workflows/ci.yml");
  const { job, steps } = workflowSteps(ci, "mock-oidc");
  const actionSteps = steps.filter((step) => step.uses);
  const setupNode = actionSteps.find(
    (step) => step.uses === reviewedActions.setupNode,
  );
  const setupPython = actionSteps.find(
    (step) => step.uses === reviewedActions.setupPython,
  );
  const setupUv = actionSteps.find((step) => step.uses === reviewedActions.setupUv);
  const populateEnvironment = steps.find(
    (step) => step.name === "Populate the exact mock OIDC dependency environment",
  );
  const runHarness = steps.find(
    (step) => step.name === "Run the pinned mock OIDC owner flow",
  );

  assert.equal(job.name, "mock-oidc");
  assert.equal(job["runs-on"], "ubuntu-latest");
  assert.equal(job["timeout-minutes"], 10);
  assert.equal(job.defaults?.run?.shell, "pwsh");
  assert.deepEqual(
    actionSteps.map((step) => step.uses),
    [
      reviewedActions.checkout,
      reviewedActions.setupNode,
      reviewedActions.setupPython,
      reviewedActions.setupUv,
    ],
    "mock OIDC CI may use only the existing reviewed setup actions",
  );
  assert.deepEqual(setupNode?.with, {
    "node-version-file": ".node-version",
    "package-manager-cache": false,
  });
  assert.deepEqual(setupPython?.with, { "python-version": "3.12" });
  assert.deepEqual(setupUv?.with, {
    version: "0.11.21",
    "enable-cache": true,
    "cache-dependency-glob": "server/uv.lock",
  });
  assert.ok(populateEnvironment);
  assert.equal(populateEnvironment["working-directory"], "server");
  assert.match(populateEnvironment.run, /uv --version/);
  assert.match(populateEnvironment.run, /3\.12/);
  assert.match(populateEnvironment.run, /uv sync --locked --exact/);
  assert.ok(runHarness);
  assert.equal(
    normalizedRunBody(runHarness.run),
    "./verification/test-mock-oidc-owner-flow.ps1",
  );
});

test("CI runs the exact fail-closed Windows dependency-boundary script", async () => {
  const ci = await readWorkflow(".github/workflows/ci.yml");
  const { steps: rustSteps } = workflowSteps(ci, "rust");
  const boundaryStep = rustSteps.find(
    (step) => step.name === "Verify exact Windows dependency boundary",
  );
  assert.ok(boundaryStep, "CI rust job must verify the target-specific glib boundary");
  assert.equal(
    normalizedRunBody(boundaryStep.run),
    "./verification/test-windows-rust-dependency-boundary.ps1",
    "the Windows graph guard must invoke the exact repository script",
  );
  assert.equal(boundaryStep["working-directory"], "${{ github.workspace }}");

  const source = await readRepoFile(
    "verification/test-windows-rust-dependency-boundary.ps1",
  );
  assert.match(source, /cargo tree/);
  assert.match(source, /--locked/);
  assert.match(source, /--offline/);
  assert.match(source, /--target x86_64-pc-windows-msvc/);
  assert.match(source, /\^glib v/);
  assert.match(source, /throw 'Unable to inspect the locked Windows dependency graph\.'/);
});

test("CI runs the exact checksum-verified RustSec audit script", async () => {
  const ci = await readWorkflow(".github/workflows/ci.yml");
  const { steps: rustSteps } = workflowSteps(ci, "rust");
  const allRunScripts = rustSteps.map((step) => String(step.run ?? "")).join("\n");
  const auditStep = rustSteps.find(
    (step) => step.name === "Audit exact Windows Rust dependencies",
  );

  assert.doesNotMatch(
    allRunScripts,
    /\bcargo(?:\.exe)?\s+install\b[^\r\n]*\bcargo-audit\b/i,
    "CI must not compile cargo-audit from source",
  );
  assert.ok(auditStep, "CI rust job must execute the reviewed cargo-audit script");
  assert.equal(
    normalizedRunBody(auditStep.run),
    "./verification/audit-windows-rust-dependencies.ps1",
    "the Rust dependency audit must invoke the exact repository script",
  );
  assert.equal(auditStep["working-directory"], "${{ github.workspace }}");

  const source = await readRepoFile(
    "verification/audit-windows-rust-dependencies.ps1",
  );
  assert.doesNotMatch(
    source,
    /\bcargo(?:\.exe)?\s+install\b[^\r\n]*\bcargo-audit\b/i,
    "the repository audit script must not compile cargo-audit from source",
  );
  assert.match(source, /\$Version = '0\.22\.2'/);
  assert.match(
    source,
    /\$ExpectedSha256 = '0a7316540862c13d954f648917ceacca593747baed6eec180fafa590be2710ab'/,
  );
  assert.match(source, /Get-FileHash -LiteralPath \$Archive -Algorithm SHA256/);
  assert.match(source, /audit --target-os windows --target-arch x86_64/);
  assert.match(source, /Remove-Item -LiteralPath \$WorkRoot -Recurse -Force/);
});
