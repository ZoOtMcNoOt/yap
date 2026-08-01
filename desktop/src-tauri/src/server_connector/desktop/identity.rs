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
    connector
        .access_tokens
        .status_with_connector_reconciliation(|| reset_connection(&app, &connector))
        .await
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
    connector
        .access_tokens
        .status_with_connector_reconciliation(|| reset_connection(&app, &connector))
        .await
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
    connector
        .access_tokens
        .status_with_connector_reconciliation(|| reset_connection(&app, &connector))
        .await
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
mod tests;
