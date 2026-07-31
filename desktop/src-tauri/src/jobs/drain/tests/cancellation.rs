use super::*;

#[test]
fn restart_keeps_terminal_lid_reconciliation_durable_when_its_origin_is_retired() {
    let root = temp_dir("terminal-lid-cancel");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    write_pcm_wav(&source, &vec![0_u8; 640_000]);
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let base_url = format!("http://{}", listener.local_addr().unwrap());
    let ledger = JobLedger::open(&database).unwrap();
    let mut job = queued_job("job-terminal-lid", source);
    job.status = RecordingJobStatus::Accepted;
    job.language_decision_locked = false;
    job.client_stage_history_complete = false;
    ledger.insert_job(&job).unwrap();
    ledger
        .accept_to_preflighting("job-terminal-lid", 10, 10_000)
        .unwrap();
    let source_pcm_sha256 = "1".repeat(64);
    let preprocessing = PreprocessingEvidence::new(
        NormalizationEvidence::canonical_pcm16_identity(
            "2".repeat(64),
            source_pcm_sha256.clone(),
            source_pcm_sha256.clone(),
            320_000,
            320_000,
            0,
        ),
        VadEvidence::complete(
            VadComponentEvidence::for_test("test-vad", "test-v1"),
            320_000,
            vec![SourceVadInterval::for_test(0, 320_000)],
        ),
    );
    ledger
        .attach_client_preflight_artifact(
            "job-terminal-lid",
            &NewClientPreflightArtifact {
                manifest_path: root.join("remote-jobs/job-terminal-lid/client-preflight.json"),
                manifest_sha256: "3".repeat(64),
                source_pcm_sha256,
                source_sample_count: 320_000,
            },
            &preprocessing,
            20,
        )
        .unwrap();
    ledger
        .begin_lid_preflight_dispatch(crate::jobs::LidPreflightDispatchStart {
            job_id: "job-terminal-lid",
            request_id: "lid-request-restart",
            server_base_url: &base_url,
            catalog_revision: &"a".repeat(64),
            component_id: "ambernet-batch-language-preflight",
            policy_revision: "ambernet-stratified-five-region-v1",
            started_at_ms: 30,
        })
        .unwrap();
    ledger.request_cancellation("job-terminal-lid", 40).unwrap();
    drop(ledger);

    let reopened = JobLedger::open(&database).unwrap();
    let connector = ServerConnector::new();
    let error = tauri::async_runtime::block_on(async {
        advance_persisted_cancellation_once(&reopened, &root.join("remote-jobs"), &connector, 50)
            .await
            .unwrap_err()
    });
    assert!(error.to_string().contains("Server sign-in is unavailable"));

    assert_eq!(
        reopened
            .get_client_preflight_artifact("job-terminal-lid")
            .unwrap()
            .unwrap()
            .lid_request_id
            .as_deref(),
        Some("lid-request-restart")
    );
    assert!(reopened.has_remote_reconciliation_work().unwrap());
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );

    drop(reopened);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn bound_failed_job_cannot_be_detached_by_the_legacy_retry_path() {
    let root = temp_dir("bound-retry-reject");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&queued_job("job-detached-cancel", source))
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
    let server_job_id = "job-0123456789abcdef0123456789abcdef";
    let base_url = "http://127.0.0.1:18765";
    ledger
        .begin_remote_create_attempt("job-detached-cancel", base_url, 1_720_000_000_200)
        .unwrap();
    ledger
        .record_server_job_id(
            "job-detached-cancel",
            server_job_id,
            base_url,
            1_720_000_000_200,
        )
        .unwrap();
    ledger
        .record_remote_error(
            "job-detached-cancel",
            "REMOTE_RETRY_EXHAUSTED",
            "The private server request did not recover.",
            None,
            1_720_000_000_300,
        )
        .unwrap();
    assert!(ledger
        .retry_to_queued_server(
            "job-detached-cancel",
            1_720_000_000_400,
            Some(1_720_604_800_400),
        )
        .is_err());
    let still_bound = ledger
        .get_prepared_remote_job("job-detached-cancel")
        .unwrap()
        .unwrap();
    assert_eq!(still_bound.server_job_id.as_deref(), Some(server_job_id));
    assert_eq!(still_bound.server_base_url.as_deref(), Some(base_url));
    assert!(ledger
        .list_detached_remote_cancellations()
        .unwrap()
        .is_empty());
    assert!(remote_jobs.join("job-detached-cancel").is_dir());
    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn current_but_unapproved_origin_cancellation_is_blocked_without_network_dispatch() {
    let root = temp_dir("current-cancel");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&queued_job("job-current-cancel", source.clone()))
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
    let server_job_id = "job-0123456789abcdef0123456789abcdef";
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let base_url = format!("http://{}", listener.local_addr().unwrap());
    ledger
        .begin_remote_create_attempt("job-current-cancel", &base_url, 1_720_000_000_200)
        .unwrap();
    ledger
        .record_server_job_id(
            "job-current-cancel",
            server_job_id,
            &base_url,
            1_720_000_000_200,
        )
        .unwrap();
    ledger
        .request_cancellation("job-current-cancel", 1_720_000_000_300)
        .unwrap();
    let boundary = ServerConnectorBoundary::new();
    boundary.configure(&ServerSettings {
        enabled: true,
        base_url: Some(base_url.clone()),
        ..ServerSettings::default()
    });
    let connector = boundary.downgrade().upgrade().unwrap();

    let error = tauri::async_runtime::block_on(async {
        advance_persisted_cancellation_once(&ledger, &remote_jobs, &connector, 1_720_000_000_400)
            .await
            .unwrap_err()
    });
    assert!(error
        .to_string()
        .contains("origin is not currently approved"));

    assert!(remote_jobs.join("job-current-cancel").exists());
    assert!(source.is_file(), "external source must never be deleted");
    let pending = ledger
        .get_prepared_remote_job("job-current-cancel")
        .unwrap()
        .unwrap();
    assert_eq!(pending.server_cancellation_acknowledged_at_ms, None);
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn attached_cleanup_rejects_same_account_under_a_different_authentication_configuration() {
    let root = temp_dir("attached-authentication-change");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&queued_job("job-attached-authentication", source.clone()))
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
    let account = "a".repeat(64);
    let original_authentication = "1".repeat(64);
    ledger
        .bind_remote_authority(
            "job-attached-authentication",
            &account,
            &original_authentication,
        )
        .unwrap();
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let base_url = format!("http://{}", listener.local_addr().unwrap());
    let server_job_id = "job-0123456789abcdef0123456789abcdef";
    ledger
        .begin_remote_create_attempt("job-attached-authentication", &base_url, 1_720_000_000_200)
        .unwrap();
    ledger
        .record_server_job_id(
            "job-attached-authentication",
            server_job_id,
            &base_url,
            1_720_000_000_201,
        )
        .unwrap();
    ledger
        .request_cancellation("job-attached-authentication", 1_720_000_000_300)
        .unwrap();
    let client = BatchApiClient::new_authorized(
        AuthenticatedRequestDispatcher::fixed_authority(
            reqwest::Client::new(),
            "different-audience-token",
            &account,
            &"2".repeat(64),
        ),
        &base_url,
    )
    .unwrap();

    let error = tauri::async_runtime::block_on(advance_cancellation_once_guarded_for_test(
        &ledger,
        &remote_jobs,
        &client,
        1_720_000_000_400,
    ))
    .unwrap_err();

    assert!(error
        .to_string()
        .contains("different server account or authentication configuration"));
    let pending = ledger
        .get_prepared_remote_job("job-attached-authentication")
        .unwrap()
        .unwrap();
    assert_eq!(pending.server_cancellation_acknowledged_at_ms, None);
    assert!(remote_jobs.join("job-attached-authentication").is_dir());
    assert!(source.is_file());
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn detached_cleanup_rejects_same_account_under_a_different_authentication_configuration() {
    let root = temp_dir("detached-authentication-change");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&queued_job("job-detached-authentication", source.clone()))
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
    let account = "a".repeat(64);
    let original_authentication = "1".repeat(64);
    ledger
        .bind_remote_authority(
            "job-detached-authentication",
            &account,
            &original_authentication,
        )
        .unwrap();
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let base_url = format!("http://{}", listener.local_addr().unwrap());
    let server_job_id = "job-0123456789abcdef0123456789abcdef";
    ledger
        .begin_remote_create_attempt("job-detached-authentication", &base_url, 1_720_000_000_200)
        .unwrap();
    ledger
        .record_server_job_id(
            "job-detached-authentication",
            server_job_id,
            &base_url,
            1_720_000_000_201,
        )
        .unwrap();
    assert_eq!(
        ledger
            .detach_changed_remote_binding(Some("http://127.0.0.1:9"), 1_720_000_000_300,)
            .unwrap()
            .as_deref(),
        Some("job-detached-authentication")
    );
    let detached = ledger.list_detached_remote_cancellations().unwrap();
    assert_eq!(detached.len(), 1);
    assert_eq!(detached[0].remote_authority_binding, account);
    assert_eq!(
        detached[0].remote_authentication_binding,
        original_authentication
    );
    let client = BatchApiClient::new_authorized(
        AuthenticatedRequestDispatcher::fixed_authority(
            reqwest::Client::new(),
            "different-audience-token",
            &"a".repeat(64),
            &"2".repeat(64),
        ),
        &base_url,
    )
    .unwrap();

    let error = tauri::async_runtime::block_on(advance_cancellation_once_guarded_for_test(
        &ledger,
        &remote_jobs,
        &client,
        1_720_000_000_400,
    ))
    .unwrap_err();

    assert!(error
        .to_string()
        .contains("account or authentication configuration changed"));
    assert_eq!(
        ledger.list_detached_remote_cancellations().unwrap().len(),
        1
    );
    assert!(remote_jobs.join("job-detached-authentication").is_dir());
    assert!(source.is_file());
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn cancelled_inflight_create_at_a_retired_origin_remains_durable_without_dispatch() {
    let root = temp_dir("cancelled-create-attempt");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&queued_job("job-cancelled-create", source.clone()))
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
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let base_url = format!("http://{}", listener.local_addr().unwrap());
    ledger
        .begin_remote_create_attempt("job-cancelled-create", &base_url, 1_720_000_000_200)
        .unwrap();
    ledger
        .request_cancellation("job-cancelled-create", 1_720_000_000_201)
        .unwrap();
    let pending_probe_resources = Arc::new(RecordingJobResources::from_storage(
        JobLedger::open(&database).unwrap(),
        owned_live.clone(),
        remote_jobs.clone(),
        root.join("recording-native-selection-registry.json"),
    ));
    let pending_probe = RemoteJobDrain::from_resources_for_test(
        pending_probe_resources,
        OwnerNamespace::local("i-pending-probe").unwrap(),
    );
    assert!(pending_probe.has_pending_work().unwrap());
    drop(pending_probe);
    let connector = ServerConnector::new();

    let error = tauri::async_runtime::block_on(async {
        advance_persisted_cancellation_once(&ledger, &remote_jobs, &connector, 1_720_000_000_300)
            .await
            .unwrap_err()
    });
    assert!(error
        .to_string()
        .contains("origin is not the current configured server"));

    let pending = ledger
        .get_prepared_remote_job("job-cancelled-create")
        .unwrap()
        .unwrap();
    assert_eq!(pending.server_job_id, None);
    assert_eq!(pending.server_cancellation_acknowledged_at_ms, None);
    assert!(remote_jobs.join("job-cancelled-create").exists());
    assert!(source.is_file(), "external source must never be deleted");
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );

    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}
