use std::{
    io::{Read, Write},
    net::TcpListener,
};

use crate::language::RecordingLanguageDecision;

use super::{
    validate_batch_base_url, AlignmentUnavailableReason, AnonymousSpeakerAttribution, ApiError,
    BatchApiClient, BatchClientError, CaptureChunkReference, ContentIdentity,
    CreateRecordingJobRequest, ServerReplayKey, ServerStageProjectionEnvelope,
    SpeakerResultRevision, TranscriptResultRevision,
};
use crate::server_connector::{client::bounded_client, AuthenticatedRequestDispatcher};

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
fn joint_speaker_result_is_capture_bound_and_rejects_named_or_forged_turns() {
    let runtime_lock = "d".repeat(64);
    let mut transcript_value = serde_json::json!({
        "sessionId": "session-1",
        "revision": 1,
        "authority": "server_authoritative",
        "createdAtUtc": "2026-08-03T03:00:00Z",
        "captureManifestSha256": "a".repeat(64),
        "previousResultSha256": null,
        "status": "complete",
        "language": {"languageBcp47": "en-US", "confidence": null},
        "transcript": "hello overlapping reply",
        "alignment": {
            "status": "unavailable",
            "reason": "ALIGNMENT_PROVIDER_UNSUPPORTED",
            "componentRevision": "joint-segment-timing-v1"
        },
        "alignedWords": [],
        "modelProvenance": [{
            "modelId": "Trelis/tiron",
            "revision": "90bc0a4d198cd5cf6679b0e478375ba3a0040575",
            "calibrationRevision": runtime_lock
        }]
    });
    let speaker_value = serde_json::json!({
        "sessionId": "session-1",
        "revision": 1,
        "authority": "server_authoritative",
        "createdAtUtc": "2026-08-03T03:00:00Z",
        "captureManifestSha256": "a".repeat(64),
        "previousResultSha256": null,
        "status": "complete",
        "language": {"languageBcp47": "en-US", "confidence": null},
        "runtimeLockSha256": runtime_lock,
        "speakerTurns": [
            {
                "turnId": "turn-000001",
                "startMs": 0,
                "endMs": 1000,
                "text": "hello",
                "attribution": {"kind": "session_speaker", "sessionSpeakerId": "speaker-1"},
                "confidence": null,
                "supportingTrackIds": ["track-1"],
                "overlapGroupId": "overlap-000001"
            },
            {
                "turnId": "turn-000002",
                "startMs": 500,
                "endMs": 1500,
                "text": "overlapping reply",
                "attribution": {"kind": "session_speaker", "sessionSpeakerId": "speaker-2"},
                "confidence": null,
                "supportingTrackIds": ["track-1"],
                "overlapGroupId": "overlap-000001"
            }
        ],
        "speakerCapacityDegradation": null,
        "alignment": {
            "status": "unavailable",
            "reason": "ALIGNMENT_PROVIDER_UNSUPPORTED",
            "componentRevision": "joint-segment-timing-v1"
        },
        "alignedWords": [],
        "modelProvenance": [
            {
                "modelId": "Trelis/tiron",
                "revision": "90bc0a4d198cd5cf6679b0e478375ba3a0040575",
                "calibrationRevision": runtime_lock
            },
            {
                "modelId": "TrelisResearch/tiron",
                "revision": "d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c",
                "calibrationRevision": runtime_lock
            },
            {
                "modelId": "speechbrain/spkrec-ecapa-voxceleb",
                "revision": "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
                "calibrationRevision": runtime_lock
            },
            {
                "modelId": "yap/speaker-epoch-reconciliation",
                "revision": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "calibrationRevision": runtime_lock
            }
        ]
    });
    let speaker: SpeakerResultRevision = serde_json::from_value(speaker_value.clone()).unwrap();
    transcript_value["speakerResultSha256"] = serde_json::json!(speaker.content_sha256().unwrap());
    let transcript: TranscriptResultRevision = serde_json::from_value(transcript_value).unwrap();

    assert!(transcript.requires_speaker_result());
    assert!(speaker.is_valid_for(&transcript, 2_000, Some(32_000), &["track-1".into()]));

    let mut duplicate_provenance = speaker.clone();
    duplicate_provenance.model_provenance[1].model_id =
        duplicate_provenance.model_provenance[0].model_id.clone();
    let mut duplicate_provenance_transcript = transcript.clone();
    duplicate_provenance_transcript.speaker_result_sha256 = duplicate_provenance.content_sha256();
    assert!(!duplicate_provenance.is_valid_for(
        &duplicate_provenance_transcript,
        2_000,
        Some(32_000),
        &["track-1".into()]
    ));

    let mut short_provenance = speaker.clone();
    short_provenance.model_provenance.pop();
    let mut short_provenance_transcript = transcript.clone();
    short_provenance_transcript.speaker_result_sha256 = short_provenance.content_sha256();
    assert!(!short_provenance.is_valid_for(
        &short_provenance_transcript,
        2_000,
        Some(32_000),
        &["track-1".into()]
    ));

    let mut wrong_final_provenance = speaker.clone();
    wrong_final_provenance.model_provenance[3].model_id = "other/reconciler".into();
    let mut wrong_final_provenance_transcript = transcript.clone();
    wrong_final_provenance_transcript.speaker_result_sha256 =
        wrong_final_provenance.content_sha256();
    assert!(!wrong_final_provenance.is_valid_for(
        &wrong_final_provenance_transcript,
        2_000,
        Some(32_000),
        &["track-1".into()]
    ));

    let mut forged_overlap = speaker.clone();
    forged_overlap.speaker_turns[1].overlap_group_id = None;
    assert!(!forged_overlap.is_valid_for(&transcript, 2_000, Some(32_000), &["track-1".into()]));

    let mut forged_text = speaker.clone();
    forged_text.speaker_turns[0].text = "different".into();
    assert!(!forged_text.is_valid_for(&transcript, 2_000, Some(32_000), &["track-1".into()]));

    let mut noncanonical_speaker = speaker.clone();
    match &mut noncanonical_speaker.speaker_turns[0].attribution {
        AnonymousSpeakerAttribution::SessionSpeaker { session_speaker_id } => {
            *session_speaker_id = "speaker-01".into();
        }
        AnonymousSpeakerAttribution::Unknown => unreachable!(),
    }
    assert!(!noncanonical_speaker.is_valid_for(
        &transcript,
        2_000,
        Some(32_000),
        &["track-1".into()]
    ));

    let mut partial_speaker_value = speaker_value.clone();
    partial_speaker_value["status"] = serde_json::json!("partial");
    partial_speaker_value["speakerCapacityDegradation"] = serde_json::json!({
        "code": "SPEAKER_CAPACITY_REACHED",
        "scope": "decode_window",
        "startSample": 0,
        "endSample": 32000,
        "observedSpeakerCount": 8,
        "speakerLimit": 8
    });
    let extra_turns = partial_speaker_value["speakerTurns"]
        .as_array_mut()
        .expect("speaker turns are an array");
    for (offset, text) in ["three", "four", "five", "six", "seven", "eight"]
        .into_iter()
        .enumerate()
    {
        let speaker_number = offset + 3;
        let start_ms = 1_500 + offset as u64 * 80;
        extra_turns.push(serde_json::json!({
            "turnId": format!("turn-{speaker_number:06}"),
            "startMs": start_ms,
            "endMs": start_ms + 80,
            "text": text,
            "attribution": {
                "kind": "session_speaker",
                "sessionSpeakerId": format!("speaker-{speaker_number}")
            },
            "confidence": null,
            "supportingTrackIds": ["track-1"],
            "overlapGroupId": null
        }));
    }
    let partial_speaker: SpeakerResultRevision =
        serde_json::from_value(partial_speaker_value).unwrap();
    let mut partial_transcript_value = serde_json::to_value(&transcript).unwrap();
    partial_transcript_value["status"] = serde_json::json!("partial");
    partial_transcript_value["transcript"] =
        serde_json::json!("hello overlapping reply three four five six seven eight");
    partial_transcript_value["speakerResultSha256"] =
        serde_json::json!(partial_speaker.content_sha256().unwrap());
    let partial_transcript: TranscriptResultRevision =
        serde_json::from_value(partial_transcript_value).unwrap();
    assert!(partial_speaker.is_valid_for(
        &partial_transcript,
        2_000,
        Some(32_000),
        &["track-1".into()]
    ));

    let mut forged_capacity_interval = partial_speaker.clone();
    let super::response::SpeakerCapacityDegradation::Reached(degradation) =
        &mut forged_capacity_interval.speaker_capacity_degradation
    else {
        unreachable!()
    };
    degradation.start_sample = 1;
    assert!(!forged_capacity_interval.is_valid_for(
        &partial_transcript,
        2_000,
        Some(32_000),
        &["track-1".into()]
    ));

    let mut missing_degradation = partial_speaker.clone();
    missing_degradation.speaker_capacity_degradation =
        super::response::SpeakerCapacityDegradation::None(());
    assert!(!missing_degradation.is_valid_for(
        &partial_transcript,
        2_000,
        Some(32_000),
        &["track-1".into()]
    ));

    let mut unknown_value = speaker_value.clone();
    unknown_value["speakerTurns"][1]["attribution"] = serde_json::json!({"kind": "unknown"});
    let unknown: SpeakerResultRevision = serde_json::from_value(unknown_value).unwrap();
    let mut unknown_transcript_value = serde_json::to_value(&transcript).unwrap();
    unknown_transcript_value["speakerResultSha256"] =
        serde_json::json!(unknown.content_sha256().unwrap());
    let unknown_transcript: TranscriptResultRevision =
        serde_json::from_value(unknown_transcript_value).unwrap();
    assert!(unknown.is_valid_for(
        &unknown_transcript,
        2_000,
        Some(32_000),
        &["track-1".into()]
    ));

    let mut high_session_id = speaker.clone();
    match &mut high_session_id.speaker_turns[1].attribution {
        AnonymousSpeakerAttribution::SessionSpeaker { session_speaker_id } => {
            *session_speaker_id = "speaker-64".into();
        }
        AnonymousSpeakerAttribution::Unknown => unreachable!(),
    }
    let mut high_session_transcript = transcript.clone();
    high_session_transcript.speaker_result_sha256 = high_session_id.content_sha256();
    assert!(high_session_id.is_valid_for(
        &high_session_transcript,
        2_000,
        Some(32_000),
        &["track-1".into()]
    ));

    let mut named = speaker_value;
    named["speakerTurns"][0]["attribution"] =
        serde_json::json!({"kind": "named", "displayName": "Someone"});
    assert!(serde_json::from_value::<SpeakerResultRevision>(named).is_err());
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
        AuthenticatedRequestDispatcher::fixed(bounded_client().unwrap(), "batch-token"),
        &format!("http://{address}"),
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
    let session_id = "s-persisted-request";
    let request = CreateRecordingJobRequest::for_test_single_chunk(
        "interview.wav",
        session_id,
        "track-1",
        &"0".repeat(64),
        200,
        &"a".repeat(64),
        320,
        RecordingLanguageDecision::primary("en-US".into()).unwrap(),
        &"b".repeat(64),
    );
    let encoded = serde_json::to_string(&request).unwrap();
    let original_key = request.create_idempotency_key().unwrap();

    assert_eq!(
        CreateRecordingJobRequest::decode_persisted(&encoded).unwrap(),
        request
    );
    assert_eq!(request.create_idempotency_key().unwrap(), original_key);
    let encoded_language = serde_json::to_string(&request.language_decision).unwrap();
    let missing_language_decision =
        encoded.replacen(&format!(",\"languageDecision\":{encoded_language}"), "", 1);
    assert_ne!(missing_language_decision, encoded);
    assert!(CreateRecordingJobRequest::decode_persisted(&missing_language_decision).is_err());
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

#[test]
fn obsolete_capture_and_preprocessing_schemas_are_rejected() {
    let current = CreateRecordingJobRequest::for_test_single_chunk(
        "interview.wav",
        "s-current-contract",
        "track-1",
        &"0".repeat(64),
        200,
        &"a".repeat(64),
        320,
        RecordingLanguageDecision::primary("en-US".into()).unwrap(),
        &"b".repeat(64),
    );

    let mut obsolete_manifest = serde_json::to_value(&current).unwrap();
    obsolete_manifest["captureManifest"]["schemaVersion"] = serde_json::json!(1);
    assert!(CreateRecordingJobRequest::decode_persisted(
        &serde_json::to_string(&obsolete_manifest).unwrap()
    )
    .is_err());

    let mut obsolete_preprocessing = serde_json::to_value(current).unwrap();
    obsolete_preprocessing["preprocessingEvidence"]["schemaVersion"] = serde_json::json!(1);
    assert!(CreateRecordingJobRequest::decode_persisted(
        &serde_json::to_string(&obsolete_preprocessing).unwrap()
    )
    .is_err());
}
