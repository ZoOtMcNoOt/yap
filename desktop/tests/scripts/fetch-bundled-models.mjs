// Stage the bundled model artifacts for a fat installer build.
//
// Downloads into desktop/src-tauri/resources/bundled-models/ — gitignored,
// because the tracked-blob-size contract exists precisely so these bytes never
// enter git. Each file is verified against the same SHA-256/size pins the
// client's own download path enforces (`stt/nemotron.rs`, `stt/silero_vad.rs`);
// the pins-agree release contract keeps this table and those tables identical.
//
// Idempotent: verified files are not re-downloaded, so a warm second run is
// free. Use with the bundling overlay:
//
//   node ./tests/scripts/fetch-bundled-models.mjs
//   pnpm tauri build --config src-tauri/tauri.bundled-models.conf.json

import { createHash } from "node:crypto";
import { createWriteStream } from "node:fs";
import { mkdir, readFile, rename, rm, stat } from "node:fs/promises";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const stagingRoot = path.resolve(
  scriptsDir, "..", "..", "src-tauri", "resources", "bundled-models",
);

const NEMOTRON_BASE =
  "https://huggingface.co/csukuangfj2/sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-1120ms-int8-2026-06-11/resolve/d2f58fb3c1ae44829133de74c1b5aa6e3e6dda04";

// Directory names mirror the client's models_dir() layout so the startup
// import is a straight copy.
const CATALOGS = [
  {
    dir: "nemotron-3.5-asr-streaming-0.6b-1120ms-int8",
    files: [
      { file: "encoder.int8.onnx", sha256: "2fff2166acaa535bd969fb223c1f0783d71029f143cb298bc54c2afe85abf772", bytes: 657_601_521 },
      { file: "decoder.int8.onnx", sha256: "19f9c98fc6d0a2c33a65a43b36fdb2e914c26c0aa9764be3aebc502a1e982fb0", bytes: 14_978_075 },
      { file: "joiner.int8.onnx", sha256: "4101c7c679a0bc30483794b27a059e34e79232aa2068d78d51231a22c8b0d7ce", bytes: 9_504_438 },
      { file: "tokens.txt", sha256: "729cc103155bafa785f9cd45746cd41cabe97eab7182fc04d594129587958f8a", bytes: 131_440 },
    ].map((entry) => ({ ...entry, url: `${NEMOTRON_BASE}/${entry.file}` })),
  },
  {
    dir: "silero-vad/sha256-9e2449e1087496d8",
    files: [
      {
        file: "silero_vad.onnx",
        sha256: "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6",
        bytes: 643_854,
        url: "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
      },
    ],
  },
];

async function fileMatches(target, entry) {
  try {
    const info = await stat(target);
    if (info.size !== entry.bytes) return false;
  } catch {
    return false;
  }
  const digest = createHash("sha256").update(await readFile(target)).digest("hex");
  return digest === entry.sha256;
}

async function fetchVerified(entry, target) {
  const temporary = `${target}.fetch-temp`;
  await rm(temporary, { force: true });
  const response = await fetch(entry.url, { redirect: "follow" });
  if (!response.ok || !response.body) {
    throw new Error(`${entry.file}: HTTP ${response.status}`);
  }
  await pipeline(Readable.fromWeb(response.body), createWriteStream(temporary, { flags: "wx" }));
  if (!(await fileMatches(temporary, entry))) {
    await rm(temporary, { force: true });
    throw new Error(`${entry.file}: downloaded bytes failed hash or size verification`);
  }
  await rename(temporary, target);
}

let staged = 0;
let reused = 0;
for (const catalog of CATALOGS) {
  const dir = path.join(stagingRoot, catalog.dir);
  await mkdir(dir, { recursive: true });
  for (const entry of catalog.files) {
    const target = path.join(dir, entry.file);
    if (await fileMatches(target, entry)) {
      reused += 1;
      continue;
    }
    process.stdout.write(`fetching ${entry.file} (${(entry.bytes / 1048576).toFixed(1)} MB)...\n`);
    await fetchVerified(entry, target);
    staged += 1;
  }
}
console.log(`bundled models staged: ${staged} fetched, ${reused} already verified, at ${stagingRoot}`);
