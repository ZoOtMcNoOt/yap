use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use time::{format_description::well_known::Rfc3339, Duration, OffsetDateTime};

use super::{
    validation::{valid_path_segment, valid_sha256},
    BatchClientError, PreprocessingEvidence,
};
use crate::language::{RecordingLanguageDecision, RecordingLanguageMode};

#[cfg(test)]
mod test_fixture;

const MAX_CREATE_REQUEST_BYTES: usize = 1024 * 1024;
const MAX_JOB_CHUNKS: usize = 4096;
const MAX_CHUNK_BYTES: u64 = 1024 * 1024;
const MAX_JOB_PCM_BYTES: u64 = 16_000 * 2 * 4 * 60 * 60;
const MAX_PRIVATE_RETENTION_DAYS: i64 = 30;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CaptureManifestReference {
    pub schema_version: u16,
    pub session_id: String,
    pub sha256: String,
    pub byte_length: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ServerReplayKey {
    pub schema_version: u16,
    pub session_id: String,
    pub track_id: String,
    pub sequence_start: u64,
    pub sequence_end: u64,
}

impl ServerReplayKey {
    pub(super) fn idempotency_key(&self) -> String {
        format!(
            "{}/{}/{}/{}/{}",
            self.schema_version,
            self.session_id,
            self.track_id,
            self.sequence_start,
            self.sequence_end
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ContentIdentity {
    pub sha256: String,
    pub byte_length: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CaptureChunkReference {
    pub replay_key: ServerReplayKey,
    pub content_identity: ContentIdentity,
    pub audio_codec: String,
    pub sample_rate_hz: u32,
    pub channels: u16,
    pub start_ms: u64,
    pub duration_ms: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct UploadTrack {
    pub track_id: String,
    pub source: serde_json::Value,
    pub device_id: Option<String>,
    pub original_sample_rate_hz: u32,
    pub original_channels: u16,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CreateRecordingJobRequest {
    pub display_name: String,
    pub metadata: crate::audio::session::SessionMetadata,
    pub language_decision: RecordingLanguageDecision,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub asr_catalog_revision: Option<String>,
    pub tracks: Vec<UploadTrack>,
    pub route: String,
    pub capture_manifest: CaptureManifestReference,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub preprocessing_evidence: Option<PreprocessingEvidence>,
    pub chunks: Vec<CaptureChunkReference>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct PreparedRecordingBounds {
    pub duration_ms: u64,
    pub end_sample: u64,
    pub track_ids: Vec<String>,
}

impl CreateRecordingJobRequest {
    pub(crate) fn decode_persisted(encoded: &str) -> Result<Self, BatchClientError> {
        if encoded.len() < 2 || encoded.len() > MAX_CREATE_REQUEST_BYTES {
            return Err(BatchClientError::InvalidPersistedRequest);
        }
        let raw: serde_json::Value =
            serde_json::from_str(encoded).map_err(|_| BatchClientError::InvalidPersistedRequest)?;
        let request: Self = serde_json::from_value(raw.clone())
            .map_err(|_| BatchClientError::InvalidPersistedRequest)?;
        let canonical = serde_json::to_value(&request)
            .map_err(|_| BatchClientError::InvalidPersistedRequest)?;
        if raw != canonical || !request.is_valid_current_slice() {
            return Err(BatchClientError::InvalidPersistedRequest);
        }
        Ok(request)
    }

    pub(crate) fn create_idempotency_key(&self) -> Result<String, BatchClientError> {
        let encoded = serde_json::to_vec(self).map_err(BatchClientError::Encode)?;
        let digest = Sha256::digest(encoded);
        let hex = digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        Ok(format!("create-{hex}"))
    }

    pub(crate) fn recording_bounds(&self) -> Result<PreparedRecordingBounds, String> {
        let duration_ms = self
            .chunks
            .iter()
            .try_fold(0_u64, |total, chunk| {
                total.checked_add(u64::from(chunk.duration_ms))
            })
            .ok_or_else(|| "prepared recording duration overflowed".to_string())?;
        let end_sample = self
            .chunks
            .iter()
            .try_fold(0_u64, |total, chunk| {
                total.checked_add(chunk.content_identity.byte_length / 2)
            })
            .ok_or_else(|| "prepared recording sample count overflowed".to_string())?;
        Ok(PreparedRecordingBounds {
            duration_ms,
            end_sample,
            track_ids: self
                .tracks
                .iter()
                .map(|track| track.track_id.clone())
                .collect(),
        })
    }

    fn is_valid_current_slice(&self) -> bool {
        use crate::audio::session::{SessionMode, SessionOrigin};

        if self.display_name.is_empty()
            || self.display_name.len() > 256
            || self.route != "server_batch"
            || self.metadata.mode != SessionMode::Meeting
            || self.metadata.origin != SessionOrigin::ImportedFile
            || !self.has_consistent_language_decision()
            || !valid_private_retention(&self.metadata)
            || self.tracks.len() != 1
            || self.chunks.is_empty()
            || self.chunks.len() > MAX_JOB_CHUNKS
        {
            return false;
        }
        let session_id = self.metadata.session_id.as_str();
        let manifest_contract_is_valid = self.capture_manifest.schema_version == 2
            && self.preprocessing_evidence.is_some()
            && self
                .asr_catalog_revision
                .as_deref()
                .is_some_and(valid_sha256);
        if self.capture_manifest.session_id != session_id
            || !valid_sha256(&self.capture_manifest.sha256)
            || !(1..=MAX_CREATE_REQUEST_BYTES as u64).contains(&self.capture_manifest.byte_length)
            || !manifest_contract_is_valid
        {
            return false;
        }
        let track = &self.tracks[0];
        if !valid_path_segment(&track.track_id)
            || track.device_id.is_some()
            || track.original_sample_rate_hz != 16_000
            || track.original_channels != 1
            || track.source != serde_json::json!({"kind": "imported", "provenance": "unknown"})
        {
            return false;
        }

        let mut expected_sequence_start = 0_u64;
        let mut expected_start_ms = 0_u64;
        let mut total_pcm_bytes = 0_u64;
        for chunk in &self.chunks {
            let replay = &chunk.replay_key;
            let content = &chunk.content_identity;
            if replay.schema_version != 1
                || replay.session_id != session_id
                || replay.track_id != track.track_id
                || replay.sequence_start != expected_sequence_start
                || replay.sequence_end < replay.sequence_start
                || !valid_sha256(&content.sha256)
                || !(2..=MAX_CHUNK_BYTES).contains(&content.byte_length)
                || content.byte_length % 2 != 0
                || chunk.audio_codec != "pcm_s16le"
                || chunk.sample_rate_hz != 16_000
                || chunk.channels != 1
                || chunk.start_ms != expected_start_ms
                || chunk.duration_ms == 0
            {
                return false;
            }
            let sample_count = replay
                .sequence_end
                .checked_sub(replay.sequence_start)
                .and_then(|count| count.checked_add(1));
            if sample_count != Some(content.byte_length / 2)
                || u128::from(content.byte_length) * 1000
                    != u128::from(chunk.duration_ms) * 16_000 * 2
            {
                return false;
            }
            let Some(next_total_pcm_bytes) = total_pcm_bytes.checked_add(content.byte_length)
            else {
                return false;
            };
            if next_total_pcm_bytes > MAX_JOB_PCM_BYTES {
                return false;
            }
            let Some(next_sequence) = replay.sequence_end.checked_add(1) else {
                return false;
            };
            let Some(next_start_ms) = expected_start_ms.checked_add(u64::from(chunk.duration_ms))
            else {
                return false;
            };
            total_pcm_bytes = next_total_pcm_bytes;
            expected_sequence_start = next_sequence;
            expected_start_ms = next_start_ms;
        }
        match &self.preprocessing_evidence {
            None => true,
            Some(evidence) => evidence.is_valid_for_output_samples(total_pcm_bytes / 2),
        }
    }

    fn has_consistent_language_decision(&self) -> bool {
        if self.language_decision.mode != RecordingLanguageMode::Fixed {
            return false;
        }
        let Some(language) = self.language_decision.language_bcp47.as_deref() else {
            return false;
        };
        self.metadata.locale_hint_bcp47.as_deref() == Some(language)
            && self.metadata.preferred_languages_bcp47.as_slice() == [language]
    }
}

fn valid_private_retention(metadata: &crate::audio::session::SessionMetadata) -> bool {
    let Some(retention) = metadata.retention_expires_at_utc.as_deref() else {
        return false;
    };
    if !metadata.started_at_utc.ends_with('Z') || !retention.ends_with('Z') {
        return false;
    }
    let Ok(started_at) = OffsetDateTime::parse(&metadata.started_at_utc, &Rfc3339) else {
        return false;
    };
    let Ok(retention_at) = OffsetDateTime::parse(retention, &Rfc3339) else {
        return false;
    };
    retention_at > started_at
        && retention_at - started_at <= Duration::days(MAX_PRIVATE_RETENTION_DAYS)
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CommitRecordingJobRequest {
    pub capture_manifest: CaptureManifestReference,
    pub chunk_count: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct RetryServerStageRequest {
    pub stage: super::ServerStageName,
    pub attempt: u64,
    pub projection_revision: u64,
    pub capture_manifest_sha256: String,
}
