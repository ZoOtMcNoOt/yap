// An 85 MB model-weight sidecar reached main inside a commit whose own message
// said "artifacts stay out of git" (#126, reverted in #127). The tree and the
// message disagreed and nothing was checking the tree: no gate owned tracked
// blob size, so a green run merged a mistake the repository will carry in
// history regardless.
//
// This contract owns that property now. The repository's largest legitimate
// blob is a 1.6 MB icon source; models, caches, and build outputs are recorded
// by hash in lock files and must never be tracked. The ceiling is deliberately
// far above everything legitimate and far below any model artifact.
//
// It lives in the hosted suite despite invoking git: the hosted exclusion list
// is a measured-slow blocklist (275 s of spawning contracts), not a spawn ban,
// and this is one bounded read-only invocation measured in tens of
// milliseconds.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

import { repoRoot } from "./workflow-access.mjs";

const MAX_TRACKED_BLOB_BYTES = 5 * 1024 * 1024;

test("no tracked blob exceeds the size a source repository can justify", () => {
  const listing = spawnSync(
    "git",
    ["ls-tree", "-r", "-l", "--full-tree", "HEAD"],
    { cwd: repoRoot, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  assert.equal(listing.status, 0, listing.stderr);

  const oversized = [];
  for (const line of listing.stdout.split("\n")) {
    if (!line) continue;
    // <mode> <type> <oid> <size>\t<path> — size is "-" for non-blobs.
    const [meta, path] = line.split("\t");
    const fields = meta.trim().split(/\s+/);
    const size = Number.parseInt(fields[3], 10);
    if (Number.isFinite(size) && size > MAX_TRACKED_BLOB_BYTES) {
      oversized.push(`${path} (${size} bytes)`);
    }
  }

  assert.deepEqual(
    oversized,
    [],
    "tracked blobs exceed the ceiling; large artifacts are recorded by hash "
      + `in lock files, not committed:\n  ${oversized.join("\n  ")}`,
  );
});
