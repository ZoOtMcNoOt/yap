use super::*;

#[test]
fn ambiguous_stage_retry_response_reconciles_without_a_second_post() {
    let root = temp_dir("stage-retry-ambiguous");
    let remote_jobs = root.join("remote-jobs");
    let ledger = JobLedger::open(root.join("jobs.sqlite3")).unwrap();
    let prepared = prepare_candidate(&root, &remote_jobs, &ledger, "job-stage-ambiguous");
    let request =
        CreateRecordingJobRequest::decode_persisted(&prepared.create_request_json).unwrap();
    let server_job_id = "job-2123456789abcdef0123456789abcdef";
    let (base_url, observed, server) = start_json_server(vec![
        (200, failed_asr_stages(server_job_id, true)),
        (
            202,
            serde_json::json!({"acceptedButResponseWasMalformed": true}),
        ),
        (200, running_asr_stages(server_job_id)),
        (
            200,
            processing_projection(server_job_id, &request, "server_processing"),
        ),
    ]);
    bind_fail_and_request_retry(
        &ledger,
        "job-stage-ambiguous",
        server_job_id,
        &base_url,
        &request,
    );
    let client = test_client(&base_url);

    let error = tauri::async_runtime::block_on(async {
        advance_processing_once(&ledger, &remote_jobs, &client, 1_720_000_000_700)
            .await
            .unwrap_err()
    });
    assert_eq!(error.code, crate::jobs::REMOTE_STAGE_RETRY_REQUESTED);
    assert_eq!(
        error.retry_disposition,
        super::super::error::RetryDisposition::DurableAmbiguousCommit
    );
    ledger
        .defer_remote_retry(
            "job-stage-ambiguous",
            error.code,
            error.user_message,
            1_720_000_005_700,
            1_720_000_000_700,
        )
        .unwrap();

    tauri::async_runtime::block_on(async {
        assert!(
            !advance_processing_once(&ledger, &remote_jobs, &client, 1_720_000_005_700,)
                .await
                .unwrap()
        );
    });
    server.join().unwrap();

    let reconciled = ledger.get_job("job-stage-ambiguous").unwrap().unwrap();
    assert_eq!(reconciled.status, RecordingJobStatus::ServerProcessing);
    assert_eq!(reconciled.error_code, None);
    assert_eq!(reconciled.next_attempt_at_ms, None);
    let requests = observed.lock().unwrap();
    assert_eq!(
        requests
            .iter()
            .filter(|request| request.starts_with("POST "))
            .count(),
        1
    );
    assert!(requests[2].starts_with(&format!("GET /v1/jobs/{server_job_id}/stages HTTP/1.1")));
    drop(requests);
    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn nonretryable_asr_stage_fails_closed_without_posting_or_detaching() {
    let root = temp_dir("stage-retry-nonretryable");
    let remote_jobs = root.join("remote-jobs");
    let ledger = JobLedger::open(root.join("jobs.sqlite3")).unwrap();
    let prepared = prepare_candidate(&root, &remote_jobs, &ledger, "job-stage-nonretryable");
    let request =
        CreateRecordingJobRequest::decode_persisted(&prepared.create_request_json).unwrap();
    let server_job_id = "job-3123456789abcdef0123456789abcdef";
    let (base_url, observed, server) =
        start_json_server(vec![(200, failed_asr_stages(server_job_id, false))]);
    bind_fail_and_request_retry(
        &ledger,
        "job-stage-nonretryable",
        server_job_id,
        &base_url,
        &request,
    );
    let client = test_client(&base_url);

    let error = tauri::async_runtime::block_on(async {
        advance_processing_once(&ledger, &remote_jobs, &client, 1_720_000_000_700)
            .await
            .unwrap_err()
    });
    server.join().unwrap();
    assert_eq!(
        error.retry_disposition,
        super::super::error::RetryDisposition::Terminal
    );
    assert!(error.detail.contains("not retryable"));
    assert_eq!(observed.lock().unwrap().len(), 1);
    let still_bound = ledger
        .get_prepared_remote_job("job-stage-nonretryable")
        .unwrap()
        .unwrap();
    assert_eq!(still_bound.server_job_id.as_deref(), Some(server_job_id));
    assert!(ledger
        .list_detached_remote_cancellations()
        .unwrap()
        .is_empty());
    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}

fn prepare_candidate(
    root: &std::path::Path,
    remote_jobs: &std::path::Path,
    ledger: &JobLedger,
    job_id: &str,
) -> crate::jobs::PreparedRemoteJobRecord {
    let source = root.join(format!("{job_id}.wav"));
    let owned_live = root.join("live-recordings");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &vec![0_u8; 320]);
    ledger.insert_job(&queued_job(job_id, source)).unwrap();
    prepare_next_queued_job(
        ledger,
        &owned_live,
        remote_jobs,
        &OwnerNamespace::local(format!("i-{job_id}")).unwrap(),
        1_720_000_000_100,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
    )
    .unwrap();
    ledger.get_prepared_remote_job(job_id).unwrap().unwrap()
}

fn bind_fail_and_request_retry(
    ledger: &JobLedger,
    job_id: &str,
    server_job_id: &str,
    base_url: &str,
    request: &CreateRecordingJobRequest,
) {
    ledger
        .begin_remote_create_attempt(job_id, base_url, 1_720_000_000_200)
        .unwrap();
    ledger
        .record_server_job_id(job_id, server_job_id, base_url, 1_720_000_000_200)
        .unwrap();
    for chunk in &request.chunks {
        ledger
            .acknowledge_remote_chunk(
                job_id,
                &chunk.replay_key.track_id,
                chunk.replay_key.sequence_start,
                chunk.replay_key.sequence_end,
                &chunk.content_identity.sha256,
                1_720_000_000_300,
            )
            .unwrap();
    }
    ledger
        .mark_remote_job_committed(job_id, 1_720_000_000_400)
        .unwrap();
    ledger
        .record_remote_error(
            job_id,
            "REMOTE_SERVER_FAILED",
            "The private server could not complete this recording.",
            None,
            1_720_000_000_500,
        )
        .unwrap();
    ledger
        .request_bound_server_stage_retry(job_id, 1_720_000_000_600, Some(1_720_604_800_600))
        .unwrap();
}

fn failed_asr_stages(server_job_id: &str, retryable: bool) -> serde_json::Value {
    serde_json::json!({
        "schemaVersion": 1,
        "jobId": server_job_id,
        "projectionRevision": 4,
        "historyComplete": true,
        "stages": [{
            "stage": "asr",
            "attempt": 1,
            "state": "failed",
            "updatedAtUtc": "2026-07-14T21:00:01Z",
            "retryable": retryable,
            "reason": "ASR_PROCESSING_FAILED"
        }]
    })
}

fn running_asr_stages(server_job_id: &str) -> serde_json::Value {
    serde_json::json!({
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
    })
}

fn processing_projection(
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

fn test_client(base_url: &str) -> BatchApiClient {
    BatchApiClient::new(
        reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(2))
            .timeout(Duration::from_secs(5))
            .build()
            .unwrap(),
        base_url,
    )
    .unwrap()
}
