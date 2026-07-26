use std::{
    io::{Read, Write},
    net::TcpListener,
    time::{Duration, UNIX_EPOCH},
};

use sha2::Digest;

use crate::audio::session::{SessionId, SessionMetadata, SessionMode, SessionOrigin, TriggerMode};
use crate::language::RecordingLanguageDecision;

use super::{
    validate_batch_base_url, AlignmentUnavailableReason, ApiError, BatchApiClient,
    BatchClientError, CaptureChunkReference, CaptureManifestReference, ContentIdentity,
    CreateRecordingJobRequest, ServerReplayKey, ServerStageProjectionEnvelope, UploadTrack,
};
use crate::server_connector::{client::bounded_client, RequestAuthorization};

#[test]
fn alignment_unavailable_reason_preserves_provider_and_language_limits() {
    assert_eq!(
        serde_json::from_str::<AlignmentUnavailableReason>(r#""ALIGNMENT_PROVIDER_UNSUPPORTED""#,)
            .unwrap(),
        AlignmentUnavailableReason::ProviderUnsupported,
    );
    assert_eq!(
        serde_json::from_str::<AlignmentUnavailableReason>(r#""ALIGNMENT_LANGUAGE_UNSUPPORTED""#,)
            .unwrap(),
        AlignmentUnavailableReason::LanguageUnsupported,
    );
}

#[test]
fn batch_transport_accepts_https_and_explicit_local_development_origins() {
    assert_eq!(
        validate_batch_base_url("http://127.0.0.1:18765").unwrap(),
        "http://127.0.0.1:18765"
    );
    assert_eq!(
        validate_batch_base_url("http://[::1]:18765/v1").unwrap(),
        "http://[::1]:18765"
    );
    assert_eq!(
        validate_batch_base_url("http://localhost:18765").unwrap(),
        "http://localhost:18765"
    );
    assert_eq!(
        validate_batch_base_url("https://yap.internal/v1").unwrap(),
        "https://yap.internal"
    );
    assert!(validate_batch_base_url("http://192.0.2.1:18765").is_err());
}

#[test]
fn shared_batch_dispatch_attaches_the_native_bearer_token() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = [0_u8; 4096];
        let read = stream.read(&mut request).unwrap();
        let request = String::from_utf8_lossy(&request[..read]);
        assert!(request.starts_with("GET /v1/jobs/job-0123456789abcdef0123456789abcdef HTTP/1.1"));
        assert!(request
            .to_ascii_lowercase()
            .contains("authorization: bearer batch-token"));
        let body = br#"{"code":"JOB_NOT_FOUND","message":"Recording job not found.","retryable":false,"requestId":"request-1"}"#;
        let headers = format!(
            "HTTP/1.1 404 Not Found\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        stream.write_all(headers.as_bytes()).unwrap();
        stream.write_all(body).unwrap();
    });
    let client = BatchApiClient::new_authorized(
        bounded_client().unwrap(),
        &format!("http://{address}"),
        RequestAuthorization::fixed("batch-token"),
    )
    .unwrap();

    let error =
        tauri::async_runtime::block_on(client.status("job-0123456789abcdef0123456789abcdef"))
            .unwrap_err();
    server.join().unwrap();

    assert!(matches!(
        error,
        BatchClientError::Api {
            status: reqwest::StatusCode::NOT_FOUND,
            ..
        }
    ));
}

#[test]
fn persisted_create_request_round_trips_strictly_before_resume() {
    let started = UNIX_EPOCH + Duration::from_secs(1_720_000_000);
    let session_id = "s-persisted-request";
    let request = CreateRecordingJobRequest {
        display_name: "interview.wav".into(),
        metadata: SessionMetadata::new(
            SessionId::new(session_id).unwrap(),
            SessionMode::Meeting,
            SessionOrigin::ImportedFile,
            TriggerMode::Toggle,
            started,
            None,
            Some("en-US".into()),
            None,
            vec!["en-US".into()],
            Some(started + Duration::from_secs(3600)),
        )
        .unwrap(),
        language_decision: RecordingLanguageDecision::primary("en-US".into()).unwrap(),
        asr_catalog_revision: None,
        tracks: vec![UploadTrack {
            track_id: "track-1".into(),
            source: serde_json::json!({"kind": "imported", "provenance": "unknown"}),
            device_id: None,
            original_sample_rate_hz: 16_000,
            original_channels: 1,
        }],
        route: "server_batch".into(),
        capture_manifest: CaptureManifestReference {
            schema_version: 1,
            session_id: session_id.into(),
            sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".into(),
            byte_length: 200,
        },
        preprocessing_evidence: None,
        chunks: vec![CaptureChunkReference {
            replay_key: ServerReplayKey {
                schema_version: 1,
                session_id: session_id.into(),
                track_id: "track-1".into(),
                sequence_start: 0,
                sequence_end: 159,
            },
            content_identity: ContentIdentity {
                sha256: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789".into(),
                byte_length: 320,
            },
            audio_codec: "pcm_s16le".into(),
            sample_rate_hz: 16_000,
            channels: 1,
            start_ms: 0,
            duration_ms: 10,
        }],
    };
    let encoded = serde_json::to_string(&request).unwrap();
    let original_key = request.create_idempotency_key().unwrap();

    assert_eq!(
        CreateRecordingJobRequest::decode_persisted(&encoded).unwrap(),
        request
    );
    assert_eq!(request.create_idempotency_key().unwrap(), original_key);
    let encoded_language = serde_json::to_string(&request.language_decision).unwrap();
    let legacy_encoded =
        encoded.replacen(&format!(",\"languageDecision\":{encoded_language}"), "", 1);
    assert_ne!(legacy_encoded, encoded);
    let legacy_value: serde_json::Value = serde_json::from_str(&legacy_encoded).unwrap();
    let legacy_request = CreateRecordingJobRequest::decode_persisted(&legacy_encoded).unwrap();
    assert!(legacy_request
        .language_decision
        .is_legacy_implicit_english_default());
    assert_eq!(serde_json::to_value(&legacy_request).unwrap(), legacy_value);
    assert_eq!(
        legacy_request.create_idempotency_key().unwrap(),
        format!(
            "create-{}",
            sha2::Sha256::digest(legacy_encoded.as_bytes())
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>()
        )
    );
    let mut new_attempt = request.clone();
    new_attempt.display_name = "a distinct immutable request".into();
    assert_ne!(new_attempt.create_idempotency_key().unwrap(), original_key);
    let with_unknown = encoded.replacen('{', r#"{"unexpected":true,"#, 1);
    assert!(CreateRecordingJobRequest::decode_persisted(&with_unknown).is_err());
    let mut missing_retention = request.clone();
    missing_retention.metadata.retention_expires_at_utc = None;
    assert!(CreateRecordingJobRequest::decode_persisted(
        &serde_json::to_string(&missing_retention).unwrap()
    )
    .is_err());
    let mut unbounded_retention = request.clone();
    unbounded_retention.metadata.retention_expires_at_utc = Some("2126-07-14T21:00:00Z".into());
    assert!(CreateRecordingJobRequest::decode_persisted(
        &serde_json::to_string(&unbounded_retention).unwrap()
    )
    .is_err());
    let mut mismatched_language = request.clone();
    mismatched_language.language_decision =
        RecordingLanguageDecision::manual_override("fr-FR".into()).unwrap();
    assert!(CreateRecordingJobRequest::decode_persisted(
        &serde_json::to_string(&mismatched_language).unwrap()
    )
    .is_err());
    let mut dynamic_language = request.clone();
    dynamic_language.language_decision = RecordingLanguageDecision::explicit_dynamic();
    assert!(CreateRecordingJobRequest::decode_persisted(
        &serde_json::to_string(&dynamic_language).unwrap()
    )
    .is_err());

    const FOUR_HOURS_PCM_BYTES: u64 = 16_000 * 2 * 4 * 60 * 60;
    let mut oversized = request;
    let chunk_bytes = 960_000_u64;
    let chunk_frames = chunk_bytes / 2;
    let chunk_duration_ms = 30_000_u32;
    oversized.chunks = (0..=(FOUR_HOURS_PCM_BYTES / chunk_bytes))
        .map(|index| {
            let sequence_start = index * chunk_frames;
            CaptureChunkReference {
                replay_key: ServerReplayKey {
                    schema_version: 1,
                    session_id: session_id.into(),
                    track_id: "track-1".into(),
                    sequence_start,
                    sequence_end: sequence_start + chunk_frames - 1,
                },
                content_identity: ContentIdentity {
                    sha256: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
                        .into(),
                    byte_length: chunk_bytes,
                },
                audio_codec: "pcm_s16le".into(),
                sample_rate_hz: 16_000,
                channels: 1,
                start_ms: index * u64::from(chunk_duration_ms),
                duration_ms: chunk_duration_ms,
            }
        })
        .collect();
    assert!(CreateRecordingJobRequest::decode_persisted(
        &serde_json::to_string(&oversized).unwrap()
    )
    .is_err());
}

#[test]
fn server_retryability_is_preserved_as_typed_transport_state() {
    let retryable = BatchClientError::Api {
        status: reqwest::StatusCode::SERVICE_UNAVAILABLE,
        code: "POOL_BUSY".into(),
        retryable: true,
    };
    let terminal = BatchClientError::Api {
        status: reqwest::StatusCode::CONFLICT,
        code: "MANIFEST_CONFLICT".into(),
        retryable: false,
    };

    assert!(retryable.is_retryable());
    assert!(!terminal.is_retryable());
    assert!(!BatchClientError::MalformedResponse.is_retryable());
}

#[test]
fn server_error_fields_are_bounded_before_logging_or_retry_decisions() {
    let valid = ApiError {
        code: "POOL_BUSY".into(),
        message: "Try again.".into(),
        retryable: true,
        request_id: "job-abc123".into(),
    };
    assert!(valid.is_valid());

    let mut injected_line = valid.clone();
    injected_line.message = "Try again.\nforged log entry".into();
    assert!(!injected_line.is_valid());

    let mut invalid_request_id = valid;
    invalid_request_id.request_id = "../../outside".into();
    assert!(!invalid_request_id.is_valid());
}

#[test]
fn server_stage_projection_is_strict_bounded_and_job_scoped() {
    let job_id = "job-0123456789abcdef0123456789abcdef";
    let valid = serde_json::json!({
        "schemaVersion": 1,
        "jobId": job_id,
        "projectionRevision": 9,
        "historyComplete": true,
        "stages": [
            {
                "stage": "asr",
                "attempt": 2,
                "state": "succeeded",
                "updatedAtUtc": "2026-07-14T21:00:02Z",
                "retryable": false,
                "reason": null
            },
            {
                "stage": "alignment",
                "attempt": 1,
                "state": "unavailable",
                "updatedAtUtc": "2026-07-14T21:00:03Z",
                "retryable": false,
                "reason": "ALIGNMENT_NOT_CONFIGURED"
            }
        ]
    });
    let projection: ServerStageProjectionEnvelope = serde_json::from_value(valid.clone()).unwrap();
    assert!(projection.is_valid_for(job_id));
    assert!(!projection.is_valid_for("job-different"));

    let mut unknown = valid.clone();
    unknown["unexpected"] = serde_json::json!(true);
    assert!(serde_json::from_value::<ServerStageProjectionEnvelope>(unknown).is_err());

    let mut bad_order = valid.clone();
    bad_order["stages"].as_array_mut().unwrap().reverse();
    let bad_order: ServerStageProjectionEnvelope = serde_json::from_value(bad_order).unwrap();
    assert!(!bad_order.is_valid_for(job_id));

    let mut excessive_attempt = valid.clone();
    excessive_attempt["stages"][0]["attempt"] = serde_json::json!(65);
    let excessive_attempt: ServerStageProjectionEnvelope =
        serde_json::from_value(excessive_attempt).unwrap();
    assert!(!excessive_attempt.is_valid_for(job_id));

    let mut injected_reason = valid;
    injected_reason["stages"][1]["reason"] = serde_json::json!("alignment\nforged");
    let injected_reason: ServerStageProjectionEnvelope =
        serde_json::from_value(injected_reason).unwrap();
    assert!(!injected_reason.is_valid_for(job_id));
}
