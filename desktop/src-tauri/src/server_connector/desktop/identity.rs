use crate::server_connector::{
    config, native_access_token_provider::AccessTokenSessionStatus, ServerConnector,
};

use super::emit_transition;

pub(in crate::server_connector) async fn session_status(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<AccessTokenSessionStatus, String> {
    crate::authorization::ensure_main(&window)?;
    let result = connector.access_tokens.status().await;
    if result.is_err() || !connector.access_tokens.session_is_open() {
        return preserve_identity_result(result, || reset_connection(&app, &connector));
    }
    result
}

pub(in crate::server_connector) async fn sign_in(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<AccessTokenSessionStatus, String> {
    crate::authorization::ensure_main(&window)?;
    let result = connector
        .access_tokens
        .sign_in(parent_window_handle(&window)?)
        .await;
    preserve_identity_result(result, || reset_connection(&app, &connector))?;
    connector.refresh(&app).await;
    let result = connector.access_tokens.status().await;
    if result.is_err() || !connector.access_tokens.session_is_open() {
        return preserve_identity_result(result, || reset_connection(&app, &connector));
    }
    result
}

pub(in crate::server_connector) async fn sign_out(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<AccessTokenSessionStatus, String> {
    crate::authorization::ensure_main(&window)?;
    let result = connector.access_tokens.sign_out().await;
    preserve_identity_result(result, || reset_connection(&app, &connector))?;
    connector.refresh(&app).await;
    let result = connector.access_tokens.status().await;
    if result.is_err() || !connector.access_tokens.session_is_open() {
        return preserve_identity_result(result, || reset_connection(&app, &connector));
    }
    result
}

fn reset_connection(app: &tauri::AppHandle, connector: &ServerConnector) -> Result<(), String> {
    reset_connection_with(connector, config::load(), |snapshot| {
        emit_transition(app, snapshot);
    })
}

fn reset_connection_with<Emit>(
    connector: &ServerConnector,
    settings: Result<config::ServerSettings, config::ConfigError>,
    emit: Emit,
) -> Result<(), String>
where
    Emit: FnOnce(&crate::server_connector::ServerConnectionSnapshot),
{
    let mut inner = connector.inner.lock().expect("server connector poisoned");
    let generation = connector.invalidate_locked(&mut inner);
    if let Ok(settings) = settings.as_ref() {
        inner.apply_server_settings(generation, settings.enabled, settings.base_url.clone());
    }
    let snapshot = inner.snapshot();
    drop(inner);
    emit(&snapshot);
    settings.map(|_| ()).map_err(|error| error.to_string())
}

fn preserve_identity_result<T, Reset>(
    identity_result: Result<T, String>,
    reset: Reset,
) -> Result<T, String>
where
    Reset: FnOnce() -> Result<(), String>,
{
    let reset_result = reset();
    match identity_result {
        Err(error) => Err(error),
        Ok(value) => reset_result.map(|_| value),
    }
}

#[cfg(windows)]
fn parent_window_handle(window: &tauri::WebviewWindow) -> Result<Option<u64>, String> {
    window
        .hwnd()
        .map(|handle| Some(handle.0 as usize as u64))
        .map_err(|error| format!("Could not obtain the sign-in parent window: {error}"))
}

#[cfg(not(windows))]
fn parent_window_handle(_window: &tauri::WebviewWindow) -> Result<Option<u64>, String> {
    Ok(None)
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, Ordering};

    use crate::{
        runtime::state::ServerConnectorState,
        server_connector::{
            client::HealthCheckResult, config, ServerCapabilities, ServerConnector,
        },
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
}
