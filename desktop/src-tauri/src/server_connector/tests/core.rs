use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc, TryLockError,
    },
    time::Duration,
};

use crate::{
    runtime,
    server_connector::{
        capability_snapshot, client, config, AsrCapabilityCatalog, ServerCapabilities,
        ServerConnector,
    },
};

const ASR_CATALOG_EXAMPLE: &[u8] =
    include_bytes!("../../../../../server/openapi/examples/asr-capabilities.ok.json");

#[test]
fn stale_batch_connection_lease_cannot_commit_after_configuration_changes() {
    let connector = ServerConnector::default();
    connector.synchronize_settings_with(
        &config::ServerSettings {
            schema_version: config::CURRENT_SCHEMA_VERSION,
            enabled: true,
            base_url: Some("http://127.0.0.1:18765".into()),
            authentication: None,
        },
        |_| {},
    );
    let (generation, _) = connector
        .begin_health_request_with(|_| {})
        .expect("configured connector begins health request");
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                batch_jobs: true,
                live_streaming: false,
                job_status: true,
                transcript_correction: false,
                librarian_queries: false,
                archivist_ingestions: false,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .batch_connection_lease()
        .unwrap()
        .expect("ready batch-capable connector yields a lease");
    connector.invalidate();

    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_batch_lease(&lease, || {
            committed.store(true, Ordering::SeqCst);
        })
        .is_err());
    assert!(!committed.load(Ordering::SeqCst));
}

#[test]
fn transcript_correction_lease_requires_capability_and_cannot_commit_after_change() {
    let connector = ServerConnector::default();
    connector.synchronize_settings_with(
        &config::ServerSettings {
            schema_version: config::CURRENT_SCHEMA_VERSION,
            enabled: true,
            base_url: Some("http://127.0.0.1:18765".into()),
            authentication: None,
        },
        |_| {},
    );
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                batch_jobs: false,
                live_streaming: false,
                job_status: false,
                transcript_correction: false,
                librarian_queries: false,
                archivist_ingestions: false,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert!(connector
        .transcript_correction_connection_lease()
        .unwrap()
        .is_none());

    connector.invalidate();
    connector.synchronize_settings_with(
        &config::ServerSettings {
            schema_version: config::CURRENT_SCHEMA_VERSION,
            enabled: true,
            base_url: Some("http://127.0.0.1:18765".into()),
            authentication: None,
        },
        |_| {},
    );
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                batch_jobs: false,
                live_streaming: false,
                job_status: false,
                transcript_correction: true,
                librarian_queries: false,
                archivist_ingestions: false,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .transcript_correction_connection_lease()
        .unwrap()
        .expect("ready transcript-correction connector yields a lease");
    connector.invalidate();
    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_transcript_correction_lease(&lease, || {
            committed.store(true, Ordering::SeqCst);
        })
        .is_err());
    assert!(!committed.load(Ordering::SeqCst));
}

#[test]
fn librarian_lease_requires_capability_and_cannot_commit_after_change() {
    let connector = ServerConnector::default();
    connector.synchronize_settings_with(
        &config::ServerSettings {
            schema_version: config::CURRENT_SCHEMA_VERSION,
            enabled: true,
            base_url: Some("http://127.0.0.1:18765".into()),
            authentication: None,
        },
        |_| {},
    );
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                batch_jobs: false,
                live_streaming: false,
                job_status: false,
                transcript_correction: false,
                librarian_queries: false,
                archivist_ingestions: false,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert!(connector.librarian_connection_lease().unwrap().is_none());

    connector.invalidate();
    connector.synchronize_settings_with(
        &config::ServerSettings {
            schema_version: config::CURRENT_SCHEMA_VERSION,
            enabled: true,
            base_url: Some("http://127.0.0.1:18765".into()),
            authentication: None,
        },
        |_| {},
    );
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                batch_jobs: false,
                live_streaming: false,
                job_status: false,
                transcript_correction: false,
                librarian_queries: true,
                archivist_ingestions: false,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .librarian_connection_lease()
        .unwrap()
        .expect("ready Librarian-capable connector yields a lease");
    connector.invalidate();
    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_librarian_lease(&lease, || {
            committed.store(true, Ordering::SeqCst);
        })
        .is_err());
    assert!(!committed.load(Ordering::SeqCst));
}

#[test]
fn archivist_lease_requires_capability_and_cannot_commit_after_change() {
    let connector = ServerConnector::default();
    connector.synchronize_settings_with(
        &config::ServerSettings {
            schema_version: config::CURRENT_SCHEMA_VERSION,
            enabled: true,
            base_url: Some("http://127.0.0.1:18765".into()),
            authentication: None,
        },
        |_| {},
    );
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                batch_jobs: false,
                live_streaming: false,
                job_status: false,
                transcript_correction: false,
                librarian_queries: false,
                archivist_ingestions: true,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .archivist_connection_lease()
        .unwrap()
        .expect("ready Archivist-capable connector yields a lease");
    connector.invalidate();
    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_archivist_lease(&lease, || {
            committed.store(true, Ordering::SeqCst);
        })
        .is_err());
    assert!(!committed.load(Ordering::SeqCst));
}

#[test]
fn stale_asr_catalog_lease_cannot_overwrite_a_newer_origin_snapshot() {
    let connector = ServerConnector::default();
    let leased_origin = "http://127.0.0.1:18765";
    let newer_origin = "http://127.0.0.1:18766";
    connector.synchronize_settings_with(
        &config::ServerSettings {
            schema_version: config::CURRENT_SCHEMA_VERSION,
            enabled: true,
            base_url: Some(leased_origin.into()),
            authentication: None,
        },
        |_| {},
    );
    let (generation, _) = connector
        .begin_health_request_with(|_| {})
        .expect("configured connector begins health request");
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities::default(),
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .asr_capability_lease()
        .expect("ready connector yields a catalog lease");
    let catalog = AsrCapabilityCatalog::parse_bounded(ASR_CATALOG_EXAMPLE).unwrap();
    let directory =
        std::env::temp_dir().join(format!("yap-asr-stale-publication-{}", std::process::id()));
    let path = directory.join("asr-capabilities-snapshot.json");
    capability_snapshot::save_to_path(newer_origin, 84, &catalog, &path).unwrap();
    connector.invalidate();

    let publication_attempted = AtomicBool::new(false);
    let commit_attempted = AtomicBool::new(false);
    assert!(connector
        .commit_current_asr_capability_catalog_with(
            &lease,
            catalog.clone(),
            |origin, stale_catalog| {
                publication_attempted.store(true, Ordering::SeqCst);
                capability_snapshot::save_to_path(origin, 42, stale_catalog, &path).unwrap();
            },
            |_| commit_attempted.store(true, Ordering::SeqCst),
        )
        .is_err());
    assert!(!publication_attempted.load(Ordering::SeqCst));
    assert!(!commit_attempted.load(Ordering::SeqCst));
    assert_eq!(
        capability_snapshot::load_from_path(newer_origin, &path).unwrap(),
        Some(capability_snapshot::LastKnownAsrCapabilities {
            observed_at_ms: 84,
            catalog,
        })
    );

    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn late_same_origin_catalog_response_cannot_overwrite_a_newer_response() {
    let connector = ServerConnector::default();
    let origin = "http://127.0.0.1:18765";
    connector.synchronize_settings_with(
        &config::ServerSettings {
            schema_version: config::CURRENT_SCHEMA_VERSION,
            enabled: true,
            base_url: Some(origin.into()),
            authentication: None,
        },
        |_| {},
    );
    let (generation, _) = connector
        .begin_health_request_with(|_| {})
        .expect("configured connector begins health request");
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities::default(),
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let older_lease = connector.asr_capability_lease().unwrap();
    let newer_lease = connector.asr_capability_lease().unwrap();
    let older_catalog = AsrCapabilityCatalog::parse_bounded(ASR_CATALOG_EXAMPLE).unwrap();
    let mut newer_catalog = older_catalog.clone();
    newer_catalog.providers[0].capabilities[0].word_alignment = true;
    newer_catalog.catalog_revision = newer_catalog.computed_revision().unwrap();
    let directory = std::env::temp_dir().join(format!(
        "yap-asr-same-origin-freshness-{}",
        std::process::id()
    ));
    let path = directory.join("asr-capabilities-snapshot.json");

    connector
        .commit_current_asr_capability_catalog_with(
            &newer_lease,
            newer_catalog.clone(),
            |leased_origin, catalog| {
                capability_snapshot::save_to_path(leased_origin, 84, catalog, &path).unwrap();
            },
            |_| (),
        )
        .unwrap();
    let stale_publication_attempted = AtomicBool::new(false);
    assert!(connector
        .commit_current_asr_capability_catalog_with(
            &older_lease,
            older_catalog,
            |_, _| stale_publication_attempted.store(true, Ordering::SeqCst),
            |_| (),
        )
        .is_err());

    assert!(!stale_publication_attempted.load(Ordering::SeqCst));
    assert_eq!(
        capability_snapshot::load_from_path(origin, &path)
            .unwrap()
            .unwrap()
            .catalog,
        newer_catalog
    );
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn asr_generation_lease_is_held_through_snapshot_and_durable_commit() {
    let connector = Arc::new(ServerConnector::default());
    let origin = "http://127.0.0.1:18765";
    connector.synchronize_settings_with(
        &config::ServerSettings {
            schema_version: config::CURRENT_SCHEMA_VERSION,
            enabled: true,
            base_url: Some(origin.into()),
            authentication: None,
        },
        |_| {},
    );
    let (generation, _) = connector
        .begin_health_request_with(|_| {})
        .expect("configured connector begins health request");
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities::default(),
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .asr_capability_lease()
        .expect("ready connector yields a catalog lease");
    let catalog = AsrCapabilityCatalog::parse_bounded(ASR_CATALOG_EXAMPLE).unwrap();
    let directory = std::env::temp_dir().join(format!(
        "yap-asr-generation-publication-{}",
        std::process::id()
    ));
    let path = directory.join("asr-capabilities-snapshot.json");
    let (publication_entered, observe_publication) = mpsc::channel();
    let (release_publication, publication_released) = mpsc::channel();

    let publishing_connector = Arc::clone(&connector);
    let publishing_path = path.clone();
    let publisher = std::thread::spawn(move || {
        publishing_connector.commit_current_asr_capability_catalog_with(
            &lease,
            catalog,
            |leased_origin, leased_catalog| {
                capability_snapshot::save_to_path(
                    leased_origin,
                    42,
                    leased_catalog,
                    &publishing_path,
                )
                .unwrap();
            },
            |leased_catalog| {
                publication_entered.send(()).unwrap();
                publication_released
                    .recv_timeout(Duration::from_secs(2))
                    .expect("generation lease test release must arrive");
                leased_catalog.clone()
            },
        )
    });

    observe_publication
        .recv_timeout(Duration::from_secs(2))
        .expect("catalog commit must reach its durable callback");
    assert!(matches!(
        connector.inner.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
    assert_eq!(connector.current(), generation);
    release_publication.send(()).unwrap();

    let published = publisher.join().unwrap().unwrap();
    assert_eq!(
        capability_snapshot::load_from_path(origin, &path)
            .unwrap()
            .unwrap()
            .catalog,
        published
    );

    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn same_revision_catalog_refresh_does_not_starve_a_ready_dispatch_proof() {
    let connector = ready_batch_connector("http://127.0.0.1:18765");
    let catalog = AsrCapabilityCatalog::parse_bounded(ASR_CATALOG_EXAMPLE).unwrap();
    let first_lease = connector.asr_capability_lease().unwrap();
    let (binding, proof) = connector
        .commit_current_asr_capability_catalog_for_test(&first_lease, catalog.clone(), |current| {
            (current.binding().clone(), current.dispatch_proof())
        })
        .unwrap();
    let refresh_lease = connector.asr_capability_lease().unwrap();
    connector
        .commit_current_asr_capability_catalog_for_test(&refresh_lease, catalog, |_| ())
        .unwrap();
    let batch_lease = connector.batch_connection_lease().unwrap().unwrap();

    let committed = connector
        .with_current_batch_catalog_proof(&batch_lease, &proof, &binding, || 42)
        .unwrap();

    assert_eq!(committed, 42);
}

#[test]
fn changed_catalog_revision_revokes_an_older_dispatch_proof() {
    let connector = ready_batch_connector("http://127.0.0.1:18765");
    let catalog = AsrCapabilityCatalog::parse_bounded(ASR_CATALOG_EXAMPLE).unwrap();
    let first_lease = connector.asr_capability_lease().unwrap();
    let (binding, proof) = connector
        .commit_current_asr_capability_catalog_for_test(&first_lease, catalog.clone(), |current| {
            (current.binding().clone(), current.dispatch_proof())
        })
        .unwrap();
    let mut changed = catalog;
    changed.providers[0].capabilities[0].word_alignment = true;
    changed.catalog_revision = changed.computed_revision().unwrap();
    let refresh_lease = connector.asr_capability_lease().unwrap();
    connector
        .commit_current_asr_capability_catalog_for_test(&refresh_lease, changed, |_| ())
        .unwrap();
    let batch_lease = connector.batch_connection_lease().unwrap().unwrap();

    assert!(connector
        .with_current_batch_catalog_proof(&batch_lease, &proof, &binding, || ())
        .is_err());
}

#[test]
fn same_lid_policy_refresh_does_not_starve_a_ready_preflight_proof() {
    let connector = ready_batch_connector("http://127.0.0.1:18765");
    let catalog = catalog_with_lid("ambernet-stratified-five-region-v1");
    let first_lease = connector.asr_capability_lease().unwrap();
    let proof = connector
        .commit_current_asr_capability_catalog_for_test(&first_lease, catalog.clone(), |current| {
            let lid = current.lid_preflight_dispatch().unwrap();
            assert_eq!(
                current.catalog().lid_preflight().unwrap().policy.revision,
                "ambernet-stratified-five-region-v1"
            );
            lid.dispatch_proof()
        })
        .unwrap();
    let refresh_lease = connector.asr_capability_lease().unwrap();
    connector
        .commit_current_asr_capability_catalog_for_test(&refresh_lease, catalog, |_| ())
        .unwrap();
    let batch_lease = connector.batch_connection_lease().unwrap().unwrap();

    assert_eq!(
        connector
            .with_current_lid_preflight_proof(&batch_lease, &proof, || 42)
            .unwrap(),
        42
    );
}

#[test]
fn changed_lid_policy_revokes_only_the_older_preflight_proof() {
    let connector = ready_batch_connector("http://127.0.0.1:18765");
    let catalog = catalog_with_lid("ambernet-stratified-five-region-v1");
    let first_lease = connector.asr_capability_lease().unwrap();
    let (binding, asr_proof, lid_proof) = connector
        .commit_current_asr_capability_catalog_for_test(&first_lease, catalog, |current| {
            (
                current.binding().clone(),
                current.dispatch_proof(),
                current.lid_preflight_dispatch().unwrap().dispatch_proof(),
            )
        })
        .unwrap();
    let refresh_lease = connector.asr_capability_lease().unwrap();
    connector
        .commit_current_asr_capability_catalog_for_test(
            &refresh_lease,
            catalog_with_lid("ambernet-stratified-five-region-v2"),
            |_| (),
        )
        .unwrap();
    let batch_lease = connector.batch_connection_lease().unwrap().unwrap();

    assert!(connector
        .with_current_batch_catalog_proof(&batch_lease, &asr_proof, &binding, || ())
        .is_ok());
    assert!(connector
        .with_current_lid_preflight_proof(&batch_lease, &lid_proof, || ())
        .is_err());
}

#[test]
fn removed_lid_capability_revokes_an_older_preflight_proof() {
    let connector = ready_batch_connector("http://127.0.0.1:18765");
    let first_lease = connector.asr_capability_lease().unwrap();
    let proof = connector
        .commit_current_asr_capability_catalog_for_test(
            &first_lease,
            catalog_with_lid("ambernet-stratified-five-region-v1"),
            |current| current.lid_preflight_dispatch().unwrap().dispatch_proof(),
        )
        .unwrap();
    let refresh_lease = connector.asr_capability_lease().unwrap();
    let without_lid = AsrCapabilityCatalog::parse_bounded(ASR_CATALOG_EXAMPLE).unwrap();
    connector
        .commit_current_asr_capability_catalog_for_test(&refresh_lease, without_lid, |_| ())
        .unwrap();
    let batch_lease = connector.batch_connection_lease().unwrap().unwrap();

    assert!(connector
        .with_current_lid_preflight_proof(&batch_lease, &proof, || ())
        .is_err());
}

fn catalog_with_lid(policy_revision: &str) -> AsrCapabilityCatalog {
    let mut value: serde_json::Value = serde_json::from_slice(ASR_CATALOG_EXAMPLE).unwrap();
    value["languagePreflight"] = serde_json::json!({
        "schemaVersion": 1,
        "componentId": "ambernet-batch-language-preflight",
        "runtime": {"pythonVersion": "3.12.13", "cpuOnly": true},
        "model": {
            "id": "nvidia/nemo/langid_ambernet",
            "revision": "1.12.0"
        },
        "transport": {
            "mediaType": "application/vnd.yap.lid-preflight.v1+octet-stream",
            "maximumBodyBytes": 1_048_576,
            "maximumManifestBytes": 32_768,
            "maximumResponseSeconds": 120
        },
        "policy": {
            "revision": policy_revision,
            "sampleRateHz": 16_000,
            "channelCount": 1,
            "sampleWidthBytes": 2,
            "minimumSourceSamples": 480_000,
            "maximumWindows": 5,
            "maximumWindowSamples": 96_000,
            "minimumVoicedSamplesPerWindow": 51_200,
            "scoreSemantics": "mean-logit-log-softmax",
            "userConfirmationRequired": true
        }
    });
    AsrCapabilityCatalog::parse_bounded(&serde_json::to_vec(&value).unwrap()).unwrap()
}

fn ready_batch_connector(origin: &str) -> ServerConnector {
    let connector = ServerConnector::default();
    connector.synchronize_settings_with(
        &config::ServerSettings {
            schema_version: config::CURRENT_SCHEMA_VERSION,
            enabled: true,
            base_url: Some(origin.into()),
            authentication: None,
        },
        |_| {},
    );
    let (generation, _) = connector
        .begin_health_request_with(|_| {})
        .expect("configured connector begins health request");
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                batch_jobs: true,
                live_streaming: false,
                job_status: true,
                transcript_correction: false,
                librarian_queries: false,
                archivist_ingestions: false,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    connector
}

#[test]
fn settings_load_cannot_run_ahead_of_the_connector_save_lock() {
    let connector = Arc::new(ServerConnector::default());
    let save_guard = connector.inner.lock().unwrap();
    let (load_started_tx, load_started_rx) = mpsc::channel();
    let waiting_connector = Arc::clone(&connector);
    let waiter = std::thread::spawn(move || {
        waiting_connector
            .with_loaded_settings(
                || {
                    load_started_tx.send(()).unwrap();
                    Ok(config::ServerSettings::default())
                },
                |_, _| (),
            )
            .unwrap();
    });

    assert!(load_started_rx
        .recv_timeout(Duration::from_millis(50))
        .is_err());
    drop(save_guard);
    load_started_rx.recv().unwrap();
    waiter.join().unwrap();
}

#[test]
fn delayed_health_response_cannot_mutate_a_new_settings_generation() {
    use std::io::{Read, Write};
    use std::net::TcpListener;

    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let base_url = format!("http://{}", listener.local_addr().unwrap());
    let (request_started_tx, request_started_rx) = mpsc::channel();
    let (release_response_tx, release_response_rx) = mpsc::channel();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = [0_u8; 1024];
        let read = stream.read(&mut request).unwrap();
        assert!(read > 0);
        request_started_tx.send(()).unwrap();
        release_response_rx.recv().unwrap();
        let body = br#"{"service":"yap-server","status":"ok","apiVersion":"1","auth":"not_configured","capabilities":{"batchJobs":true,"liveStreaming":true,"jobStatus":true,"transcriptCorrection":true,"librarianQueries":true,"archivistIngestions":true}}"#;
        write!(
            stream,
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        )
        .unwrap();
        stream.write_all(body).unwrap();
    });

    let connector = Arc::new(ServerConnector::default());
    {
        let mut inner = connector.inner.lock().unwrap();
        inner.apply_server_settings(0, true, Some(base_url.clone()));
        assert!(inner.begin_health_request(0, 10));
    }
    let request_connector = Arc::clone(&connector);
    let request = std::thread::spawn(move || {
        tauri::async_runtime::block_on(client::check_health(
            &request_connector.client,
            &base_url,
            false,
        ))
    });

    request_started_rx.recv().unwrap();
    assert_eq!(connector.invalidate(), 1);
    release_response_tx.send(()).unwrap();
    let result = request.join().unwrap();
    server.join().unwrap();

    let mut inner = connector.inner.lock().unwrap();
    assert!(inner
        .finish_health_request(0, result, 20, |_| Duration::ZERO)
        .is_none());
    assert_eq!(
        inner.snapshot().state,
        runtime::state::ServerConnectorState::NotSet
    );
    assert_eq!(inner.snapshot().capabilities, ServerCapabilities::default());
}

#[test]
fn settings_changes_advance_the_connector_generation() {
    let connector = ServerConnector::default();

    assert_eq!(connector.current(), 0);
    assert_eq!(connector.invalidate(), 1);
    assert_eq!(connector.current(), 1);
}

#[test]
fn server_settings_save_has_one_end_to_end_owner() {
    let connector = ServerConnector::default();

    let first = connector.begin_settings_save().unwrap();
    assert_eq!(
        connector.begin_settings_save().unwrap_err(),
        "A server settings update is already active."
    );

    drop(first);
    assert!(connector.begin_settings_save().is_ok());
}
