use super::super::error::RetryDisposition;
use super::super::scheduler::DurableStateCircuit;
use super::*;

#[test]
fn durable_state_circuit_requires_a_successful_write_probe_before_closing() {
    let mut circuit = DurableStateCircuit::default();
    assert!(!circuit.is_open());
    assert!(!circuit
        .try_close_with(|| Ok::<_, &'static str>(()))
        .unwrap());

    circuit.trip();
    assert!(circuit.is_open());
    assert_eq!(
        circuit.try_close_with(|| Err::<(), _>("write unavailable")),
        Err("write unavailable")
    );
    assert!(circuit.is_open());

    assert!(circuit
        .try_close_with(|| Ok::<_, &'static str>(()))
        .unwrap());
    assert!(!circuit.is_open());
}

#[test]
fn stale_catalog_upload_defers_without_consuming_remote_attempt_budget() {
    let dir = temp_dir("catalog-stale-no-budget");
    let source = dir.join("source.wav");
    fs::write(&source, b"external source").unwrap();
    let mut job = queued_job("job-catalog-stale", source);
    job.status = RecordingJobStatus::Uploading;
    let resources = Arc::new(RecordingJobResources::from_storage(
        JobLedger::open_in_memory().unwrap(),
        dir.join("recordings"),
        dir.join("remote-jobs"),
        dir.join("recording-native-selection-registry.json"),
    ));
    resources.ledger().insert_job(&job).unwrap();
    let drain = RemoteJobDrain::from_resources_for_test(
        Arc::clone(&resources),
        OwnerNamespace::local("i-catalog-stale").unwrap(),
    );

    drain
        .handle_upload_error(
            &job.job_id,
            &DrainStepError::catalog_revalidation("test stale catalog proof"),
            100,
            30_100,
        )
        .unwrap();

    let deferred = resources.ledger().get_job(&job.job_id).unwrap().unwrap();
    assert_eq!(deferred.status, RecordingJobStatus::Uploading);
    assert_eq!(deferred.attempt_count, 0);
    assert_eq!(deferred.next_attempt_at_ms, Some(30_100));
    assert_eq!(
        deferred.error_code.as_deref(),
        Some("ASR_CAPABILITY_UNAVAILABLE")
    );

    drop(drain);
    drop(resources);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn unsupported_catalog_defers_before_preprocessing_or_remote_artifact_creation() {
    let dir = temp_dir("unsupported-catalog-preprocessing");
    let source = dir.join("source.wav");
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let mut job = queued_job("job-unsupported-catalog", source);
    job.language_decision =
        crate::jobs::RecordingLanguageDecision::manual_override("fr-FR".into()).unwrap();
    let ledger = JobLedger::open_in_memory().unwrap();
    let job = ledger.insert_job(&job).unwrap();
    let catalog = crate::server_connector::AsrCapabilityCatalog::parse_bounded(include_bytes!(
        "../../../../../../server/openapi/examples/asr-capabilities.ok.json"
    ))
    .unwrap();
    let binding = crate::jobs::AsrCatalogBinding::try_new(
        "http://127.0.0.1:28765".into(),
        catalog.catalog_revision.clone(),
    )
    .unwrap();

    assert!(
        !claim_preprocessing_for_catalog(&ledger, &job, &catalog, &binding, 100, 30_100,).unwrap()
    );

    let deferred = ledger.get_job(&job.job_id).unwrap().unwrap();
    assert_eq!(deferred.status, RecordingJobStatus::QueuedServer);
    assert_eq!(deferred.attempt_count, 0);
    assert_eq!(deferred.next_attempt_at_ms, Some(30_100));
    assert!(ledger
        .get_prepared_remote_job(&job.job_id)
        .unwrap()
        .is_none());
    assert!(!dir.join("remote-jobs").join(&job.job_id).exists());

    drop(ledger);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn compatible_catalog_rebinds_the_exact_job_before_preprocessing() {
    let dir = temp_dir("compatible-catalog-rebind");
    let source = dir.join("source.wav");
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let job = queued_job("job-compatible-catalog", source);
    let ledger = JobLedger::open_in_memory().unwrap();
    let job = ledger.insert_job(&job).unwrap();
    let catalog = crate::server_connector::AsrCapabilityCatalog::parse_bounded(include_bytes!(
        "../../../../../../server/openapi/examples/asr-capabilities.ok.json"
    ))
    .unwrap();
    let binding = crate::jobs::AsrCatalogBinding::try_new(
        "http://127.0.0.1:28765".into(),
        catalog.catalog_revision.clone(),
    )
    .unwrap();

    assert!(
        claim_preprocessing_for_catalog(&ledger, &job, &catalog, &binding, 100, 30_100,).unwrap()
    );

    let claimed = ledger.get_job(&job.job_id).unwrap().unwrap();
    assert_eq!(claimed.status, RecordingJobStatus::Preprocessing);
    assert_eq!(claimed.asr_catalog_binding, Some(binding));

    drop(ledger);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn unconfirmed_language_cannot_cross_catalog_preprocessing_admission() {
    let dir = temp_dir("unconfirmed-language-admission");
    let source = dir.join("source.wav");
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let mut job = queued_job("job-unconfirmed-language", source);
    job.language_decision_locked = false;
    let ledger = JobLedger::open_in_memory().unwrap();
    let job = ledger.insert_job(&job).unwrap();
    let catalog = crate::server_connector::AsrCapabilityCatalog::parse_bounded(include_bytes!(
        "../../../../../../server/openapi/examples/asr-capabilities.ok.json"
    ))
    .unwrap();
    let binding = crate::jobs::AsrCatalogBinding::try_new(
        "http://127.0.0.1:28765".into(),
        catalog.catalog_revision.clone(),
    )
    .unwrap();

    assert!(
        claim_preprocessing_for_catalog(&ledger, &job, &catalog, &binding, 100, 30_100,).is_err()
    );

    let unchanged = ledger.get_job(&job.job_id).unwrap().unwrap();
    assert_eq!(unchanged.status, RecordingJobStatus::QueuedServer);
    assert!(!unchanged.language_decision_locked);
    assert!(ledger
        .get_prepared_remote_job(&job.job_id)
        .unwrap()
        .is_none());
    drop(ledger);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn retention_interrupts_active_preprocessing_after_the_durable_cancel() {
    let dir = temp_dir("retention-interrupts-preprocessing");
    let source = dir.join("source.wav");
    fs::write(&source, b"external source").unwrap();
    let mut job = queued_job("job-retention-preprocessing", source.clone());
    job.expires_at_ms = Some(100);
    let resources = Arc::new(RecordingJobResources::from_storage(
        JobLedger::open_in_memory().unwrap(),
        dir.join("recordings"),
        dir.join("remote-jobs"),
        dir.join("recording-native-selection-registry.json"),
    ));
    resources.ledger().insert_job(&job).unwrap();
    resources
        .ledger()
        .transition(
            "job-retention-preprocessing",
            RecordingJobStatus::Preprocessing,
            2,
        )
        .unwrap();
    let preprocessing = resources
        .begin_preprocessing("job-retention-preprocessing")
        .unwrap();
    let drain = RemoteJobDrain::from_resources_for_test(
        Arc::clone(&resources),
        OwnerNamespace::local("i-retention-interrupt").unwrap(),
    );

    assert!(drain.enforce_retention(100).unwrap());

    let cancelled = resources
        .ledger()
        .get_job("job-retention-preprocessing")
        .unwrap()
        .unwrap();
    assert_eq!(cancelled.status, RecordingJobStatus::Cancelled);
    assert_eq!(
        preprocessing.ensure_active().unwrap_err(),
        "recording job preprocessing was cancelled"
    );
    assert!(source.is_file());

    drop(preprocessing);
    drop(drain);
    drop(resources);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn retention_drain_removes_pruned_private_spools_before_acknowledging_cleanup() {
    let dir = temp_dir("pruned-spool-cleanup");
    let remote_jobs_directory = dir.join("remote-jobs");
    let job_id = "job-0123456789abcdef01234567";
    let owned_spool = remote_jobs_directory.join(job_id);
    fs::create_dir_all(&owned_spool).unwrap();
    fs::write(owned_spool.join("private.pcm"), b"private bytes").unwrap();
    let ledger = JobLedger::open_in_memory().unwrap();
    {
        let connection = ledger.connection.lock().unwrap();
        connection
            .execute(
                "INSERT INTO remote_spool_cleanup (job_id, queued_at_ms) VALUES (?1, 1)",
                [job_id],
            )
            .unwrap();
    }
    let resources = Arc::new(RecordingJobResources::from_storage(
        ledger,
        dir.join("recordings"),
        remote_jobs_directory,
        dir.join("recording-native-selection-registry.json"),
    ));
    let drain = RemoteJobDrain::from_resources_for_test(
        Arc::clone(&resources),
        OwnerNamespace::local("i-pruned-spool-test").unwrap(),
    );

    assert!(drain.has_pending_work().unwrap());
    let mutation = resources.mutation().lock().unwrap();
    let (completed_tx, completed_rx) = std::sync::mpsc::channel();
    let retention = thread::spawn(move || {
        completed_tx.send(drain.enforce_retention(2)).unwrap();
    });
    assert!(completed_rx
        .recv_timeout(Duration::from_millis(50))
        .is_err());
    drop(mutation);
    assert!(completed_rx
        .recv_timeout(Duration::from_secs(1))
        .unwrap()
        .unwrap());
    retention.join().unwrap();
    assert!(!owned_spool.exists());
    assert!(resources
        .ledger()
        .list_pending_remote_spool_cleanup()
        .unwrap()
        .is_empty());

    drop(resources);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn pending_owned_spool_cleanup_does_not_require_initialized_server_settings() {
    let dir = temp_dir("pending-spool-cleanup");
    let remote_jobs_directory = dir.join("remote-jobs");
    let job_id = "job-0123456789abcdef01234567";
    let owned_spool = remote_jobs_directory.join(job_id);
    fs::create_dir_all(&owned_spool).unwrap();
    fs::write(owned_spool.join("private.pcm"), b"private bytes").unwrap();
    let ledger = JobLedger::open_in_memory().unwrap();
    {
        let connection = ledger.connection.lock().unwrap();
        connection
            .execute(
                "INSERT INTO remote_spool_cleanup (job_id, queued_at_ms) VALUES (?1, 1)",
                [job_id],
            )
            .unwrap();
    }
    let connector = ServerConnector::new();

    let cleaned = tauri::async_runtime::block_on(advance_persisted_cancellation_once(
        &ledger,
        &remote_jobs_directory,
        &connector,
        2,
    ))
    .unwrap();

    assert!(cleaned);
    assert!(!owned_spool.exists());
    assert!(ledger
        .list_pending_remote_spool_cleanup()
        .unwrap()
        .is_empty());

    drop(ledger);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn automatic_remote_retries_are_typed_and_bounded() {
    let transient = DrainStepError::transient_state("request timed out");
    let permanent = DrainStepError::permanent("manifest conflicts with durable state");

    assert_eq!(
        remote_retry_plan(&transient, 0, 10_000),
        (
            Some(11_000),
            "REMOTE_REQUEST_RETRYING",
            "The private-server request did not complete. Yap will retry automatically.",
        )
    );
    assert_eq!(
            remote_retry_plan(&transient, 6, 10_000),
            (
                None,
                "REMOTE_RETRY_EXHAUSTED",
                "The private-server request did not recover after bounded retries. Retry the recording to start a new server job.",
            )
        );
    assert_eq!(
            remote_retry_plan(&permanent, 0, 10_000),
            (
                None,
                "REMOTE_STATE_INVALID",
                "The private-server job state is incompatible. Retry the recording to start a new server job.",
            )
        );
}

#[test]
fn capacity_and_ambiguous_commit_retries_remain_durable_after_bounded_budget_exhaustion() {
    let capacity =
        DrainStepError::from_commit_error(crate::server_connector::batch::BatchClientError::Api {
            status: reqwest::StatusCode::TOO_MANY_REQUESTS,
            code: "SERVER_BUSY".into(),
            retryable: true,
        });
    let ambiguous =
        DrainStepError::from_commit_error(crate::server_connector::batch::BatchClientError::Api {
            status: reqwest::StatusCode::CONFLICT,
            code: "JOB_NOT_COMMITTABLE".into(),
            retryable: false,
        });
    let malformed = DrainStepError::from_commit_error(
        crate::server_connector::batch::BatchClientError::MalformedResponse,
    );

    assert_eq!(
        capacity.retry_disposition,
        RetryDisposition::DurableCapacity
    );
    assert_eq!(
        remote_retry_plan(&capacity, 6, 10_000),
        (
            Some(40_000),
            "REMOTE_CAPACITY_WAITING",
            "The private server is busy. Yap will retry this recording automatically.",
        )
    );
    assert_eq!(
        ambiguous.retry_disposition,
        RetryDisposition::DurableAmbiguousCommit
    );
    assert_eq!(
        remote_retry_plan(&ambiguous, 6, 10_000),
        (
            Some(15_000),
            "REMOTE_COMMIT_RECONCILING",
            "Yap is confirming whether the private server accepted this recording and will retry automatically.",
        )
    );
    assert_eq!(
        malformed.retry_disposition,
        RetryDisposition::DurableAmbiguousCommit
    );
    assert_eq!(
        remote_retry_plan(&malformed, 6, 10_000),
        (
            Some(15_000),
            "REMOTE_COMMIT_RECONCILING",
            "Yap is confirming whether the private server accepted this recording and will retry automatically.",
        )
    );
}

#[test]
fn durable_remote_deferrals_do_not_consume_attempts_and_retention_or_cancellation_still_wins() {
    let dir = temp_dir("durable-remote-deferral");
    let capacity_source = dir.join("capacity.wav");
    let ambiguous_source = dir.join("ambiguous.wav");
    fs::write(&capacity_source, b"external source").unwrap();
    fs::write(&ambiguous_source, b"external source").unwrap();
    let mut capacity_job = queued_job("job-capacity-deferral", capacity_source.clone());
    capacity_job.status = RecordingJobStatus::Uploading;
    capacity_job.attempt_count = 6;
    capacity_job.expires_at_ms = Some(150);
    let mut ambiguous_job = queued_job("job-ambiguous-deferral", ambiguous_source.clone());
    ambiguous_job.status = RecordingJobStatus::Uploading;
    ambiguous_job.attempt_count = 6;
    let resources = Arc::new(RecordingJobResources::from_storage(
        JobLedger::open_in_memory().unwrap(),
        dir.join("recordings"),
        dir.join("remote-jobs"),
        dir.join("recording-native-selection-registry.json"),
    ));
    resources
        .ledger()
        .insert_jobs(&[capacity_job, ambiguous_job])
        .unwrap();
    let drain = RemoteJobDrain::from_resources_for_test(
        Arc::clone(&resources),
        OwnerNamespace::local("i-durable-deferral").unwrap(),
    );
    let capacity =
        DrainStepError::from_commit_error(crate::server_connector::batch::BatchClientError::Api {
            status: reqwest::StatusCode::TOO_MANY_REQUESTS,
            code: "SERVER_BUSY".into(),
            retryable: true,
        });
    let ambiguous =
        DrainStepError::from_commit_error(crate::server_connector::batch::BatchClientError::Api {
            status: reqwest::StatusCode::CONFLICT,
            code: "JOB_NOT_COMMITTABLE".into(),
            retryable: false,
        });

    assert!(drain
        .handle_upload_error("job-capacity-deferral", &capacity, 100, 30_100)
        .unwrap());
    assert!(drain
        .handle_upload_error("job-ambiguous-deferral", &ambiguous, 100, 30_100)
        .unwrap());

    let capacity_job = resources
        .ledger()
        .get_job("job-capacity-deferral")
        .unwrap()
        .unwrap();
    assert_eq!(capacity_job.status, RecordingJobStatus::Uploading);
    assert_eq!(capacity_job.attempt_count, 6);
    assert_eq!(capacity_job.next_attempt_at_ms, Some(30_100));
    assert_eq!(
        capacity_job.error_code.as_deref(),
        Some("REMOTE_CAPACITY_WAITING")
    );
    let ambiguous_job = resources
        .ledger()
        .get_job("job-ambiguous-deferral")
        .unwrap()
        .unwrap();
    assert_eq!(ambiguous_job.status, RecordingJobStatus::Uploading);
    assert_eq!(ambiguous_job.attempt_count, 6);
    assert_eq!(ambiguous_job.next_attempt_at_ms, Some(5_100));
    assert_eq!(
        ambiguous_job.error_code.as_deref(),
        Some("REMOTE_COMMIT_RECONCILING")
    );

    resources
        .ledger()
        .request_cancellation("job-ambiguous-deferral", 101)
        .unwrap();
    assert!(!drain
        .handle_upload_error("job-ambiguous-deferral", &ambiguous, 5_100, 35_100)
        .unwrap());
    assert_eq!(
        resources
            .ledger()
            .get_job("job-ambiguous-deferral")
            .unwrap()
            .unwrap()
            .status,
        RecordingJobStatus::Cancelled
    );

    assert!(drain.enforce_retention(150).unwrap());
    assert_eq!(
        resources
            .ledger()
            .get_job("job-capacity-deferral")
            .unwrap()
            .unwrap()
            .status,
        RecordingJobStatus::Cancelled
    );
    assert!(capacity_source.is_file());
    assert!(ambiguous_source.is_file());

    drop(drain);
    drop(resources);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn terminal_server_diagnostics_do_not_copy_server_controlled_messages() {
    let private_message = "Private transcript and C:/private/audio.wav";
    let error = ApiError {
        code: "ASR_WORKER_FAILED".into(),
        message: private_message.into(),
        retryable: true,
        request_id: "job-abc123".into(),
    };

    let diagnostic = DrainStepError::terminal_server(&error);

    assert!(diagnostic.detail.contains("ASR_WORKER_FAILED"));
    assert!(diagnostic.detail.contains("job-abc123"));
    assert!(!diagnostic.detail.contains(private_message));
}
