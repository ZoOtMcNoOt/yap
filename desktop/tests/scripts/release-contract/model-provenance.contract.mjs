import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { readRepoFile } from "./workflow-access.mjs";

test("desktop model provenance pins the Silero bytes, lineage, runtime, and native archive", async () => {
  const lock = JSON.parse(await readRepoFile("desktop/model-artifacts.lock.json"));
  const artifact = lock.artifacts.find(({ id }) => id === "silero-vad-v4-k2-export");
  const source = await readRepoFile("desktop/src-tauri/src/stt/silero_vad.rs");
  const cargo = await readRepoFile("desktop/src-tauri/Cargo.toml");
  const notice = await readRepoFile("THIRD_PARTY_NOTICES.md");
  const tauri = JSON.parse(await readRepoFile("desktop/src-tauri/tauri.conf.json"));
  const apacheLicense = await readRepoFile(
    "server/runtime/asr/licenses/APACHE-2.0.txt",
  );

  assert.equal(lock.schemaVersion, 1);
  assert.ok(artifact);
  assert.equal(artifact.role, "client-advisory-vad");
  assert.equal(artifact.distribution.releaseAssetId, 271935959);
  assert.equal(artifact.distribution.sizeBytes, 643854);
  assert.equal(
    artifact.distribution.sha256,
    "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6",
  );
  assert.equal(artifact.distribution.bundled, false);
  assert.equal(artifact.distribution.installedOnlyByExplicitUserAction, true);
  assert.equal(
    artifact.lineage.model.revision,
    "915dd3d639b8333a52e001af095f87c5b7f1e0ac",
  );
  assert.equal(artifact.lineage.model.license, "MIT");
  assert.equal(
    artifact.lineage.exporter.revision,
    "8e51a975508fd69d3eed53d5098862201889fafd",
  );
  assert.equal(artifact.lineage.exporter.license, "Apache-2.0");
  assert.equal(artifact.runtime.version, "1.13.4");
  assert.equal(
    artifact.runtime.revision,
    "142807252687d81b40d6315f23470a1512a00de3",
  );
  assert.equal(artifact.runtime.nativeArchives.length, 1);
  assert.deepEqual(artifact.runtime.nativeArchives[0], {
    platform: "windows-x86_64",
    releaseAssetId: 469211798,
    fileName: "sherpa-onnx-v1.13.4-win-x64-static-MT-Release-lib.tar.bz2",
    source: "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.4/sherpa-onnx-v1.13.4-win-x64-static-MT-Release-lib.tar.bz2",
    sizeBytes: 119847445,
    sha256: "d81bd1d25112540862d2387072e76b2b6843ef962918d6b5c7db5a19c6276b4c",
  });

  assert.match(source, new RegExp(artifact.distribution.sha256));
  assert.match(source, new RegExp(String(artifact.distribution.sizeBytes).replace("643854", "643_854")));
  assert.match(source, /releases\/download\/asr-models\/silero_vad\.onnx/);
  assert.match(cargo, /^sherpa-onnx = "1\.13\.4"$/m);
  assert.match(notice, /^## Silero VAD v4 model$/m);
  assert.match(notice, /^## sherpa-onnx$/m);
  assert.match(notice, /Copyright \(c\) 2020-present Silero Team/);
  assert.match(notice, /Copyright \(c\) Microsoft Corporation/);
  assert.equal(
    tauri.bundle.resources?.["../model-artifacts.lock.json"],
    "model-artifacts.lock.json",
  );
  assert.equal(
    tauri.bundle.resources?.[
      "../../server/runtime/asr/licenses/APACHE-2.0.txt"
    ],
    "licenses/APACHE-2.0.txt",
  );
  assert.deepEqual(Object.keys(tauri.bundle.resources ?? {}).sort(), [
    "../../THIRD_PARTY_NOTICES.md",
    "../../THIRD_PARTY_PROVENANCE.json",
    "../../server/runtime/asr/licenses/APACHE-2.0.txt",
    "../model-artifacts.lock.json",
  ]);
  assert.equal(
    createHash("sha256").update(apacheLicense).digest("hex"),
    "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
  );
});

test("desktop model provenance pins the import-only AmberNet language detector and its open gaps", async () => {
  const lock = JSON.parse(await readRepoFile("desktop/model-artifacts.lock.json"));
  const artifact = lock.artifacts.find(
    ({ id }) => id === "ambernet-1.12.0-int8-qdq-acoustic-lid",
  );
  const source = await readRepoFile(
    "desktop/src-tauri/src/stt/ambernet_language_detector.rs",
  );
  const lifecycle = await readRepoFile(
    "desktop/src-tauri/src/stt/ambernet_language_detector/lifecycle.rs",
  );
  const cargo = await readRepoFile("desktop/src-tauri/Cargo.toml");
  const notice = await readRepoFile("THIRD_PARTY_NOTICES.md");
  const tauri = JSON.parse(await readRepoFile("desktop/src-tauri/tauri.conf.json"));

  assert.ok(artifact);
  assert.equal(artifact.role, "client-acoustic-language-identification");
  assert.equal(artifact.distribution.totalSizeBytes, 29613392);
  assert.equal(artifact.distribution.bundled, false);
  assert.equal(artifact.distribution.networkDownloadSupported, false);
  assert.equal(artifact.distribution.installedOnlyByExplicitUserAction, true);
  assert.equal(artifact.distribution.redistributionApproval, "not-approved");
  assert.deepEqual(
    artifact.distribution.files.map(({ fileName, sizeBytes, sha256 }) => ({
      fileName,
      sizeBytes,
      sha256,
    })),
    [
      {
        fileName: "ambernet-1.12.0-classifier-int8-qdq.onnx",
        sizeBytes: 29613392,
        sha256: "ef1006c7637803540e12ab01021e442382857689cbe0b1909d3128acf66a0a3e",
      },
    ],
  );
  assert.equal(artifact.lineage.model.revision, "1.12.0");
  assert.equal(artifact.lineage.model.sourceSizeBytes, 116049920);
  assert.equal(
    artifact.lineage.model.sourceSha256,
    "2f92d645b9ea5824d7663584fecb9ecc52557d0d700e24266747f38a61ba1681",
  );
  assert.equal(artifact.lineage.model.languageLabelCount, 107);
  assert.equal(artifact.lineage.model.termsOwnerApproval, false);
  assert.equal(artifact.lineage.conversion.onnxContract.opset, 17);
  assert.deepEqual(artifact.lineage.conversion.onnxContract.input.shape, [1, 80, 304]);
  assert.deepEqual(artifact.lineage.conversion.onnxContract.output.shape, [1, 107]);
  assert.equal(artifact.lineage.conversion.calibration.license, "CC-BY-4.0");
  assert.equal(
    artifact.lineage.conversion.calibration.exactManifestIdentitiesVerified,
    false,
  );
  assert.equal(artifact.lineage.conversion.environment.containerDigestVerified, false);
  assert.equal(artifact.runtime.inferenceCrateVersion, "2.0.0-rc.12");
  assert.equal(artifact.runtime.onnxRuntimeVersion, "1.27.0");
  assert.equal(artifact.runtime.fftCrateVersion, "3.5.0");
  assert.equal(artifact.runtime.intraOpThreads, 1);
  assert.equal(artifact.runtime.interOpThreads, 1);
  assert.equal(artifact.evaluationStatus, "selected-bounded-client-candidate");

  for (const file of artifact.distribution.files) {
    assert.match(source, new RegExp(file.sha256));
    assert.match(source, new RegExp(String(file.sizeBytes).replace(/(\d)(?=(\d{3})+$)/g, "$1_")));
  }
  assert.match(lifecycle, /import_verified_file/);
  assert.doesNotMatch(lifecycle, /download_to_verified/);
  assert.match(cargo, /^ort = .*2\.0\.0-rc\.12/m);
  assert.match(cargo, /^realfft = "=3\.5\.0"$/m);
  assert.match(notice, /^## NVIDIA AmberNet 1\.12\.0 language detector$/m);
  assert.match(notice, /No AmberNet\s+model bytes are bundled or hosted by Yap/);
  assert.deepEqual(Object.keys(tauri.bundle.resources ?? {}).sort(), [
    "../../THIRD_PARTY_NOTICES.md",
    "../../THIRD_PARTY_PROVENANCE.json",
    "../../server/runtime/asr/licenses/APACHE-2.0.txt",
    "../model-artifacts.lock.json",
  ]);
  assert.doesNotMatch(JSON.stringify(artifact), /yap-private-evaluation/i);
});

test("server Nemotron reference pins canonical model bytes, runtime, and OpenMDW terms", async () => {
  const lock = JSON.parse(await readRepoFile("server/nemotron-model-pool.lock.json"));
  const dockerfile = await readRepoFile("server/runtime/asr/Dockerfile");
  const notice = await readRepoFile("server/runtime/asr/THIRD_PARTY_NOTICES.md");
  const license = await readRepoFile(
    "server/runtime/asr/licenses/NEMOTRON_OPENMDW-1.1.txt",
  );

  assert.equal(lock.schemaVersion, 1);
  assert.equal(lock.runtime.pythonVersion, "3.12");
  assert.equal(lock.runtime.overlayPackages.transformers, "5.13.1");
  assert.equal(lock.pool.id, "nemotron-batch");
  assert.equal(lock.pool.engine, "transformers");
  assert.equal(lock.pool.model.id, "nvidia/nemotron-3.5-asr-streaming-0.6b");
  assert.equal(
    lock.pool.model.revision,
    "f3d333391852ba876df169dcc9ba902d25b6ab0b",
  );
  assert.equal(lock.pool.model.license, "OpenMDW-1.1");
  assert.equal(lock.pool.model.distribution.id, lock.pool.model.id);
  assert.equal(lock.pool.model.distribution.revision, lock.pool.model.revision);
  assert.equal(lock.pool.supportedLanguages.length, 33);
  assert.ok(lock.pool.supportedLanguages.includes("auto"));
  assert.ok(lock.pool.supportedLanguages.includes("en-US"));
  assert.ok(!lock.pool.supportedLanguages.includes("el-GR"));
  assert.equal(
    lock.pool.artifacts.find(({ path }) => path === "model.safetensors")?.sha256,
    "9eebdd6590289cb3030f310858f3df93256600a800a3e8200c5993d5f967e174",
  );
  assert.match(dockerfile, /COPY nemotron-model-pool\.lock\.json/);
  assert.match(dockerfile, /AutoModelForRNNT/);
  assert.match(notice, /nvidia\/nemotron-3\.5-asr-streaming-0\.6b/);
  assert.match(license, /^OpenMDW License Agreement, version 1\.1/m);
  assert.equal(
    createHash("sha256").update(license).digest("hex"),
    "30256aeeb89973968078f923ab5eb44c86ef0123df718499361614b55c0ed8ee",
  );
});
