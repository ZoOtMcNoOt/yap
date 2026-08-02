// The bundled-models fetch script and the client's download path each carry
// the artifact pins — the script stages what the installer bundles, the Rust
// tables verify what the client trusts. If they drift, the installer ships
// bytes the client re-downloads or, worse, refuses. Nothing structural forces
// them to agree, so this does.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { repoRoot } from "./workflow-access.mjs";

function pinsFrom(source) {
  const pins = [];
  const pattern =
    /file:\s*"([^"]+)",\s*sha256:\s*"([0-9a-f]{64})",\s*bytes:\s*([0-9_]+)/g;
  for (const match of source.matchAll(pattern)) {
    pins.push({
      file: match[1],
      sha256: match[2],
      bytes: Number(match[3].replaceAll("_", "")),
    });
  }
  return pins.sort((left, right) => left.file.localeCompare(right.file));
}

test("the fetch script's pins are the client's pins, byte for byte", () => {
  const script = readFileSync(
    path.join(repoRoot, "desktop/tests/scripts/fetch-bundled-models.mjs"),
    "utf8",
  );
  const nemotron = readFileSync(
    path.join(repoRoot, "desktop/src-tauri/src/stt/nemotron.rs"),
    "utf8",
  );
  const silero = readFileSync(
    path.join(repoRoot, "desktop/src-tauri/src/stt/silero_vad.rs"),
    "utf8",
  );

  // Nemotron's Rust table and the script's object literals share one shape and
  // parse with one pattern. Silero routes its pin through named consts, so its
  // three values are read from the declarations themselves.
  const sileroPins = [{
    file: silero.match(/const MODEL_FILE: &str = "([^"]+)"/)[1],
    sha256: silero.match(/pub const ARTIFACT_SHA256: &str =\s*"([0-9a-f]{64})"/)[1],
    bytes: Number(
      silero.match(/pub const ARTIFACT_BYTES: u64 = ([0-9_]+)/)[1].replaceAll("_", ""),
    ),
  }];
  const scriptPins = pinsFrom(script);
  const clientPins = [...pinsFrom(nemotron), ...sileroPins].sort(
    (left, right) => left.file.localeCompare(right.file),
  );

  assert.ok(scriptPins.length >= 5, `script pins missing: found ${scriptPins.length}`);
  assert.deepEqual(scriptPins, clientPins);

  // The staging URLs must be the pinned-revision forms, never a mutable ref.
  assert.match(script, /resolve\/d2f58fb3c1ae44829133de74c1b5aa6e3e6dda04/);
  assert.doesNotMatch(script, /resolve\/main/);
});
