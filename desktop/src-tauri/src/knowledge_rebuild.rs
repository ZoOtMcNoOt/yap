use crate::server_connector::{
    knowledge_rebuild::{RebuildError, RebuildRequest, RebuildResponse},
    ServerConnector,
};
static REQUEST: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(1);
#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AuthorizedRebuildResponse {
    authority_revision: String,
    response: RebuildResponse,
}
#[tauri::command]
pub(crate) async fn knowledge_rebuild(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    request: RebuildRequest,
    authority_revision: String,
) -> Result<AuthorizedRebuildResponse, RebuildError> {
    crate::authorization::ensure_main(&window).map_err(|_| RebuildError::new("denied", false))?;
    let _permit = REQUEST
        .try_acquire()
        .map_err(|_| RebuildError::new("busy", false))?;
    let lease = connector
        .knowledge_rebuild_connection_lease()
        .map_err(|_| RebuildError::new("identityChanged", false))?
        .ok_or_else(|| RebuildError::new("unavailable", false))?;
    let revision = lease.authority_revision();
    if authority_revision != revision {
        return Err(RebuildError::new("identityChanged", false));
    }
    // Writes have no cancellation command: dropping a remote reply cannot undo a commit.
    let result = tokio::time::timeout(
        std::time::Duration::from_secs(20),
        lease.client().execute(&request),
    )
    .await
    .map_err(|_| RebuildError::new("unavailable", request.mutates()))??;
    connector
        .with_current_knowledge_rebuild_lease(&lease, || AuthorizedRebuildResponse {
            authority_revision: revision,
            response: result,
        })
        .map_err(|_| RebuildError::new("identityChanged", request.mutates()))
}
