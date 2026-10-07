import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { MochaAdapter } from "@wdio/mocha-framework";

const adapterRequire = createRequire(import.meta.resolve("@wdio/mocha-framework"));
const mochaRequire = createRequire(adapterRequire.resolve("mocha"));

test("the adapter's Mocha preserves unified and inline assertion diffs", () => {
  const Base = mochaRequire("./lib/reporters/base.js");
  const previous = { inlineDiffs: Base.inlineDiffs, useColors: Base.useColors };
  try {
    Base.useColors = false;
    for (const inline of [false, true]) {
      Base.inlineDiffs = inline;
      const output = Base.generateDiff("before\n", "after\n");
      assert.doesNotMatch(output, /failed to generate Mocha diff/i);
      assert.match(output, /before/);
      assert.match(output, /after/);
      if (!inline) {
        assert.match(output, /-before/);
        assert.match(output, /\+after/);
      }
    }
  } finally {
    Object.assign(Base, previous);
  }
});

test("the adapter's diff parser terminates on hostile headers and retains patch roundtrips", () => {
  const script = `
    const assert = require('node:assert/strict');
    const diff = require(process.argv[1]);
    for (const header of ['--- a\\rb', '--- \\ra', '--- a\\u2028b']) {
      const patch = header + '\\n+++ b\\n@@ -1 +1 @@\\n-before\\n+after\\n';
      for (const operation of [() => diff.parsePatch(patch), () => diff.applyPatch('before\\n', patch)]) {
        try { operation(); } catch (error) { assert.ok(error instanceof Error); }
      }
    }
    const ordinary = diff.createPatch('fixture', 'before\\n', 'after\\n');
    assert.equal(diff.applyPatch('before\\n', ordinary), 'after\\n');
    process.stdout.write('completed');
  `;
  const output = execFileSync(process.execPath, ["-e", script, mochaRequire.resolve("diff")], {
    timeout: 2000,
    encoding: "utf8",
    maxBuffer: 4096,
  });
  assert.equal(output, "completed");
});

// Exercise the actual locked adapter after the security-driven Mocha upgrade.
// These are framework checks; they do not launch or qualify a desktop driver.
for (const withFailure of [false, true]) {
  test(`WDIO retains async hooks, retries, skips and ${withFailure ? "failure" : "success"} reporting`, async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "yap-wdio-framework-"));
    const spec = path.join(directory, "compatibility.mjs");
    const events = [];
    try {
      await writeFile(spec, `
        import assert from 'node:assert/strict';
        let ready=false; let beforeCount=0; let afterCount=0; let attempts=0;
        describe('locked adapter', () => {
          before(async()=>{ready=true});
          beforeEach(async()=>{beforeCount++});
          afterEach(async()=>{afterCount++});
          it('runs async tests after hooks', async()=>{await Promise.resolve(); assert.equal(ready,true)});
          it('retries', function(){this.retries(1); assert.equal(++attempts,2)});
          it.skip('retains skips',()=>{});
          ${withFailure ? "it('forwards assertion failure',()=>{assert.fail('expected framework fixture failure')});" : ""}
          after(()=>{assert.equal(beforeCount,${withFailure ? 4 : 3}); assert.equal(afterCount,${withFailure ? 4 : 3})});
        });
      `);
      const adapter = await new MochaAdapter("0-0", {
        rootDir: directory,
        mochaOpts: { ui: "bdd", timeout: 2000 },
        beforeSuite: [], afterSuite: [], beforeTest: [], afterTest: [],
        beforeHook: [], afterHook: [], after: [],
      }, [spec], {}, { emit: (event) => events.push(event) }).init();
      assert.equal(adapter.hasTests(), true);
      assert.equal(await adapter.run(), withFailure ? 1 : 0);
      assert.equal(events.filter(event => event === "test:pass").length, 2);
      assert.equal(events.filter(event => event === "test:pending").length, 1);
      assert.equal(events.filter(event => event === "test:retry").length, 1);
      assert.equal(events.filter(event => event === "test:fail").length, withFailure ? 1 : 0);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
}
