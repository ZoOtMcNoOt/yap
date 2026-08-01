// Documentation drifts in one repeatable way here: a phase merges, its branch
// is deleted, its plan completes — and prose keeps describing the old state.
// Closing Phase 7 meant hand-fixing ten documents that still called it an
// active branch, one of which claimed an unwired authorization layer was
// "enforced". These checks make that class of rot fail a gate instead of
// waiting for a reader to notice.
//
// Deliberately structural, not semantic: they assert that documents do not
// reference branches that no longer exist and that "current work" claims agree
// with the plan tree. Whether prose is *true* still needs a human; whether it
// names dead branches does not.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { repoRoot } from "./workflow-access.mjs";

const docsRoot = path.join(repoRoot, "docs");

function markdownFiles(root) {
  const files = [];
  for (const entry of readdirSync(root, { recursive: true })) {
    const relative = String(entry);
    if (relative.endsWith(".md")) files.push(path.join(root, relative));
  }
  return files;
}

function liveBranches() {
  const output = execFileSync(
    "git",
    ["for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes/origin"],
    { cwd: repoRoot, encoding: "utf8" },
  );
  return new Set(
    output
      .split("\n")
      .map((name) => name.replace(/^origin\//, ""))
      .filter(Boolean),
  );
}

// Historical records legitimately name branches that are gone; only documents
// that describe the present are held to present-tense truth.
const CURRENT_TRUTH_DOCUMENTS = [
  "docs/CURRENT-STATUS.md",
  "docs/README.md",
  "docs/roadmap/ROADMAP.md",
  "docs/ADR-IMPLEMENTATION-STATUS.md",
  "docs/architecture/CURRENT-ARCHITECTURE.md",
  "README.md",
];

test("current-truth documents do not describe work on deleted branches", () => {
  const branches = liveBranches();
  const pattern = /`(feat|fix|refactor|perf|docs|chore)\/[a-z0-9._/-]+`/g;
  const offenders = [];
  for (const relative of CURRENT_TRUTH_DOCUMENTS) {
    const text = readFileSync(path.join(repoRoot, relative), "utf8");
    for (const match of text.matchAll(pattern)) {
      const branch = match[0].slice(1, -1);
      // "Active on `<branch>`" style claims about branches that no longer
      // exist are exactly how Phase 7's docs rotted.
      const context = text.slice(Math.max(0, match.index - 80), match.index).toLowerCase();
      const claimsPresent = /active|current work|in flight|open on|now on/.test(context);
      if (claimsPresent && !branches.has(branch)) {
        offenders.push(`${relative}: ${branch}`);
      }
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `Documents describe active work on branches that do not exist:\n  ${offenders.join("\n  ")}`,
  );
});

test("plans in active/ are not claimed complete, and completed plans are not claimed active", () => {
  const offenders = [];
  for (const state of ["active", "completed"]) {
    const root = path.join(docsRoot, "plans", state);
    for (const file of markdownFiles(root)) {
      const text = readFileSync(file, "utf8");
      const statusLine = text.match(/^\*\*Status:\*\*\s*(.+)$/m)?.[1] ?? "";
      const relative = path.relative(repoRoot, file);
      if (state === "completed" && /^Active\b/i.test(statusLine)) {
        offenders.push(`${relative}: completed/ but Status says Active`);
      }
      if (state === "active" && /^Completed\b/i.test(statusLine)) {
        offenders.push(`${relative}: active/ but Status says Completed`);
      }
    }
  }
  assert.deepEqual(offenders, [], offenders.join("\n"));
});

test("every relative link in docs resolves", () => {
  const offenders = [];
  const linkPattern = /\]\((?!https?:|mailto:|#)([^)#\s]+)/g;
  for (const file of [...markdownFiles(docsRoot), path.join(repoRoot, "README.md")]) {
    // Fenced code blocks legitimately contain ](... shapes that are not links.
    const text = readFileSync(file, "utf8").replace(/```[\s\S]*?```/g, "");
    for (const match of text.matchAll(linkPattern)) {
      const target = path.resolve(path.dirname(file), decodeURI(match[1]));
      try {
        readdirSync(path.dirname(target));
        readFileSync(target);
      } catch (error) {
        if (error.code === "EISDIR") continue;
        offenders.push(`${path.relative(repoRoot, file)} -> ${match[1]}`);
      }
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `Broken relative links:\n  ${offenders.join("\n  ")}`,
  );
});
