use crate::server_connector::{config, identity_adapter::IdentitySessionStatus, ServerConnector};

use super::emit_transition;

pub(in crate::server_connector) async fn session_status(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<IdentitySessionStatus, String> {
    crate::authorization::ensure_main(&window)?;
    connector.identity.status().await
}

pub(in crate::server_connector) async fn sign_in(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<IdentitySessionStatus, String> {
    crate::authorization::ensure_main(&window)?;
    connector
        .identity
        .sign_in(parent_window_handle(&window)?)
        .await?;
    reset_connection(&app, &connector)?;
    connector.refresh(&app).await;
    connector.identity.status().await
}

pub(in crate::server_connector) async fn sign_out(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<IdentitySessionStatus, String> {
    crate::authorization::ensure_main(&window)?;
    connector.identity.sign_out().await?;
    reset_connection(&app, &connector)?;
    connector.refresh(&app).await;
    connector.identity.status().await
}

fn reset_connection(app: &tauri::AppHandle, connector: &ServerConnector) -> Result<(), String> {
    let settings = config::load().map_err(|error| error.to_string())?;
    let mut inner = connector.inner.lock().expect("server connector poisoned");
    let generation = connector.invalidate_locked(&mut inner);
    inner.apply_server_settings(generation, settings.enabled, settings.base_url);
    emit_transition(app, &inner.snapshot());
    Ok(())
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
