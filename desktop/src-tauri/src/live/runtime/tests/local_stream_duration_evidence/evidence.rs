use serde::Serialize;
use std::path::PathBuf;

use crate::private_evidence::publish_private_json;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct LocalStreamDurationEvidence {
    pub(super) schema_version: u8,
    pub(super) checked_head: String,
    pub(super) plan_sha256: String,
    pub(super) suite_sha256: String,
    pub(super) model_artifact_lock_sha256: String,
    pub(super) model_id: &'static str,
    pub(super) primary_language_bcp47: &'static str,
    pub(super) inference_threads: i32,
    pub(super) logical_processor_budget: usize,
    pub(super) sample_rate_hz: u32,
    pub(super) paced_frame_samples: usize,
    pub(super) measurement_boundary: &'static str,
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
    pub(super) adapter_drain_ms: u128,
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

pub(super) fn required_checked_head() -> String {
    let checked_head = required_string("YAP_CHECKED_HEAD");
    assert!(valid_checked_head(&checked_head));
    checked_head
}

pub(super) fn persist_private_evidence(evidence: &LocalStreamDurationEvidence) {
    let destination = PathBuf::from(required_string("YAP_TEST_LOCAL_DURATION_EVIDENCE"));
    publish_private_json(&destination, evidence)
        .unwrap_or_else(|error| panic!("failed to publish private duration evidence: {error}"));
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

fn valid_checked_head(value: &str) -> bool {
    value.len() == 40
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
