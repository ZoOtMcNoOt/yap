use super::*;

#[test]
fn exact_processing_target_does_not_fall_through_to_a_neighbor_after_cancellation() {
    let root = temp_dir("exact-processing-target");
    let remote_jobs = root.join("remote-jobs");
    let source_a = root.join("source-a.wav");
    let source_b = root.join("source-b.wav");
    write_pcm_wav(&source_a, &[0_u8; 320]);
    write_pcm_wav(&source_b, &[0_u8; 320]);
    let ledger = JobLedger::open_in_memory().unwrap();
    let mut job_a = queued_job("job-exact-processing-a", source_a);
    job_a.status = RecordingJobStatus::ServerProcessing;
    let mut job_b = queued_job("job-exact-processing-b", source_b);
    job_b.status = RecordingJobStatus::ServerProcessing;
    ledger.insert_jobs(&[job_a, job_b]).unwrap();
    ledger
        .request_cancellation("job-exact-processing-a", 1_720_000_000_100)
        .unwrap();
    let client = BatchApiClient::new(
        reqwest::Client::builder().build().unwrap(),
        "http://127.0.0.1:9",
    )
    .unwrap();

    tauri::async_runtime::block_on(async {
        assert!(!advance_processing_job_once_guarded_for_test(
            &ledger,
            &remote_jobs,
            &client,
            "job-exact-processing-a",
            1_720_000_000_200,
            &BatchCommitGuard::Unchecked,
        )
        .await
        .unwrap());
    });

    let cancelled = ledger.get_job("job-exact-processing-a").unwrap().unwrap();
    assert_eq!(cancelled.status, RecordingJobStatus::Cancelled);
    let neighbor = ledger.get_job("job-exact-processing-b").unwrap().unwrap();
    assert_eq!(neighbor.status, RecordingJobStatus::ServerProcessing);
    assert_eq!(neighbor.attempt_count, 0);
    assert_eq!(neighbor.error_code, None);

    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn completed_server_result_is_published_before_the_ledger_becomes_complete() {
    let root = temp_dir("result");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&queued_job("job-drain-result", source))
        .unwrap();
    let owner = OwnerNamespace::local("i-drain-test").unwrap();
    prepare_next_queued_job(
        &ledger,
        &owned_live,
        &remote_jobs,
        &owner,
        1_720_000_000_100,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
    )
    .unwrap();
    let prepared = ledger
        .get_prepared_remote_job("job-drain-result")
        .unwrap()
        .unwrap();
    let request =
        CreateRecordingJobRequest::decode_persisted(&prepared.create_request_json).unwrap();
    let server_job_id = "job-0123456789abcdef0123456789abcdef";
    let projection = serde_json::json!({
        "jobId": server_job_id,
        "sessionId": request.metadata.session_id.as_str(),
        "displayName": request.display_name,
        "sessionMode": "meeting",
        "sessionOrigin": "imported_file",
        "status": "complete",
        "route": "server_batch",
        "captureManifest": request.capture_manifest,
        "createdAtUtc": "2026-07-14T21:00:00Z",
        "updatedAtUtc": "2026-07-14T21:00:02Z"
    });
    let runtime_lock = "d".repeat(64);
    let mut result = serde_json::json!({
        "sessionId": request.metadata.session_id.as_str(),
        "revision": 1,
        "authority": "server_authoritative",
        "createdAtUtc": "2026-07-14T21:00:02Z",
        "captureManifestSha256": request.capture_manifest.sha256,
        "previousResultSha256": null,
        "status": "complete",
        "language": {
            "languageBcp47": "en-US",
            "confidence": null
        },
        "transcript": "Phase five is connected.",
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
    let speaker_result = serde_json::json!({
        "sessionId": request.metadata.session_id.as_str(),
        "revision": 1,
        "authority": "server_authoritative",
        "createdAtUtc": "2026-07-14T21:00:02Z",
        "captureManifestSha256": request.capture_manifest.sha256,
        "previousResultSha256": null,
        "status": "complete",
        "language": {"languageBcp47": "en-US", "confidence": null},
        "runtimeLockSha256": runtime_lock,
        "speakerTurns": [{
            "turnId": "turn-000001",
            "startMs": 0,
            "endMs": 10,
            "text": "Phase five is connected.",
            "attribution": {"kind": "session_speaker", "sessionSpeakerId": "speaker-1"},
            "confidence": null,
            "supportingTrackIds": ["track-1"],
            "overlapGroupId": null
        }],
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
            }
        ]
    });
    let decoded_speaker_result: crate::server_connector::batch::SpeakerResultRevision =
        serde_json::from_value(speaker_result.clone()).unwrap();
    result["speakerResultSha256"] =
        serde_json::json!(decoded_speaker_result.content_sha256().unwrap());
    let valid_result: crate::server_connector::batch::TranscriptResultRevision =
        serde_json::from_value(result.clone()).unwrap();
    let mut aligned_value = result.clone();
    aligned_value["alignment"] = serde_json::json!({
        "status": "available",
        "reason": null,
        "componentRevision": "cohere-attention-en-v1"
    });
    aligned_value["alignedWords"] = serde_json::json!([
        {"wordIndex": 0, "text": "Phase", "startMs": 0, "endMs": 2,
         "turnId": null, "attribution": {"kind": "unknown"}, "confidence": null},
        {"wordIndex": 1, "text": "five", "startMs": 2, "endMs": 4,
         "turnId": null, "attribution": {"kind": "unknown"}, "confidence": null},
        {"wordIndex": 2, "text": "is", "startMs": 4, "endMs": 6,
         "turnId": null, "attribution": {"kind": "unknown"}, "confidence": null},
        {"wordIndex": 3, "text": "connected.", "startMs": 6, "endMs": 10,
         "turnId": null, "attribution": {"kind": "unknown"}, "confidence": null}
    ]);
    let aligned_result: crate::server_connector::batch::TranscriptResultRevision =
        serde_json::from_value(aligned_value).unwrap();
    assert!(validate_result_revision(&aligned_result, &request).is_ok());
    let mut out_of_source = aligned_result;
    out_of_source.aligned_words[3].end_ms = 11;
    assert!(validate_result_revision(&out_of_source, &request).is_err());
    let mut silent_result = valid_result.clone();
    silent_result.transcript.clear();
    assert!(validate_result_revision(&silent_result, &request).is_ok());
    let mut empty_result = valid_result.clone();
    empty_result.transcript = " \n\t".into();
    assert!(validate_result_revision(&empty_result, &request).is_err());
    let mut offset_timestamp = valid_result;
    offset_timestamp.created_at_utc = "2026-07-14T16:00:02-05:00".into();
    assert!(validate_result_revision(&offset_timestamp, &request).is_err());
    let (base_url, observed, server) = start_json_server(vec![
        (200, projection),
        (200, result),
        (200, speaker_result.clone()),
    ]);
    ledger
        .begin_remote_create_attempt("job-drain-result", &base_url, 1_720_000_000_200)
        .unwrap();
    ledger
        .record_server_job_id(
            "job-drain-result",
            server_job_id,
            &base_url,
            1_720_000_000_200,
        )
        .unwrap();
    for chunk in &request.chunks {
        ledger
            .acknowledge_remote_chunk(
                "job-drain-result",
                &chunk.replay_key.track_id,
                chunk.replay_key.sequence_start,
                chunk.replay_key.sequence_end,
                &chunk.content_identity.sha256,
                1_720_000_000_300,
            )
            .unwrap();
    }
    ledger
        .mark_remote_job_committed("job-drain-result", 1_720_000_000_400)
        .unwrap();
    let client = BatchApiClient::new(
        reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(2))
            .timeout(Duration::from_secs(5))
            .build()
            .unwrap(),
        &base_url,
    )
    .unwrap();

    tauri::async_runtime::block_on(async {
        assert!(
            super::advance_processing_once(&ledger, &remote_jobs, &client, 1_720_000_000_500,)
                .await
                .unwrap()
        );
    });
    server.join().unwrap();

    let completed = ledger.get_job("job-drain-result").unwrap().unwrap();
    assert_eq!(completed.status, RecordingJobStatus::Complete);
    assert_eq!(completed.expires_at_ms, Some(1_722_592_000_000));
    let output = completed.output_path.unwrap();
    assert_eq!(
        fs::read_to_string(&output).unwrap(),
        "Phase five is connected.\n"
    );
    let result_path = output.parent().unwrap().join("result.json");
    let persisted: serde_json::Value =
        serde_json::from_slice(&fs::read(result_path).unwrap()).unwrap();
    assert_eq!(
        persisted["captureManifestSha256"],
        request.capture_manifest.sha256
    );
    let persisted_speaker: serde_json::Value = serde_json::from_slice(
        &fs::read(output.parent().unwrap().join("speaker-result.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(persisted_speaker, speaker_result);
    let requests = observed.lock().unwrap();
    assert_eq!(requests.len(), 3);
    assert!(requests[0].starts_with(&format!("GET /v1/jobs/{server_job_id} HTTP/1.1")));
    assert!(requests[1].starts_with(&format!("GET /v1/jobs/{server_job_id}/result HTTP/1.1")));
    assert!(requests[2].starts_with(&format!(
        "GET /v1/jobs/{server_job_id}/speaker-result HTTP/1.1"
    )));
    drop(requests);
    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}
