import assert from "node:assert/strict";
import test from "node:test";
import { cp, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import {
  verifyGlibBackportSelection,
  verifyGlibBackportSources,
} from "../../../../verification/verify-glib-backport.mjs";

import {
  cargoCommandEnvironment,
  verifyShippedDependencyInventory,
  verifyShippedDependencyNotices,
} from "../shipped-dependency-inventory.mjs";
import { readRepoFile } from "./workflow-access.mjs";

test("GLib backport rejects reverted, changed, missing and additional source", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "yap-glib-integrity-"));
  const source = path.resolve(import.meta.dirname, "../../../../desktop/src-tauri/vendor");
  const destination = path.join(root, "desktop/src-tauri/vendor");
  try {
    await cp(source, destination, { recursive: true });
    await verifyGlibBackportSources(root);
    const iterator = path.join(destination, "glib/src/variant_iter.rs");
    const original = await readFile(iterator, "utf8");
    await writeFile(iterator, original.replace("let mut p =", "let p =").replace("&mut p,", "&p,"));
    await assert.rejects(verifyGlibBackportSources(root), /hash mismatch/);
    await writeFile(iterator, original);
    const license = path.join(destination, "glib/LICENSE");
    const licenseBytes = await readFile(license);
    await writeFile(license, "changed license");
    await assert.rejects(verifyGlibBackportSources(root), /hash mismatch/);
    await rm(license);
    await assert.rejects(verifyGlibBackportSources(root), /file set differs/);
    await writeFile(license, licenseBytes);
    await writeFile(path.join(destination, "glib/unrecorded.rs"), "extra source");
    await assert.rejects(verifyGlibBackportSources(root), /hash mismatch/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("GLib selection rejects registry fallback and absent or different local sources", () => {
  const root = path.resolve(import.meta.dirname, "../../../..");
  const selected = {
    name: "glib", version: "0.18.5", source: null, id: "verified-glib",
    manifest_path: path.join(root, "desktop/src-tauri/vendor/glib/Cargo.toml"),
  };
  const metadata = (item, nodes = [{ id: selected.id }]) => ({ packages: [item], resolve: { nodes } });
  verifyGlibBackportSelection(metadata(selected), root);
  assert.throws(() => verifyGlibBackportSelection(metadata({ ...selected, source: "registry+https://github.com/rust-lang/crates.io-index" }), root), /unpatched registry/);
  assert.throws(() => verifyGlibBackportSelection(metadata({ ...selected, manifest_path: path.join(root, "other/Cargo.toml") }), root), /does not select/);
  assert.throws(() => verifyGlibBackportSelection(metadata(selected, []), root), /does not contain/);
});

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
  assert.ok(notices.documents.length > 0);
  for (const ecosystem of ["javascript", "rust"]) {
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

test("authenticated WebSocket dependencies stay exact, minimal, and notice-bound", async () => {
  const cargoManifest = await readRepoFile("desktop/src-tauri/Cargo.toml");
  assert.match(
    cargoManifest,
    /^reqwest-websocket = \{ version = "=0\.6\.0", default-features = false \}$/m,
  );
  assert.match(
    cargoManifest,
    /^futures-util = \{ version = "0\.3\.32", default-features = false, features = \["sink"\] \}$/m,
  );
  assert.match(
    cargoManifest,
    /^tungstenite = \{ version = "=0\.28\.0", default-features = false, features = \["handshake"\] \}$/m,
  );

  const inventory = await verifyShippedDependencyInventory();
  const expected = new Map([
    ["async-tungstenite", ["0.32.1", "MIT"]],
    ["data-encoding", ["2.11.0", "MIT"]],
    ["reqwest-websocket", ["0.6.0", "MIT"]],
    ["sha1", ["0.10.7", "MIT OR Apache-2.0"]],
    ["tungstenite", ["0.28.0", "MIT OR Apache-2.0"]],
  ]);
  for (const [name, [version, licenseExpression]] of expected) {
    const packageRecord = inventory.packages.rust.find(
      (candidate) => candidate.name === name,
    );
    assert.ok(packageRecord, `${name} is absent from the shipped Rust inventory.`);
    assert.equal(packageRecord.version, version);
    assert.equal(packageRecord.licenseExpression, licenseExpression);
    assert.ok(packageRecord.noticeDocuments.length > 0);
  }
});
