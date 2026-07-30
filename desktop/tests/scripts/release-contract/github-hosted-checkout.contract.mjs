import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmodSync,
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { readWorkflow, workflowSteps } from "./workflow-access.mjs";

const contractRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(contractRoot, "..", "..", "..", "..");
const initializerPath = path.join(
  repositoryRoot,
  "verification",
  "initialize-github-hosted-checkout-proof.ps1",
);
const guardPath = path.join(
  repositoryRoot,
  "verification",
  "verify-github-hosted-checkout.ps1",
);
const checkedHead = "a".repeat(40);
const localRunnerOs = process.platform === "win32" ? "Windows" : "Linux";
const powerShellCommand = process.platform === "win32" ? "pwsh.exe" : "pwsh";

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function resolveApplicationPath(commandName) {
  const result = spawnSync(
    powerShellCommand,
    [
      "-NoLogo",
      "-NoProfile",
      "-NonInteractive",
      "-Command",
      `(Get-Command '${commandName}' -CommandType Application | Select-Object -First 1).Source`,
    ],
    { encoding: "utf8", windowsHide: true },
  );
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const resolved = result.stdout.trim();
  assert.ok(path.isAbsolute(resolved), `${commandName} did not resolve absolutely`);
  return resolved;
}

const trustedPowerShell = resolveApplicationPath(powerShellCommand);
const trustedPowerShellSha256 = sha256(readFileSync(trustedPowerShell));
const trustedGit = resolveApplicationPath(
  process.platform === "win32" ? "git.exe" : "git",
);

function createFakeFixture(root) {
  const fakeRepository = path.join(root, "repository");
  const gitDirectory = path.join(fakeRepository, ".git");
  const trackedPath = "tracked.txt";
  const trackedFile = path.join(fakeRepository, trackedPath);
  const gitIndex = path.join(gitDirectory, "index");
  mkdirSync(gitDirectory, { recursive: true });
  writeFileSync(trackedFile, "initial tracked content\n");
  writeFileSync(gitIndex, "initial fake index\n");

  const fakeGit = path.join(root, "fake-git.ps1");
  writeFileSync(fakeGit, String.raw`param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $GitArguments
)

$CommandIndex = -1
for ($Index = 0; $Index -lt $GitArguments.Count; $Index++) {
    if (
        $GitArguments[$Index] -cin @(
            'ls-files',
            'ls-tree',
            'rev-parse',
            'status'
        )
    ) {
        $CommandIndex = $Index
        break
    }
}
if ($CommandIndex -lt 0) {
    exit 10
}
$Command = $GitArguments[$CommandIndex]
$HasRequiredFileMode = $false
for ($Index = 0; $Index + 1 -lt $GitArguments.Count; $Index++) {
    if (
        $GitArguments[$Index] -ceq '-c' -and
        $GitArguments[$Index + 1] -ceq 'core.fileMode=true'
    ) {
        $HasRequiredFileMode = $true
        break
    }
}
if (
    $env:FAKE_REQUIRE_FILE_MODE_TRUE -ceq '1' -and
    -not $HasRequiredFileMode
) {
    exit 12
}
$Tail = @(
    if ($CommandIndex + 1 -lt $GitArguments.Count) {
        $GitArguments[($CommandIndex + 1)..($GitArguments.Count - 1)]
    }
)

if ($Command -ceq 'rev-parse') {
    if ($Tail.Count -eq 1 -and $Tail[0] -ceq 'HEAD') {
        if ($env:FAKE_HEAD_EXIT) {
            exit [int] $env:FAKE_HEAD_EXIT
        }
        Write-Output $env:FAKE_HEAD
        exit 0
    }
    if ($Tail -contains '--show-toplevel') {
        Write-Output $env:FAKE_REPOSITORY_ROOT
        exit 0
    }
    if ($Tail -contains '--git-dir') {
        Write-Output (Join-Path $env:FAKE_REPOSITORY_ROOT '.git')
        exit 0
    }
}
if ($Command -ceq 'ls-tree') {
    $ObjectId = 'b' * 40
    Write-Output -NoEnumerate (
        "100644 blob $ObjectId" +
        [char] 9 +
        "$env:FAKE_TRACKED_PATH$([char] 0)"
    )
    exit 0
}
if ($Command -ceq 'ls-files') {
    $Tag = if ($env:FAKE_INDEX_TAG) {
        $env:FAKE_INDEX_TAG
    }
    else {
        'H'
    }
    Write-Output -NoEnumerate (
        "$Tag $env:FAKE_TRACKED_PATH$([char] 0)"
    )
    exit 0
}
if ($Command -ceq 'status') {
    if (
        $env:FAKE_REQUIRE_TRACKED_ONLY -ceq '1' -and
        $Tail -cnotcontains '--untracked-files=no'
    ) {
        exit 9
    }
    if ($env:FAKE_STATUS_EXIT) {
        exit [int] $env:FAKE_STATUS_EXIT
    }
    if ($env:FAKE_STATUS_OUTPUT) {
        Write-Output $env:FAKE_STATUS_OUTPUT
    }
    exit 0
}
exit 10
`);
  return {
    fakeGit,
    fakeRepository,
    gitIndex,
    trackedFile,
    trackedPath,
  };
}

function trackedManifestSha256(fixture) {
  const content = readFileSync(fixture.trackedFile);
  const record = Buffer.from(
    `100644\0${fixture.trackedPath}\0file\0${content.length}\0${sha256(content)}\n`,
    "utf8",
  );
  return sha256(record);
}

function proofForFixture(fixture) {
  return {
    gitIndexSha256: sha256(readFileSync(fixture.gitIndex)),
    trackedManifestSha256: trackedManifestSha256(fixture),
  };
}

function fakeEnvironment(fixture, runnerOs, overrides = {}) {
  return {
    ...process.env,
    GITHUB_ACTIONS: "true",
    RUNNER_OS: runnerOs,
    FAKE_HEAD: checkedHead,
    FAKE_REPOSITORY_ROOT: fixture.fakeRepository,
    FAKE_TRACKED_PATH: fixture.trackedPath,
    ...overrides,
  };
}

function spawnGuard({
  environment,
  expectedGitIndexSha256,
  expectedGitSha256,
  expectedHead,
  expectedTrackedManifestSha256,
  gitExecutable,
  repository,
  runnerEnvironment = "github-hosted",
  runnerOs = localRunnerOs,
  stage = "Initial",
}) {
  const args = [
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-File",
    guardPath,
    "-ExpectedHead",
    expectedHead,
    "-VerificationStage",
    stage,
    "-RunnerEnvironment",
    runnerEnvironment,
    "-ExpectedRunnerOs",
    runnerOs,
    "-GitExecutable",
    gitExecutable,
    "-ExpectedGitSha256",
    expectedGitSha256,
    "-RepositoryRoot",
    repository,
  ];
  if (stage === "Final") {
    args.push(
      "-ExpectedTrackedManifestSha256",
      expectedTrackedManifestSha256,
      "-ExpectedGitIndexSha256",
      expectedGitIndexSha256,
    );
  }
  return spawnSync(trustedPowerShell, args, {
    cwd: repository,
    encoding: "utf8",
    env: environment,
    windowsHide: true,
  });
}

function runGuard(
  fixture,
  {
    environment = {},
    expectedGitIndexSha256,
    expectedGitSha256 = sha256(readFileSync(fixture.fakeGit)),
    expectedTrackedManifestSha256,
    runnerEnvironment = "github-hosted",
    runnerOs = localRunnerOs,
    stage = "Initial",
  } = {},
) {
  const proof = proofForFixture(fixture);
  return spawnGuard({
    environment: fakeEnvironment(fixture, runnerOs, environment),
    expectedGitIndexSha256:
      expectedGitIndexSha256 ?? proof.gitIndexSha256,
    expectedGitSha256,
    expectedHead: checkedHead,
    expectedTrackedManifestSha256:
      expectedTrackedManifestSha256 ?? proof.trackedManifestSha256,
    gitExecutable: fixture.fakeGit,
    repository: fixture.fakeRepository,
    runnerEnvironment,
    runnerOs,
    stage,
  });
}

function readOutputFile(outputFile) {
  return Object.fromEntries(
    readFileSync(outputFile, "utf8")
      .trim()
      .split(/\r?\n/)
      .map((line) => {
        const separator = line.indexOf("=");
        assert.ok(separator > 0, `invalid hosted proof output: ${line}`);
        return [line.slice(0, separator), line.slice(separator + 1)];
      }),
  );
}

function readInitialGuardProof(stdout) {
  const lines = stdout.trim().split(/\r?\n/);
  const manifestLine = lines.find((line) => (
    line.startsWith("GITHUB_HOSTED_TRACKED_MANIFEST_SHA256=")
  ));
  const indexLine = lines.find((line) => (
    line.startsWith("GITHUB_HOSTED_GIT_INDEX_SHA256=")
  ));
  const checkoutLine = lines.find((line) => (
    line.startsWith("GITHUB_HOSTED_CHECKOUT=verified:")
  ));
  assert.equal(lines.length, 3, stdout);
  assert.ok(manifestLine, stdout);
  assert.ok(indexLine, stdout);
  assert.ok(checkoutLine, stdout);
  return {
    checkout: checkoutLine,
    gitIndexSha256: indexLine.slice(
      "GITHUB_HOSTED_GIT_INDEX_SHA256=".length,
    ),
    trackedManifestSha256: manifestLine.slice(
      "GITHUB_HOSTED_TRACKED_MANIFEST_SHA256=".length,
    ),
  };
}

function runRealGit(repository, args) {
  const result = spawnSync(trustedGit, ["-C", repository, ...args], {
    encoding: "utf8",
    windowsHide: true,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return result.stdout.trim();
}

test("hosted checkout guard declares its exact runtime and immutable state inputs", () => {
  const source = readFileSync(guardPath, "utf8");
  assert.match(source, /^#requires -Version 7\.4\r?$/im);
  assert.match(source, /^#requires -PSEdition Core\r?$/im);
  assert.match(source, /PSEdition -cne 'Core'/);
  assert.match(source, /PSVersion -lt \[version\] '7\.4'/);
  assert.match(source, /GITHUB_ACTIONS -cne 'true'/);
  assert.match(source, /RUNNER_OS -cne \$ExpectedRunnerOs/);
  assert.match(source, /RunnerEnvironment -cne 'github-hosted'/);
  assert.match(source, /ExpectedHead -cnotmatch '\^\[0-9a-f\]\{40\}\$'/);
  assert.match(source, /ExpectedGitSha256 -cnotmatch '\^\[0-9a-f\]\{64\}\$'/);
  assert.match(source, /\$env:GIT_OPTIONAL_LOCKS = '0'/);
  assert.match(source, /\$env:GIT_NO_REPLACE_OBJECTS = '1'/);
  assert.match(source, /core\.fileMode=true/);
  assert.match(source, /'ls-tree'/);
  assert.match(source, /IncrementalHash\]::CreateHash/);
  assert.match(source, /reviewed tracked ancestor is not one real directory/);
  assert.match(source, /'ls-files', '-v', '-z'/);
  assert.match(source, /hidden or noncanonical tracked state/);
  assert.match(source, /Git index changed after exact-head admission/);
  assert.match(source, /tracked content changed after exact-head admission/);
  assert.match(source, /selected Git executable changed after exact-head admission/);
});

test("hosted checkout proof captures deterministic process and repository identities", () => {
  const source = readFileSync(initializerPath, "utf8");
  assert.match(source, /^#requires -Version 7\.4\r?$/im);
  assert.match(source, /^#requires -PSEdition Core\r?$/im);
  assert.match(source, /PSEdition -cne 'Core'/);
  assert.match(source, /PSVersion -lt \[version\] '7\.4'/);
  assert.match(
    source,
    /Get-Command[\s\S]+-CommandType Application[\s\S]+Select-Object -First 1/,
  );
  assert.match(source, /\[Environment\]::ProcessPath/);
  assert.match(source, /\[ScriptBlock\]::Create\(\$GuardText\)/);
  for (const output of [
    "git_executable_base64",
    "git_sha256",
    "guard_sha256",
    "guard_source_base64",
    "powershell_executable_base64",
    "powershell_sha256",
    "repository_root_base64",
    "tracked_manifest_sha256",
    "git_index_sha256",
  ]) {
    assert.match(source, new RegExp(`${output}=`));
  }
});

test(
  "Windows custom shell survives the GitHub runner command split",
  { skip: process.platform !== "win32" },
  async () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-shell-"));
    try {
      const probeScript = path.join(root, "runner-generated-script");
      writeFileSync(probeScript, "exit 17\n");
      const ci = await readWorkflow(".github/workflows/ci.yml");
      const boundary = workflowSteps(ci, "frontend").steps.find(
        (step) => step.name === "Verify exact GitHub-hosted checkout",
      );
      assert.ok(boundary);
      const separator = boundary.shell.indexOf(" ");
      assert.ok(separator > 0);
      const shellCommand = boundary.shell.slice(0, separator);
      const shellArguments = boundary.shell
        .slice(separator + 1)
        .replace(
          "C:\\Program Files\\PowerShell\\7\\pwsh.exe",
          trustedPowerShell,
        )
        .replace("{0}", probeScript);
      const commandPrefix = "/d /s /c ";
      assert.equal(shellCommand, "C:\\Windows\\System32\\cmd.exe");
      assert.ok(shellArguments.startsWith(commandPrefix));
      const result = spawnSync(
        shellCommand,
        ["/d", "/s", "/c", shellArguments.slice(commandPrefix.length)],
        {
          encoding: "utf8",
          windowsHide: true,
          windowsVerbatimArguments: true,
        },
      );
      assert.equal(result.status, 17, result.stderr || result.stdout);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  },
);

test("hosted checkout proof selects the first Git when discovery returns duplicates", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-proof-"));
  try {
    const fixture = createFakeFixture(root);
    const missingSecondGit = path.join(root, "missing-second-git.ps1");
    const outputFile = path.join(root, "github-output.txt");
    const wrapperPath = path.join(root, "run-initializer.ps1");
    writeFileSync(wrapperPath, String.raw`$ErrorActionPreference = 'Stop'
function Get-Command {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string] $Name,
        [string] $CommandType
    )

    [pscustomobject]@{ Source = $env:FAKE_GIT_PRIMARY }
    [pscustomobject]@{ Source = $env:FAKE_GIT_SECONDARY }
}

$InitializerArguments = @{
    ExpectedHead                 = $env:FAKE_HEAD
    RunnerEnvironment            = 'github-hosted'
    ExpectedRunnerOs             = $env:RUNNER_OS
    GitCommandName               = $env:FAKE_GIT_COMMAND_NAME
    ExpectedPowerShellExecutable = $env:FAKE_POWERSHELL
    OutputFile                   = $env:YAP_HOSTED_PROOF_OUTPUT
}
& $env:YAP_HOSTED_PROOF_INITIALIZER @InitializerArguments
`);
    const result = spawnSync(
      trustedPowerShell,
      [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        wrapperPath,
      ],
      {
        cwd: fixture.fakeRepository,
        encoding: "utf8",
        env: {
          ...fakeEnvironment(fixture, localRunnerOs),
          GITHUB_WORKSPACE: fixture.fakeRepository,
          FAKE_GIT_COMMAND_NAME:
            process.platform === "win32" ? "git.exe" : "git",
          FAKE_GIT_PRIMARY: fixture.fakeGit,
          FAKE_GIT_SECONDARY: missingSecondGit,
          FAKE_POWERSHELL: trustedPowerShell,
          YAP_HOSTED_PROOF_INITIALIZER: initializerPath,
          YAP_HOSTED_PROOF_OUTPUT: outputFile,
        },
        windowsHide: true,
      },
    );
    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.equal(
      result.stdout.trim(),
      `GITHUB_HOSTED_CHECKOUT=verified:${localRunnerOs.toLowerCase()}:initial`,
    );

    const outputs = readOutputFile(outputFile);
    const guardBytes = readFileSync(guardPath);
    const expectedProof = proofForFixture(fixture);
    assert.equal(
      Buffer.from(outputs.git_executable_base64, "base64").toString("utf8"),
      path.resolve(fixture.fakeGit),
    );
    assert.equal(outputs.git_sha256, sha256(readFileSync(fixture.fakeGit)));
    assert.equal(outputs.guard_sha256, sha256(guardBytes));
    assert.deepEqual(
      Buffer.from(outputs.guard_source_base64, "base64"),
      guardBytes,
    );
    assert.equal(
      Buffer.from(outputs.powershell_executable_base64, "base64").toString(
        "utf8",
      ),
      trustedPowerShell,
    );
    assert.equal(outputs.powershell_sha256, trustedPowerShellSha256);
    assert.equal(
      Buffer.from(outputs.repository_root_base64, "base64").toString("utf8"),
      fixture.fakeRepository,
    );
    assert.equal(
      outputs.tracked_manifest_sha256,
      expectedProof.trackedManifestSha256,
    );
    assert.equal(outputs.git_index_sha256, expectedProof.gitIndexSha256);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("hosted checkout guard accepts an exact clean initial checkout", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-checkout-"));
  try {
    const fixture = createFakeFixture(root);
    const result = runGuard(fixture);
    assert.equal(result.status, 0, result.stderr || result.stdout);
    const proof = readInitialGuardProof(result.stdout);
    assert.equal(
      proof.checkout,
      `GITHUB_HOSTED_CHECKOUT=verified:${localRunnerOs.toLowerCase()}:initial`,
    );
    assert.deepEqual(
      {
        gitIndexSha256: proof.gitIndexSha256,
        trackedManifestSha256: proof.trackedManifestSha256,
      },
      proofForFixture(fixture),
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("hosted checkout guard fails closed when git status fails silently", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-checkout-"));
  try {
    const fixture = createFakeFixture(root);
    const result = runGuard(fixture, {
      environment: { FAKE_STATUS_EXIT: "7" },
    });
    assert.notEqual(result.status, 0);
    assert.match(
      result.stderr,
      /Git could not verify the disposable checkout state/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("hosted checkout guard rejects dirty tracked or untracked inputs", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-checkout-"));
  try {
    const fixture = createFakeFixture(root);
    const result = runGuard(fixture, {
      environment: { FAKE_STATUS_OUTPUT: " M tracked.txt" },
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /checkout is not clean/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("hosted checkout final guard accepts unchanged tracked state with generated outputs", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-checkout-"));
  try {
    const fixture = createFakeFixture(root);
    writeFileSync(path.join(fixture.fakeRepository, "generated.log"), "ignored\n");
    const result = runGuard(fixture, {
      stage: "Final",
      environment: { FAKE_REQUIRE_TRACKED_ONLY: "1" },
    });
    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.equal(
      result.stdout.trim(),
      `GITHUB_HOSTED_CHECKOUT=verified:${localRunnerOs.toLowerCase()}:final`,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("hosted checkout guard accepts the declared GitHub-hosted Linux runner", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-checkout-"));
  try {
    const fixture = createFakeFixture(root);
    const result = runGuard(fixture, {
      environment: { FAKE_REQUIRE_FILE_MODE_TRUE: "1" },
      runnerOs: "Linux",
    });
    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.equal(
      readInitialGuardProof(result.stdout).checkout,
      "GITHUB_HOSTED_CHECKOUT=verified:linux:initial",
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("hosted checkout guard rejects runner substitution before git", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-checkout-"));
  try {
    const fixture = createFakeFixture(root);
    const result = runGuard(fixture, {
      runnerEnvironment: "self-hosted",
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /requires a fresh GitHub-hosted/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("hosted checkout guard rejects a changed admitted Git executable", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-checkout-"));
  try {
    const fixture = createFakeFixture(root);
    const expectedGitSha256 = sha256(readFileSync(fixture.fakeGit));
    writeFileSync(
      fixture.fakeGit,
      `${readFileSync(fixture.fakeGit, "utf8")}\n# changed\n`,
    );
    const result = runGuard(fixture, { expectedGitSha256 });
    assert.notEqual(result.status, 0);
    assert.match(
      result.stderr,
      /selected Git executable changed after exact-head admission/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("hosted checkout final guard rejects assume-unchanged and skip-worktree tags", () => {
  for (const indexTag of ["h", "S"]) {
    const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-index-"));
    try {
      const fixture = createFakeFixture(root);
      const result = runGuard(fixture, {
        stage: "Final",
        environment: { FAKE_INDEX_TAG: indexTag },
      });
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, /hidden or noncanonical tracked state/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  }
});

test("hosted checkout final guard hashes tracked bytes independently of status", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-content-"));
  try {
    const fixture = createFakeFixture(root);
    const initialProof = proofForFixture(fixture);
    writeFileSync(fixture.trackedFile, "changed while fake status stays clean\n");
    const result = runGuard(fixture, {
      stage: "Final",
      expectedGitIndexSha256: initialProof.gitIndexSha256,
      expectedTrackedManifestSha256: initialProof.trackedManifestSha256,
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /tracked content changed after exact-head admission/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("real Git assume-unchanged cannot hide modified tracked content", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-real-git-index-"));
  try {
    runRealGit(root, ["init", "--quiet"]);
    writeFileSync(path.join(root, "tracked.txt"), "initial\n");
    runRealGit(root, ["add", "tracked.txt"]);
    runRealGit(root, [
      "-c",
      "user.name=Yap Contract",
      "-c",
      "user.email=yap-contract@example.invalid",
      "commit",
      "--quiet",
      "-m",
      "fixture",
    ]);
    const head = runRealGit(root, ["rev-parse", "HEAD"]);
    const gitSha256 = sha256(readFileSync(trustedGit));
    const initial = spawnGuard({
      environment: {
        ...process.env,
        GITHUB_ACTIONS: "true",
        RUNNER_OS: localRunnerOs,
      },
      expectedGitSha256: gitSha256,
      expectedHead: head,
      gitExecutable: trustedGit,
      repository: root,
      runnerOs: localRunnerOs,
      stage: "Initial",
    });
    assert.equal(initial.status, 0, initial.stderr || initial.stdout);
    const proof = readInitialGuardProof(initial.stdout);

    runRealGit(root, ["update-index", "--assume-unchanged", "tracked.txt"]);
    writeFileSync(path.join(root, "tracked.txt"), "modified but hidden\n");
    const final = spawnGuard({
      environment: {
        ...process.env,
        GITHUB_ACTIONS: "true",
        RUNNER_OS: localRunnerOs,
      },
      expectedGitIndexSha256: proof.gitIndexSha256,
      expectedGitSha256: gitSha256,
      expectedHead: head,
      expectedTrackedManifestSha256: proof.trackedManifestSha256,
      gitExecutable: trustedGit,
      repository: root,
      runnerOs: localRunnerOs,
      stage: "Final",
    });
    assert.notEqual(final.status, 0);
    assert.match(
      final.stderr,
      /hidden or noncanonical tracked state|Git index changed|tracked content changed/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test(
  "real Git executable-bit drift cannot hide behind repository configuration",
  { skip: process.platform !== "linux" },
  () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "yap-real-git-mode-"));
    try {
      runRealGit(root, ["init", "--quiet"]);
      const trackedFile = path.join(root, "tracked.sh");
      writeFileSync(trackedFile, "#!/bin/sh\nexit 0\n");
      chmodSync(trackedFile, 0o755);
      runRealGit(root, ["add", "tracked.sh"]);
      runRealGit(root, [
        "-c",
        "user.name=Yap Contract",
        "-c",
        "user.email=yap-contract@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
      ]);
      const head = runRealGit(root, ["rev-parse", "HEAD"]);
      const gitSha256 = sha256(readFileSync(trustedGit));
      const initial = spawnGuard({
        environment: {
          ...process.env,
          GITHUB_ACTIONS: "true",
          RUNNER_OS: "Linux",
        },
        expectedGitSha256: gitSha256,
        expectedHead: head,
        gitExecutable: trustedGit,
        repository: root,
        runnerOs: "Linux",
        stage: "Initial",
      });
      assert.equal(initial.status, 0, initial.stderr || initial.stdout);
      const proof = readInitialGuardProof(initial.stdout);

      runRealGit(root, ["config", "core.fileMode", "false"]);
      chmodSync(trackedFile, 0o644);
      assert.equal(runRealGit(root, ["status", "--porcelain"]), "");
      const final = spawnGuard({
        environment: {
          ...process.env,
          GITHUB_ACTIONS: "true",
          RUNNER_OS: "Linux",
        },
        expectedGitIndexSha256: proof.gitIndexSha256,
        expectedGitSha256: gitSha256,
        expectedHead: head,
        expectedTrackedManifestSha256: proof.trackedManifestSha256,
        gitExecutable: trustedGit,
        repository: root,
        runnerOs: "Linux",
        stage: "Final",
      });
      assert.notEqual(final.status, 0);
      assert.match(final.stderr, /checkout is not unchanged/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  },
);

test(
  "real Windows junction ancestors cannot redirect tracked content",
  { skip: process.platform !== "win32" },
  () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "yap-real-git-junction-"));
    try {
      const repository = path.join(root, "repository");
      const trackedDirectory = path.join(repository, "tracked-parent");
      const trackedFile = path.join(trackedDirectory, "tracked.txt");
      const externalDirectory = path.join(root, "external");
      mkdirSync(trackedDirectory, { recursive: true });
      runRealGit(repository, ["init", "--quiet"]);
      writeFileSync(trackedFile, "reviewed bytes\n");
      runRealGit(repository, ["add", "tracked-parent/tracked.txt"]);
      runRealGit(repository, [
        "-c",
        "user.name=Yap Contract",
        "-c",
        "user.email=yap-contract@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
      ]);
      const head = runRealGit(repository, ["rev-parse", "HEAD"]);
      const gitSha256 = sha256(readFileSync(trustedGit));
      const initial = spawnGuard({
        environment: {
          ...process.env,
          GITHUB_ACTIONS: "true",
          RUNNER_OS: "Windows",
        },
        expectedGitSha256: gitSha256,
        expectedHead: head,
        gitExecutable: trustedGit,
        repository,
        runnerOs: "Windows",
        stage: "Initial",
      });
      assert.equal(initial.status, 0, initial.stderr || initial.stdout);
      const proof = readInitialGuardProof(initial.stdout);

      mkdirSync(externalDirectory);
      writeFileSync(
        path.join(externalDirectory, "tracked.txt"),
        "reviewed bytes\n",
      );
      rmSync(trackedDirectory, { recursive: true, force: true });
      symlinkSync(externalDirectory, trackedDirectory, "junction");
      runRealGit(repository, ["config", "core.symlinks", "true"]);
      assert.equal(runRealGit(repository, ["status", "--porcelain"]), "");

      const final = spawnGuard({
        environment: {
          ...process.env,
          GITHUB_ACTIONS: "true",
          RUNNER_OS: "Windows",
        },
        expectedGitIndexSha256: proof.gitIndexSha256,
        expectedGitSha256: gitSha256,
        expectedHead: head,
        expectedTrackedManifestSha256: proof.trackedManifestSha256,
        gitExecutable: trustedGit,
        repository,
        runnerOs: "Windows",
        stage: "Final",
      });
      assert.notEqual(final.status, 0);
      assert.match(final.stderr, /tracked ancestor is not one real directory/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  },
);

test("final workflow proof resists mutable helper and post-project PATH substitution", async () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "yap-hosted-final-"));
  try {
    const fixture = createFakeFixture(root);
    const proof = proofForFixture(fixture);
    const mutableGuard = path.join(
      fixture.fakeRepository,
      "verification",
      "verify-github-hosted-checkout.ps1",
    );
    mkdirSync(path.dirname(mutableGuard), { recursive: true });
    writeFileSync(mutableGuard, "exit 0\n");

    const pathHijack = path.join(root, "path-hijack");
    mkdirSync(pathHijack);
    const fakeShell = path.join(
      pathHijack,
      process.platform === "win32" ? "pwsh.exe" : "pwsh",
    );
    if (process.platform === "win32") {
      copyFileSync(process.env.ComSpec, fakeShell);
    } else {
      writeFileSync(fakeShell, "#!/bin/sh\nexit 0\n");
      chmodSync(fakeShell, 0o755);
    }
    const substitutedEnvironment = {
      ...fakeEnvironment(fixture, "Windows"),
      PATH: `${pathHijack}${path.delimiter}${process.env.PATH}`,
      FAKE_REQUIRE_TRACKED_ONLY: "1",
    };
    const bareLookup = process.platform === "win32"
      ? spawnSync("where.exe", ["pwsh.exe"], {
          encoding: "utf8",
          env: substitutedEnvironment,
          windowsHide: true,
        })
      : spawnSync("/bin/sh", ["-c", "command -v pwsh"], {
          encoding: "utf8",
          env: substitutedEnvironment,
        });
    assert.equal(bareLookup.status, 0, bareLookup.stderr || bareLookup.stdout);
    assert.equal(
      path.resolve(bareLookup.stdout.trim().split(/\r?\n/)[0]),
      path.resolve(fakeShell),
    );

    const guardBytes = readFileSync(guardPath);
    const replacements = new Map([
      [
        "${{ steps.exact_head_checkout.outputs.guard_source_base64 }}",
        guardBytes.toString("base64"),
      ],
      [
        "${{ steps.exact_head_checkout.outputs.guard_sha256 }}",
        sha256(guardBytes),
      ],
      [
        "${{ steps.exact_head_checkout.outputs.git_executable_base64 }}",
        Buffer.from(path.resolve(fixture.fakeGit), "utf8").toString("base64"),
      ],
      [
        "${{ steps.exact_head_checkout.outputs.git_sha256 }}",
        sha256(readFileSync(fixture.fakeGit)),
      ],
      [
        "${{ steps.exact_head_checkout.outputs.powershell_executable_base64 }}",
        Buffer.from(trustedPowerShell, "utf8").toString("base64"),
      ],
      [
        "${{ steps.exact_head_checkout.outputs.powershell_sha256 }}",
        trustedPowerShellSha256,
      ],
      [
        "${{ steps.exact_head_checkout.outputs.repository_root_base64 }}",
        Buffer.from(fixture.fakeRepository, "utf8").toString("base64"),
      ],
      [
        "${{ steps.exact_head_checkout.outputs.tracked_manifest_sha256 }}",
        proof.trackedManifestSha256,
      ],
      [
        "${{ steps.exact_head_checkout.outputs.git_index_sha256 }}",
        proof.gitIndexSha256,
      ],
      ["${{ github.event.pull_request.head.sha || github.sha }}", checkedHead],
      ["${{ runner.environment }}", "github-hosted"],
    ]);
    const ci = await readWorkflow(".github/workflows/ci.yml");
    const finalStep = workflowSteps(ci, "frontend").steps.find(
      (step) => (
        step.name === "Verify exact GitHub-hosted checkout remained unchanged"
      ),
    );
    assert.ok(finalStep);
    let finalSource = finalStep.run;
    for (const [placeholder, value] of replacements) {
      finalSource = finalSource.split(placeholder).join(value);
    }
    const finalScript = path.join(root, "run-final-guard.ps1");
    writeFileSync(finalScript, finalSource);

    writeFileSync(
      fixture.trackedFile,
      "tracked content changed after initial proof\n",
    );
    const result = spawnSync(
      trustedPowerShell,
      [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        finalScript,
      ],
      {
        cwd: fixture.fakeRepository,
        encoding: "utf8",
        env: substitutedEnvironment,
        windowsHide: true,
      },
    );
    assert.notEqual(result.status, 0);
    assert.match(
      result.stderr,
      /tracked content changed after exact-head admission/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
