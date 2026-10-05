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
fn private_knowledge_submissions_bind_the_renderer_revision_to_the_native_lease() {
    let connector = ServerConnector::default();
    let mut settings = config::ServerSettings {
        schema_version: config::CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("http://127.0.0.1:18765".into()),
        authentication: None,
    };
    let old = connector.synchronize_settings_with(&settings, |_| {});
    settings.base_url = Some("http://127.0.0.1:18766".into());
    let current = connector.synchronize_settings_with(&settings, |_| {});
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                librarian_queries: true,
                analyst_answers: true,
                coordinator_bundles: true,
                auditor_reports: true,
                curator_proposals: true,
                ..ServerCapabilities::default()
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let librarian = connector.librarian_connection_lease().unwrap().unwrap();
    let analyst = connector.analyst_connection_lease().unwrap().unwrap();
    let coordinator = connector.coordinator_connection_lease().unwrap().unwrap();
    let auditor = connector.auditor_connection_lease().unwrap().unwrap();
    let curator = connector.curator_connection_lease().unwrap().unwrap();
    for result in [
        librarian.require_authority_revision(&current.authority_revision),
        analyst.require_authority_revision(&current.authority_revision),
        coordinator.require_authority_revision(&current.authority_revision),
        auditor.require_authority_revision(&current.authority_revision),
        curator.require_authority_revision(&current.authority_revision),
    ] {
        assert!(result.is_ok());
    }
    for revision in [&old.authority_revision, "", "01", "18446744073709551616"] {
        for result in [
            librarian.require_authority_revision(revision),
            analyst.require_authority_revision(revision),
            coordinator.require_authority_revision(revision),
            auditor.require_authority_revision(revision),
            curator.require_authority_revision(revision),
        ] {
            assert_eq!(
                result,
                Err("Your server or sign-in changed. Refresh before submitting.".into())
            );
        }
    }
}

#[test]
fn snapshot_revision_follows_the_native_configuration_and_identity_owner() {
    let connector = ServerConnector::default();
    let mut settings = config::ServerSettings {
        schema_version: config::CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("http://127.0.0.1:18765".into()),
        authentication: None,
    };
    let initial = connector.synchronize_settings_with(&settings, |_| {});
    let unchanged = connector.synchronize_settings_with(&settings, |_| {});
    assert_eq!(initial.authority_revision, unchanged.authority_revision);
    settings.base_url = Some("http://127.0.0.1:18766".into());
    let configured = connector.synchronize_settings_with(&settings, |_| {});
    assert_ne!(initial.authority_revision, configured.authority_revision);
    connector.invalidate();
    assert_ne!(
        configured.authority_revision,
        connector.snapshot().authority_revision
    );
    let signed_in = connector.synchronize_settings_with(&settings, |_| {});
    assert_eq!(
        connector.snapshot().authority_revision,
        signed_in.authority_revision
    );
    assert_ne!(configured.authority_revision, signed_in.authority_revision);
}

#[test]
fn terminology_lease_requires_capability_and_rejects_stale_commits() {
    let connector = ServerConnector::default();
    let settings = config::ServerSettings {
        schema_version: config::CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("http://127.0.0.1:18765".into()),
        authentication: None,
    };
    connector.synchronize_settings_with(&settings, |_| {});
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities::default(),
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert!(connector.terminology_connection_lease().unwrap().is_none());
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: true,
                ..ServerCapabilities::default()
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector.terminology_connection_lease().unwrap().unwrap();
    assert_eq!(
        lease.client().base_url_identity(),
        "http://127.0.0.1:18765/"
    );
    assert_eq!(lease.authority_revision(), generation.to_string());
    connector.invalidate();
    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_terminology_lease(&lease, || committed.store(true, Ordering::SeqCst))
        .is_err());
    assert!(!committed.load(Ordering::SeqCst));
}

#[test]
fn knowledge_connections_lease_requires_capability_and_rejects_stale_commits() {
    let connector = ServerConnector::default();
    let settings = config::ServerSettings {
        schema_version: config::CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("http://127.0.0.1:18765".into()),
        authentication: None,
    };
    connector.synchronize_settings_with(&settings, |_| {});
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities::default(),
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert!(connector
        .knowledge_connections_connection_lease()
        .unwrap()
        .is_none());
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                knowledge_connections: true,
                knowledge_rebuild: false,
                personal_terminology: false,
                ..ServerCapabilities::default()
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .knowledge_connections_connection_lease()
        .unwrap()
        .unwrap();
    assert_eq!(
        lease.client().base_url_identity(),
        "http://127.0.0.1:18765/"
    );
    assert_eq!(lease.authority_revision(), generation.to_string());
    connector.invalidate();
    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_knowledge_connections_lease(&lease, || committed
            .store(true, Ordering::SeqCst))
        .is_err());
    assert!(!committed.load(Ordering::SeqCst));
}

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
                analyst_answers: false,
                student_questions: false,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: false,
                curator_proposals: false,
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
fn batch_lease_keeps_commit_locked_and_requires_both_current_capabilities() {
    let connector = ready_batch_connector("http://127.0.0.1:18765");
    let lease = connector.batch_connection_lease().unwrap().unwrap();
    assert_eq!(
        connector
            .with_current_batch_lease(&lease, || {
                assert!(matches!(
                    connector.inner.try_lock(),
                    Err(TryLockError::WouldBlock)
                ));
                "committed"
            })
            .unwrap(),
        "committed"
    );
    assert!(connector.inner.try_lock().is_ok());

    for capabilities in [
        ServerCapabilities {
            batch_jobs: true,
            ..ServerCapabilities::default()
        },
        ServerCapabilities {
            job_status: true,
            ..ServerCapabilities::default()
        },
    ] {
        let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
        connector.accept_health_result_with(
            generation,
            client::HealthCheckResult::Ready {
                api_version: "1".into(),
                capabilities,
            },
            |_| {},
            |_, _, _| tauri::async_runtime::spawn(async {}),
        );
        assert_eq!(connector.current(), generation);
        assert!(connector.batch_connection_lease().unwrap().is_none());
        assert_eq!(
            connector.with_current_batch_lease(&lease, || -> () {
                panic!("unavailable result exposed")
            }),
            Err("Server connection changed before the batch response could commit.".into())
        );
    }
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
                analyst_answers: false,
                student_questions: false,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: false,
                curator_proposals: false,
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
                analyst_answers: false,
                student_questions: false,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: false,
                curator_proposals: false,
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
                analyst_answers: false,
                student_questions: false,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: false,
                curator_proposals: false,
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
                analyst_answers: false,
                student_questions: false,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: false,
                curator_proposals: false,
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
fn analyst_lease_requires_capability_and_cannot_commit_after_change() {
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
            capabilities: ServerCapabilities::default(),
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert!(connector.analyst_connection_lease().unwrap().is_none());

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
                analyst_answers: true,
                ..ServerCapabilities::default()
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .analyst_connection_lease()
        .unwrap()
        .expect("ready Analyst-capable connector yields a lease");
    connector.invalidate();
    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_analyst_lease(&lease, || {
            committed.store(true, Ordering::SeqCst);
        })
        .is_err());
    assert!(!committed.load(Ordering::SeqCst));
}

#[test]
fn coordinator_lease_requires_capability_and_cannot_commit_after_change() {
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
            capabilities: ServerCapabilities::default(),
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert!(connector.coordinator_connection_lease().unwrap().is_none());

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
                coordinator_bundles: true,
                ..ServerCapabilities::default()
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .coordinator_connection_lease()
        .unwrap()
        .expect("ready Coordinator-capable connector yields a lease");
    connector.invalidate();
    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_coordinator_lease(&lease, || {
            committed.store(true, Ordering::SeqCst);
        })
        .is_err());
    assert!(!committed.load(Ordering::SeqCst));
}

#[test]
fn auditor_lease_requires_capability_and_cannot_commit_after_change() {
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
            capabilities: ServerCapabilities::default(),
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert!(connector.auditor_connection_lease().unwrap().is_none());

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
                auditor_reports: true,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                ..ServerCapabilities::default()
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .auditor_connection_lease()
        .unwrap()
        .expect("ready Auditor-capable connector yields a lease");
    connector.invalidate();
    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_auditor_lease(&lease, || {
            committed.store(true, Ordering::SeqCst);
        })
        .is_err());
    assert!(!committed.load(Ordering::SeqCst));
}

#[test]
fn student_lease_requires_capability_and_cannot_commit_after_change() {
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
                analyst_answers: false,
                student_questions: false,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: false,
                curator_proposals: false,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert!(connector.student_connection_lease().unwrap().is_none());

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
                librarian_queries: false,
                analyst_answers: false,
                student_questions: true,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: false,
                curator_proposals: false,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .student_connection_lease()
        .unwrap()
        .expect("ready Student-capable connector yields a lease");
    connector.invalidate();
    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_student_lease(&lease, || {
            committed.store(true, Ordering::SeqCst);
        })
        .is_err());
    assert!(!committed.load(Ordering::SeqCst));
}

#[test]
fn curator_lease_requires_capability_and_cannot_commit_after_change() {
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
                analyst_answers: false,
                student_questions: false,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: false,
                curator_proposals: false,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert!(connector.curator_connection_lease().unwrap().is_none());

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
                librarian_queries: false,
                analyst_answers: false,
                student_questions: false,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: false,
                curator_proposals: true,
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .curator_connection_lease()
        .unwrap()
        .expect("ready Curator-capable connector yields a lease");
    connector.invalidate();
    let committed = AtomicBool::new(false);
    assert!(connector
        .with_current_curator_lease(&lease, || {
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
                analyst_answers: false,
                student_questions: false,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: true,
                curator_proposals: false,
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
                analyst_answers: false,
                student_questions: false,
                coordinator_bundles: false,
                auditor_reports: false,
                knowledge_connections: false,
                knowledge_rebuild: false,
                personal_terminology: false,
                archivist_ingestions: false,
                curator_proposals: false,
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
        let body = br#"{"service":"yap-server","status":"ok","apiVersion":"1","auth":"not_configured","capabilities":{"batchJobs":true,"liveStreaming":true,"jobStatus":true,"transcriptCorrection":true,"librarianQueries":true,"analystAnswers":true,"coordinatorBundles":true,"auditorReports":true, "knowledgeConnections":false,"knowledgeRebuild":false,"personalTerminology": false,"studentQuestions":true,"archivistIngestions":true,"curatorProposals":true}}"#;
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

#[test]
fn rebuild_lease_uses_its_service_presence_and_refuses_changed_authority() {
    let connector = ServerConnector::default();
    let settings = config::ServerSettings {
        schema_version: config::CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("http://127.0.0.1:18765".into()),
        authentication: None,
    };
    connector.synchronize_settings_with(&settings, |_| {});
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                knowledge_rebuild: true,
                ..ServerCapabilities::default()
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let lease = connector
        .knowledge_rebuild_connection_lease()
        .unwrap()
        .unwrap();
    assert!(connector
        .knowledge_connections_connection_lease()
        .unwrap()
        .is_none());
    assert!(connector.curator_connection_lease().unwrap().is_none());
    assert_eq!(
        connector
            .with_current_knowledge_rebuild_lease(&lease, || "owned")
            .unwrap(),
        "owned"
    );
    let mut changed = settings.clone();
    changed.base_url = Some("http://127.0.0.1:18766".into());
    connector.synchronize_settings_with(&changed, |_| {});
    assert!(connector
        .with_current_knowledge_rebuild_lease(&lease, || panic!("stale result exposed"))
        .is_err());
}

#[test]
fn unchanged_knowledge_leases_commit_using_the_configured_origin() {
    let connector = ServerConnector::default();
    let settings = config::ServerSettings {
        schema_version: config::CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("http://127.0.0.1:18765".into()),
        authentication: None,
    };
    connector.synchronize_settings_with(&settings, |_| {});
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        client::HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities {
                knowledge_connections: true,
                librarian_queries: true,
                analyst_answers: true,
                coordinator_bundles: true,
                auditor_reports: true,
                curator_proposals: true,
                student_questions: true,
                archivist_ingestions: true,
                ..ServerCapabilities::default()
            },
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    let connections = connector
        .knowledge_connections_connection_lease()
        .unwrap()
        .unwrap();
    assert_eq!(
        connector
            .with_current_knowledge_connections_lease(&connections, || "connections")
            .unwrap(),
        "connections"
    );
    let librarian = connector.librarian_connection_lease().unwrap().unwrap();
    assert_eq!(
        connector
            .with_current_librarian_lease(&librarian, || "librarian")
            .unwrap(),
        "librarian"
    );
    let analyst = connector.analyst_connection_lease().unwrap().unwrap();
    assert_eq!(
        connector
            .with_current_analyst_lease(&analyst, || "analyst")
            .unwrap(),
        "analyst"
    );
    let coordinator = connector.coordinator_connection_lease().unwrap().unwrap();
    assert_eq!(
        connector
            .with_current_coordinator_lease(&coordinator, || "coordinator")
            .unwrap(),
        "coordinator"
    );
    let auditor = connector.auditor_connection_lease().unwrap().unwrap();
    assert_eq!(
        connector
            .with_current_auditor_lease(&auditor, || "auditor")
            .unwrap(),
        "auditor"
    );
    let curator = connector.curator_connection_lease().unwrap().unwrap();
    assert_eq!(
        connector
            .with_current_curator_lease(&curator, || "curator")
            .unwrap(),
        "curator"
    );
    let student = connector.student_connection_lease().unwrap().unwrap();
    assert_eq!(
        connector
            .with_current_student_lease(&student, || "student")
            .unwrap(),
        "student"
    );
    let archivist = connector.archivist_connection_lease().unwrap().unwrap();
    assert_eq!(
        connector
            .with_current_archivist_lease(&archivist, || "archivist")
            .unwrap(),
        "archivist"
    );
}
