use crate::server_connector::{allow_insecure_private_server, config, ServerConnector};

use super::emit_transition;

pub(in crate::server_connector) fn load(
    window: tauri::WebviewWindow,
) -> Result<config::ServerSettings, String> {
    crate::authorization::ensure_main(&window)?;
    config::load().map_err(|error| error.to_string())
}

pub(in crate::server_connector) async fn save(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
    settings: config::ServerSettings,
) -> Result<config::ServerSettings, String> {
    crate::authorization::ensure_main(&window)?;
    let _save = connector.begin_settings_save()?;
    let normalized = config::normalize_settings(&settings, allow_insecure_private_server())
        .map_err(|error| error.to_string())?;
    let current = config::load().map_err(|error| error.to_string())?;
    let origin_is_approved = normalized
        .base_url
        .as_deref()
        .is_some_and(|origin| config::origin_is_approved(origin).unwrap_or(false));
    let approval_origin = if requires_origin_confirmation(&current, &normalized, origin_is_approved)
    {
        let origin = normalized
            .base_url
            .clone()
            .expect("enabled normalized server settings have an origin");
        if !confirm_origin(app.clone(), origin.clone()).await? {
            return Err("Server connection change was cancelled.".into());
        }
        Some(origin)
    } else {
        None
    };

    let previous_authentication = current.authentication.clone();
    let access_tokens = connector.access_tokens.clone();
    access_tokens
        .transition_configuration(previous_authentication.as_ref(), || {
            let mut inner = connector.inner.lock().expect("server connector poisoned");
            let generation = connector.invalidate_locked(&mut inner);

            // The authenticated session has already been cancelled and drained
            // before either durable settings or origin approval are published.
            let save_result = config::save(&normalized).and_then(|saved| {
                if let Some(origin) = approval_origin.as_deref() {
                    config::approve_origin(origin)?;
                }
                Ok(saved)
            });
            let result = finish_after_revocation(save_result);
            let effective = result
                .as_ref()
                .ok()
                .cloned()
                .or_else(|| config::load().ok())
                .unwrap_or_else(|| current.clone());
            inner.apply_server_settings(generation, effective.enabled, effective.base_url.clone());
            emit_transition(&app, &inner.snapshot());
            (result, effective.authentication)
        })
        .await
}

pub(in crate::server_connector) fn requires_origin_confirmation(
    current: &config::ServerSettings,
    candidate: &config::ServerSettings,
    origin_is_approved: bool,
) -> bool {
    candidate.enabled
        && (!origin_is_approved
            || !current.enabled
            || current.base_url.as_deref() != candidate.base_url.as_deref())
}

async fn confirm_origin(app: tauri::AppHandle, origin: String) -> Result<bool, String> {
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

    tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .message(format!(
                "Allow Yap to connect to this private server?\n\n{origin}\n\nOnly approve an address supplied by your trusted administrator."
            ))
            .title("Confirm private server")
            .kind(MessageDialogKind::Warning)
            .buttons(MessageDialogButtons::OkCancelCustom(
                "Connect".into(),
                "Cancel".into(),
            ))
            .blocking_show()
    })
    .await
    .map_err(|error| format!("Could not show server confirmation: {error}"))
}

#[cfg(test)]
pub(in crate::server_connector) fn finish_save(
    connector: &ServerConnector,
    result: Result<config::ServerSettings, config::ConfigError>,
) -> Result<config::ServerSettings, String> {
    let mut inner = connector.inner.lock().expect("server connector poisoned");
    connector.invalidate_locked(&mut inner);
    finish_after_revocation(result)
}

fn finish_after_revocation(
    result: Result<config::ServerSettings, config::ConfigError>,
) -> Result<config::ServerSettings, String> {
    result.map_err(|error| error.to_string())
}
