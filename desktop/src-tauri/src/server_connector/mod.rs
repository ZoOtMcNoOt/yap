mod access_token_expiry;
pub(crate) mod analyst;
pub(crate) mod archivist;
mod authorization;
pub(crate) mod batch;
mod boundary;
mod capabilities;
mod capability_snapshot;
mod client;
pub mod config;
pub(crate) mod coordinator;
mod core;
pub(crate) mod curator;
mod desktop;
pub(crate) mod librarian;
pub(crate) mod lid;
pub(crate) mod student;
// Never in a shipped binary: it trusts a synthetic issuer and carries a
// published client secret.
#[cfg(debug_assertions)]
mod demo_access_token_provider;
mod native_access_token_provider;
mod state;
pub(crate) mod transcript_correction;
#[cfg(windows)]
mod wam_access_token_provider;

pub(crate) use authorization::AuthenticatedRequestDispatcher;
pub use authorization::{
    AuthenticatedLiveConnection, AuthenticatedLiveError, AuthenticatedLiveMessage,
};
pub use boundary::ServerConnectorBoundary;
pub use capabilities::AsrCapabilityCatalog;
pub(crate) use capabilities::LidPreflightCapability;
pub(crate) use capability_snapshot::LastKnownAsrCapabilities;
pub use core::ServerConnector;
#[cfg(test)]
pub(crate) use core::{
    analyst_connection_lease_for_test, archivist_connection_lease_for_test,
    coordinator_connection_lease_for_test, curator_connection_lease_for_test,
    librarian_connection_lease_for_test, student_connection_lease_for_test,
    transcript_correction_connection_lease_for_test,
};
pub(crate) use core::{
    AnalystConnectionLease, ArchivistConnectionLease, AsrCatalogDispatchProof,
    BatchConnectionLease, CoordinatorConnectionLease, CuratorConnectionLease, CurrentAsrCatalog,
    LibrarianConnectionLease, LidPreflightDispatchProof, StudentConnectionLease,
    TranscriptCorrectionConnectionLease,
};
pub(crate) use desktop::{
    current_asr_capabilities, last_known_asr_capabilities, with_current_asr_capabilities,
};
pub use state::{ServerCapabilities, ServerConnectionSnapshot};

fn allow_insecure_private_server() -> bool {
    std::env::var("YAP_ALLOW_INSECURE_PRIVATE_SERVER").as_deref() == Ok("1")
}

#[tauri::command]
pub(crate) fn server_connection_status(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<ServerConnectionSnapshot, String> {
    desktop::connection_status(window, app, connector)
}

#[tauri::command]
pub(crate) async fn refresh_server_connection(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<ServerConnectionSnapshot, String> {
    desktop::refresh_connection(window, app, connector).await
}

#[tauri::command]
pub(crate) async fn server_asr_capabilities(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<Option<AsrCapabilityCatalog>, String> {
    desktop::asr_capabilities(window, app, connector).await
}

#[tauri::command]
pub(crate) async fn probe_local_server(
    window: tauri::WebviewWindow,
) -> Result<Option<desktop::LocalServerOffer>, String> {
    desktop::probe_local_server(window).await
}

#[tauri::command]
pub(crate) fn server_settings(
    window: tauri::WebviewWindow,
) -> Result<config::ServerSettings, String> {
    desktop::load_settings(window)
}

#[tauri::command]
pub(crate) async fn set_server_settings(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
    settings: config::ServerSettings,
) -> Result<config::ServerSettings, String> {
    desktop::save_settings(window, app, connector, settings).await
}

#[tauri::command]
pub(crate) async fn server_identity_status(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<native_access_token_provider::AccessTokenSessionStatus, String> {
    desktop::identity_session_status(window, app, connector).await
}

#[tauri::command]
pub(crate) async fn sign_in_to_server(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<native_access_token_provider::AccessTokenSessionStatus, String> {
    desktop::sign_in_to_server(window, app, connector).await
}

#[tauri::command]
pub(crate) async fn sign_out_of_server(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<native_access_token_provider::AccessTokenSessionStatus, String> {
    desktop::sign_out_of_server(window, app, connector).await
}

#[cfg(test)]
mod tests;
