import assert from "node:assert/strict";
import test from "node:test";

import {
  cargoCommandEnvironment,
  verifyShippedDependencyInventory,
  verifyShippedDependencyNotices,
} from "../shipped-dependency-inventory.mjs";
import { readRepoFile } from "./workflow-access.mjs";

test("Cargo dependency inventory disables terminal color in machine-readable output", () => {
  assert.deepEqual(
    cargoCommandEnvironment({
      CARGO_TERM_COLOR: "always",
      PRESERVED_ENVIRONMENT_VALUE: "preserved",
    }),
    {
      CARGO_TERM_COLOR: "never",
      PRESERVED_ENVIRONMENT_VALUE: "preserved",
    },
  );
});

test("desktop runtime dependencies are exhaustively mapped from exact lockfiles", async () => {
  const inventory = await verifyShippedDependencyInventory();
  const notices = await verifyShippedDependencyNotices(inventory);
  const tauriConfig = JSON.parse(await readRepoFile("desktop/src-tauri/tauri.conf.json"));

  assert.ok(inventory.packages.javascript.length > 0);
  assert.ok(inventory.packages.rust.length > 0);
  assert.ok(inventory.packages.dotnet.length > 0);
  assert.ok(notices.documents.length > 0);
  for (const ecosystem of ["javascript", "rust", "dotnet"]) {
    assert.deepEqual(
      notices.packages[ecosystem].map(({ name, version }) => ({ name, version })),
      inventory.packages[ecosystem].map(({ name, version }) => ({ name, version })),
    );
    for (const packageRecord of inventory.packages[ecosystem]) {
      assert.ok(packageRecord.noticeDocuments.length > 0);
      assert.ok(
        packageRecord.noticeDocuments.every(({ sha256 }) =>
          notices.documents.some((document) => document.sha256 === sha256)),
      );
    }
  }
  assert.equal(
    tauriConfig.bundle.resources?.["../../SHIPPED_DEPENDENCY_INVENTORY.json"],
    "SHIPPED_DEPENDENCY_INVENTORY.json",
  );
  assert.equal(
    tauriConfig.bundle.resources?.["../../SHIPPED_DEPENDENCY_NOTICES.json"],
    "SHIPPED_DEPENDENCY_NOTICES.json",
  );
});
