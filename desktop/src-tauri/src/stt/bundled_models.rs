//! First-run import of installer-bundled models.
//!
//! The installer may carry the model artifacts under
//! `resources/bundled-models/`, staged at build time by
//! `desktop/tests/scripts/fetch-bundled-models.mjs` from the same pinned
//! URL/SHA-256/size triples the download path uses. At startup, any catalog
//! that is not already present under `models_dir()` is imported from the
//! resources by copy — through the same verification the network path runs, so
//! bundling changes where bytes come from and nothing about what is trusted.
//!
//! Import is all-or-nothing per catalog: a partial resource set (one file
//! missing or corrupt) imports nothing, leaving the ordinary
//! explicit-user-action download flow exactly as it was. A build without the
//! staging directory therefore behaves identically to today's builds.

use std::path::{Path, PathBuf};

use crate::stt::nemotron::Artifact;

pub(crate) struct BundledCatalog {
    /// Destination directory under `models_dir()`.
    pub(crate) model_dir: &'static str,
    pub(crate) artifacts: &'static [Artifact],
}

pub(crate) fn catalogs() -> [BundledCatalog; 2] {
    [
        BundledCatalog {
            model_dir: crate::stt::nemotron::BUNDLED_MODEL_DIR,
            artifacts: crate::stt::nemotron::BUNDLED_ARTIFACTS,
        },
        BundledCatalog {
            model_dir: crate::stt::silero_vad::BUNDLED_MODEL_DIR,
            artifacts: crate::stt::silero_vad::ARTIFACTS,
        },
    ]
}

/// Import every bundled catalog that is not already fully present. Failures
/// are reported, never fatal: the download path remains behind this.
pub(crate) fn import_all(resource_root: &Path, models_root: &Path) {
    for catalog in catalogs() {
        match import_catalog(resource_root, models_root, &catalog) {
            Ok(ImportOutcome::Imported) => crate::diagnostics::log(&format!(
                "bundled models: imported {} from installer resources",
                catalog.model_dir
            )),
            Ok(ImportOutcome::AlreadyPresent | ImportOutcome::NotBundled) => {}
            Err(error) => crate::diagnostics::log(&format!(
                "bundled models: {} import skipped: {error}",
                catalog.model_dir
            )),
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum ImportOutcome {
    Imported,
    AlreadyPresent,
    NotBundled,
}

pub(crate) fn import_catalog(
    resource_root: &Path,
    models_root: &Path,
    catalog: &BundledCatalog,
) -> Result<ImportOutcome, String> {
    let destination_dir = models_root.join(catalog.model_dir);
    let source_dir = resource_root.join("bundled-models").join(catalog.model_dir);

    if catalog
        .artifacts
        .iter()
        .all(|artifact| artifact_matches(&destination_dir.join(artifact.file), artifact))
    {
        return Ok(ImportOutcome::AlreadyPresent);
    }

    // All-or-nothing: verify the complete bundled set before placing anything,
    // so a partial or corrupt resource directory cannot leave a half catalog
    // that the status surfaces would report as a broken install.
    for artifact in catalog.artifacts {
        let source = source_dir.join(artifact.file);
        if !source.is_file() {
            return Ok(ImportOutcome::NotBundled);
        }
        if !artifact_matches(&source, artifact) {
            return Err(format!(
                "bundled {} failed hash or size verification",
                artifact.file
            ));
        }
    }

    std::fs::create_dir_all(&destination_dir)
        .map_err(|error| format!("could not create {}: {error}", destination_dir.display()))?;

    for artifact in catalog.artifacts {
        place_verified_copy(
            &source_dir.join(artifact.file),
            &destination_dir.join(artifact.file),
            artifact,
        )?;
    }
    Ok(ImportOutcome::Imported)
}

fn artifact_matches(path: &Path, artifact: &Artifact) -> bool {
    path.metadata()
        .is_ok_and(|meta| meta.len() == artifact.bytes)
        && crate::stt::model::verify_sha256(path, artifact.sha256).is_ok()
}

/// Copy through a temp name in the destination directory, verify the copy —
/// not the source — then rename into place. A crash mid-copy leaves a temp
/// file the existing stale-temp cleanup already handles, never a wrong model
/// at the real name.
fn place_verified_copy(
    source: &Path,
    destination: &Path,
    artifact: &Artifact,
) -> Result<(), String> {
    let temporary: PathBuf = destination.with_extension("bundled-import-temp");
    let _ = std::fs::remove_file(&temporary);
    std::fs::copy(source, &temporary)
        .map_err(|error| format!("copy of {} failed: {error}", artifact.file))?;

    let copied_matches = artifact_matches(&temporary, artifact);
    if !copied_matches {
        let _ = std::fs::remove_file(&temporary);
        return Err(format!("copied {} failed verification", artifact.file));
    }
    std::fs::rename(&temporary, destination)
        .map_err(|error| format!("rename of {} failed: {error}", artifact.file))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The repo idiom: std temp dir + process id, removed on drop. No
    /// tempfile dependency — a new crate would ripple into the shipped
    /// dependency inventory for a test convenience.
    struct TestDir(PathBuf);

    impl TestDir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir()
                .join(format!("yap-bundled-models-{label}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&path);
            std::fs::create_dir_all(&path).unwrap();
            Self(path)
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    // sha256 of the exact bytes below, so the tests exercise the real
    // verification rather than a stub of it.
    const PAYLOAD: &[u8] = b"bundled-model-test-payload";
    const PAYLOAD_SHA256: &str = "8c7967b898eb2b211e94993688c2d574fac25d38bfcd43d6916a3e39b7a1de03";

    fn test_artifacts() -> &'static [Artifact] {
        &[Artifact {
            file: "model.onnx",
            sha256: PAYLOAD_SHA256,
            bytes: 26,
        }]
    }

    fn catalog() -> BundledCatalog {
        BundledCatalog {
            model_dir: "test-model",
            artifacts: test_artifacts(),
        }
    }

    fn stage(resource_root: &Path, contents: &[u8]) {
        let dir = resource_root.join("bundled-models").join("test-model");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("model.onnx"), contents).unwrap();
    }

    #[test]
    fn a_bundled_catalog_lands_verified_and_a_rerun_is_a_no_op() {
        let resources = TestDir::new("res-import");
        let models = TestDir::new("dst-import");
        stage(resources.path(), PAYLOAD);

        let outcome = import_catalog(resources.path(), models.path(), &catalog()).unwrap();
        assert_eq!(outcome, ImportOutcome::Imported);
        let installed = models.path().join("test-model/model.onnx");
        assert_eq!(std::fs::read(&installed).unwrap(), PAYLOAD);

        let outcome = import_catalog(resources.path(), models.path(), &catalog()).unwrap();
        assert_eq!(outcome, ImportOutcome::AlreadyPresent);
    }

    #[test]
    fn an_unbundled_build_is_a_clean_no_op() {
        let resources = TestDir::new("res-empty");
        let models = TestDir::new("dst-empty");

        let outcome = import_catalog(resources.path(), models.path(), &catalog()).unwrap();
        assert_eq!(outcome, ImportOutcome::NotBundled);
        assert!(!models.path().join("test-model").exists());
    }

    #[test]
    fn a_corrupt_bundled_file_imports_nothing_and_says_so() {
        let resources = TestDir::new("res-corrupt");
        let models = TestDir::new("dst-corrupt");
        stage(resources.path(), b"the wrong bytes entirely!!");

        let error = import_catalog(resources.path(), models.path(), &catalog()).unwrap_err();
        assert!(error.contains("verification"), "{error}");
        assert!(!models.path().join("test-model/model.onnx").exists());
    }

    #[test]
    fn an_existing_verified_install_is_never_touched() {
        let resources = TestDir::new("res-existing");
        let models = TestDir::new("dst-existing");
        // Installed already, correct bytes; resources carry garbage. The
        // installed copy must win without the garbage ever being read into
        // place.
        let dir = models.path().join("test-model");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("model.onnx"), PAYLOAD).unwrap();
        stage(resources.path(), b"garbage that must not be read!");

        let outcome = import_catalog(resources.path(), models.path(), &catalog()).unwrap();
        assert_eq!(outcome, ImportOutcome::AlreadyPresent);
        assert_eq!(std::fs::read(dir.join("model.onnx")).unwrap(), PAYLOAD);
    }
}
