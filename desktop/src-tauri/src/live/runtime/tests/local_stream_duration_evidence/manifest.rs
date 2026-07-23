use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

use super::SAMPLE_RATE_HZ;

const MAXIMUM_SUITE_BYTES: usize = 64 * 1_024;
const MAXIMUM_TRACK_MANIFEST_BYTES: usize = 4 * 1_024 * 1_024;
const MAXIMUM_TRACK_SEGMENTS: usize = 4_096;
const SHORT_BOUNDARIES: &str = "short-boundaries";
const COMPLETE_LOCAL_DURATION_LADDERS: &str = "complete-local-duration-ladders";

pub(super) struct LoadedLocalDurationSuite {
    pub(super) definition: LocalDurationSuite,
    pub(super) root: PathBuf,
    pub(super) plan_sha256: String,
    pub(super) suite_sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct LocalDurationSuite {
    schema_version: u8,
    plan_sha256: String,
    pub(super) qualification_profile: String,
    pub(super) cases: Vec<LocalDurationSuiteCase>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct LocalDurationSuiteCase {
    pub(super) ladder_id: String,
    pub(super) case_id: String,
    pub(super) duration_samples: u64,
    track_manifest_sha256: String,
    pub(super) expect_text: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct DurationTrackManifest {
    schema_version: u8,
    case_id: String,
    runtime_control_kind: String,
    pub(super) audio: DurationTrackAudio,
    sources: Vec<DurationTrackSource>,
    segments: Vec<DurationTrackSegment>,
    accuracy_sample_increment: u8,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct DurationTrackAudio {
    pub(super) sha256: String,
    pub(super) decoded_pcm_sha256: String,
    pub(super) byte_length: u64,
    pub(super) duration_samples: u64,
    pub(super) sample_rate_hz: u32,
    pub(super) channels: u16,
    pub(super) sample_width_bytes: u16,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct DurationTrackSource {
    sha256: String,
    decoded_pcm_sha256: String,
    byte_length: u64,
    frame_count: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct DurationTrackSegment {
    source_index: usize,
    source_start_sample: u64,
    source_end_sample_exclusive: u64,
    output_start_sample: u64,
    output_end_sample_exclusive: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PlannedDurationCase {
    ladder_id: String,
    case_id: String,
    duration_samples: u64,
}

pub(super) fn load_local_duration_suite() -> LoadedLocalDurationSuite {
    let suite_path = required_path("YAP_TEST_LOCAL_DURATION_SUITE");
    assert_private_external_path(&suite_path);
    let suite_bytes = crate::bounded_file::read_bytes(&suite_path, MAXIMUM_SUITE_BYTES)
        .expect("local duration suite must be a bounded regular file");
    let suite_sha256 = required_sha256("YAP_TEST_LOCAL_DURATION_SUITE_SHA256");
    assert_eq!(sha256(&suite_bytes), suite_sha256);
    let definition: LocalDurationSuite =
        serde_json::from_slice(&suite_bytes).expect("local duration suite must be valid JSON");
    let expected_profile = required_string("YAP_TEST_LOCAL_DURATION_PROFILE");
    assert!(
        supported_qualification_profile(&expected_profile),
        "local duration qualification profile is unsupported"
    );
    assert_eq!(definition.qualification_profile, expected_profile);
    let (plan_sha256, planned_cases) =
        planned_local_duration_cases(&definition.qualification_profile);
    validate_suite(&definition, &plan_sha256, &planned_cases);
    let root = suite_path
        .parent()
        .expect("duration suite must have a parent")
        .canonicalize()
        .expect("duration suite parent must be readable");
    LoadedLocalDurationSuite {
        definition,
        root,
        plan_sha256,
        suite_sha256,
    }
}

pub(super) fn load_track_manifest(
    suite_root: &Path,
    definition: &LocalDurationSuiteCase,
) -> DurationTrackManifest {
    let path = direct_case_file(suite_root, &definition.case_id, "manifest.json");
    let bytes = crate::bounded_file::read_bytes(&path, MAXIMUM_TRACK_MANIFEST_BYTES)
        .expect("duration track manifest must be a bounded regular file");
    assert_eq!(sha256(&bytes), definition.track_manifest_sha256);
    let manifest: DurationTrackManifest =
        serde_json::from_slice(&bytes).expect("duration track manifest must be valid JSON");
    validate_track_manifest(&manifest, definition);
    manifest
}

pub(super) fn direct_case_file(root: &Path, case_id: &str, file_name: &str) -> PathBuf {
    assert!(valid_identifier(case_id));
    let case_directory = root.join(case_id);
    let directory_metadata =
        std::fs::symlink_metadata(&case_directory).expect("duration track directory must exist");
    assert!(directory_metadata.is_dir());
    assert!(!crate::stt::model::metadata_is_link_or_reparse(
        &directory_metadata
    ));
    let canonical_directory = case_directory
        .canonicalize()
        .expect("duration track directory must be readable");
    assert_eq!(canonical_directory.parent(), Some(root));
    let path = canonical_directory.join(file_name);
    let metadata = std::fs::symlink_metadata(&path).expect("duration track file must exist");
    assert!(metadata.is_file());
    assert!(!crate::stt::model::metadata_is_link_or_reparse(&metadata));
    path
}

fn validate_track_manifest(manifest: &DurationTrackManifest, definition: &LocalDurationSuiteCase) {
    assert_eq!(manifest.schema_version, 1);
    assert_eq!(manifest.case_id, definition.case_id);
    assert!(matches!(
        manifest.runtime_control_kind.as_str(),
        "truncated" | "concatenated" | "looped"
    ));
    assert_eq!(manifest.accuracy_sample_increment, 0);
    assert_eq!(manifest.audio.duration_samples, definition.duration_samples);
    assert_eq!(manifest.audio.sample_rate_hz, SAMPLE_RATE_HZ);
    assert_eq!(manifest.audio.channels, 1);
    assert_eq!(manifest.audio.sample_width_bytes, 2);
    assert!(valid_sha256(&manifest.audio.sha256));
    assert!(valid_sha256(&manifest.audio.decoded_pcm_sha256));
    assert!(manifest.audio.byte_length > 44);
    assert!((1..=64).contains(&manifest.sources.len()));
    for source in &manifest.sources {
        assert!(valid_sha256(&source.sha256));
        assert!(valid_sha256(&source.decoded_pcm_sha256));
        assert!(source.byte_length > 44 && source.frame_count > 0);
    }
    assert!((1..=MAXIMUM_TRACK_SEGMENTS).contains(&manifest.segments.len()));
    let mut expected_output_start = 0_u64;
    for segment in &manifest.segments {
        assert!(segment.source_index < manifest.sources.len());
        assert_eq!(segment.source_start_sample, 0);
        assert!(segment.source_end_sample_exclusive > 0);
        assert!(
            segment.source_end_sample_exclusive
                <= manifest.sources[segment.source_index].frame_count
        );
        assert_eq!(segment.output_start_sample, expected_output_start);
        assert_eq!(
            segment.output_end_sample_exclusive - segment.output_start_sample,
            segment.source_end_sample_exclusive
        );
        expected_output_start = segment.output_end_sample_exclusive;
    }
    assert_eq!(expected_output_start, definition.duration_samples);
}

fn planned_local_duration_cases(qualification_profile: &str) -> (String, Vec<PlannedDurationCase>) {
    assert!(
        supported_qualification_profile(qualification_profile),
        "local duration qualification profile is unsupported"
    );
    let path = repository_root().join("server/asr-evaluation-plan.json");
    let bytes = crate::bounded_file::read_bytes(&path, 256 * 1_024)
        .expect("runtime evaluation plan must be readable");
    let plan_sha256 = sha256(&bytes);
    let plan: serde_json::Value =
        serde_json::from_slice(&bytes).expect("runtime evaluation plan must be valid JSON");
    assert_eq!(plan["schemaVersion"], 5);
    let ladders = plan["durationLadders"]
        .as_array()
        .expect("runtime evaluation plan must contain duration ladders");
    let mut cases = Vec::new();
    for ladder_id in ["live-endpoint", "live-session"] {
        let ladder = ladders
            .iter()
            .find(|ladder| ladder["id"] == ladder_id)
            .expect("local duration ladder must exist");
        assert_eq!(
            ladder["systemIds"],
            serde_json::json!(["local-live-nemotron"])
        );
        assert_eq!(ladder["pacing"], "realtime");
        if qualification_profile == SHORT_BOUNDARIES && ladder_id != "live-endpoint" {
            continue;
        }
        for duration in ladder["durationSamples"]
            .as_array()
            .expect("local duration ladder must contain sample counts")
        {
            let duration_samples = duration
                .as_u64()
                .expect("local duration sample count must be an integer");
            cases.push(PlannedDurationCase {
                ladder_id: ladder_id.into(),
                case_id: format!("{ladder_id}-{duration_samples}-samples"),
                duration_samples,
            });
        }
    }
    (plan_sha256, cases)
}

fn validate_suite(suite: &LocalDurationSuite, plan_sha256: &str, planned: &[PlannedDurationCase]) {
    assert_eq!(suite.schema_version, 2);
    assert_eq!(suite.plan_sha256, plan_sha256);
    assert!(supported_qualification_profile(
        &suite.qualification_profile
    ));
    assert_eq!(suite.cases.len(), planned.len());
    for (definition, expected) in suite.cases.iter().zip(planned) {
        assert_eq!(definition.ladder_id, expected.ladder_id);
        assert_eq!(definition.case_id, expected.case_id);
        assert_eq!(definition.duration_samples, expected.duration_samples);
        assert!(valid_sha256(&definition.track_manifest_sha256));
    }
}

fn supported_qualification_profile(value: &str) -> bool {
    matches!(value, SHORT_BOUNDARIES | COMPLETE_LOCAL_DURATION_LADDERS)
}

pub(super) fn repository_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("repository root must be readable")
}

fn assert_private_external_path(path: &Path) {
    assert!(path.is_absolute());
    let canonical = path
        .canonicalize()
        .expect("private evidence path must be readable");
    assert!(!canonical.starts_with(repository_root()));
}

fn required_path(environment: &str) -> PathBuf {
    PathBuf::from(required_string(environment))
}

fn required_sha256(environment: &str) -> String {
    let value = required_string(environment);
    assert!(
        valid_sha256(&value),
        "{environment} must be lowercase SHA-256"
    );
    value
}

fn required_string(environment: &str) -> String {
    std::env::var(environment).unwrap_or_else(|_| panic!("{environment} is required"))
}

fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn valid_identifier(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value.as_bytes()[0].is_ascii_lowercase()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
}

#[test]
fn qualification_profiles_select_proportional_and_complete_duration_cases() {
    let (_, proportional) = planned_local_duration_cases(SHORT_BOUNDARIES);
    assert_eq!(proportional.len(), 9);
    assert_eq!(proportional[0].duration_samples, 4_000);
    assert_eq!(proportional[4].duration_samples, 17_920);
    assert_eq!(proportional[8].duration_samples, 480_000);

    let (_, complete) = planned_local_duration_cases(COMPLETE_LOCAL_DURATION_LADDERS);
    assert_eq!(complete.len(), 15);
    assert_eq!(complete[9].case_id, "live-session-480000-samples");
    assert_eq!(complete[14].duration_samples, 115_200_000);
}

#[test]
fn identifier_and_digest_contracts_reject_ambiguous_inputs() {
    assert!(valid_identifier("live-endpoint-4000-samples"));
    assert!(!valid_identifier("../audio"));
    assert!(!valid_identifier("Uppercase"));
    assert!(valid_sha256(&"a".repeat(64)));
    assert!(!valid_sha256(&"A".repeat(64)));
    assert!(!valid_sha256(&"g".repeat(64)));
}
