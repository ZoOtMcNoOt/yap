use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    time::{Duration, UNIX_EPOCH},
};

use crate::audio::session::OwnerNamespace;

use super::{
    prepare_imported_client_preflight_with_cancellation, ImportedClientPreflightPreparation,
};

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct QualificationLock {
    schema_version: u16,
    preprocessing_owner: &'static str,
    vad_model_id: &'static str,
    vad_model_revision: &'static str,
    items: Vec<QualificationItem>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct QualificationItem {
    source_file: String,
    client_manifest_sha256: String,
    source_pcm_sha256: String,
    source_sample_count: u64,
    preprocessing_evidence: serde_json::Value,
}

#[test]
#[ignore = "requires a private natural-speech screen plus the pinned Silero artifact"]
fn natural_speech_screen_uses_the_production_client_preprocessing_path() {
    let source_root = required_absolute_directory("YAP_TEST_CLIENT_PREPROCESSING_AUDIO_ROOT");
    let lock_path = required_new_private_file("YAP_TEST_CLIENT_PREPROCESSING_LOCK", &source_root);
    let spool_root =
        required_new_private_directory("YAP_TEST_CLIENT_PREPROCESSING_SPOOL", &source_root);
    assert!(
        !spool_root.exists(),
        "client preprocessing spool must be an immutable new directory"
    );
    let expected_count = std::env::var("YAP_TEST_CLIENT_PREPROCESSING_COUNT")
        .expect("YAP_TEST_CLIENT_PREPROCESSING_COUNT is required")
        .parse::<usize>()
        .expect("YAP_TEST_CLIENT_PREPROCESSING_COUNT must be an integer");
    assert!((1..=64).contains(&expected_count));
    let mut sources = fs::read_dir(&source_root)
        .expect("private speech screen must be readable")
        .map(|entry| entry.expect("private speech entry must be readable").path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.ends_with(".speech.wav"))
        })
        .collect::<Vec<_>>();
    sources.sort();
    assert_eq!(sources.len(), expected_count);
    crate::stt::silero_vad::verify().expect("the pinned Silero artifact must verify");

    let owner = OwnerNamespace::local("i-natural-speech-qualification")
        .expect("qualification owner must be valid");
    let mut items = Vec::with_capacity(sources.len());
    for (index, path) in sources.iter().enumerate() {
        let source_file = path
            .file_name()
            .and_then(|name| name.to_str())
            .expect("speech filename must be Unicode")
            .to_owned();
        let job_id = format!("natural-speech-{index:02}");
        let mut source = File::open(path).expect("private speech WAV must open");
        let preflight = prepare_imported_client_preflight_with_cancellation(
            ImportedClientPreflightPreparation {
                job_id: &job_id,
                display_name: &source_file,
                source: &mut source,
                spool_root: &spool_root,
                owner_namespace: &owner,
                started_at: UNIX_EPOCH + Duration::from_secs(1_800_000_000 + index as u64),
                decoded_from: None,
            },
            || Ok(()),
        )
        .expect("production client preprocessing must complete");
        let (artifact, preprocessing) = preflight.into_ledger_state();
        assert!(artifact.manifest_path.starts_with(&spool_root));
        items.push(QualificationItem {
            source_file,
            client_manifest_sha256: artifact.manifest_sha256,
            source_pcm_sha256: artifact.source_pcm_sha256,
            source_sample_count: artifact.source_sample_count,
            preprocessing_evidence: serde_json::to_value(preprocessing)
                .expect("preprocessing evidence must serialize"),
        });
    }
    let lock = QualificationLock {
        schema_version: 1,
        preprocessing_owner: "desktop-imported-pcm16-preflight",
        vad_model_id: crate::stt::silero_vad::MODEL_ID,
        vad_model_revision: crate::stt::silero_vad::MODEL_REVISION,
        items,
    };
    let mut encoded = serde_json::to_vec(&lock).expect("qualification lock must encode");
    encoded.push(b'\n');
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&lock_path)
        .expect("qualification lock must be immutable");
    output
        .write_all(&encoded)
        .expect("qualification lock must be written");
    output
        .sync_all()
        .expect("qualification lock must be durable");
    let sha256 = Sha256::digest(&encoded)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    println!("client_preprocessing_items={expected_count} lock_sha256={sha256}");
}

fn required_absolute_directory(variable: &str) -> PathBuf {
    let path = PathBuf::from(std::env::var(variable).expect("private source root is required"));
    assert!(path.is_absolute(), "private source root must be absolute");
    let resolved = path
        .canonicalize()
        .expect("private source root must already exist");
    assert!(resolved.is_dir(), "private source root must be a directory");
    resolved
}

fn required_new_private_file(variable: &str, private_root: &Path) -> PathBuf {
    let path = PathBuf::from(std::env::var(variable).expect("private lock path is required"));
    assert!(path.is_absolute(), "private lock path must be absolute");
    let parent = path
        .parent()
        .expect("private lock path must have a parent")
        .canonicalize()
        .expect("private lock parent must already exist");
    assert_eq!(parent, private_root);
    let resolved = parent.join(
        path.file_name()
            .expect("private lock path must have a filename"),
    );
    assert!(!resolved.exists(), "private lock path must be new");
    resolved
}

fn required_new_private_directory(variable: &str, private_root: &Path) -> PathBuf {
    let path = PathBuf::from(std::env::var(variable).expect("private spool path is required"));
    assert!(path.is_absolute(), "private spool path must be absolute");
    let parent = path
        .parent()
        .expect("private spool path must have a parent")
        .canonicalize()
        .expect("private spool parent must already exist");
    assert_eq!(parent, private_root);
    let resolved = parent.join(
        path.file_name()
            .expect("private spool path must have a filename"),
    );
    assert!(!resolved.exists(), "private spool path must be new");
    resolved
}
