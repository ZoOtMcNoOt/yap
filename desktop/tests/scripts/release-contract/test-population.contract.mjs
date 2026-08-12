// Two ways a suite stops testing without failing, both hit in one session.
//
// A `test.skip(condition, reason)` written at file scope skips every test in
// that file rather than the next one. Guarding a single browser-specific case
// that way silently disabled all eleven overlay tests, and the only signal was
// the runner printing "11 skipped" instead of "1".
//
// The second is duller and likelier: a spec file stops being discovered, or its
// tests are commented out, and the suite quietly shrinks. Nothing goes red.
//
// So this counts. A floor per file makes disappearance loud, and a scope check
// makes the file-level skip form impossible to reintroduce.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { repoRoot } from "./workflow-access.mjs";

const e2eRoot = path.join(repoRoot, "desktop", "tests", "e2e");

function specFiles() {
  return readdirSync(e2eRoot)
    .filter((name) => name.endsWith(".spec.ts"))
    .sort();
}

// Counted at any indentation, because app-queue declares its case inside a
// loop; a templated test is still a test that must not vanish.
// Floors, not exact counts: adding tests must never require touching this file,
// but losing them must fail. Raise a floor only alongside the tests that earn
// it.
const MINIMUM_TESTS_PER_SPEC = Object.freeze({
  "app-history.spec.ts": 2,
  "app-language-accessibility.spec.ts": 3,
  "app-queue.spec.ts": 1,
  "app-shortcuts.spec.ts": 1,
  "app.spec.ts": 6,
  "history-recoverable-actions.spec.ts": 1,
  "live-overlay.spec.ts": 13,
  "local-server-offer.spec.ts": 3,
  "playback-authorization.spec.ts": 4,
  "transcript-correction.spec.ts": 1,
});

test("every e2e spec file is still discovered", () => {
  assert.deepEqual(
    specFiles(),
    Object.keys(MINIMUM_TESTS_PER_SPEC),
    "An e2e spec appeared or vanished; update the floors deliberately.",
  );
});

test("no e2e spec has fewer tests than its floor", () => {
  const shortfalls = [];
  for (const [name, floor] of Object.entries(MINIMUM_TESTS_PER_SPEC)) {
    const source = readFileSync(path.join(e2eRoot, name), "utf8");
    const declared = source.match(/^\s*test\(/gm)?.length ?? 0;
    if (declared < floor) shortfalls.push(`${name}: ${declared} tests, floor ${floor}`);
  }
  assert.deepEqual(shortfalls, [], shortfalls.join("\n"));
});

// The specific form that bit: `test.skip(cond, reason)` as a statement rather
// than inside a test body. Playwright treats that as a file-level skip.
test("skips are scoped to a test rather than a whole spec file", () => {
  const offenders = [];
  for (const name of specFiles()) {
    const source = readFileSync(path.join(e2eRoot, name), "utf8");
    for (const [index, line] of source.split("\n").entries()) {
      // Inside a body it is indented; at file scope it starts the line.
      if (/^test\.skip\(/.test(line)) {
        offenders.push(`${name}:${index + 1} skips the entire file`);
      }
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `File-scope test.skip disables every test in the file:\n  ${offenders.join("\n  ")}`,
  );
});
