use super::*;

#[test]
fn descriptor_pins_the_approved_silero_artifact() {
    assert_eq!(ARTIFACTS.len(), 1);
    assert_eq!(ARTIFACTS[0].file, "silero_vad.onnx");
    assert_eq!(ARTIFACTS[0].bytes, 643_854);
    assert_eq!(ARTIFACTS[0].sha256, ARTIFACT_SHA256);
    assert_eq!(ARTIFACT_SHA256.len(), 64);
    assert!(DOWNLOAD_URL.starts_with("https://github.com/k2-fsa/sherpa-onnx/releases/"));
}

#[test]
fn missing_and_malformed_artifacts_have_distinct_status() {
    let root = std::env::temp_dir().join(format!(
        "yap-silero-status-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let _ = std::fs::remove_dir_all(&root);
    let path = root.join("silero_vad.onnx");

    assert_eq!(status_at(&path).status, SileroVadStatus::Missing);
    std::fs::create_dir_all(&root).unwrap();
    std::fs::write(&path, b"not a model").unwrap();
    assert_eq!(status_at(&path).status, SileroVadStatus::Corrupted);

    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn canonical_model_path_is_content_addressed_under_the_models_root() {
    let path = model_path();
    assert!(path.ends_with("silero-vad/sha256-9e2449e1087496d8/silero_vad.onnx"));
}

#[test]
fn non_directory_model_root_is_corrupted() {
    let parent = std::env::temp_dir().join(format!(
        "yap-silero-file-root-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ));
    std::fs::create_dir_all(&parent).unwrap();
    let root = parent.join("installed-model");
    std::fs::write(&root, b"not a model directory").unwrap();
    let path = root.join(MODEL_FILE);

    assert_eq!(status_at(&path).status, SileroVadStatus::Corrupted);
    assert_eq!(resolve_model_at(&path), Err(SttError::ModelCorrupt));

    std::fs::remove_dir_all(parent).ok();
}

#[test]
fn removal_cleans_only_owned_interrupted_install_temps() {
    let root = std::env::temp_dir().join(format!(
        "yap-silero-remove-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let path = root.join(MODEL_FILE);
    std::fs::write(root.join("silero_vad.onnx.op-1-2-3-4.part"), b"partial").unwrap();

    assert_eq!(
        remove_at(&root, &path).unwrap().status,
        SileroVadStatus::Missing
    );
    assert!(!root.exists());
}

#[test]
fn removal_refuses_an_unrelated_file() {
    let root = std::env::temp_dir().join(format!(
        "yap-silero-remove-unrelated-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let path = root.join(MODEL_FILE);
    std::fs::write(root.join("keep.txt"), b"not owned by model removal").unwrap();

    assert!(matches!(
        remove_at(&root, &path),
        Err(SttError::ModelCorrupt)
    ));
    assert!(root.join("keep.txt").is_file());
    std::fs::remove_dir_all(root).unwrap();
}
