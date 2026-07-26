use super::*;

#[test]
fn prepared_remote_job_is_attached_atomically_and_survives_restart() {
    let dir = temp_dir("prepared-remote-restart");
    let database_path = dir.join("jobs.sqlite3");
    let source_path = dir.join("interview.wav");
    let manifest_path = dir.join("spool/job-remote/capture-manifest.json");
    let chunk_path = dir.join("spool/job-remote/track-1-0-9.pcm");
    fs::create_dir_all(manifest_path.parent().unwrap()).unwrap();
    fs::write(&source_path, b"RIFF-restart-fixture").unwrap();
    fs::write(&manifest_path, b"{}").unwrap();
    fs::write(&chunk_path, vec![7_u8; 320]).unwrap();
    let capture_manifest_sha256 =
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    {
        let ledger = JobLedger::open(&database_path).unwrap();
        let mut job = imported_job_at("job-remote", source_path.clone());
        job.status = RecordingJobStatus::QueuedServer;
        job.route = Some(RecordingRoute::ServerBatch);
        job.asr_catalog_binding = Some(crate::jobs::AsrCatalogBinding::for_test());
        ledger.insert_job(&job).unwrap();
        ledger
            .transition("job-remote", RecordingJobStatus::Preprocessing, 101)
            .unwrap();
        let prepared = prepared_remote_job_at(
            manifest_path.clone(),
            chunk_path.clone(),
            capture_manifest_sha256,
        );

        let attached = ledger
            .attach_prepared_remote_job("job-remote", &prepared, 102)
            .unwrap();

        assert_eq!(attached.status, RecordingJobStatus::Uploading);
        let stages = ledger.list_client_stage_attempts("job-remote").unwrap();
        assert_eq!(stages.len(), 2);
        assert_eq!(stages[0].state, crate::jobs::ClientStageState::Succeeded);
        assert_eq!(stages[1].state, crate::jobs::ClientStageState::Unavailable);
        assert!(ledger
            .attach_prepared_remote_job("job-remote", &prepared, 103)
            .is_err());
        assert_eq!(ledger.list_chunks("job-remote").unwrap().len(), 1);
    }

    let ledger = JobLedger::open(&database_path).unwrap();
    let recovered = ledger
        .get_prepared_remote_job("job-remote")
        .unwrap()
        .unwrap();
    let decoded = crate::server_connector::batch::CreateRecordingJobRequest::decode_persisted(
        &recovered.create_request_json,
    )
    .unwrap();
    assert_eq!(decoded.capture_manifest.sha256, capture_manifest_sha256);
    assert_eq!(recovered.capture_manifest_path, manifest_path);
    assert_eq!(recovered.server_job_id, None);
    assert_eq!(recovered.create_attempt_base_url, None);
    assert_eq!(
        ledger.get_job("job-remote").unwrap().unwrap().status,
        RecordingJobStatus::Uploading
    );
    assert_eq!(
        ledger.list_chunks("job-remote").unwrap()[0].artifact_path,
        chunk_path
    );
    drop(ledger);
    fs::remove_dir_all(dir).unwrap();
}
#[test]
fn remote_create_chunk_ack_and_commit_are_idempotent_and_restart_safe() {
    let dir = temp_dir("remote-progress-restart");
    let database_path = dir.join("jobs.sqlite3");
    let source_path = dir.join("interview.wav");
    let manifest_path = dir.join("spool/job-progress/capture-manifest.json");
    let chunk_path = dir.join("spool/job-progress/track-1-0-9.pcm");
    fs::create_dir_all(manifest_path.parent().unwrap()).unwrap();
    fs::write(&source_path, b"RIFF-restart-fixture").unwrap();
    fs::write(&manifest_path, b"{}").unwrap();
    fs::write(&chunk_path, vec![7_u8; 320]).unwrap();

    {
        let ledger = JobLedger::open(&database_path).unwrap();
        let mut job = imported_job_at("job-progress", source_path);
        job.status = RecordingJobStatus::QueuedServer;
        job.route = Some(RecordingRoute::ServerBatch);
        job.asr_catalog_binding = Some(crate::jobs::AsrCatalogBinding::for_test());
        ledger.insert_job(&job).unwrap();
        ledger
            .transition("job-progress", RecordingJobStatus::Preprocessing, 101)
            .unwrap();
        ledger
            .attach_prepared_remote_job(
                "job-progress",
                &prepared_remote_job_at(
                    manifest_path,
                    chunk_path,
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                ),
                102,
            )
            .unwrap();

        ledger
            .begin_remote_create_attempt("job-progress", "http://127.0.0.1:18765", 103)
            .unwrap();
        assert_eq!(
            ledger
                .get_prepared_remote_job("job-progress")
                .unwrap()
                .unwrap()
                .create_attempt_base_url
                .as_deref(),
            Some("http://127.0.0.1:18765")
        );
        assert!(ledger
            .record_server_job_id(
                "job-progress",
                "job-server-1",
                "http://127.0.0.1:18766",
                104,
            )
            .is_err());
        ledger
            .record_server_job_id(
                "job-progress",
                "job-server-1",
                "http://127.0.0.1:18765",
                105,
            )
            .unwrap();
        ledger
            .record_server_job_id(
                "job-progress",
                "job-server-1",
                "http://127.0.0.1:18765",
                106,
            )
            .unwrap();
        assert!(ledger
            .record_server_job_id(
                "job-progress",
                "job-server-conflict",
                "http://127.0.0.1:18765",
                107,
            )
            .is_err());
        assert!(ledger
            .record_server_job_id(
                "job-progress",
                "job-server-1",
                "http://127.0.0.1:18766",
                107,
            )
            .is_err());
        assert_eq!(
            ledger
                .get_prepared_remote_job("job-progress")
                .unwrap()
                .unwrap()
                .create_attempt_base_url,
            None
        );
        assert!(ledger
            .mark_remote_job_committed("job-progress", 106)
            .is_err());

        ledger
            .acknowledge_remote_chunk("job-progress", "microphone", 0, 159, &"b".repeat(64), 107)
            .unwrap();
        ledger
            .acknowledge_remote_chunk("job-progress", "microphone", 0, 159, &"b".repeat(64), 108)
            .unwrap();
        let deferred = ledger
            .defer_remote_retry(
                "job-progress",
                "REMOTE_COMMIT_RECONCILING",
                "Yap is confirming whether the private server accepted this recording and will retry automatically.",
                5_108,
                108,
            )
            .unwrap();
        assert_eq!(deferred.status, RecordingJobStatus::Uploading);
        assert_eq!(deferred.attempt_count, 0);
        assert_eq!(deferred.next_attempt_at_ms, Some(5_108));
        let committed = ledger
            .mark_remote_job_committed("job-progress", 109)
            .unwrap();
        assert_eq!(committed.next_attempt_at_ms, None);
        assert_eq!(committed.error_code, None);
        assert_eq!(committed.error_message, None);
    }

    let ledger = JobLedger::open(&database_path).unwrap();
    let recovered = ledger.get_job("job-progress").unwrap().unwrap();
    assert_eq!(recovered.status, RecordingJobStatus::ServerProcessing);
    assert_eq!(recovered.next_attempt_at_ms, None);
    assert_eq!(recovered.error_code, None);
    assert_eq!(recovered.error_message, None);
    assert_eq!(
        ledger
            .get_prepared_remote_job("job-progress")
            .unwrap()
            .unwrap()
            .server_job_id
            .as_deref(),
        Some("job-server-1")
    );
    let chunks = ledger.list_chunks("job-progress").unwrap();
    assert_eq!(chunks[0].content_byte_length, 320);
    assert_eq!(chunks[0].upload_offset, chunks[0].content_byte_length);
    assert_eq!(chunks[0].acknowledged_at_ms, Some(107));
    let cancelled = ledger.request_cancellation("job-progress", 110).unwrap();
    assert_eq!(cancelled.status, RecordingJobStatus::Cancelled);
    let pending = ledger.list_pending_remote_cancellations().unwrap();
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].server_job_id.as_deref(), Some("job-server-1"));
    assert_eq!(
        pending[0].server_base_url.as_deref(),
        Some("http://127.0.0.1:18765")
    );
    ledger
        .acknowledge_server_cancellation("job-progress", "job-server-1", 111)
        .unwrap();
    assert!(ledger
        .list_pending_remote_cancellations()
        .unwrap()
        .is_empty());
    drop(ledger);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn deferred_remote_retry_survives_restart_without_consuming_attempt_budget() {
    let dir = temp_dir("remote-deferral-restart");
    let database_path = dir.join("jobs.sqlite3");
    let source_path = dir.join("interview.wav");
    fs::write(&source_path, b"RIFF-restart-fixture").unwrap();

    {
        let ledger = JobLedger::open(&database_path).unwrap();
        let mut job = imported_job_at("job-durable-deferral", source_path);
        job.status = RecordingJobStatus::Uploading;
        job.route = Some(RecordingRoute::ServerBatch);
        job.attempt_count = 6;
        job.asr_catalog_binding = Some(crate::jobs::AsrCatalogBinding::for_test());
        ledger.insert_job(&job).unwrap();
        let deferred = ledger
            .defer_remote_retry(
                "job-durable-deferral",
                "REMOTE_CAPACITY_WAITING",
                "The private server is busy. Yap will retry this recording automatically.",
                40_000,
                10_000,
            )
            .unwrap();
        assert_eq!(deferred.attempt_count, 6);
    }

    let ledger = JobLedger::open(&database_path).unwrap();
    let recovered = ledger.get_job("job-durable-deferral").unwrap().unwrap();
    assert_eq!(recovered.status, RecordingJobStatus::Uploading);
    assert_eq!(recovered.attempt_count, 6);
    assert_eq!(recovered.next_attempt_at_ms, Some(40_000));
    assert_eq!(
        recovered.error_code.as_deref(),
        Some("REMOTE_CAPACITY_WAITING")
    );
    drop(ledger);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn failed_remote_retry_preserves_capture_across_source_mutation_and_restart() {
    let dir = temp_dir("remote-retry-reset");
    let database_path = dir.join("jobs.sqlite3");
    let source_path = dir.join("source.wav");
    let manifest_path = dir.join("spool/job-retry/capture-manifest.json");
    let chunk_path = dir.join("spool/job-retry/track-1-0-9.pcm");
    fs::create_dir_all(manifest_path.parent().unwrap()).unwrap();
    fs::write(&source_path, b"RIFF-retry-fixture").unwrap();
    fs::write(&manifest_path, b"{}").unwrap();
    let prepared_audio = vec![7_u8; 320];
    fs::write(&chunk_path, &prepared_audio).unwrap();
    let ledger = JobLedger::open(&database_path).unwrap();
    let mut job = imported_job_at("job-retry", source_path.clone());
    job.status = RecordingJobStatus::QueuedServer;
    job.route = Some(RecordingRoute::ServerBatch);
    job.asr_catalog_binding = Some(crate::jobs::AsrCatalogBinding::for_test());
    ledger.insert_job(&job).unwrap();
    ledger
        .transition("job-retry", RecordingJobStatus::Preprocessing, 201)
        .unwrap();
    let capture_manifest_sha256 =
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    let prepared = prepared_remote_job_at(
        manifest_path.clone(),
        chunk_path.clone(),
        capture_manifest_sha256,
    );
    let create_request_json = prepared.create_request_json.clone();
    ledger
        .attach_prepared_remote_job("job-retry", &prepared, 202)
        .unwrap();
    ledger
        .begin_remote_create_attempt("job-retry", "http://127.0.0.1:18765", 203)
        .unwrap();
    ledger
        .record_server_job_id(
            "job-retry",
            "job-server-retry",
            "http://127.0.0.1:18765",
            203,
        )
        .unwrap();
    ledger
        .acknowledge_remote_chunk("job-retry", "microphone", 0, 159, &"b".repeat(64), 204)
        .unwrap();
    ledger.mark_remote_job_committed("job-retry", 205).unwrap();
    let failed = ledger
        .record_remote_error(
            "job-retry",
            "SERVER_CONTRACT_ERROR",
            "The private server returned incompatible job state.",
            None,
            206,
        )
        .unwrap();
    assert_eq!(failed.status, RecordingJobStatus::Failed);

    fs::write(&source_path, b"RIFF-mutated-after-admission").unwrap();
    drop(ledger);
    let ledger = JobLedger::open(&database_path).unwrap();

    assert!(ledger
        .retry_to_queued_server("job-retry", 207, Some(604_800_207))
        .is_err());
    let retried = ledger
        .request_bound_server_stage_retry("job-retry", 208, Some(604_800_208))
        .unwrap();
    assert_eq!(retried.status, RecordingJobStatus::ServerProcessing);
    assert_eq!(
        retried.error_code.as_deref(),
        Some(crate::jobs::REMOTE_STAGE_RETRY_REQUESTED)
    );
    assert_eq!(
        retried.capture_manifest_sha256.as_deref(),
        Some(capture_manifest_sha256)
    );
    let preserved = ledger
        .get_prepared_remote_job("job-retry")
        .unwrap()
        .expect("prepared capture survives retry");
    assert_eq!(preserved.create_request_json, create_request_json);
    assert_eq!(preserved.capture_manifest_path, manifest_path);
    assert_eq!(preserved.capture_manifest_sha256, capture_manifest_sha256);
    assert_eq!(preserved.server_job_id.as_deref(), Some("job-server-retry"));
    assert_eq!(
        preserved.server_base_url.as_deref(),
        Some("http://127.0.0.1:18765")
    );
    assert_eq!(preserved.create_attempt_base_url, None);
    let chunks = ledger.list_chunks("job-retry").unwrap();
    assert_eq!(chunks.len(), 1);
    assert_eq!(chunks[0].artifact_path, chunk_path);
    assert_eq!(chunks[0].upload_offset, chunks[0].content_byte_length);
    assert_eq!(
        chunks[0].acknowledged_object_id.as_deref(),
        Some("job-server-retry")
    );
    assert_eq!(chunks[0].acknowledged_at_ms, Some(204));
    assert_eq!(fs::read(&chunks[0].artifact_path).unwrap(), prepared_audio);
    assert!(ledger
        .list_detached_remote_cancellations()
        .unwrap()
        .is_empty());
    drop(ledger);
    fs::remove_dir_all(dir).unwrap();
}
