use serde::Serialize;
use std::{
    path::{Path, PathBuf},
    process::Command,
};

use crate::private_evidence::publish_private_json;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct LocalStreamDurationEvidence {
    pub(super) schema_version: u8,
    pub(super) checked_head: String,
    pub(super) plan_sha256: String,
    pub(super) suite_sha256: String,
    pub(super) qualification_profile: String,
    pub(super) model_artifact_lock_sha256: String,
    pub(super) model_id: &'static str,
    pub(super) primary_language_bcp47: &'static str,
    pub(super) inference_threads: i32,
    pub(super) logical_processor_budget: usize,
    pub(super) sample_rate_hz: u32,
    pub(super) paced_frame_samples: usize,
    pub(super) measurement_boundary: &'static str,
    pub(super) adapter_drain_target_ms: u128,
    pub(super) adapter_drain_timeout_ms: u128,
    pub(super) cases: Vec<LocalStreamDurationCaseEvidence>,
    pub(super) all_cases_passed: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct LocalStreamDurationCaseEvidence {
    pub(super) ladder_id: String,
    pub(super) case_id: String,
    pub(super) duration_samples: u64,
    pub(super) duration_ms: u64,
    pub(super) expected_frames: u64,
    pub(super) accepted_frames: u64,
    pub(super) dropped_frames: u64,
    pub(super) queue_high_water_mark: usize,
    pub(super) source_wall_ms: u128,
    pub(super) source_overrun_ms: u128,
    pub(super) adapter_status: &'static str,
    pub(super) adapter_drain_ms: u128,
    pub(super) adapter_drain_target_met: bool,
    pub(super) finalization_ms: u128,
    pub(super) processed_audio_samples: usize,
    pub(super) decode_chunks: usize,
    pub(super) decode_ms: u128,
    pub(super) worker_first_text_ms: Option<u128>,
    pub(super) capture_to_first_text_ms: Option<u128>,
    pub(super) partial_updates: u64,
    pub(super) final_updates: u64,
    pub(super) expected_text: bool,
    pub(super) text_seen: bool,
    pub(super) language_degraded: bool,
    pub(super) transcription_unavailable: bool,
    pub(super) stream_status: &'static str,
    pub(super) passed: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct LocalStreamDurationFailureEvidence {
    pub(super) schema_version: u8,
    pub(super) checked_head: String,
    pub(super) suite_sha256: String,
    pub(super) case_id: String,
    pub(super) duration_ms: u64,
    pub(super) adapter_status: &'static str,
    pub(super) stream_status: Option<&'static str>,
    pub(super) adapter_drain_ms: u128,
    pub(super) accepted_frames: u64,
    pub(super) dropped_frames: u64,
    pub(super) queue_high_water_mark: usize,
}

pub(super) fn required_checked_head(repository_root: &Path) -> String {
    let checked_head = required_string("YAP_CHECKED_HEAD");
    assert!(valid_checked_head(&checked_head));
    let actual_head = git_output(repository_root, &["rev-parse", "HEAD"]);
    let worktree_status = git_output(
        repository_root,
        &["status", "--porcelain=v1", "--untracked-files=normal"],
    );
    validate_repository_identity(&checked_head, &actual_head, &worktree_status)
        .unwrap_or_else(|error| panic!("{error}"));
    checked_head
}

pub(super) fn persist_private_evidence(evidence: &LocalStreamDurationEvidence) {
    let destination = PathBuf::from(required_string("YAP_TEST_LOCAL_DURATION_EVIDENCE"));
    publish_private_json(&destination, evidence)
        .unwrap_or_else(|error| panic!("failed to publish private duration evidence: {error}"));
}

pub(super) fn persist_private_failure(evidence: &LocalStreamDurationFailureEvidence) {
    let destination = PathBuf::from(required_string("YAP_TEST_LOCAL_DURATION_EVIDENCE"));
    let failure_destination = private_failure_destination(&destination);
    publish_private_json(&failure_destination, evidence)
        .unwrap_or_else(|error| panic!("failed to publish private duration failure: {error}"));
}

fn private_failure_destination(destination: &Path) -> PathBuf {
    let file_name = destination
        .file_name()
        .and_then(|name| name.to_str())
        .expect("private duration evidence file name must be UTF-8");
    destination.with_file_name(format!("{file_name}.failure.json"))
}

fn required_string(environment: &str) -> String {
    std::env::var(environment).unwrap_or_else(|_| panic!("{environment} is required"))
}

#[test]
fn checked_head_requires_one_full_lowercase_git_sha() {
    for invalid in ["", "../head", "a1b2c3", &"A".repeat(40)] {
        assert!(!valid_checked_head(invalid));
    }
    assert!(valid_checked_head(&"a".repeat(40)));
}

#[test]
fn repository_identity_requires_the_exact_clean_head() {
    let expected = "a".repeat(40);
    assert!(validate_repository_identity(&expected, &expected, "").is_ok());
    assert_eq!(
        validate_repository_identity(&expected, &"b".repeat(40), ""),
        Err("YAP_CHECKED_HEAD does not match the checked-out repository HEAD")
    );
    assert_eq!(
        validate_repository_identity(&expected, &expected, " M source.rs"),
        Err("local duration evidence requires a clean checked head")
    );
}

#[test]
fn duration_failure_uses_a_distinct_sibling_destination() {
    let destination = Path::new("C:/private/local-stream-short-boundaries.json");
    assert_eq!(
        private_failure_destination(destination),
        Path::new("C:/private/local-stream-short-boundaries.json.failure.json"),
    );
}

fn valid_checked_head(value: &str) -> bool {
    value.len() == 40
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn validate_repository_identity(
    expected_head: &str,
    actual_head: &str,
    worktree_status: &str,
) -> Result<(), &'static str> {
    if actual_head.trim() != expected_head {
        return Err("YAP_CHECKED_HEAD does not match the checked-out repository HEAD");
    }
    if !worktree_status.trim().is_empty() {
        return Err("local duration evidence requires a clean checked head");
    }
    Ok(())
}

fn git_output(repository_root: &Path, arguments: &[&str]) -> String {
    let output = Command::new("git")
        .arg("-C")
        .arg(repository_root)
        .args(arguments)
        .output()
        .expect("git must be available for local duration evidence");
    assert!(
        output.status.success(),
        "git failed while checking local duration evidence identity"
    );
    String::from_utf8(output.stdout)
        .expect("git output must be UTF-8")
        .trim_end()
        .to_owned()
}
