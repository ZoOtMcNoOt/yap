use super::*;

#[test]
fn client_preflight_retry_reuses_owned_evidence_without_reopening_the_external_source() {
    let dir = temp_dir("client-preflight-retry");
    let database = dir.join("jobs.sqlite3");
    let source = dir.join("source.wav");
    write_pcm_wav(&source, &vec![7_u8; 640_000]);
    let jobs = RecordingJobs::from_ledger(JobLedger::open(&database).unwrap(), &dir);
    let media = MediaOwner::new();
    let job_id = jobs
        .create_imports(&media, vec![source.clone()], 5_800)
        .unwrap()[0]
        .id
        .clone();
    let (manifest, _) = attach_test_client_preflight(&jobs, &job_id, 5_801);
    jobs.ledger()
        .record_manual_lid_preflight(
            &job_id,
            "server_preflight_unavailable",
            &"a".repeat(64),
            "server-preflight-unavailable-v1",
            5_802,
        )
        .unwrap();
    jobs.ledger()
        .fail_client_preflight(
            &job_id,
            "CLIENT_PREFLIGHT_FAILED",
            "The selected recording could not be prepared safely for language review.",
            5_803,
        )
        .unwrap();
    drop(jobs);
    drop(media);
    fs::remove_file(&source).unwrap();

    let jobs = RecordingJobs::from_ledger(JobLedger::open(&database).unwrap(), &dir);
    let media = MediaOwner::new();
    let retried = jobs.retry(&media, &job_id, 5_804, || {}).unwrap();

    assert_eq!(retried.status, RecordingJobStatus::Preflighting);
    assert_eq!(retried.source_path, None);
    assert_eq!(retried.playback_path, None);
    assert!(retried.language_review.is_some());
    assert!(manifest.is_file());
    assert!(jobs
        .ledger()
        .get_client_preflight_artifact(&job_id)
        .unwrap()
        .is_some());
    let snapshot = jobs.snapshot(&media, 5_805).unwrap();
    assert_eq!(snapshot[0].status, RecordingJobStatus::Preflighting);
    assert!(snapshot[0].language_review.is_some());
    assert_eq!(snapshot[0].source_path, None);

    drop(media);
    drop(jobs);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn prepared_retry_uses_immutable_spool_after_external_source_changes() {
    let dir = temp_dir("prepared-retry-immutable-source");
    let database = dir.join("jobs.sqlite3");
    let source = dir.join("source.wav");
    write_pcm_wav(&source, &vec![7_u8; 320]);
    let original_source = fs::read(&source).unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open(&database).unwrap(), &dir);
    let media = MediaOwner::new();
    let decision = crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap();
    let binding = crate::jobs::AsrCatalogBinding::for_test();
    let prepared = jobs.prepare_imports(vec![source.clone()]).unwrap();
    let committed = jobs
        .commit_prepared_imports(prepared, 5_900, decision.clone(), &binding)
        .unwrap();
    let job_id = jobs.ledger().list_recoverable_jobs().unwrap()[0]
        .job_id
        .clone();
    // This test exercises a downstream immutable server capture. Record an
    // explicit Accepted-state decision so projection takes the compatibility
    // path used by already-admitted legacy jobs.
    jobs.ledger()
        .confirm_language_decision(
            &job_id,
            &decision,
            &"c".repeat(64),
            5_900,
            Some(serde_json::json!({"source": "test-fixture"})),
            None,
        )
        .unwrap();
    assert_eq!(
        jobs.project_committed_imports(&media, committed, 5_900)
            .unwrap()[0]
            .status,
        RecordingJobStatus::QueuedServer
    );
    jobs.ledger()
        .transition(&job_id, RecordingJobStatus::Preprocessing, 5_901)
        .unwrap();
    let spool = jobs.remote_jobs_directory().join(&job_id);
    fs::create_dir_all(&spool).unwrap();
    let manifest = spool.join("capture-manifest.json");
    let chunk = spool.join("track-1-0-159.pcm");
    let chunk_bytes = vec![7_u8; 320];
    fs::write(&manifest, b"{}").unwrap();
    fs::write(&chunk, &chunk_bytes).unwrap();
    let capture_sha256 = "a".repeat(64);
    let durable_chunk = crate::jobs::NewJobChunk {
        owner_namespace: "local:i-prepared-retry".into(),
        session_id: "s-prepared-retry".into(),
        track_id: "track-1".into(),
        sequence_start: 0,
        sequence_end: 159,
        content_sha256: "b".repeat(64),
        content_byte_length: chunk_bytes.len() as u64,
        artifact_path: chunk.clone(),
        upload_offset: 0,
        acknowledged_object_id: None,
        acknowledged_at_ms: None,
    };
    let request = crate::server_connector::batch::CreateRecordingJobRequest::for_test_single_chunk(
        "source.wav",
        &durable_chunk.session_id,
        &durable_chunk.track_id,
        &capture_sha256,
        2,
        &durable_chunk.content_sha256,
        durable_chunk.content_byte_length,
        crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap(),
        &"a".repeat(64),
    );
    jobs.ledger()
        .attach_prepared_remote_job(
            &job_id,
            &crate::jobs::NewPreparedRemoteJob {
                create_request_json: serde_json::to_string(&request).unwrap(),
                capture_manifest_path: manifest.clone(),
                capture_manifest_sha256: capture_sha256.clone(),
                chunks: vec![durable_chunk],
            },
            5_902,
        )
        .unwrap();
    jobs.ledger()
        .record_remote_error(
            &job_id,
            "SERVER_CONTRACT_ERROR",
            "The private server rejected the prepared request.",
            None,
            5_903,
        )
        .unwrap();
    drop(media);
    drop(jobs);

    write_pcm_wav(&source, &vec![9_u8; 640]);
    assert_ne!(fs::read(&source).unwrap(), original_source);

    let jobs = RecordingJobs::from_ledger(JobLedger::open(&database).unwrap(), &dir);
    let media = MediaOwner::new();
    let retried = jobs.retry(&media, &job_id, 5_904, || {}).unwrap();

    assert_eq!(retried.status, RecordingJobStatus::Uploading);
    assert_eq!(retried.source_path, None);
    assert_eq!(retried.playback_path, None);
    assert_eq!(fs::read(&manifest).unwrap(), b"{}");
    assert_eq!(fs::read(&chunk).unwrap(), chunk_bytes);
    let durable = jobs.ledger().get_job(&job_id).unwrap().unwrap();
    assert_eq!(
        durable.capture_manifest_sha256.as_deref(),
        Some(capture_sha256.as_str())
    );
    assert!(jobs
        .ledger()
        .get_prepared_remote_job(&job_id)
        .unwrap()
        .is_some());

    drop(media);
    drop(jobs);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn cancellation_and_retry_follow_ledger_legality_and_preserve_external_files() {
    let dir = temp_dir("cancel-retry");
    let cancel_source = dir.join("cancel.wav");
    let retry_source = dir.join("retry.wav");
    fs::write(&cancel_source, b"RIFF-cancel-fixture").unwrap();
    fs::write(&retry_source, b"RIFF-retry-fixture").unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open_in_memory().unwrap(), &dir);
    let media = MediaOwner::new();
    let cancel_id = jobs
        .create_imports(&media, vec![cancel_source.display().to_string()], 6_000)
        .unwrap()[0]
        .id
        .clone();
    let retry_id = jobs
        .create_imports(&media, vec![retry_source.display().to_string()], 6_001)
        .unwrap()[0]
        .id
        .clone();
    let admissions_before_illegal_dismiss = media.active_admission_count_for_test();
    assert!(jobs.dismiss(&media, &cancel_id, 6_002, || {}).is_err());
    assert_eq!(
        jobs.ledger().get_job(&cancel_id).unwrap().unwrap().status,
        RecordingJobStatus::Preflighting
    );
    assert_eq!(
        media.active_admission_count_for_test(),
        admissions_before_illegal_dismiss
    );
    jobs.ledger()
        .fail_source_validation(&retry_id, "SOURCE_UNSAFE", 6_003)
        .unwrap();

    let cancelled = jobs.cancel(&media, &cancel_id, 6_004, || {}).unwrap();
    let retried = jobs.retry(&media, &retry_id, 6_005, || {}).unwrap();

    assert_eq!(cancelled.status, RecordingJobStatus::Cancelled);
    assert!(cancel_source.is_file());
    assert_eq!(retried.status, RecordingJobStatus::Preflighting);
    assert!(jobs.cancel(&media, &cancel_id, 6_006, || {}).is_err());
    let admissions_before_illegal_retry = media.active_admission_count_for_test();
    let registry_before_illegal_retry = fs::read(&jobs.registry_path).unwrap();
    assert!(jobs.retry(&media, &cancel_id, 6_007, || {}).is_err());
    assert_eq!(
        media.active_admission_count_for_test(),
        admissions_before_illegal_retry
    );
    assert_eq!(
        fs::read(&jobs.registry_path).unwrap(),
        registry_before_illegal_retry
    );
    let recreated = jobs
        .create_imports(&media, vec![cancel_source.display().to_string()], 6_008)
        .unwrap();
    assert_ne!(recreated[0].id, cancel_id);
    assert_eq!(recreated[0].status, RecordingJobStatus::Preflighting);

    drop(media);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn restart_rejects_a_source_replaced_by_a_reparse_point() {
    let dir = temp_dir("restart-reparse");
    let database = dir.join("jobs.sqlite3");
    let source = dir.join("source.wav");
    let target_dir = dir.join("reparse-target");
    fs::create_dir_all(&target_dir).unwrap();
    let target = target_dir.join("target.wav");
    fs::write(&source, b"RIFF-original-fixture").unwrap();
    fs::write(&target, b"RIFF-target-fixture").unwrap();
    {
        let jobs = RecordingJobs::from_ledger(JobLedger::open(&database).unwrap(), &dir);
        let media = MediaOwner::new();
        jobs.create_imports(&media, vec![source.display().to_string()], 7_000)
            .unwrap();
    }
    fs::remove_file(&source).unwrap();
    create_reparse_point(&target, &source).expect(
        "reparse fixture creation failed; tests require file symlinks or NTFS directory junctions",
    );
    let link_metadata = fs::symlink_metadata(&source).unwrap();
    assert!(
        link_metadata.file_type().is_symlink()
            || crate::recording_access::metadata_is_reparse_point_for_test(&link_metadata),
        "fixture must be a symlink or Windows reparse point"
    );

    let jobs = RecordingJobs::from_ledger(JobLedger::open(&database).unwrap(), &dir);
    let media = MediaOwner::new();
    let snapshot = jobs.snapshot(&media, 7_001).unwrap();

    assert_eq!(snapshot[0].status, RecordingJobStatus::Failed);
    assert_eq!(snapshot[0].error.as_deref(), Some("SOURCE_UNSAFE"));
    assert_eq!(snapshot[0].source_path, None);
    assert_eq!(snapshot[0].playback_path, None);

    remove_reparse_point(&source).unwrap();
    drop(media);
    drop(jobs);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn create_and_cancel_notifications_observe_committed_ledger_state() {
    let dir = temp_dir("event-after-commit");
    let source = dir.join("event.wav");
    fs::write(&source, b"RIFF-event-fixture").unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open_in_memory().unwrap(), &dir);
    let media = MediaOwner::new();

    let created = mutate_then_notify(
        || jobs.create_imports(&media, vec![source.display().to_string()], 8_000),
        || {
            assert_eq!(jobs.ledger().list_jobs().unwrap().len(), 1);
        },
    )
    .unwrap();
    let job_id = created[0].id.clone();
    mutate_then_notify(
        || jobs.cancel(&media, &job_id, 8_001, || {}),
        || {
            assert_eq!(
                jobs.ledger().get_job(&job_id).unwrap().unwrap().status,
                RecordingJobStatus::Cancelled
            );
        },
    )
    .unwrap();

    drop(media);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn accepted_retry_notifies_only_after_atomic_preflight_returns_to_server_queue() {
    let dir = temp_dir("accepted-retry-event");
    let source = dir.join("accepted.wav");
    fs::write(&source, b"RIFF-accepted-fixture").unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open_in_memory().unwrap(), &dir);
    let media = MediaOwner::new();
    let selected_source = jobs.validate_source(&source).unwrap();
    crate::recording_access::register_native_selected_recording_job_source_at(
        &selected_source,
        &jobs.selection_registry_path,
        jobs.owned_dir(),
    )
    .unwrap();
    jobs.ledger()
        .insert_job(&NewRecordingJob {
            job_id: "job-accepted".into(),
            session_mode: SessionMode::Meeting,
            session_origin: SessionOrigin::ImportedFile,
            source_path: Some(source.canonicalize().unwrap()),
            source_ownership: SourceOwnership::External,
            output_path: None,
            display_name: "accepted.wav".into(),
            status: RecordingJobStatus::Accepted,
            route: Some(RecordingRoute::ServerBatch),
            attempt_count: 0,
            next_attempt_at_ms: None,
            cancellation_requested: false,
            capture_commit_path: None,
            capture_manifest_sha256: None,
            error_code: None,
            error_message: None,
            created_at_ms: 8_500,
            updated_at_ms: 8_500,
            expires_at_ms: Some(8_500 + PENDING_JOB_LIFETIME_MS),
            language_decision: crate::jobs::RecordingLanguageDecision::primary("en-US".into())
                .unwrap(),
            language_decision_locked: true,
            client_stage_history_complete: true,
            asr_catalog_binding: Some(crate::jobs::AsrCatalogBinding::for_test()),
        })
        .unwrap();

    let retried = jobs
        .retry(&media, "job-accepted", 8_501, || {
            assert_eq!(
                jobs.ledger()
                    .get_job("job-accepted")
                    .unwrap()
                    .unwrap()
                    .status,
                RecordingJobStatus::QueuedServer
            );
        })
        .unwrap();

    assert_eq!(retried.status, RecordingJobStatus::QueuedServer);
    let renewed_expiry = 8_501 + PENDING_JOB_LIFETIME_MS;
    assert_eq!(
        jobs.ledger()
            .get_job("job-accepted")
            .unwrap()
            .unwrap()
            .expires_at_ms,
        Some(renewed_expiry)
    );
    assert_eq!(
        jobs.snapshot(&media, renewed_expiry - 1).unwrap()[0].status,
        RecordingJobStatus::QueuedServer
    );
    let at_boundary = jobs.snapshot(&media, renewed_expiry).unwrap();
    assert_eq!(at_boundary[0].status, RecordingJobStatus::Failed);
    assert_eq!(at_boundary[0].error.as_deref(), Some("PENDING_EXPIRED"));
    drop(media);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn authority_failed_retry_stays_capability_free_until_a_second_explicit_retry() {
    let dir = temp_dir("retry-admission-failure");
    let database = dir.join("jobs.sqlite3");
    let general_registry = dir.join("recording-playback-registry.json");
    let source = dir.join("retry.wav");
    let source_bytes = b"RIFF-retry-admission-fixture";
    fs::write(&source, source_bytes).unwrap();
    let canonical_source = source.canonicalize().unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open(&database).unwrap(), &dir);
    let media = MediaOwner::new();
    let job_id = jobs
        .create_imports(&media, vec![source.display().to_string()], 8_700)
        .unwrap()[0]
        .id
        .clone();
    jobs.ledger()
        .fail_source_validation(&job_id, "INITIAL_FAILURE", 8_701)
        .unwrap();
    jobs.inject_projection_failures_for_test(vec![command_error(
        "PLAYBACK_AUTHORITY_FAILED",
        "injected retry admission failure",
    )]);
    let authority_denied_before_event_snapshot = Cell::new(false);
    let authority_denied_after_event_snapshot = Cell::new(false);
    let event_snapshot = RefCell::new(None);

    let retried = mutate_then_notify(
        || jobs.retry(&media, &job_id, 8_702, || {}),
        || {
            authority_denied_before_event_snapshot.set(open_and_reveal_are_denied(
                &jobs,
                &source,
                &general_registry,
            ));
            let snapshot = jobs.snapshot(&media, 8_703).unwrap();
            authority_denied_after_event_snapshot.set(open_and_reveal_are_denied(
                &jobs,
                &source,
                &general_registry,
            ));
            *event_snapshot.borrow_mut() = Some(snapshot);
        },
    )
    .unwrap();
    let event_snapshot = event_snapshot.into_inner().unwrap();
    let committed = jobs.ledger().get_job(&job_id).unwrap().unwrap();

    assert_eq!(committed.status, RecordingJobStatus::Failed);
    assert_eq!(committed.attempt_count, 1);
    assert_eq!(
        committed.error_code.as_deref(),
        Some("PLAYBACK_AUTHORITY_FAILED")
    );
    assert_eq!(
        committed.source_path.as_deref(),
        Some(canonical_source.as_path())
    );
    assert!(capability_free_failed(&retried));
    assert!(capability_free_failed(&event_snapshot[0]));
    assert!(authority_denied_before_event_snapshot.get());
    assert!(authority_denied_after_event_snapshot.get());
    assert_eq!(fs::read(&source).unwrap(), source_bytes);

    drop(media);
    drop(jobs);

    let jobs = RecordingJobs::from_ledger(JobLedger::open(&database).unwrap(), &dir);
    let media = MediaOwner::new();
    let restart_snapshot = jobs.snapshot(&media, 8_704).unwrap();
    assert!(capability_free_failed(&restart_snapshot[0]));
    assert!(open_and_reveal_are_denied(
        &jobs,
        &source,
        &general_registry
    ));
    let restarted = jobs.ledger().get_job(&job_id).unwrap().unwrap();
    assert_eq!(restarted.attempt_count, 1);
    assert_eq!(
        restarted.source_path.as_deref(),
        Some(canonical_source.as_path())
    );

    let second_retry = jobs.retry(&media, &job_id, 8_705, || {}).unwrap();
    assert_eq!(second_retry.status, RecordingJobStatus::Preflighting);
    assert_eq!(
        second_retry.source_path.as_deref(),
        canonical_source.to_str()
    );
    assert!(second_retry.playback_path.is_some());
    assert_eq!(
        jobs.ledger()
            .get_job(&job_id)
            .unwrap()
            .unwrap()
            .attempt_count,
        2
    );
    assert_eq!(
        crate::recording_access::openable_app_path_from_registries(
            source.display().to_string(),
            &general_registry,
            &jobs.registry_path,
            jobs.owned_dir(),
        )
        .unwrap(),
        canonical_source
    );
    assert_eq!(fs::read(&source).unwrap(), source_bytes);

    drop(media);
    drop(jobs);
    fs::remove_dir_all(dir).unwrap();
}
