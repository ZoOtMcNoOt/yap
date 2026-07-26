use super::{
    CaptureChunkReference, CaptureManifestReference, ContentIdentity, CreateRecordingJobRequest,
    ServerReplayKey, UploadTrack,
};
use crate::{
    audio::session::{SessionId, SessionMetadata, SessionMode, SessionOrigin, TriggerMode},
    language::RecordingLanguageDecision,
    server_connector::batch::{
        NormalizationEvidence, PreprocessingEvidence, VadComponentEvidence, VadEvidence,
    },
};

impl CreateRecordingJobRequest {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn for_test_single_chunk(
        display_name: &str,
        session_id: &str,
        track_id: &str,
        capture_manifest_sha256: &str,
        capture_manifest_byte_length: u64,
        chunk_sha256: &str,
        chunk_byte_length: u64,
        language_decision: RecordingLanguageDecision,
        asr_catalog_revision: &str,
    ) -> Self {
        assert!(chunk_byte_length > 0 && chunk_byte_length.is_multiple_of(32));
        let sample_count = chunk_byte_length / 2;
        let language = language_decision
            .language_bcp47
            .clone()
            .expect("test request uses a fixed language");
        Self {
            display_name: display_name.into(),
            metadata: SessionMetadata {
                session_id: SessionId::new(session_id).unwrap(),
                mode: SessionMode::Meeting,
                origin: SessionOrigin::ImportedFile,
                trigger_mode: TriggerMode::Toggle,
                started_at_utc: "2026-07-16T12:00:00Z".into(),
                utc_offset_minutes_at_start: Some(0),
                locale_hint_bcp47: Some(language.clone()),
                country_code_hint: None,
                preferred_languages_bcp47: vec![language],
                app_version: "test".into(),
                platform: "test".into(),
                privacy_policy_version: "test".into(),
                retention_expires_at_utc: Some("2026-07-17T12:00:00Z".into()),
            },
            language_decision,
            asr_catalog_revision: Some(asr_catalog_revision.into()),
            tracks: vec![UploadTrack {
                track_id: track_id.into(),
                source: serde_json::json!({"kind": "imported", "provenance": "unknown"}),
                device_id: None,
                original_sample_rate_hz: 16_000,
                original_channels: 1,
            }],
            route: "server_batch".into(),
            capture_manifest: CaptureManifestReference {
                schema_version: 2,
                session_id: session_id.into(),
                sha256: capture_manifest_sha256.into(),
                byte_length: capture_manifest_byte_length,
            },
            preprocessing_evidence: Some(PreprocessingEvidence::new(
                NormalizationEvidence::canonical_pcm16_identity(
                    "c".repeat(64),
                    chunk_sha256.into(),
                    chunk_sha256.into(),
                    sample_count,
                    sample_count,
                    0,
                ),
                VadEvidence::error(
                    VadComponentEvidence::for_test("test-vad", "test-v1"),
                    sample_count,
                    "artifact_unavailable",
                ),
            )),
            chunks: vec![CaptureChunkReference {
                replay_key: ServerReplayKey {
                    schema_version: 1,
                    session_id: session_id.into(),
                    track_id: track_id.into(),
                    sequence_start: 0,
                    sequence_end: sample_count - 1,
                },
                content_identity: ContentIdentity {
                    sha256: chunk_sha256.into(),
                    byte_length: chunk_byte_length,
                },
                audio_codec: "pcm_s16le".into(),
                sample_rate_hz: 16_000,
                channels: 1,
                start_ms: 0,
                duration_ms: u32::try_from(chunk_byte_length / 32).unwrap(),
            }],
        }
    }
}
