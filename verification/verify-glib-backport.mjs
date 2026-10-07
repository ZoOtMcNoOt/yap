import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(import.meta.dirname, "..");
const manifestSha256 = "007b66df6ff3109580b89e6357afe7be293754e38b0eba47bacdb340d1f8d6b6";
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");

// cargo-audit skips path packages. Bind all original archive bytes and the
// single repaired file independently of advisory matching or package version.
export async function verifyGlibBackportSources(repoRoot = repositoryRoot) {
  const manifestBytes = await readFile(path.join(repoRoot, "desktop/src-tauri/vendor/glib-backport.json"));
  assert.equal(hash(manifestBytes), manifestSha256, "GLib backport provenance manifest changed");
  const manifest = JSON.parse(manifestBytes);
  const directory = path.join(repoRoot, "desktop/src-tauri/vendor/glib");
  const expected = new Map(manifest.originalFiles.map(({ path: file, sha256 }) => [file, sha256]));
  expected.set(manifest.patch.path, manifest.patch.patchedSha256);
  const actual = [];
  async function walk(relative = "") {
    const base = path.join(directory, relative);
    assert.ok((await lstat(base)).isDirectory(), "GLib source directory is not a regular directory");
    for (const entry of await readdir(base, { withFileTypes: true })) {
      const file = relative ? `${relative}/${entry.name}` : entry.name;
      if (entry.isDirectory()) await walk(file);
      else {
        assert.ok(entry.isFile(), `GLib source is not a regular file: ${file}`);
        actual.push(file);
        assert.equal(hash(await readFile(path.join(directory, file))), expected.get(file), `GLib source hash mismatch: ${file}`);
      }
    }
  }
  await walk();
  assert.deepEqual(actual.sort(), [...expected.keys()].sort(), "GLib source file set differs from the original archive");
  return manifest;
}

export function verifyGlibBackportSelection(metadata, repoRoot = repositoryRoot) {
  const packages = metadata.packages.filter((item) => item.name === "glib" && item.version === "0.18.5");
  assert.equal(packages.length, 1, "GLib 0.18.5 must resolve to exactly one package");
  const selected = packages[0];
  assert.equal(selected.source, null, "GLib 0.18.5 reverted to an unpatched registry source");
  assert.equal(path.resolve(selected.manifest_path), path.join(repoRoot, "desktop/src-tauri/vendor/glib/Cargo.toml"), "GLib 0.18.5 does not select the verified backport");
  assert.ok(metadata.resolve.nodes.some((node) => node.id === selected.id), "The Linux graph does not contain the verified GLib backport");
}

export async function verifyGlibBackport(repoRoot = repositoryRoot) {
  await verifyGlibBackportSources(repoRoot);
  const metadata = JSON.parse(execFileSync(process.platform === "win32" ? "cargo.exe" : "cargo", [
    "metadata", "--locked", "--format-version", "1", "--filter-platform", "x86_64-unknown-linux-gnu",
    "--manifest-path", path.join(repoRoot, "desktop/src-tauri/Cargo.toml"),
  ], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024, env: { ...process.env, CARGO_TERM_COLOR: "never" } }));
  verifyGlibBackportSelection(metadata, repoRoot);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await verifyGlibBackport();
  console.log("GLib backport: all 121 source files and exact Linux graph selection verified.");
}
