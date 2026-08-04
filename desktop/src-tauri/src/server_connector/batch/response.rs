use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::validation::valid_path_segment;
use crate::language::{
    span_contract::{
        sequence_is_valid, LanguageSpan, LanguageSpanBoundaryAuthority, LanguageSpanDisposition,
        LANGUAGE_SPAN_SAMPLE_RATE_HZ, LANGUAGE_SPAN_SCHEMA_VERSION,
    },
    valid_bcp47,
};

const YAP_SPEAKER_RECONCILIATION_COMPONENT_ID: &str = "yap/speaker-epoch-reconciliation";
const MAX_SERVER_STAGE_ATTEMPTS: u64 = 64;
const MAX_SERVER_STAGE_REASON_CHARS: usize = 512;
const MAX_TRANSCRIPT_BYTES: usize = 1024 * 1024;
pub(crate) const MAX_TRANSCRIPT_RESULT_BYTES: usize = 4 * 1024 * 1024;
pub(crate) const MAX_SPEAKER_RESULT_BYTES: usize = 4 * 1024 * 1024;
const MAX_SPEAKER_TURNS: usize = 100_000;

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct RecordingJob {
    pub job_id: String,
    pub session_id: String,
    pub display_name: String,
    pub session_mode: String,
    pub session_origin: String,
    pub status: String,
    pub route: Option<String>,
    pub capture_manifest: CaptureManifestReferenceWire,
    pub progress_percent: Option<f64>,
    pub progress_message: Option<String>,
    pub error: Option<ApiError>,
    pub created_at_utc: String,
    pub updated_at_utc: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CaptureManifestReferenceWire {
    pub schema_version: u16,
    pub session_id: String,
    pub sha256: String,
    pub byte_length: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ApiError {
    pub code: String,
    pub message: String,
    pub retryable: bool,
    pub request_id: String,
}

impl ApiError {
    pub(crate) fn is_valid(&self) -> bool {
        !self.code.is_empty()
            && self.code.len() <= 64
            && self
                .code
                .bytes()
                .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
            && !self.message.is_empty()
            && self.message.len() <= 512
            && !self.message.chars().any(char::is_control)
            && valid_path_segment(&self.request_id)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ChunkUploadReceipt {
    pub replay_key: ServerReplayKeyWire,
    pub content_identity: ContentIdentityWire,
    pub disposition: String,
    pub accepted_at_utc: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ServerReplayKeyWire {
    pub schema_version: u16,
    pub session_id: String,
    pub track_id: String,
    pub sequence_start: u64,
    pub sequence_end: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ContentIdentityWire {
    pub sha256: String,
    pub byte_length: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct TranscriptResultRevision {
    pub session_id: String,
    pub revision: u64,
    pub authority: String,
    pub created_at_utc: String,
    pub capture_manifest_sha256: String,
    pub previous_result_sha256: Option<String>,
    pub status: String,
    pub language: Option<LanguageDecision>,
    pub transcript: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub speaker_result_sha256: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub language_segments: Option<Vec<LanguageSegment>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub language_span_evidence: Option<ServerLanguageSpanEvidence>,
    pub alignment: AlignmentOutcome,
    pub aligned_words: Vec<AlignedWord>,
    pub model_provenance: Vec<ModelRevision>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct SpeakerResultRevision {
    pub session_id: String,
    pub revision: u64,
    pub authority: String,
    pub created_at_utc: String,
    pub capture_manifest_sha256: String,
    pub previous_result_sha256: Option<String>,
    pub status: String,
    pub language: LanguageDecision,
    pub runtime_lock_sha256: String,
    pub speaker_turns: Vec<SpeakerTurn>,
    pub speaker_capacity_degradation: SpeakerCapacityDegradation,
    pub alignment: AlignmentOutcome,
    pub aligned_words: Vec<AlignedWord>,
    pub model_provenance: Vec<ModelRevision>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub(crate) enum SpeakerCapacityDegradation {
    None(()),
    Reached(SpeakerCapacityReached),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct SpeakerCapacityReached {
    pub code: String,
    pub scope: SpeakerCapacityScope,
    pub start_sample: u64,
    pub end_sample: u64,
    pub observed_speaker_count: u8,
    pub speaker_limit: u8,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum SpeakerCapacityScope {
    DecodeWindow,
    Meeting,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct SpeakerTurn {
    pub turn_id: String,
    pub start_ms: u64,
    pub end_ms: u64,
    pub text: String,
    pub attribution: AnonymousSpeakerAttribution,
    pub confidence: Option<f64>,
    pub supporting_track_ids: Vec<String>,
    pub overlap_group_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum AnonymousSpeakerAttribution {
    SessionSpeaker {
        #[serde(rename = "sessionSpeakerId")]
        session_speaker_id: String,
    },
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct AlignmentOutcome {
    pub status: AlignmentStatus,
    pub reason: Option<AlignmentUnavailableReason>,
    pub component_revision: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum AlignmentStatus {
    Available,
    Unavailable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) enum AlignmentUnavailableReason {
    #[serde(rename = "ALIGNMENT_EMPTY_TRANSCRIPT")]
    EmptyTranscript,
    #[serde(rename = "ALIGNMENT_PROVIDER_UNSUPPORTED")]
    ProviderUnsupported,
    #[serde(rename = "ALIGNMENT_LANGUAGE_UNSUPPORTED")]
    LanguageUnsupported,
    #[serde(rename = "ALIGNMENT_TOKEN_LIMIT")]
    TokenLimit,
    #[serde(rename = "ALIGNMENT_WORD_LIMIT")]
    WordLimit,
    #[serde(rename = "ALIGNMENT_SOURCE_LIMIT")]
    SourceLimit,
    #[serde(rename = "ALIGNMENT_TOKEN_TRANSCRIPT_DIVERGED")]
    TokenTranscriptDiverged,
    #[serde(rename = "ALIGNMENT_EVIDENCE_INVALID")]
    EvidenceInvalid,
    #[serde(rename = "ALIGNMENT_RESULT_LIMIT")]
    ResultLimit,
    #[serde(rename = "ALIGNMENT_RUNTIME_FAILED")]
    RuntimeFailed,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct AlignedWord {
    pub word_index: u64,
    pub text: String,
    pub start_ms: u64,
    pub end_ms: u64,
    pub turn_id: Option<String>,
    pub attribution: AlignedWordAttribution,
    pub confidence: Option<f64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub(crate) enum AlignedWordAttribution {
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LanguageSegment {
    pub index: u64,
    pub source_span_index: u64,
    pub text: String,
    pub status: LanguageSegmentStatus,
    pub language_bcp47: Option<String>,
    pub raw_language_tag: Option<String>,
    pub reason: Option<LanguageSegmentReason>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ServerLanguageSpanEvidence {
    pub schema_version: u16,
    pub sample_rate_hz: u32,
    pub source_end_sample: u64,
    pub boundary_authority: LanguageSpanBoundaryAuthority,
    pub provider_id: String,
    pub pool_id: String,
    pub model_id: String,
    pub model_revision: String,
    pub utterance_plan_sha256: String,
    pub spans: Vec<LanguageSpan>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) enum LanguageSegmentStatus {
    Detected,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) enum LanguageSegmentReason {
    #[serde(rename = "DISABLED_LANGUAGE_TAG")]
    DisabledLanguageTag,
    #[serde(rename = "EMPTY_TAGGED_TRANSCRIPT")]
    EmptyTaggedTranscript,
    #[serde(rename = "MISSING_LANGUAGE_TAG")]
    MissingLanguageTag,
}

impl TranscriptResultRevision {
    pub(crate) fn requires_speaker_result(&self) -> bool {
        self.speaker_result_sha256.is_some()
    }

    pub(crate) fn transcript_is_canonical(&self) -> bool {
        self.transcript.len() <= MAX_TRANSCRIPT_BYTES
            && !self.transcript.contains('\0')
            && !self.transcript.starts_with(' ')
            && !self.transcript.ends_with(' ')
            && !self.transcript.contains("  ")
            && !self
                .transcript
                .chars()
                .any(|character| character.is_whitespace() && character != ' ')
    }

    pub(crate) fn language_evidence_is_valid(
        &self,
        expected_source_end_sample: Option<u64>,
        maximum_end_ms: u64,
    ) -> bool {
        let Some(language) = self.language.as_ref() else {
            return false;
        };
        match (
            language.language_bcp47.as_str(),
            self.language_segments.as_ref(),
            self.language_span_evidence.as_ref(),
        ) {
            ("und", Some(segments), Some(evidence)) => {
                let Some(model) = self.model_provenance.first() else {
                    return false;
                };
                if self.model_provenance.len() != 1
                    || !evidence.is_valid_for(expected_source_end_sample, maximum_end_ms, model)
                    || segments.is_empty()
                    || segments.len() > 4_096
                {
                    return false;
                }
                let mut rendered = Vec::with_capacity(segments.len());
                let mut by_source_span = vec![Vec::new(); evidence.spans.len()];
                for (index, segment) in segments.iter().enumerate() {
                    let Ok(source_span_index) = usize::try_from(segment.source_span_index) else {
                        return false;
                    };
                    if segment.index != index as u64
                        || source_span_index >= evidence.spans.len()
                        || segment.text.contains('\0')
                        || segment.text
                            != segment
                                .text
                                .split_whitespace()
                                .collect::<Vec<_>>()
                                .join(" ")
                    {
                        return false;
                    }
                    let valid = match segment.status {
                        LanguageSegmentStatus::Detected => {
                            !segment.text.is_empty()
                                && segment.language_bcp47.as_deref()
                                    == segment.raw_language_tag.as_deref()
                                && segment.language_bcp47.as_deref().is_some_and(valid_bcp47)
                                && segment.reason.is_none()
                        }
                        LanguageSegmentStatus::Unknown => {
                            segment.language_bcp47.is_none()
                                && match segment.reason {
                                    Some(LanguageSegmentReason::MissingLanguageTag) => {
                                        segment.raw_language_tag.is_none()
                                    }
                                    Some(LanguageSegmentReason::DisabledLanguageTag) => {
                                        segment.raw_language_tag.as_deref().is_some_and(valid_bcp47)
                                    }
                                    Some(LanguageSegmentReason::EmptyTaggedTranscript) => {
                                        segment.text.is_empty()
                                            && segment
                                                .raw_language_tag
                                                .as_deref()
                                                .is_some_and(valid_bcp47)
                                    }
                                    None => false,
                                }
                        }
                    };
                    if !valid {
                        return false;
                    }
                    by_source_span[source_span_index].push(segment);
                    if !segment.text.is_empty() {
                        rendered.push(segment.text.as_str());
                    }
                }
                rendered.join(" ") == self.transcript
                    && by_source_span.iter().zip(&evidence.spans).all(
                        |(source_segments, source_span)| {
                            source_span_matches_segments(source_span, source_segments)
                        },
                    )
            }
            (fixed_language, None, None) => fixed_language != "und",
            _ => false,
        }
    }

    pub(crate) fn alignment_is_valid(&self, maximum_end_ms: u64) -> bool {
        let alignment = &self.alignment;
        match alignment.status {
            AlignmentStatus::Unavailable => {
                alignment.reason.is_some()
                    && matches!(
                        alignment.component_revision.as_str(),
                        "cohere-attention-en-v1"
                            | "cohere-attention-alignment-candidate-v1"
                            | "joint-segment-timing-v1"
                    )
                    && self.aligned_words.is_empty()
            }
            AlignmentStatus::Available => {
                if alignment.reason.is_some()
                    || alignment.component_revision != "cohere-attention-en-v1"
                    || self.aligned_words.is_empty()
                    || self.aligned_words.len() > 16_384
                {
                    return false;
                }
                let mut previous_end = 0_u64;
                let mut rendered = Vec::with_capacity(self.aligned_words.len());
                for (index, word) in self.aligned_words.iter().enumerate() {
                    if word.word_index != index as u64
                        || word.text.is_empty()
                        || word.text.len() > 512
                        || word.text.chars().any(char::is_whitespace)
                        || word.start_ms < previous_end
                        || word.end_ms <= word.start_ms
                        || word.end_ms > maximum_end_ms
                        || word.turn_id.is_some()
                        || word.attribution != AlignedWordAttribution::Unknown
                        || word.confidence.is_some()
                    {
                        return false;
                    }
                    previous_end = word.end_ms;
                    rendered.push(word.text.as_str());
                }
                rendered.join(" ") == self.transcript
            }
        }
    }
}

impl SpeakerResultRevision {
    pub(crate) fn content_sha256(&self) -> Option<String> {
        let encoded = serde_json::to_vec(self).ok()?;
        let digest = Sha256::digest(encoded);
        Some(digest.iter().map(|byte| format!("{byte:02x}")).collect())
    }

    pub(crate) fn is_valid_for(
        &self,
        transcript: &TranscriptResultRevision,
        source_duration_ms: u64,
        expected_source_end_sample: Option<u64>,
        source_track_ids: &[String],
    ) -> bool {
        if self.session_id != transcript.session_id
            || self.revision != transcript.revision
            || self.authority != transcript.authority
            || self.created_at_utc != transcript.created_at_utc
            || self.capture_manifest_sha256 != transcript.capture_manifest_sha256
            || self.previous_result_sha256 != transcript.previous_result_sha256
            || self.status != transcript.status
            || transcript.language.as_ref() != Some(&self.language)
            || transcript.speaker_result_sha256.as_deref() != self.content_sha256().as_deref()
            || !super::validation::valid_sha256(&self.runtime_lock_sha256)
            || self.alignment.status != AlignmentStatus::Unavailable
            || self.alignment.reason != Some(AlignmentUnavailableReason::ProviderUnsupported)
            || self.alignment.component_revision != "joint-segment-timing-v1"
            || !self.aligned_words.is_empty()
            || self.speaker_turns.len() > MAX_SPEAKER_TURNS
            || self.model_provenance.len() != 4
            || self.model_provenance.first() != transcript.model_provenance.first()
            || self
                .model_provenance
                .last()
                .map(|model| model.model_id.as_str())
                != Some(YAP_SPEAKER_RECONCILIATION_COMPONENT_ID)
            || self
                .model_provenance
                .iter()
                .map(|model| model.model_id.as_str())
                .collect::<BTreeSet<_>>()
                .len()
                != 4
            || self.model_provenance.iter().any(|model| {
                model.model_id.is_empty()
                    || model.model_id.len() > 256
                    || model.revision.len() != 40
                    || !model
                        .revision
                        .bytes()
                        .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
                    || model.calibration_revision != self.runtime_lock_sha256
            })
            || !self.speaker_capacity_degradation.is_valid_for(
                &self.status,
                source_duration_ms,
                expected_source_end_sample,
            )
        {
            return false;
        }

        let mut previous_start_ms = 0_u64;
        let mut intervals = Vec::with_capacity(self.speaker_turns.len());
        let mut rendered_text = Vec::with_capacity(self.speaker_turns.len());
        let mut observed_speakers = BTreeSet::new();
        for (index, turn) in self.speaker_turns.iter().enumerate() {
            let expected_turn_id = format!("turn-{:06}", index + 1);
            let speaker_id_is_canonical = match &turn.attribution {
                AnonymousSpeakerAttribution::SessionSpeaker { session_speaker_id } => {
                    let canonical = (1..=64).any(|speaker_number| {
                        session_speaker_id == &format!("speaker-{speaker_number}")
                    });
                    if canonical {
                        observed_speakers.insert(session_speaker_id.as_str());
                    }
                    canonical
                }
                AnonymousSpeakerAttribution::Unknown => true,
            };
            if turn.turn_id != expected_turn_id
                || (index > 0 && turn.start_ms < previous_start_ms)
                || turn.end_ms <= turn.start_ms
                || turn.end_ms > source_duration_ms
                || !canonical_nonempty_transcript_text(&turn.text)
                || turn.confidence.is_some()
                || turn.supporting_track_ids != source_track_ids
                || !speaker_id_is_canonical
            {
                return false;
            }
            previous_start_ms = turn.start_ms;
            intervals.push((turn.start_ms, turn.end_ms));
            rendered_text.push(turn.text.as_str());
        }
        let capacity_roster_is_valid = match &self.speaker_capacity_degradation {
            SpeakerCapacityDegradation::Reached(degradation)
                if degradation.scope == SpeakerCapacityScope::Meeting =>
            {
                observed_speakers.len() == 64
            }
            _ => true,
        };
        capacity_roster_is_valid
            && observed_speakers.len() <= 64
            && rendered_text.join(" ") == transcript.transcript
            && expected_overlap_groups(&intervals)
                == self
                    .speaker_turns
                    .iter()
                    .map(|turn| turn.overlap_group_id.clone())
                    .collect::<Vec<_>>()
    }
}

impl SpeakerCapacityDegradation {
    fn is_valid_for(
        &self,
        status: &str,
        source_duration_ms: u64,
        expected_source_end_sample: Option<u64>,
    ) -> bool {
        let Self::Reached(degradation) = self else {
            return status == "complete";
        };
        if status != "partial"
            || degradation.code != "SPEAKER_CAPACITY_REACHED"
            || degradation.observed_speaker_count != degradation.speaker_limit
        {
            return false;
        }
        let Some(maximum_source_end) = source_duration_ms
            .checked_mul(16)
            .and_then(|value| value.checked_add(15))
        else {
            return false;
        };
        if degradation.start_sample >= degradation.end_sample
            || degradation.end_sample > maximum_source_end
        {
            return false;
        }
        match degradation.scope {
            SpeakerCapacityScope::DecodeWindow => {
                let Some(expected_source_end) = expected_source_end_sample else {
                    return false;
                };
                degradation.speaker_limit == 8
                    && degradation.start_sample % 480_000 == 0
                    && degradation.end_sample
                        == expected_source_end.min(degradation.start_sample + 480_000)
            }
            SpeakerCapacityScope::Meeting => {
                degradation.speaker_limit == 64
                    && degradation.start_sample == 0
                    && expected_source_end_sample
                        .is_none_or(|expected| degradation.end_sample == expected)
            }
        }
    }
}

fn canonical_nonempty_transcript_text(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_TRANSCRIPT_BYTES
        && !value.contains('\0')
        && !value.starts_with(' ')
        && !value.ends_with(' ')
        && !value.contains("  ")
        && !value
            .chars()
            .any(|character| character.is_whitespace() && character != ' ')
}

fn expected_overlap_groups(intervals: &[(u64, u64)]) -> Vec<Option<String>> {
    let mut groups = vec![None; intervals.len()];
    let mut group_number = 0_usize;
    let mut start = 0_usize;
    while start < intervals.len() {
        let mut end = start + 1;
        let mut maximum_end = intervals[start].1;
        while end < intervals.len() && intervals[end].0 < maximum_end {
            maximum_end = maximum_end.max(intervals[end].1);
            end += 1;
        }
        if end - start > 1 {
            group_number += 1;
            let group_id = format!("overlap-{group_number:06}");
            groups[start..end].fill(Some(group_id));
        }
        start = end;
    }
    groups
}

impl ServerLanguageSpanEvidence {
    fn is_valid_for(
        &self,
        expected_source_end_sample: Option<u64>,
        maximum_end_ms: u64,
        model: &ModelRevision,
    ) -> bool {
        let maximum_source_samples = maximum_end_ms
            .checked_mul(u64::from(LANGUAGE_SPAN_SAMPLE_RATE_HZ) / 1_000)
            .and_then(|samples| samples.checked_add(15));
        self.schema_version == LANGUAGE_SPAN_SCHEMA_VERSION
            && self.sample_rate_hz == LANGUAGE_SPAN_SAMPLE_RATE_HZ
            && self.source_end_sample > 0
            && maximum_source_samples.is_some_and(|maximum| self.source_end_sample <= maximum)
            && expected_source_end_sample.is_none_or(|expected| self.source_end_sample == expected)
            && self.boundary_authority == LanguageSpanBoundaryAuthority::ServerUtterance
            && valid_route_id(&self.provider_id)
            && valid_route_id(&self.pool_id)
            && valid_model_id(&self.model_id)
            && valid_model_revision(&self.model_revision)
            && self.model_id == model.model_id
            && self.model_revision == model.revision
            && super::validation::valid_sha256(&self.utterance_plan_sha256)
            && sequence_is_valid(self.boundary_authority, self.source_end_sample, &self.spans)
            && self.spans.iter().all(|span| {
                span.component_revision.as_deref() == Some(self.model_revision.as_str())
            })
    }
}

fn source_span_matches_segments(source_span: &LanguageSpan, segments: &[&LanguageSegment]) -> bool {
    if segments.is_empty() {
        return false;
    }
    let mut detected = BTreeSet::new();
    let mut has_nonempty_unknown = false;
    for segment in segments {
        if segment.text.is_empty() {
            continue;
        }
        match segment.status {
            LanguageSegmentStatus::Detected => {
                let Some(language) = segment.language_bcp47.as_deref() else {
                    return false;
                };
                detected.insert(language);
            }
            LanguageSegmentStatus::Unknown => has_nonempty_unknown = true,
        }
    }
    if detected.len() == 1 && !has_nonempty_unknown {
        source_span.disposition == LanguageSpanDisposition::ServerDetected
            && source_span.language_bcp47 == *detected.first().unwrap()
    } else {
        source_span.disposition == LanguageSpanDisposition::ServerUnknown
            && source_span.language_bcp47 == "und"
    }
}

fn valid_route_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn valid_model_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value.is_ascii()
        && !value
            .bytes()
            .any(|byte| byte.is_ascii_control() || byte == b' ')
}

fn valid_model_revision(value: &str) -> bool {
    value.len() == 40
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LanguageDecision {
    pub language_bcp47: String,
    pub confidence: Option<f64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ModelRevision {
    pub model_id: String,
    pub revision: String,
    pub calibration_revision: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ServerStageName {
    Asr,
    Alignment,
    ResultPublication,
}

impl ServerStageName {
    pub(crate) const fn as_path(self) -> &'static str {
        match self {
            Self::Asr => "asr",
            Self::Alignment => "alignment",
            Self::ResultPublication => "result_publication",
        }
    }

    const fn order(self) -> u8 {
        match self {
            Self::Asr => 0,
            Self::Alignment => 1,
            Self::ResultPublication => 2,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ServerStageState {
    Running,
    Succeeded,
    Unavailable,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ServerStageProjection {
    pub stage: ServerStageName,
    pub attempt: u64,
    pub state: ServerStageState,
    pub updated_at_utc: String,
    pub retryable: Option<bool>,
    pub reason: Option<String>,
}

impl ServerStageProjection {
    fn is_valid(&self) -> bool {
        if !(1..=MAX_SERVER_STAGE_ATTEMPTS).contains(&self.attempt)
            || self.updated_at_utc.is_empty()
            || self.updated_at_utc.len() > 64
            || !self.updated_at_utc.ends_with('Z')
            || self.reason.as_ref().is_some_and(|reason| {
                reason.is_empty()
                    || reason.len() > MAX_SERVER_STAGE_REASON_CHARS
                    || !reason.bytes().all(|byte| {
                        byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_'
                    })
            })
        {
            return false;
        }
        match self.state {
            ServerStageState::Running => self.retryable.is_none() && self.reason.is_none(),
            ServerStageState::Succeeded => self.retryable == Some(false) && self.reason.is_none(),
            ServerStageState::Unavailable
            | ServerStageState::Failed
            | ServerStageState::Cancelled => self.retryable.is_some() && self.reason.is_some(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ServerStageProjectionEnvelope {
    pub schema_version: u16,
    pub job_id: String,
    pub projection_revision: u64,
    pub history_complete: bool,
    pub stages: Vec<ServerStageProjection>,
}

impl ServerStageProjectionEnvelope {
    pub(crate) fn is_valid_for(&self, expected_job_id: &str) -> bool {
        if self.schema_version != 1
            || self.job_id != expected_job_id
            || !valid_path_segment(&self.job_id)
            || self.projection_revision == 0
            || self.stages.len() > 3
            || self.stages.iter().any(|stage| !stage.is_valid())
        {
            return false;
        }
        self.stages
            .windows(2)
            .all(|pair| pair[0].stage.order() < pair[1].stage.order())
    }
}
