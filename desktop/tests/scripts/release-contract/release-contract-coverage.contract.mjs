import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const contractDirectory = import.meta.dirname;
const scriptsDirectory = path.dirname(contractDirectory);
const aggregators = Object.freeze({
  hosted: "release-evidence.contract.mjs",
  local: "release-evidence-local.contract.mjs",
});

function importedContracts(aggregator) {
  const source = readFileSync(path.join(scriptsDirectory, aggregator), "utf8");
  return [...source.matchAll(/^import "\.\/release-contract\/(\S+?)";$/gm)]
    .map(([, name]) => name);
}

test("every release contract belongs to exactly one suite", () => {
  const present = readdirSync(contractDirectory)
    .filter((name) => name.endsWith(".contract.mjs"))
    .sort();
  const hosted = importedContracts(aggregators.hosted);
  const local = importedContracts(aggregators.local);
  const imported = [...hosted, ...local];

  const duplicated = imported.filter((name, index) => imported.indexOf(name) !== index);
  assert.deepEqual(duplicated, [], "a contract is imported by both suites");

  const missing = present.filter((name) => !imported.includes(name));
  assert.deepEqual(
    missing,
    [],
    "a contract runs in neither suite; add it to "
      + `${aggregators.hosted} if it only parses files, or `
      + `${aggregators.local} if it spawns processes or asserts on wall clock`,
  );

  const absent = imported.filter((name) => !present.includes(name));
  assert.deepEqual(absent, [], "a suite imports a contract that no longer exists");
});

test("the hosted suite stays free of process-spawning contracts", () => {
  // These five were measured at 275 s of the suite's 289 s on the workstation.
  // A hosted runner is roughly ten times slower, which is why they moved out.
  const measuredSlow = Object.freeze([
    "artifact.contract.mjs",
    "bounded-command-windows-job.contract.mjs",
    "github-hosted-checkout.contract.mjs",
    "hosted-windows-runtime-check.contract.mjs",
    "integrated-gate.contract.mjs",
  ]);
  const hosted = importedContracts(aggregators.hosted);
  const regressed = measuredSlow.filter((name) => hosted.includes(name));
  assert.deepEqual(regressed, [], "a measured-slow contract was added back to the hosted suite");
});
