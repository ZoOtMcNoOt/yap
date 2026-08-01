use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc, Mutex as StandardMutex,
    },
    thread,
    time::Duration,
};

use crate::{
    runtime::state::ServerConnectorState,
    server_connector::{client::HealthCheckResult, config, ServerCapabilities, ServerConnector},
};

use super::{preserve_identity_result, reset_connection_with};

#[test]
fn identity_failure_is_preserved_after_the_reset_attempt() {
    let reset_attempted = AtomicBool::new(false);
    assert_eq!(
        preserve_identity_result::<(), _>(Err("identity failed".into()), || {
            reset_attempted.store(true, Ordering::SeqCst);
            Err("reset failed".into())
        }),
        Err("identity failed".into())
    );
    assert!(reset_attempted.load(Ordering::SeqCst));
}

#[test]
fn invalidated_identity_emits_a_non_ready_snapshot_even_when_settings_reload_fails() {
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
        HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities::default(),
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert_eq!(connector.snapshot().state, ServerConnectorState::Ready);
    let emitted = AtomicBool::new(false);

    assert_eq!(
        reset_connection_with(
            &connector,
            Err(config::ConfigError::Invalid("settings reload failed")),
            |snapshot| {
                emitted.store(true, Ordering::SeqCst);
                assert_ne!(snapshot.state, ServerConnectorState::Ready);
            },
        ),
        Err("settings reload failed".into())
    );
    assert!(emitted.load(Ordering::SeqCst));
    assert_ne!(connector.snapshot().state, ServerConnectorState::Ready);
}

#[test]
fn reset_failure_is_reported_after_identity_success() {
    assert_eq!(
        preserve_identity_result(Ok(()), || Err("reset failed".into())),
        Err("reset failed".into())
    );
}

#[test]
fn unauthenticated_session_reopens_only_after_stale_ready_connector_is_invalidated() {
    let access_tokens =
        crate::server_connector::native_access_token_provider::NativeAccessTokenManager::unconfigured_loopback_for_test();
    let connector = ServerConnector::with_access_tokens_for_test(access_tokens);
    let loopback_settings = config::ServerSettings {
        schema_version: config::CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("http://127.0.0.1:18765".into()),
        authentication: None,
    };
    connector.synchronize_settings_with(&loopback_settings, |_| {});
    let (generation, _) = connector.begin_health_request_with(|_| {}).unwrap();
    connector.accept_health_result_with(
        generation,
        HealthCheckResult::Ready {
            api_version: "1".into(),
            capabilities: ServerCapabilities::default(),
        },
        |_| {},
        |_, _, _| tauri::async_runtime::spawn(async {}),
    );
    assert_eq!(
        connector.snapshot().state,
        crate::runtime::state::ServerConnectorState::Ready
    );
    assert!(connector.asr_capability_lease().is_some());
    tauri::async_runtime::block_on(connector.access_tokens.session().invalidate_and_wait());
    assert!(!connector.access_tokens.session_is_open());

    let reset_observed_closed_session = AtomicBool::new(false);
    let status = tauri::async_runtime::block_on(
        connector
            .access_tokens
            .status_with_connector_reconciliation(|| {
                reset_observed_closed_session
                    .store(!connector.access_tokens.session_is_open(), Ordering::SeqCst);
                reset_connection_with(&connector, Ok(loopback_settings), |_| {})
            }),
    )
    .unwrap();

    assert!(!status.configured);
    assert!(!status.signed_in);
    assert!(reset_observed_closed_session.load(Ordering::SeqCst));
    assert!(connector.access_tokens.session_is_open());
    assert_ne!(
        connector.snapshot().state,
        crate::runtime::state::ServerConnectorState::Ready
    );
    assert!(connector.asr_capability_lease().is_none());
}

#[test]
fn settings_publication_waits_for_identity_reconciliation_and_wins_final_state() {
    let initial_settings = config::ServerSettings {
        schema_version: config::CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("http://127.0.0.1:18765".into()),
        authentication: None,
    };
    let settings = Arc::new(StandardMutex::new(initial_settings.clone()));
    let access_tokens =
        crate::server_connector::native_access_token_provider::NativeAccessTokenManager::with_settings_for_test(
            Arc::clone(&settings),
        );
    let connector = Arc::new(ServerConnector::with_access_tokens_for_test(Arc::clone(
        &access_tokens,
    )));
    connector.synchronize_settings_with(&initial_settings, |_| {});
    tauri::async_runtime::block_on(access_tokens.session().invalidate_and_wait());

    let (reset_entered_tx, reset_entered_rx) = mpsc::channel();
    let (release_reset_tx, release_reset_rx) = mpsc::channel();
    let reconciling_connector = Arc::clone(&connector);
    let reconciling_settings = Arc::clone(&settings);
    let reconciliation = thread::spawn(move || {
        tauri::async_runtime::block_on(
            reconciling_connector
                .access_tokens
                .status_with_connector_reconciliation(|| {
                    reset_entered_tx.send(()).unwrap();
                    release_reset_rx
                        .recv_timeout(Duration::from_secs(2))
                        .unwrap();
                    let current = reconciling_settings.lock().unwrap().clone();
                    reset_connection_with(&reconciling_connector, Ok(current), |_| {})
                }),
        )
    });
    reset_entered_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap();

    let final_authentication = config::MicrosoftEntraSettings {
        tenant_id: "11111111-1111-1111-1111-111111111111".into(),
        client_id: "22222222-2222-2222-2222-222222222222".into(),
        api_scope: "api://33333333-3333-3333-3333-333333333333/access_as_user".into(),
    };
    let final_settings = config::ServerSettings {
        schema_version: config::CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("https://127.0.0.1:18766".into()),
        authentication: Some(final_authentication.clone()),
    };
    let (transition_started_tx, transition_started_rx) = mpsc::channel();
    let (transition_entered_tx, transition_entered_rx) = mpsc::channel();
    let publishing_connector = Arc::clone(&connector);
    let publishing_settings = Arc::clone(&settings);
    let publishing_access_tokens = Arc::clone(&access_tokens);
    let publication = thread::spawn(move || {
        transition_started_tx.send(()).unwrap();
        tauri::async_runtime::block_on(publishing_access_tokens.transition_configuration(
            None,
            || {
                transition_entered_tx.send(()).unwrap();
                *publishing_settings.lock().unwrap() = final_settings.clone();
                let mut inner = publishing_connector
                    .inner
                    .lock()
                    .expect("server connector poisoned");
                let generation = publishing_connector.invalidate_locked(&mut inner);
                inner.apply_server_settings(
                    generation,
                    final_settings.enabled,
                    final_settings.base_url.clone(),
                );
                ((), final_settings.authentication)
            },
        ))
    });
    transition_started_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    assert!(transition_entered_rx
        .recv_timeout(Duration::from_millis(50))
        .is_err());

    release_reset_tx.send(()).unwrap();
    reconciliation.join().unwrap().unwrap();
    publication.join().unwrap();
    transition_entered_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap();

    assert_eq!(
        settings.lock().unwrap().authentication.as_ref(),
        Some(&final_authentication)
    );
    assert_eq!(
        connector.configured_batch_origin().unwrap().as_deref(),
        Some("https://127.0.0.1:18766")
    );
    assert!(connector.access_tokens.session_is_open());
}
