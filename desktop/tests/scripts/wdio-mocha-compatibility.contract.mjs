import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { MochaAdapter } from "@wdio/mocha-framework";

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
