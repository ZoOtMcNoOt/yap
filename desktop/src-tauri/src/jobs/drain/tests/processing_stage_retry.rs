use super::*;

#[test]
fn failed_asr_retry_reuses_the_bound_job_and_exact_uploaded_capture() {
    let root = temp_dir("stage-retry");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&queued_job("job-stage-retry", source))
        .unwrap();
    let owner = OwnerNamespace::local("i-stage-retry-test").unwrap();
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
        .get_prepared_remote_job("job-stage-retry")
        .unwrap()
        .unwrap();
    let request =
        CreateRecordingJobRequest::decode_persisted(&prepared.create_request_json).unwrap();
    let server_job_id = "job-1123456789abcdef0123456789abcdef";

    let failed_stages = serde_json::json!({
        "schemaVersion": 1,
        "jobId": server_job_id,
        "projectionRevision": 4,
        "historyComplete": true,
        "stages": [{
            "stage": "asr",
            "attempt": 1,
            "state": "failed",
            "updatedAtUtc": "2026-07-14T21:00:01Z",
            "retryable": true,
            "reason": "ASR_PROCESSING_FAILED"
        }]
    });
    let running_stages = serde_json::json!({
        "schemaVersion": 1,
        "jobId": server_job_id,
        "projectionRevision": 5,
        "historyComplete": true,
        "stages": [{
            "stage": "asr",
            "attempt": 2,
            "state": "running",
            "updatedAtUtc": "2026-07-14T21:00:02Z",
            "retryable": null,
            "reason": null
        }]
    });
    let processing_projection = server_projection(server_job_id, &request, "server_processing");
    let complete_projection = server_projection(server_job_id, &request, "complete");
    let result = serde_json::json!({
        "sessionId": request.metadata.session_id.as_str(),
        "revision": 1,
        "authority": "server_authoritative",
        "createdAtUtc": "2026-07-14T21:00:04Z",
        "captureManifestSha256": request.capture_manifest.sha256,
        "previousResultSha256": null,
        "status": "complete",
        "language": {"languageBcp47": "en-US", "confidence": null},
        "transcript": "The retained capture was retried once.",
        "alignment": {
            "status": "unavailable",
            "reason": "ALIGNMENT_RUNTIME_FAILED",
            "componentRevision": "cohere-attention-alignment-candidate-v1"
        },
        "alignedWords": [],
        "modelProvenance": [{
            "modelId": "CohereLabs/cohere-transcribe-03-2026",
            "revision": "b1eacc2686a3d08ceaae5f24a88b1d519620bc09",
            "calibrationRevision": "asr-not-applicable"
        }]
    });
    let (base_url, observed, server) = start_json_server(vec![
        (200, failed_stages),
        (202, running_stages),
        (200, processing_projection),
        (200, complete_projection),
        (200, result),
    ]);
    ledger
        .begin_remote_create_attempt("job-stage-retry", &base_url, 1_720_000_000_200)
        .unwrap();
    ledger
        .record_server_job_id(
            "job-stage-retry",
            server_job_id,
            &base_url,
            1_720_000_000_200,
        )
        .unwrap();
    for chunk in &request.chunks {
        ledger
            .acknowledge_remote_chunk(
                "job-stage-retry",
                &chunk.replay_key.track_id,
                chunk.replay_key.sequence_start,
                chunk.replay_key.sequence_end,
                &chunk.content_identity.sha256,
                1_720_000_000_300,
            )
            .unwrap();
    }
    ledger
        .mark_remote_job_committed("job-stage-retry", 1_720_000_000_400)
        .unwrap();
    ledger
        .record_remote_error(
            "job-stage-retry",
            "REMOTE_SERVER_FAILED",
            "The private server could not complete this recording.",
            None,
            1_720_000_000_500,
        )
        .unwrap();
    ledger
        .request_bound_server_stage_retry(
            "job-stage-retry",
            1_720_000_000_600,
            Some(1_720_604_800_600),
        )
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
            !advance_processing_once(&ledger, &remote_jobs, &client, 1_720_000_000_700,)
                .await
                .unwrap()
        );
        let reconciled = ledger.get_job("job-stage-retry").unwrap().unwrap();
        assert_eq!(reconciled.status, RecordingJobStatus::ServerProcessing);
        assert_eq!(reconciled.error_code, None);

        assert!(
            advance_processing_once(&ledger, &remote_jobs, &client, 1_720_000_000_800,)
                .await
                .unwrap()
        );
    });
    server.join().unwrap();

    let completed = ledger.get_job("job-stage-retry").unwrap().unwrap();
    assert_eq!(completed.status, RecordingJobStatus::Complete);
    assert_eq!(
        fs::read_to_string(completed.output_path.unwrap()).unwrap(),
        "The retained capture was retried once.\n"
    );
    let bound = ledger
        .get_prepared_remote_job("job-stage-retry")
        .unwrap()
        .unwrap();
    assert_eq!(bound.server_job_id.as_deref(), Some(server_job_id));
    let chunks = ledger.list_chunks("job-stage-retry").unwrap();
    assert!(chunks.iter().all(|chunk| {
        chunk.upload_offset == chunk.content_byte_length
            && chunk.acknowledged_object_id.as_deref() == Some(server_job_id)
    }));
    assert!(ledger
        .list_detached_remote_cancellations()
        .unwrap()
        .is_empty());

    let requests = observed.lock().unwrap();
    assert!(requests[0].starts_with(&format!("GET /v1/jobs/{server_job_id}/stages HTTP/1.1")));
    assert!(requests[1].starts_with(&format!(
        "POST /v1/jobs/{server_job_id}/stages/asr/retry HTTP/1.1"
    )));
    let body = requests[1].split("\r\n\r\n").nth(1).unwrap();
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(body).unwrap(),
        serde_json::json!({
            "stage": "asr",
            "attempt": 1,
            "projectionRevision": 4,
            "captureManifestSha256": request.capture_manifest.sha256
        })
    );
    assert!(requests[2].starts_with(&format!("GET /v1/jobs/{server_job_id} HTTP/1.1")));
    assert!(requests[3].starts_with(&format!("GET /v1/jobs/{server_job_id} HTTP/1.1")));
    assert!(requests[4].starts_with(&format!("GET /v1/jobs/{server_job_id}/result HTTP/1.1")));
    drop(requests);
    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}

fn server_projection(
    server_job_id: &str,
    request: &CreateRecordingJobRequest,
    status: &str,
) -> serde_json::Value {
    serde_json::json!({
        "jobId": server_job_id,
        "sessionId": request.metadata.session_id.as_str(),
        "displayName": request.display_name,
        "sessionMode": "meeting",
        "sessionOrigin": "imported_file",
        "status": status,
        "route": "server_batch",
        "captureManifest": request.capture_manifest,
        "createdAtUtc": "2026-07-14T21:00:00Z",
        "updatedAtUtc": "2026-07-14T21:00:03Z"
    })
}
