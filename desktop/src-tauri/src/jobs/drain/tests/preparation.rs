use super::*;

#[test]
fn background_preprocessing_requires_durable_native_selection_authority() {
    let root = temp_dir("preprocessing-selection-authority");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    let selection_registry = root.join("recording-native-selection-registry.json");
    fs::create_dir_all(&owned_live).unwrap();
    let source = root.join("source.wav");
    write_pcm_wav(&source, &[0_u8; 320]);
    let resources = RecordingJobResources::from_storage(
        JobLedger::open_in_memory().unwrap(),
        owned_live,
        remote_jobs.clone(),
        selection_registry.clone(),
    );
    let mut job = queued_job("job-selection-authority", source.clone());
    job.status = RecordingJobStatus::Preprocessing;
    resources.ledger().insert_job(&job).unwrap();
    let owner = OwnerNamespace::local("i-selection-authority").unwrap();

    let error = super::super::preparation::prepare_job_for_resources(
        &resources,
        &owner,
        &job.job_id,
        1_720_000_000_100,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
    )
    .unwrap_err();
    assert!(error
        .to_string()
        .contains("Recording file is not registered for playback"));
    assert!(!remote_jobs.join(&job.job_id).exists());

    let validated = crate::recording_access::validate_recording_job_source_at(
        &source,
        resources.owned_live_directory(),
    )
    .unwrap();
    crate::recording_access::register_native_selected_recording_job_source_at(
        &validated,
        &selection_registry,
        resources.owned_live_directory(),
    )
    .unwrap();
    assert_eq!(
        super::super::preparation::prepare_job_for_resources(
            &resources,
            &owner,
            &job.job_id,
            1_720_000_000_200,
            UNIX_EPOCH + Duration::from_secs(1_720_000_000),
        )
        .unwrap(),
        Some(job.job_id.clone())
    );

    drop(resources);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn durable_preprocessing_cancellation_is_typed_as_cancellation() {
    let root = temp_dir("prepare-typed-cancellation");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    let source = root.join("source.wav");
    write_pcm_wav(&source, &[0_u8; 320]);
    let resources = RecordingJobResources::from_storage(
        JobLedger::open_in_memory().unwrap(),
        owned_live,
        remote_jobs,
        root.join("recording-native-selection-registry.json"),
    );
    let mut cancelled = queued_job("job-preprocessing-cancelled", source);
    cancelled.status = RecordingJobStatus::Preprocessing;
    cancelled.cancellation_requested = true;
    resources.ledger().insert_job(&cancelled).unwrap();
    let owner = OwnerNamespace::local("i-typed-preprocessing-cancellation").unwrap();

    let error = super::super::preparation::prepare_next_queued_job_for_resources(
        &resources,
        &owner,
        1_720_000_000_200,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
    )
    .unwrap_err();

    assert_eq!(error.job_id(), Some("job-preprocessing-cancelled"));
    assert!(error.is_cancelled());
    assert_eq!(
        resources
            .ledger()
            .get_job("job-preprocessing-cancelled")
            .unwrap()
            .unwrap()
            .status,
        RecordingJobStatus::Preprocessing
    );

    drop(resources);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn preprocessing_failure_identifies_and_fails_only_its_exact_job() {
    let root = temp_dir("prepare-exact-failure-owner");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    let missing = root.join("missing.wav");
    let healthy = root.join("healthy.wav");
    write_pcm_wav(&healthy, &[0_u8; 320]);
    let resources = Arc::new(RecordingJobResources::from_storage(
        JobLedger::open_in_memory().unwrap(),
        owned_live,
        remote_jobs,
        root.join("recording-native-selection-registry.json"),
    ));
    resources
        .ledger()
        .insert_jobs(&[
            queued_job("job-a-preprocessing-failure", missing),
            queued_job("job-b-preprocessing-neighbor", healthy),
        ])
        .unwrap();
    for job_id in [
        "job-a-preprocessing-failure",
        "job-b-preprocessing-neighbor",
    ] {
        resources
            .ledger()
            .transition(job_id, RecordingJobStatus::Preprocessing, 1_720_000_000_100)
            .unwrap();
    }
    let owner = OwnerNamespace::local("i-exact-preprocessing-failure").unwrap();
    let drain = RemoteJobDrain::from_resources_for_test(Arc::clone(&resources), owner.clone());

    let error = super::super::preparation::prepare_next_queued_job_for_resources(
        &resources,
        &owner,
        1_720_000_000_200,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
    )
    .unwrap_err();

    assert_eq!(error.job_id(), Some("job-a-preprocessing-failure"));
    assert!(!error.is_cancelled());
    drain
        .fail_preprocessing_job(error.job_id().unwrap(), 1_720_000_000_300)
        .unwrap();
    assert_eq!(
        resources
            .ledger()
            .get_job("job-a-preprocessing-failure")
            .unwrap()
            .unwrap()
            .status,
        RecordingJobStatus::Failed
    );
    assert_eq!(
        resources
            .ledger()
            .get_job("job-b-preprocessing-neighbor")
            .unwrap()
            .unwrap()
            .status,
        RecordingJobStatus::Preprocessing
    );

    drop(drain);
    drop(resources);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn queued_wav_is_preprocessed_into_durable_owned_replay_state() {
    let root = temp_dir("prepare");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let original = fs::read(&source).unwrap();
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&NewRecordingJob {
            job_id: "job-drain-prepare".into(),
            session_mode: SessionMode::Meeting,
            session_origin: SessionOrigin::ImportedFile,
            source_path: Some(source.clone()),
            source_ownership: SourceOwnership::External,
            output_path: None,
            display_name: "source.wav".into(),
            status: RecordingJobStatus::QueuedServer,
            route: Some(RecordingRoute::ServerBatch),
            attempt_count: 0,
            next_attempt_at_ms: None,
            cancellation_requested: false,
            capture_commit_path: None,
            capture_manifest_sha256: None,
            error_code: None,
            error_message: None,
            created_at_ms: 1_720_000_000_000,
            updated_at_ms: 1_720_000_000_000,
            expires_at_ms: Some(1_720_604_800_000),
            language_decision: crate::jobs::RecordingLanguageDecision::primary("en-US".into())
                .unwrap(),
            language_decision_locked: true,
            client_stage_history_complete: true,
            asr_catalog_binding: Some(crate::jobs::AsrCatalogBinding::for_test()),
        })
        .unwrap();
    let owner = OwnerNamespace::local("i-drain-test").unwrap();

    assert!(prepare_next_queued_job(
        &ledger,
        &owned_live,
        &remote_jobs,
        &owner,
        1_720_000_000_100,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
    )
    .unwrap());

    let job = ledger.get_job("job-drain-prepare").unwrap().unwrap();
    assert_eq!(job.status, RecordingJobStatus::Uploading);
    let prepared = ledger
        .get_prepared_remote_job("job-drain-prepare")
        .unwrap()
        .unwrap();
    assert!(prepared.capture_manifest_path.is_file());
    assert_eq!(ledger.list_chunks("job-drain-prepare").unwrap().len(), 1);
    assert_eq!(fs::read(source).unwrap(), original);

    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn a_cancelled_preprocessing_race_removes_the_unattached_owned_spool() {
    let root = temp_dir("prepare-cancel-race");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    let remote_jobs = root.join("remote-jobs");
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&queued_job("job-prepare-cancel-race", source.clone()))
        .unwrap();
    ledger
        .transition(
            "job-prepare-cancel-race",
            RecordingJobStatus::Preprocessing,
            1_720_000_000_100,
        )
        .unwrap();
    let owner = OwnerNamespace::local("i-drain-test").unwrap();
    let mut source_file = File::open(&source).unwrap();
    let prepared = crate::jobs::remote::prepare_imported_pcm_wav(
        "job-prepare-cancel-race",
        "source.wav",
        &mut source_file,
        &remote_jobs,
        &owner,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
        &crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap(),
    )
    .unwrap()
    .into_ledger_state()
    .unwrap();
    assert!(remote_jobs.join("job-prepare-cancel-race").is_dir());
    ledger
        .request_cancellation("job-prepare-cancel-race", 1_720_000_000_200)
        .unwrap();

    assert!(attach_prepared_remote_job_or_cleanup(
        &ledger,
        "job-prepare-cancel-race",
        &prepared,
        &remote_jobs,
        1_720_000_000_300,
    )
    .is_err());
    assert!(!remote_jobs.join("job-prepare-cancel-race").exists());
    assert!(source.is_file(), "external source must never be deleted");

    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}
