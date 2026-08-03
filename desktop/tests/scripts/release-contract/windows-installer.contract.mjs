import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { access } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { readRepoFile, readWorkflow, repoRoot } from "./workflow-access.mjs";

test("NSIS uses stock Tauri behavior inside a disposable Windows boundary", async () => {
  const config = JSON.parse(await readRepoFile("desktop/src-tauri/tauri.conf.json"));
  const paths = await readRepoFile("desktop/src-tauri/src/paths.rs");
  const migration = await readRepoFile("desktop/src-tauri/src/paths/legacy_migration.rs");
  const migrationPlatform = await readRepoFile(
    "desktop/src-tauri/src/paths/legacy_migration/platform.rs",
  );
  const migrationRecovery = await readRepoFile(
    "desktop/src-tauri/src/paths/legacy_migration/recovery.rs",
  );
  const migrationTree = await readRepoFile(
    "desktop/src-tauri/src/paths/legacy_migration/secure_tree.rs",
  );
  const app = await readRepoFile("desktop/src-tauri/src/app.rs");
  const smoke = await readRepoFile("desktop/tests/scripts/smoke-nsis.ps1");
  assert.equal(config.identifier, "com.mcnatg1.yap");
  assert.match(paths, new RegExp(`PRODUCTION_IDENTIFIER: &str = "${config.identifier}"`));
  assert.equal(config.bundle.windows?.nsis?.installerHooks, undefined);
  assert.equal(config.bundle.windows?.nsis?.installMode, "currentUser");
  assert.deepEqual(config.bundle.windows?.webviewInstallMode, {
    type: "offlineInstaller",
    silent: true,
  });
  assert.match(migration, /\.legacy-migration\.lock/);
  assert.match(migration, /MIGRATION_LOCK_TIMEOUT/);
  assert.match(migration, /try_lock\(\)/);
  assert.match(migration, /MIGRATION_COMPLETION_FILE/);
  assert.match(migrationRecovery, /recover_migration_residue/);
  assert.match(migrationTree, /copy_tree_verified/);
  assert.match(migrationTree, /output\.sync_all\(\)/);
  assert.match(migrationTree, /trees_equal/);
  assert.match(migrationPlatform, /rename_no_replace/);
  assert.doesNotMatch(migrationPlatform, /MOVEFILE_REPLACE_EXISTING/);
  assert.match(app, /MessageBoxW/);
  assert.match(app, /Yap-startup-migration-error/);
  assert.doesNotMatch(app, /bundled_models|installer-bundled models/);
  assert.doesNotMatch(JSON.stringify(config), /installerHooks|nsis-hooks\.nsh/);
  assert.doesNotMatch(JSON.stringify(config.bundle.resources ?? {}), /bundled-models/);
  assert.match(smoke, /GITHUB_ACTIONS/);
  assert.match(smoke, /RUNNER_ENVIRONMENT/);
  assert.match(smoke, /github-hosted/);
  assert.match(smoke, /YAP_DISPOSABLE_WINDOWS/);
  assert.match(smoke, /com\.mcnatg1\.yap/);
  assert.match(smoke, /ApplicationData/);
  assert.match(smoke, /LocalApplicationData/);
  assert.match(smoke, /expectedInstallLocation/);
  assert.match(smoke, /Start-Process/);
  assert.match(smoke, /WaitForExit/);
  assert.match(smoke, /Kill\(\$true\)/);
  assert.match(smoke, /function Wait-ForPathAbsence[\s\S]*?Start-Sleep -Milliseconds 100/);
  assert.match(smoke, /-LiteralPaths @\(\$uninstallRegistryPath, \$installLocation\)/);
  assert.match(smoke, /ExpectedInstallerSha256/);
  assert.match(smoke, /THIRD_PARTY_NOTICES\.md/);
  assert.match(smoke, /THIRD_PARTY_PROVENANCE\.json/);
  assert.match(smoke, /SHIPPED_DEPENDENCY_INVENTORY\.json/);
  assert.match(smoke, /SHIPPED_DEPENDENCY_NOTICES\.json/);
  assert.match(smoke, /stockSilentUninstallPreservedProductRegistry/);
  assert.match(smoke, /@\("\/S"\)/);
  assert.match(smoke, /preserved/i);
  assert.doesNotMatch(smoke, /DELETEAPPDATA|RMDir|Remove-Item|YAP_APP_DATA_DIR/);
  for (const retiredPath of [
    "desktop/src-tauri/nsis-hooks.nsh",
    "desktop/src-tauri/tauri.bundled-models.conf.json",
    "desktop/src-tauri/tauri.test.conf.json",
    "desktop/src-tauri/src/stt/bundled_models.rs",
    "desktop/tests/scripts/build-nsis-test.ps1",
    "desktop/tests/scripts/fetch-bundled-models.mjs",
    "desktop/tests/scripts/release-contract/bundled-model-pins.contract.mjs",
    "desktop/tests/scripts/nsis-smoke-helpers.psm1",
    "desktop/tests/scripts/nsis-smoke-helpers.test.ps1",
    "desktop/tests/scripts/smoke-nsis-local.ps1",
    "desktop/tests/scripts/smoke-nsis-production-delete.ps1",
    "desktop/tests/scripts/smoke-nsis-test-delete.ps1",
  ]) {
    await assert.rejects(access(path.join(repoRoot, retiredPath)), /ENOENT/);
  }
});

test("tracked PowerShell automation declares its reviewed runtime boundary", async () => {
  const powerShellFiles = execFileSync(
    "git",
    ["ls-files", "--", "*.ps1", "*.psm1"],
    { cwd: repoRoot, encoding: "utf8" },
  )
    .trim()
    .split(/\r?\n/)
    .filter(Boolean)
    .sort();
  assert.ok(
    powerShellFiles.length > 0,
    "PowerShell runtime contract requires at least one tracked script or module",
  );
  const coreRuntimeRequirement =
    /^#requires -Version 7\.4\r?\n#requires -PSEdition Core\b/i;
  const inboxRuntimeFiles = new Set([
    "verification/private-gate-artifacts.ps1",
    "verification/read-windows-build-tools-optional-diagnostics-settings.ps1",
  ]);
  assert.deepEqual(
    powerShellFiles.filter((relativePath) => inboxRuntimeFiles.has(relativePath)),
    [...inboxRuntimeFiles].sort(),
    "The reviewed inbox-runtime exception must stay explicit and exhaustive",
  );

  for (const relativePath of powerShellFiles) {
    const source = await readRepoFile(relativePath);
    if (inboxRuntimeFiles.has(relativePath)) {
      assert.match(
        source,
        /^#requires -Version 5\.1\b/i,
        `${relativePath} must remain compatible with its pinned inbox host`,
      );
      assert.doesNotMatch(
        source,
        /^#requires -PSEdition Core\b/im,
        `${relativePath} must not reject its pinned Desktop-edition host`,
      );
      continue;
    }
    assert.match(
      source,
      coreRuntimeRequirement,
      `${relativePath} must fail fast outside PowerShell Core 7.4 or newer`,
    );
  }

  const legacyWindowsPowerShell = ["power", "shell.exe"].join("");
  const runtimeSelectors = [
    "desktop/package.json",
    "desktop/tests/scripts/release-contract/windows-installer.contract.mjs",
    "desktop/tests/wdio/live-overlay.spec.js",
    "desktop/tests/wdio/live-overlay-window-fixture.js",
  ];
  for (const relativePath of runtimeSelectors) {
    const source = (await readRepoFile(relativePath)).toLowerCase();
    assert.equal(
      source.includes(legacyWindowsPowerShell),
      false,
      `${relativePath} still selects legacy Windows PowerShell`,
    );
  }
  const liveOverlayFixture = await readRepoFile(
    "desktop/tests/wdio/live-overlay-window-fixture.js",
  );
  assert.match(liveOverlayFixture, /execFileAsync\(\s*"pwsh\.exe"/);

  const packageJson = JSON.parse(await readRepoFile("desktop/package.json"));
  assert.match(packageJson.scripts["test:nsis:disposable"], /(?:^|\s)pwsh\.exe\s/i);

  for (const relativePath of [
    ".github/workflows/ci.yml",
    ".github/workflows/nsis-smoke.yml",
    ".github/workflows/release.yml",
  ]) {
    const workflow = await readWorkflow(relativePath);
    for (const [jobName, job] of Object.entries(workflow.jobs ?? {})) {
      const runsOn = String(job["runs-on"] ?? "");
      if (!runsOn.startsWith("windows-")) continue;

      assert.equal(
        job.defaults?.run?.shell,
        "pwsh",
        `${relativePath} ${jobName} must explicitly default run steps to PowerShell Core`,
      );
      const guard = job.steps?.find((step) => step.name === "Verify PowerShell 7.4 Core");
      assert.ok(
        guard,
        `${relativePath} ${jobName} must validate its isolated runner's PowerShell runtime`,
      );
      assert.equal(guard.shell, "pwsh");
      assert.equal(
        job.steps.find((step) => step.run),
        guard,
        `${relativePath} ${jobName} must validate PowerShell before any other run step`,
      );
      assert.match(guard.run, /\$PSVersionTable\.PSEdition\s+-cne\s+["']Core["']/);
      assert.match(guard.run, /\$PSVersionTable\.PSVersion\s+-lt\s+\[version\]["']7\.4["']/);
      assert.match(guard.run, /\bthrow\b/);
      assert.equal(
        job.steps.some((step) => /^powershell(?:\.exe)?$/i.test(String(step.shell ?? ""))),
        false,
        `${relativePath} ${jobName} overrides a run step back to legacy PowerShell`,
      );
    }
  }

  const ciWorkflow = await readWorkflow(".github/workflows/ci.yml");
  const expectedCheckedHeadExpression =
    "${{ github.event.pull_request.head.sha || github.sha }}";
  for (const jobName of ["rust", "native-wdio"]) {
    const job = ciWorkflow.jobs?.[jobName];
    assert.ok(job, `required ${jobName} CI job is missing`);
    assert.equal(job["runs-on"], "windows-latest");
    const checkout = job.steps.find((step) => (
      typeof step.uses === "string" && step.uses.startsWith("actions/checkout@")
    ));
    assert.equal(
      checkout?.with?.ref,
      expectedCheckedHeadExpression,
      `${jobName} must check out the exact reviewed head`,
    );
    assert.equal(
      checkout?.with?.["persist-credentials"],
      false,
      `${jobName} product runtime checks must not retain checkout credentials`,
    );
    assert.equal(
      job.env?.YAP_CHECKED_HEAD,
      expectedCheckedHeadExpression,
      `${jobName} must bind its build and runtime to the reviewed head`,
    );
    assert.equal(
      job.env?.YAP_RUNNER_ENVIRONMENT,
      undefined,
      `${jobName} must not evaluate runner context before runner assignment`,
    );
    const boundary = job.steps.find(
      (step) => step.name === "Verify exact GitHub-hosted checkout",
    );
    assert.ok(boundary, `${jobName} must verify its disposable runner boundary`);
    assert.equal(boundary.id, "exact_head_checkout");
    assert.equal(
      boundary.shell,
      "C:\\Windows\\System32\\cmd.exe /d /s /c "
        + '""C:\\Program Files\\PowerShell\\7\\pwsh.exe" '
        + '-NoLogo -NoProfile -NonInteractive -Command - < "{0}""',
    );
    assert.equal(boundary["working-directory"], "${{ github.workspace }}");
    assert.match(
      boundary.run,
      /\.\/verification\/initialize-github-hosted-checkout-proof\.ps1/,
    );
    assert.match(boundary.run, /-GitCommandName git\.exe/);
    assert.match(
      boundary.run,
      /-ExpectedPowerShellExecutable 'C:\\Program Files\\PowerShell\\7\\pwsh\.exe'/,
    );
    assert.match(boundary.run, /-OutputFile \$env:GITHUB_OUTPUT/);
    assert.match(boundary.run, /-RunnerEnvironment '\$\{\{ runner\.environment \}\}'/);
    assert.match(boundary.run, /-ExpectedRunnerOs Windows/);
    assert.ok(
      boundary.run.includes(`-ExpectedHead '${expectedCheckedHeadExpression}'`),
      `${jobName} initial guard must bind the exact reviewed head`,
    );

    const finalBoundary = job.steps.find(
      (step) => (
        step.name === "Verify exact GitHub-hosted checkout remained unchanged"
      ),
    );
    assert.ok(finalBoundary, `${jobName} must verify final tracked-source state`);
    assert.equal(
      finalBoundary.shell,
      "C:\\Windows\\System32\\cmd.exe /d /s /c "
        + '""C:\\Program Files\\PowerShell\\7\\pwsh.exe" '
        + '-NoLogo -NoProfile -NonInteractive -Command - < "{0}""',
    );
    assert.equal(finalBoundary["working-directory"], "${{ github.workspace }}");
    assert.doesNotMatch(
      finalBoundary.run,
      /\.\/verification\/(?:initialize|verify)-github-hosted-checkout/,
    );
    assert.doesNotMatch(finalBoundary.run, /\bGet-Command\b/);
    assert.match(
      finalBoundary.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.guard_source_base64 \}\}/,
    );
    assert.match(
      finalBoundary.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.git_executable_base64 \}\}/,
    );
    assert.match(
      finalBoundary.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.powershell_executable_base64 \}\}/,
    );
    assert.match(
      finalBoundary.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.tracked_manifest_sha256 \}\}/,
    );
    assert.match(
      finalBoundary.run,
      /\$\{\{ steps\.exact_head_checkout\.outputs\.git_index_sha256 \}\}/,
    );
    assert.match(finalBoundary.run, /\[Environment\]::ProcessPath/);
    assert.match(finalBoundary.run, /\[ScriptBlock\]::Create/);
    assert.match(finalBoundary.run, /-VerificationStage Final/);
    assert.match(
      finalBoundary.run,
      /-RunnerEnvironment '\$\{\{ runner\.environment \}\}'/,
    );
    assert.match(finalBoundary.run, /-ExpectedRunnerOs Windows/);
    assert.ok(
      finalBoundary.run.includes(`-ExpectedHead '${expectedCheckedHeadExpression}'`),
      `${jobName} final guard must bind the exact reviewed head`,
    );
    assert.ok(
      job.steps.indexOf(boundary) < job.steps.indexOf(finalBoundary),
      `${jobName} checkout guards must enclose native execution`,
    );
  }

  const rustSteps = ciWorkflow.jobs.rust.steps;
  const serverConnectorStep = rustSteps.find(
    (step) => step.name === "Run exact server connector integration",
  );
  assert.equal(
    serverConnectorStep?.run,
    "node ./verification/run-hosted-windows-runtime-check.mjs server-connector",
  );
  assert.equal(
    serverConnectorStep?.env?.YAP_RUNNER_ENVIRONMENT,
    "${{ runner.environment }}",
  );
  const authenticatedConnectorStep = rustSteps.find(
    (step) => step.name === "Run exact authenticated connector integration",
  );
  assert.equal(
    authenticatedConnectorStep?.run,
    "node ./verification/run-hosted-windows-runtime-check.mjs authenticated-server-connector",
  );
  assert.equal(
    authenticatedConnectorStep?.env?.YAP_RUNNER_ENVIRONMENT,
    "${{ runner.environment }}",
  );
  assert.equal(
    rustSteps.find(
      (step) => step.name === "Verify exact Windows dependency boundary",
    )?.run,
    "./verification/test-windows-rust-dependency-boundary.ps1",
  );
  assert.equal(
    rustSteps.find(
      (step) => step.name === "Audit exact Windows Rust dependencies",
    )?.run,
    "./verification/audit-windows-rust-dependencies.ps1",
  );
  const nativeWdioSteps = ciWorkflow.jobs["native-wdio"].steps;
  assert.equal(
    nativeWdioSteps.find(
      (step) => step.name === "Build the WDIO-enabled app once",
    )?.run,
    "pnpm test:desktop:build",
  );
  const requiredNativeWdioStep = nativeWdioSteps.find(
    (step) => step.name === "Run required hardware-independent WDIO specs",
  );
  assert.match(
    requiredNativeWdioStep?.run,
    /^node \.\/verification\/run-hosted-windows-runtime-check\.mjs native-wdio$/,
  );
  assert.equal(
    requiredNativeWdioStep?.env?.YAP_RUNNER_ENVIRONMENT,
    "${{ runner.environment }}",
  );

  const compatibilityJob = ciWorkflow.jobs?.frontend;
  assert.ok(compatibilityJob, "required frontend CI job is missing");
  assert.equal(compatibilityJob.env.POWERSHELL_74_VERSION, "7.4.17");
  assert.equal(compatibilityJob.env.POWERSHELL_TELEMETRY_OPTOUT, "1");
  assert.equal(
    compatibilityJob.env.POWERSHELL_74_SHA256,
    "266479A93B82CD0DC0F043419388FD4A738A51082821C301FFF497212FAF6760",
  );
  const installPowerShell = compatibilityJob.steps.find(
    (step) => step.name === "Install pinned PowerShell 7.4 runtime",
  );
  assert.match(installPowerShell.run, /PowerShell\/PowerShell\/releases\/download/);
  assert.match(installPowerShell.run, /Get-FileHash/);
  assert.match(installPowerShell.run, /POWERSHELL_74_SHA256/);
  assert.match(installPowerShell.run, /Expand-Archive/);
  assert.match(installPowerShell.run, /GITHUB_PATH/);
  const runCompatibilitySuite = compatibilityJob.steps.find(
    (step) => step.name === "Run focused suite under PowerShell 7.4",
  );
  assert.match(runCompatibilitySuite.run, /YAP_POWERSHELL_74/);
  assert.match(runCompatibilitySuite.run, /Language\.Parser/);
  assert.match(runCompatibilitySuite.run, /PSEdition -cne "Core"/);
  assert.match(runCompatibilitySuite.run, /PSVersion\.ToString\(\)/);
  assert.match(runCompatibilitySuite.run, /POWERSHELL_74_VERSION/);
  assert.doesNotMatch(runCompatibilitySuite.run, /nsis-smoke-helpers/);

  const smokeScriptPath = path
    .join(repoRoot, "desktop/tests/scripts/smoke-nsis.ps1")
    .replaceAll("'", "''");
  const legacyResult = spawnSync(
    legacyWindowsPowerShell,
    ["-NoProfile", "-NonInteractive", "-File", smokeScriptPath],
    { cwd: repoRoot, encoding: "utf8", timeout: 120_000 },
  );
  // The refusal is a property of the legacy host, so it can only be observed
  // where that host exists. Asserting `status !== 0` alone would pass on a
  // machine that lacks the legacy interpreter, where spawn never starts a
  // process and status is null, so an absent host would read as a proven
  // refusal. This test's own source may not name that interpreter literally,
  // which is why the executable is assembled from fragments above.
  if (legacyResult.error?.code === "ENOENT") {
    assert.equal(
      process.platform === "win32",
      false,
      "Windows hosts must provide legacy Windows PowerShell for this boundary",
    );
    return;
  }
  // A hosted runner is roughly ten times slower than the workstation, so the
  // budget here is for a cold interpreter under load, not for the refusal
  // itself, which is immediate: the script fails its `#requires` before doing
  // any work. A timeout still fails rather than passing quietly, because a
  // spawn that never completed proves nothing about the refusal.
  assert.equal(
    legacyResult.error,
    undefined,
    `legacy Windows PowerShell failed to launch: ${legacyResult.error?.message}`,
  );
  assert.notEqual(
    legacyResult.status,
    0,
    "legacy Windows PowerShell unexpectedly ran release automation",
  );
  assert.match(
    `${legacyResult.stdout}\n${legacyResult.stderr}`,
    /#requires[\s\S]*PowerShell 7\.4|PSEdition Core/i,
  );
});
