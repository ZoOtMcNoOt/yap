import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const policyRepoRoot = path.resolve(import.meta.dirname, "..", "..", "..", "..");

/// Only these actions may appear in a workflow. The exact revision is NOT
/// listed: it is read back from the workflows themselves, because a
/// hand-copied SHA here is a duplicate of a value only Dependabot changes,
/// and every bump desynchronized the two and broke CI. The controls that
/// matter — no floating tags, no unreviewed action — are asserted below.
const reviewedActionRepositories = Object.freeze({
  cacheRestore: "actions/cache/restore",
  cacheSave: "actions/cache/save",
  checkout: "actions/checkout",
  downloadArtifact: "actions/download-artifact",
  setupNode: "actions/setup-node",
  setupPnpm: "pnpm/action-setup",
  setupPython: "actions/setup-python",
  setupRust: "dtolnay/rust-toolchain",
  setupUv: "astral-sh/setup-uv",
  uploadArtifact: "actions/upload-artifact",
});

// Regex rather than a YAML parse: this module is imported by every contract
// test, and pulling a parser in at module load is what made the release
// contract unrunnable without desktop dependencies installed.
const USES = /^\s*-?\s*uses:\s*(\S+)[^\S\n]*(?:#.*)?$/gm;

function pinnedActionRevisions() {
  const observed = new Map();
  for (const workflowPath of [
    ".github/workflows/ci.yml",
    ".github/workflows/nsis-smoke.yml",
    ".github/workflows/release.yml",
  ]) {
    const source = readFileSync(path.join(policyRepoRoot, workflowPath), "utf8");
    for (const [, uses] of source.matchAll(USES)) {
      const separator = uses.lastIndexOf("@");
      assert.notEqual(separator, -1, `${uses} in ${workflowPath} is not pinned`);
      const repository = uses.slice(0, separator);
      const revision = uses.slice(separator + 1);
      assert.match(
        revision,
        /^[0-9a-f]{40}$/,
        `${uses} in ${workflowPath} must pin a full commit SHA, not a tag`,
      );
      assert.ok(
        Object.values(reviewedActionRepositories).includes(repository),
        `${repository} in ${workflowPath} is not a reviewed action`,
      );
      const previous = observed.get(repository);
      assert.ok(
        previous === undefined || previous === uses,
        `${repository} is pinned to two revisions across workflows`,
      );
      observed.set(repository, uses);
    }
  }
  return observed;
}

const observedActions = pinnedActionRevisions();

export const reviewedActions = Object.freeze(
  Object.fromEntries(
    Object.entries(reviewedActionRepositories).map(([name, repository]) => {
      const uses = observedActions.get(repository);
      assert.ok(uses, `${repository} is reviewed but used by no workflow`);
      return [name, uses];
    }),
  ),
);

export const reviewedActionUses = new Set(Object.values(reviewedActions));

export const workflowPaths = Object.freeze([
  ".github/workflows/ci.yml",
  ".github/workflows/nsis-smoke.yml",
  ".github/workflows/release.yml",
]);

export const exactCacheKeys = Object.freeze({
  cargo: "cargo-deps-v1-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('desktop/src-tauri/Cargo.lock') }}",
  playwright: "playwright-v1-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('desktop/pnpm-lock.yaml') }}",
  pnpm: "pnpm-store-v11-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('desktop/pnpm-lock.yaml') }}",
});

export const expectedCacheFamilies = Object.freeze({
  ".github/workflows/ci.yml": Object.freeze({
    frontend: Object.freeze(["playwright", "pnpm"]),
    "native-wdio": Object.freeze(["cargo", "pnpm"]),
    rust: Object.freeze(["cargo"]),
  }),
  ".github/workflows/nsis-smoke.yml": Object.freeze({
    "nsis-bundle-smoke": Object.freeze(["cargo", "pnpm"]),
  }),
  ".github/workflows/release.yml": Object.freeze({
    "build-nsis": Object.freeze(["cargo", "pnpm"]),
  }),
});

export const pnpmStoreBindingScriptPath = "desktop/tests/scripts/bind-pnpm-cache-store.ps1";

export const reviewedPnpmStoreBindingInvocation = String.raw`
& "$env:GITHUB_WORKSPACE\desktop\tests\scripts\bind-pnpm-cache-store.ps1"
`.trim();

export const reviewedPnpmStoreBindingScript = String.raw`
#requires -Version 7.4
#requires -PSEdition Core

$ErrorActionPreference = "Stop"
$localAppData = [Environment]::GetFolderPath(
  [Environment+SpecialFolder]::LocalApplicationData
)
$expectedStore = [IO.Path]::GetFullPath(
  (Join-Path $localAppData "pnpm\store\v11")
)
$cacheStore = [IO.Path]::GetFullPath(
  (Join-Path $HOME "AppData\Local\pnpm\store\v11")
)
if ($expectedStore -ine $cacheStore) {
  throw "The reviewed pnpm cache path does not match Windows LocalApplicationData."
}
$env:PNPM_CONFIG_STORE_DIR = $expectedStore
$actualStoreOutput = @(pnpm store path)
if ($LASTEXITCODE -ne 0 -or $actualStoreOutput.Count -ne 1) {
  throw "Failed to resolve the configured pnpm dependency store."
}
$actualStore = [IO.Path]::GetFullPath(([string]$actualStoreOutput[0]).Trim())
if ($actualStore -ine $expectedStore) {
  throw "pnpm did not accept the reviewed dependency store."
}
"PNPM_CONFIG_STORE_DIR=$expectedStore" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
`.trim();

export const releaseActionUses = new Set([
  reviewedActions.cacheRestore,
  reviewedActions.checkout,
  reviewedActions.downloadArtifact,
  reviewedActions.setupNode,
  reviewedActions.setupPnpm,
  reviewedActions.setupRust,
  reviewedActions.uploadArtifact,
]);
