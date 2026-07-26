import assert from "node:assert/strict";
import test from "node:test";

import { verifyShippedDependencyInventory } from "../shipped-dependency-inventory.mjs";
import { readRepoFile } from "./workflow-access.mjs";

test("desktop runtime dependencies are exhaustively mapped from exact lockfiles", async () => {
  const inventory = await verifyShippedDependencyInventory();
  const tauriConfig = JSON.parse(await readRepoFile("desktop/src-tauri/tauri.conf.json"));

  assert.ok(inventory.packages.javascript.length > 0);
  assert.ok(inventory.packages.rust.length > 0);
  assert.equal(
    tauriConfig.bundle.resources?.["../../SHIPPED_DEPENDENCY_INVENTORY.json"],
    "SHIPPED_DEPENDENCY_INVENTORY.json",
  );
});
