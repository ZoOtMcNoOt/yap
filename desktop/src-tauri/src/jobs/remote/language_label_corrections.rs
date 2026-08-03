use super::{
    artifact_io::{
        metadata_is_link_or_reparse, next_staging_nonce, sha256_bytes, valid_sha256,
        write_new_synced,
    },
    result::{read_bounded_regular_artifact, read_published_remote_transcript},
};
use crate::{language::valid_bcp47, server_connector::batch::LanguageSegmentStatus};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::{Path, PathBuf},
};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};

const CORRECTION_DIRECTORY_NAME: &str = "language-label-corrections";
const CORRECTION_SCHEMA_VERSION: u16 = 1;
const MAX_CORRECTION_ARTIFACT_BYTES: usize = 4 * 1024;
const MAX_CORRECTION_REVISIONS: usize = 4_096;
const MAX_CORRECTION_DIRECTORY_ENTRIES: usize = MAX_CORRECTION_REVISIONS * 2;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LanguageLabelReview {
    pub schema_version: u16,
    pub session_id: String,
    pub source_result_sha256: String,
    pub revision: u64,
    pub active_correction_count: u64,
    pub review_required_count: u64,
    pub segments: Vec<LanguageLabelReviewSegment>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LanguageLabelReviewSegment {
    pub index: u64,
    pub source_span_index: u64,
    pub text: String,
    pub source_status: LanguageSegmentStatus,
    pub source_language_bcp47: Option<String>,
    pub effective_language_bcp47: Option<String>,
    pub has_user_correction: bool,
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum LanguageLabelCorrectionError {
    Unavailable(String),
    Conflict(String),
    InvalidRequest(String),
    NoChange(String),
    InvalidArtifacts(String),
    Storage(String),
}

impl LanguageLabelCorrectionError {
    pub(crate) fn code(&self) -> &'static str {
        match self {
            Self::Unavailable(_) => "LANGUAGE_LABEL_REVIEW_UNAVAILABLE",
            Self::Conflict(_) => "LANGUAGE_LABEL_CORRECTION_CONFLICT",
            Self::InvalidRequest(_) => "LANGUAGE_LABEL_CORRECTION_INVALID",
            Self::NoChange(_) => "LANGUAGE_LABEL_CORRECTION_NO_CHANGE",
            Self::InvalidArtifacts(_) => "LANGUAGE_LABEL_CORRECTION_ARTIFACT_INVALID",
            Self::Storage(_) => "LANGUAGE_LABEL_CORRECTION_STORAGE_ERROR",
        }
    }
}

impl std::fmt::Display for LanguageLabelCorrectionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unavailable(message)
            | Self::Conflict(message)
            | Self::InvalidRequest(message)
            | Self::NoChange(message)
            | Self::InvalidArtifacts(message)
            | Self::Storage(message) => formatter.write_str(message),
        }
    }
}

impl std::error::Error for LanguageLabelCorrectionError {}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum LanguageLabelCorrectionAuthority {
    UserCorrected,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LanguageLabelCorrectionRevision {
    schema_version: u16,
    session_id: String,
    revision: u64,
    authority: LanguageLabelCorrectionAuthority,
    created_at_utc: String,
    source_result_sha256: String,
    previous_correction_sha256: Option<String>,
    segment_index: u64,
    source_span_index: u64,
    source_language_bcp47: Option<String>,
    replacement_language_bcp47: Option<String>,
}

struct LoadedCorrectionChain {
    review: LanguageLabelReview,
    last_correction_sha256: Option<String>,
}

pub(crate) fn read_language_label_review(
    transcript_path: &Path,
    spool_root: &Path,
) -> Result<LanguageLabelReview, LanguageLabelCorrectionError> {
    load_correction_chain(transcript_path, spool_root).map(|loaded| loaded.review)
}

pub(crate) fn append_language_label_correction(
    transcript_path: &Path,
    spool_root: &Path,
    expected_revision: u64,
    segment_index: u64,
    replacement_language_bcp47: Option<String>,
) -> Result<LanguageLabelReview, LanguageLabelCorrectionError> {
    let created_at_utc = OffsetDateTime::now_utc()
        .format(&Rfc3339)
        .map_err(|error| {
            LanguageLabelCorrectionError::Storage(format!(
                "failed to format language-label correction time: {error}"
            ))
        })?;
    append_language_label_correction_at(
        transcript_path,
        spool_root,
        expected_revision,
        segment_index,
        replacement_language_bcp47,
        created_at_utc,
    )
}

fn append_language_label_correction_at(
    transcript_path: &Path,
    spool_root: &Path,
    expected_revision: u64,
    segment_index: u64,
    replacement_language_bcp47: Option<String>,
    created_at_utc: String,
) -> Result<LanguageLabelReview, LanguageLabelCorrectionError> {
    if !replacement_language_is_valid(replacement_language_bcp47.as_deref()) {
        return Err(LanguageLabelCorrectionError::InvalidRequest(
            "Choose a canonical supported language tag, or leave the segment unknown.".into(),
        ));
    }
    let loaded = load_correction_chain(transcript_path, spool_root)?;
    if loaded.review.revision != expected_revision {
        return Err(LanguageLabelCorrectionError::Conflict(
            "Language labels changed after this review was loaded. Refresh and try again.".into(),
        ));
    }
    let segment = loaded
        .review
        .segments
        .get(usize::try_from(segment_index).map_err(|_| {
            LanguageLabelCorrectionError::InvalidRequest(
                "The requested transcript segment is invalid.".into(),
            )
        })?)
        .filter(|segment| segment.index == segment_index)
        .ok_or_else(|| {
            LanguageLabelCorrectionError::InvalidRequest(
                "The requested transcript segment is unavailable.".into(),
            )
        })?;
    if segment.effective_language_bcp47 == replacement_language_bcp47 {
        return Err(LanguageLabelCorrectionError::NoChange(
            "The selected language already labels this segment.".into(),
        ));
    }
    let revision = expected_revision.checked_add(1).ok_or_else(|| {
        LanguageLabelCorrectionError::InvalidArtifacts(
            "The language-label correction history is too large.".into(),
        )
    })?;
    if revision > MAX_CORRECTION_REVISIONS as u64 {
        return Err(LanguageLabelCorrectionError::InvalidArtifacts(format!(
            "A transcript accepts at most {MAX_CORRECTION_REVISIONS} language-label corrections."
        )));
    }
    let correction = LanguageLabelCorrectionRevision {
        schema_version: CORRECTION_SCHEMA_VERSION,
        session_id: loaded.review.session_id.clone(),
        revision,
        authority: LanguageLabelCorrectionAuthority::UserCorrected,
        created_at_utc,
        source_result_sha256: loaded.review.source_result_sha256.clone(),
        previous_correction_sha256: loaded.last_correction_sha256,
        segment_index,
        source_span_index: segment.source_span_index,
        source_language_bcp47: segment.source_language_bcp47.clone(),
        replacement_language_bcp47,
    };
    validate_correction_revision(&correction, None, &loaded.review.segments)?;
    let bytes = serde_json::to_vec(&correction).map_err(|error| {
        LanguageLabelCorrectionError::Storage(format!(
            "failed to encode language-label correction: {error}"
        ))
    })?;
    if bytes.len() > MAX_CORRECTION_ARTIFACT_BYTES {
        return Err(LanguageLabelCorrectionError::InvalidRequest(
            "The language-label correction is too large.".into(),
        ));
    }

    let verified = read_published_remote_transcript(transcript_path, spool_root)
        .map_err(LanguageLabelCorrectionError::InvalidArtifacts)?;
    if verified.result_sha256 != loaded.review.source_result_sha256 {
        return Err(LanguageLabelCorrectionError::Conflict(
            "The immutable server result changed before the correction was saved.".into(),
        ));
    }
    let job_root = verified.result_directory.parent().ok_or_else(|| {
        LanguageLabelCorrectionError::InvalidArtifacts(
            "The server result has no canonical job owner.".into(),
        )
    })?;
    let correction_directory = prepare_correction_directory(job_root)?;
    let filename = correction_filename(revision);
    write_correction_atomically(&correction_directory, &filename, &bytes)?;

    let persisted = load_correction_chain(transcript_path, spool_root)?;
    if persisted.review.revision != revision {
        return Err(LanguageLabelCorrectionError::Storage(
            "The saved language-label correction could not be verified.".into(),
        ));
    }
    Ok(persisted.review)
}

fn load_correction_chain(
    transcript_path: &Path,
    spool_root: &Path,
) -> Result<LoadedCorrectionChain, LanguageLabelCorrectionError> {
    let verified = read_published_remote_transcript(transcript_path, spool_root)
        .map_err(LanguageLabelCorrectionError::InvalidArtifacts)?;
    let segments = verified
        .result
        .language_segments
        .as_ref()
        .filter(|segments| {
            verified
                .result
                .language
                .as_ref()
                .is_some_and(|language| language.language_bcp47 == "und")
                && verified.result.language_span_evidence.is_some()
                && !segments.is_empty()
        })
        .ok_or_else(|| {
            LanguageLabelCorrectionError::Unavailable(
                "Language-label review is available only for dynamic server transcripts.".into(),
            )
        })?;
    let job_root = verified.result_directory.parent().ok_or_else(|| {
        LanguageLabelCorrectionError::InvalidArtifacts(
            "The server result has no canonical job owner.".into(),
        )
    })?;
    let mut review_segments = segments
        .iter()
        .map(|segment| LanguageLabelReviewSegment {
            index: segment.index,
            source_span_index: segment.source_span_index,
            text: segment.text.clone(),
            source_status: segment.status,
            source_language_bcp47: segment.language_bcp47.clone(),
            effective_language_bcp47: segment.language_bcp47.clone(),
            has_user_correction: false,
        })
        .collect::<Vec<_>>();
    let correction_directory = job_root.join(CORRECTION_DIRECTORY_NAME);
    let correction_files = list_correction_files(&correction_directory)?;
    let mut previous_sha256 = None;
    let mut latest_revision = 0_u64;
    for (expected_index, (revision, path)) in correction_files.into_iter().enumerate() {
        let expected_revision = expected_index as u64 + 1;
        if revision != expected_revision {
            return Err(LanguageLabelCorrectionError::InvalidArtifacts(
                "Language-label correction revisions are not a complete ordered sequence.".into(),
            ));
        }
        let bytes = read_bounded_regular_artifact(
            &path,
            MAX_CORRECTION_ARTIFACT_BYTES,
            "language-label correction revision",
        )
        .map_err(LanguageLabelCorrectionError::InvalidArtifacts)?;
        let correction: LanguageLabelCorrectionRevision =
            serde_json::from_slice(&bytes).map_err(|_| {
                LanguageLabelCorrectionError::InvalidArtifacts(
                    "A language-label correction revision is incompatible.".into(),
                )
            })?;
        validate_correction_revision(&correction, Some(expected_revision), &review_segments)?;
        if correction.session_id != verified.result.session_id
            || correction.source_result_sha256 != verified.result_sha256
            || correction.previous_correction_sha256 != previous_sha256
        {
            return Err(LanguageLabelCorrectionError::InvalidArtifacts(
                "A language-label correction is not bound to its immutable result history.".into(),
            ));
        }
        let segment = &mut review_segments[correction.segment_index as usize];
        if segment.effective_language_bcp47 == correction.replacement_language_bcp47 {
            return Err(LanguageLabelCorrectionError::InvalidArtifacts(
                "A language-label correction revision does not change its predecessor.".into(),
            ));
        }
        segment.effective_language_bcp47 = correction.replacement_language_bcp47;
        previous_sha256 = Some(sha256_bytes(&bytes));
        latest_revision = expected_revision;
    }
    for segment in &mut review_segments {
        segment.has_user_correction =
            segment.effective_language_bcp47 != segment.source_language_bcp47;
    }
    let active_correction_count = review_segments
        .iter()
        .filter(|segment| segment.has_user_correction)
        .count() as u64;
    let review_required_count = review_segments
        .iter()
        .filter(|segment| segment.effective_language_bcp47.is_none())
        .count() as u64;
    Ok(LoadedCorrectionChain {
        review: LanguageLabelReview {
            schema_version: CORRECTION_SCHEMA_VERSION,
            session_id: verified.result.session_id,
            source_result_sha256: verified.result_sha256,
            revision: latest_revision,
            active_correction_count,
            review_required_count,
            segments: review_segments,
        },
        last_correction_sha256: previous_sha256,
    })
}

fn validate_correction_revision(
    correction: &LanguageLabelCorrectionRevision,
    expected_revision: Option<u64>,
    segments: &[LanguageLabelReviewSegment],
) -> Result<(), LanguageLabelCorrectionError> {
    let timestamp_valid = correction.created_at_utc.ends_with('Z')
        && correction.created_at_utc.len() <= 64
        && OffsetDateTime::parse(&correction.created_at_utc, &Rfc3339).is_ok();
    let segment_index = usize::try_from(correction.segment_index).map_err(|_| {
        LanguageLabelCorrectionError::InvalidArtifacts(
            "A language-label correction segment index is invalid.".into(),
        )
    })?;
    let segment = segments.get(segment_index).ok_or_else(|| {
        LanguageLabelCorrectionError::InvalidArtifacts(
            "A language-label correction references a missing transcript segment.".into(),
        )
    })?;
    if correction.schema_version != CORRECTION_SCHEMA_VERSION
        || correction.revision == 0
        || expected_revision.is_some_and(|expected| correction.revision != expected)
        || correction.authority != LanguageLabelCorrectionAuthority::UserCorrected
        || !timestamp_valid
        || !valid_sha256(&correction.source_result_sha256)
        || correction
            .previous_correction_sha256
            .as_deref()
            .is_some_and(|value| !valid_sha256(value))
        || correction.segment_index != segment.index
        || correction.source_span_index != segment.source_span_index
        || correction.source_language_bcp47 != segment.source_language_bcp47
    {
        return Err(LanguageLabelCorrectionError::InvalidArtifacts(
            "A language-label correction conflicts with its source transcript segment.".into(),
        ));
    }
    if !replacement_language_is_valid(correction.replacement_language_bcp47.as_deref()) {
        return Err(LanguageLabelCorrectionError::InvalidArtifacts(
            "A language-label correction contains a noncanonical replacement language.".into(),
        ));
    }
    Ok(())
}

fn replacement_language_is_valid(language_bcp47: Option<&str>) -> bool {
    language_bcp47.is_none_or(|language| language != "und" && valid_bcp47(language))
}

fn list_correction_files(
    directory: &Path,
) -> Result<Vec<(u64, PathBuf)>, LanguageLabelCorrectionError> {
    let metadata = match fs::symlink_metadata(directory) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => {
            return Err(LanguageLabelCorrectionError::Storage(format!(
                "failed to inspect language-label corrections: {error}"
            )))
        }
    };
    if !metadata.is_dir() || metadata_is_link_or_reparse(&metadata) {
        return Err(LanguageLabelCorrectionError::InvalidArtifacts(
            "Language-label corrections are not stored in a safe owned directory.".into(),
        ));
    }
    let mut corrections = Vec::new();
    let mut entry_count = 0_usize;
    for entry in fs::read_dir(directory).map_err(|error| {
        LanguageLabelCorrectionError::Storage(format!(
            "failed to inspect language-label correction history: {error}"
        ))
    })? {
        entry_count += 1;
        if entry_count > MAX_CORRECTION_DIRECTORY_ENTRIES {
            return Err(LanguageLabelCorrectionError::InvalidArtifacts(
                "The language-label correction directory contains too many artifacts.".into(),
            ));
        }
        let entry = entry.map_err(|error| {
            LanguageLabelCorrectionError::Storage(format!(
                "failed to inspect a language-label correction artifact: {error}"
            ))
        })?;
        let name = entry.file_name().into_string().map_err(|_| {
            LanguageLabelCorrectionError::InvalidArtifacts(
                "A language-label correction artifact name is invalid.".into(),
            )
        })?;
        if let Some(revision) = parse_correction_filename(&name) {
            corrections.push((revision, entry.path()));
            continue;
        }
        if valid_staging_filename(&name) {
            let metadata = fs::symlink_metadata(entry.path()).map_err(|error| {
                LanguageLabelCorrectionError::Storage(format!(
                    "failed to inspect a staged language-label correction: {error}"
                ))
            })?;
            if !metadata.is_file()
                || metadata_is_link_or_reparse(&metadata)
                || metadata.len() > MAX_CORRECTION_ARTIFACT_BYTES as u64
            {
                return Err(LanguageLabelCorrectionError::InvalidArtifacts(
                    "A staged language-label correction is not a bounded regular artifact.".into(),
                ));
            }
            continue;
        }
        return Err(LanguageLabelCorrectionError::InvalidArtifacts(
            "The language-label correction directory contains an unexpected artifact.".into(),
        ));
    }
    if corrections.len() > MAX_CORRECTION_REVISIONS {
        return Err(LanguageLabelCorrectionError::InvalidArtifacts(
            "The language-label correction history is too large.".into(),
        ));
    }
    corrections.sort_by_key(|(revision, _)| *revision);
    Ok(corrections)
}

fn prepare_correction_directory(job_root: &Path) -> Result<PathBuf, LanguageLabelCorrectionError> {
    let job_metadata = fs::symlink_metadata(job_root).map_err(|error| {
        LanguageLabelCorrectionError::Storage(format!(
            "failed to inspect the language-label correction owner: {error}"
        ))
    })?;
    if !job_metadata.is_dir() || metadata_is_link_or_reparse(&job_metadata) {
        return Err(LanguageLabelCorrectionError::InvalidArtifacts(
            "The language-label correction owner is not a safe Yap directory.".into(),
        ));
    }
    let directory = job_root.join(CORRECTION_DIRECTORY_NAME);
    match fs::create_dir(&directory) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(error) => {
            return Err(LanguageLabelCorrectionError::Storage(format!(
                "failed to create language-label correction history: {error}"
            )))
        }
    }
    let metadata = fs::symlink_metadata(&directory).map_err(|error| {
        LanguageLabelCorrectionError::Storage(format!(
            "failed to inspect language-label correction history: {error}"
        ))
    })?;
    if !metadata.is_dir() || metadata_is_link_or_reparse(&metadata) {
        return Err(LanguageLabelCorrectionError::InvalidArtifacts(
            "Language-label corrections are not stored in a safe owned directory.".into(),
        ));
    }
    Ok(directory)
}

fn write_correction_atomically(
    directory: &Path,
    filename: &str,
    bytes: &[u8],
) -> Result<(), LanguageLabelCorrectionError> {
    let destination = directory.join(filename);
    if destination.exists() {
        return Err(LanguageLabelCorrectionError::Conflict(
            "A newer language-label correction already exists. Refresh and try again.".into(),
        ));
    }
    let nonce = next_staging_nonce();
    let staging_path = directory.join(format!(
        ".{filename}-staging-{}-{nonce}",
        std::process::id()
    ));
    let mut staging = StagedCorrectionFile::new(staging_path);
    write_new_synced(&staging.path, bytes).map_err(LanguageLabelCorrectionError::Storage)?;
    fs::rename(&staging.path, &destination).map_err(|error| {
        LanguageLabelCorrectionError::Storage(format!(
            "failed to publish language-label correction revision: {error}"
        ))
    })?;
    staging.published = true;
    let reopened = read_bounded_regular_artifact(
        &destination,
        MAX_CORRECTION_ARTIFACT_BYTES,
        "language-label correction revision",
    )
    .map_err(LanguageLabelCorrectionError::InvalidArtifacts)?;
    if reopened != bytes {
        return Err(LanguageLabelCorrectionError::InvalidArtifacts(
            "The published language-label correction differs from the committed revision.".into(),
        ));
    }
    Ok(())
}

struct StagedCorrectionFile {
    path: PathBuf,
    published: bool,
}

impl StagedCorrectionFile {
    fn new(path: PathBuf) -> Self {
        Self {
            path,
            published: false,
        }
    }
}

impl Drop for StagedCorrectionFile {
    fn drop(&mut self) {
        if !self.published {
            let _ = fs::remove_file(&self.path);
        }
    }
}

fn correction_filename(revision: u64) -> String {
    format!("correction-{revision:020}.json")
}

fn parse_correction_filename(name: &str) -> Option<u64> {
    let revision = name.strip_prefix("correction-")?.strip_suffix(".json")?;
    (revision.len() == 20 && revision.bytes().all(|byte| byte.is_ascii_digit()))
        .then(|| revision.parse::<u64>().ok())
        .flatten()
        .filter(|revision| *revision > 0)
}

fn valid_staging_filename(name: &str) -> bool {
    let Some(staging) = name.strip_prefix(".correction-") else {
        return false;
    };
    let Some((revision, process_and_nonce)) = staging.split_once(".json-staging-") else {
        return false;
    };
    let Some((process, nonce)) = process_and_nonce.split_once('-') else {
        return false;
    };
    revision.len() == 20
        && revision.bytes().all(|byte| byte.is_ascii_digit())
        && !process.is_empty()
        && process.bytes().all(|byte| byte.is_ascii_digit())
        && !nonce.is_empty()
        && nonce.bytes().all(|byte| byte.is_ascii_digit())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        language::span_contract::{
            LanguageSpan, LanguageSpanBoundaryAuthority, LanguageSpanDisposition,
        },
        server_connector::batch::{
            LanguageDecision, LanguageSegment, LanguageSegmentReason, ModelRevision,
            ServerLanguageSpanEvidence, TranscriptResultRevision,
        },
    };
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_TEST_DIRECTORY: AtomicU64 = AtomicU64::new(0);

    fn test_directory(label: &str) -> PathBuf {
        let nonce = NEXT_TEST_DIRECTORY.fetch_add(1, Ordering::Relaxed);
        std::env::temp_dir().join(format!(
            "yap-language-label-correction-{label}-{}-{nonce}",
            std::process::id()
        ))
    }

    fn publish_dynamic_result(root: &Path) -> (PathBuf, PathBuf) {
        let spool = root.join("remote-jobs");
        let job_id = "job-language-review";
        fs::create_dir_all(spool.join(job_id)).unwrap();
        let result = TranscriptResultRevision {
            session_id: "session-language-review".into(),
            revision: 1,
            authority: "server_authoritative".into(),
            created_at_utc: "2026-07-18T12:00:00Z".into(),
            capture_manifest_sha256:
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".into(),
            previous_result_sha256: None,
            status: "complete".into(),
            language: Some(LanguageDecision {
                language_bcp47: "und".into(),
                confidence: None,
            }),
            transcript: "hello bonjour".into(),
            speaker_result_sha256: None,
            language_segments: Some(vec![
                LanguageSegment {
                    index: 0,
                    source_span_index: 0,
                    text: "hello".into(),
                    status: LanguageSegmentStatus::Detected,
                    language_bcp47: Some("en-US".into()),
                    raw_language_tag: Some("en-US".into()),
                    reason: None,
                },
                LanguageSegment {
                    index: 1,
                    source_span_index: 0,
                    text: "bonjour".into(),
                    status: LanguageSegmentStatus::Unknown,
                    language_bcp47: None,
                    raw_language_tag: Some("el-GR".into()),
                    reason: Some(LanguageSegmentReason::DisabledLanguageTag),
                },
            ]),
            language_span_evidence: Some(ServerLanguageSpanEvidence {
                schema_version: 1,
                sample_rate_hz: 16_000,
                source_end_sample: 16_000,
                boundary_authority: LanguageSpanBoundaryAuthority::ServerUtterance,
                provider_id: "nemotron".into(),
                pool_id: "nemotron-batch".into(),
                model_id: "nvidia/nemotron-3.5-asr-streaming-0.6b".into(),
                model_revision: "f3d333391852ba876df169dcc9ba902d25b6ab0b".into(),
                utterance_plan_sha256:
                    "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee".into(),
                spans: vec![LanguageSpan {
                    start_sample: 0,
                    end_sample: 16_000,
                    language_bcp47: "und".into(),
                    decision_revision: 1,
                    disposition: LanguageSpanDisposition::ServerUnknown,
                    component_revision: Some("f3d333391852ba876df169dcc9ba902d25b6ab0b".into()),
                    decision_evidence: None,
                }],
            }),
            alignment: None,
            aligned_words: Vec::new(),
            model_provenance: vec![ModelRevision {
                model_id: "nvidia/nemotron-3.5-asr-streaming-0.6b".into(),
                revision: "f3d333391852ba876df169dcc9ba902d25b6ab0b".into(),
                calibration_revision: "asr-not-applicable".into(),
            }],
        };
        let transcript_path =
            super::super::publish_remote_result(job_id, &spool, &result, None).unwrap();
        (spool, transcript_path)
    }

    #[test]
    fn language_label_corrections_are_hash_chained_without_mutating_the_server_result() {
        let root = test_directory("immutable");
        let _ = fs::remove_dir_all(&root);
        let (spool, transcript_path) = publish_dynamic_result(&root);
        let result_path = transcript_path.parent().unwrap().join("result.json");
        let original_result = fs::read(&result_path).unwrap();
        let original_transcript = fs::read(&transcript_path).unwrap();

        let initial = read_language_label_review(&transcript_path, &spool).unwrap();
        assert_eq!(initial.revision, 0);
        assert_eq!(initial.review_required_count, 1);

        let corrected = append_language_label_correction_at(
            &transcript_path,
            &spool,
            0,
            1,
            Some("fr-FR".into()),
            "2026-07-18T12:01:00Z".into(),
        )
        .unwrap();
        assert_eq!(corrected.revision, 1);
        assert_eq!(corrected.active_correction_count, 1);
        assert_eq!(corrected.review_required_count, 0);
        assert_eq!(
            corrected.segments[1].effective_language_bcp47.as_deref(),
            Some("fr-FR")
        );

        let reverted = append_language_label_correction_at(
            &transcript_path,
            &spool,
            1,
            1,
            None,
            "2026-07-18T12:02:00Z".into(),
        )
        .unwrap();
        assert_eq!(reverted.revision, 2);
        assert_eq!(reverted.active_correction_count, 0);
        assert_eq!(reverted.review_required_count, 1);
        assert_eq!(fs::read(&result_path).unwrap(), original_result);
        assert_eq!(fs::read(&transcript_path).unwrap(), original_transcript);

        let first = fs::read(
            root.join("remote-jobs/job-language-review/language-label-corrections/correction-00000000000000000001.json"),
        )
        .unwrap();
        let second: serde_json::Value = serde_json::from_slice(
            &fs::read(
                root.join("remote-jobs/job-language-review/language-label-corrections/correction-00000000000000000002.json"),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(second["previousCorrectionSha256"], sha256_bytes(&first));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn language_label_correction_rejects_stale_noop_and_noncanonical_requests() {
        let root = test_directory("requests");
        let _ = fs::remove_dir_all(&root);
        let (spool, transcript_path) = publish_dynamic_result(&root);

        assert!(matches!(
            append_language_label_correction_at(
                &transcript_path,
                &spool,
                0,
                0,
                Some("en-US".into()),
                "2026-07-18T12:01:00Z".into(),
            ),
            Err(LanguageLabelCorrectionError::NoChange(_))
        ));
        assert!(matches!(
            append_language_label_correction_at(
                &transcript_path,
                &spool,
                0,
                0,
                Some("EN-us".into()),
                "2026-07-18T12:01:00Z".into(),
            ),
            Err(LanguageLabelCorrectionError::InvalidRequest(_))
        ));
        append_language_label_correction_at(
            &transcript_path,
            &spool,
            0,
            1,
            Some("fr-FR".into()),
            "2026-07-18T12:01:00Z".into(),
        )
        .unwrap();
        assert!(matches!(
            append_language_label_correction_at(
                &transcript_path,
                &spool,
                0,
                0,
                Some("de-DE".into()),
                "2026-07-18T12:02:00Z".into(),
            ),
            Err(LanguageLabelCorrectionError::Conflict(_))
        ));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn language_label_correction_history_fails_closed_on_future_or_unexpected_artifacts() {
        let root = test_directory("tamper");
        let _ = fs::remove_dir_all(&root);
        let (spool, transcript_path) = publish_dynamic_result(&root);
        append_language_label_correction_at(
            &transcript_path,
            &spool,
            0,
            1,
            Some("fr-FR".into()),
            "2026-07-18T12:01:00Z".into(),
        )
        .unwrap();
        let corrections = root.join("remote-jobs/job-language-review/language-label-corrections");
        fs::write(corrections.join("notes.txt"), b"unexpected").unwrap();
        assert!(matches!(
            read_language_label_review(&transcript_path, &spool),
            Err(LanguageLabelCorrectionError::InvalidArtifacts(_))
        ));
        fs::remove_file(corrections.join("notes.txt")).unwrap();

        let correction_path = corrections.join("correction-00000000000000000001.json");
        let mut correction: serde_json::Value =
            serde_json::from_slice(&fs::read(&correction_path).unwrap()).unwrap();
        correction["schemaVersion"] = serde_json::json!(2);
        fs::write(&correction_path, serde_json::to_vec(&correction).unwrap()).unwrap();
        assert!(matches!(
            read_language_label_review(&transcript_path, &spool),
            Err(LanguageLabelCorrectionError::InvalidArtifacts(_))
        ));
        fs::remove_dir_all(root).unwrap();
    }
}
