//! Explicit export of current, permission-checked noncanonical evidence.

use crate::file_actions::export::{export_destination, export_permit, ExportKind};
use crate::server_connector::{
    knowledge_connections::{
        ConnectionsClient, ConnectionsError, ConnectionsRequest, ConnectionsResponse,
    },
    ServerConnector,
};
use serde::Serialize;
use std::time::Duration;
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;

#[derive(Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "status", rename_all = "camelCase")]
pub(crate) enum ReviewExport {
    Cancelled,
    Saved { path: String },
}

#[cfg(test)]
mod tests;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ReviewExportReceipt {
    authority_revision: String,
    proposal_id: String,
    generation_sha256: String,
    result: ReviewExport,
}

async fn current_package(
    client: &ConnectionsClient,
    request: &ConnectionsRequest,
    generation: &str,
) -> Result<String, ConnectionsError> {
    let response = tokio::time::timeout(Duration::from_secs(20), client.execute(request))
        .await
        .map_err(|_| ConnectionsError::new("unavailable", true))??;
    match response {
        ConnectionsResponse::Proposal(proposal) => proposal.review_package(generation),
        _ => Err(ConnectionsError::new("invalidResponse", false)),
    }
}

fn publish_package(
    admitted: &str,
    current: &str,
    destination: &crate::atomic_text::NewFileDestination,
) -> Result<ReviewExport, ConnectionsError> {
    if admitted != current {
        return Err(ConnectionsError::new("knowledgeChanged", false));
    }
    crate::atomic_text::write_new(destination, current).map_err(|error| {
        ConnectionsError::new(
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                "destinationExists"
            } else {
                "exportUnconfirmed"
            },
            true,
        )
    })?;
    Ok(ReviewExport::Saved {
        path: destination.path().to_string_lossy().into_owned(),
    })
}

#[tauri::command]
pub(crate) async fn export_connection_review_package(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    proposal_id: String,
    generation_sha256: String,
    authority_revision: String,
) -> Result<ReviewExportReceipt, ConnectionsError> {
    crate::authorization::ensure_main(&window)
        .map_err(|_| ConnectionsError::new("denied", false))?;
    let request_permit = super::REQUEST
        .try_acquire()
        .map_err(|_| ConnectionsError::new("busy", true))?;
    let file_permit = export_permit().map_err(|_| ConnectionsError::new("busy", true))?;
    let lease = connector
        .knowledge_connections_connection_lease()
        .map_err(|_| ConnectionsError::new("identityChanged", false))?
        .ok_or_else(|| ConnectionsError::new("unavailable", true))?;
    let revision = lease.authority_revision();
    super::validate_authority(&authority_revision, &revision)?;
    let request = ConnectionsRequest::Proposal {
        proposal_id: proposal_id.clone(),
    };
    let admitted = current_package(lease.client(), &request, &generation_sha256).await?;
    connector
        .with_current_knowledge_connections_lease(&lease, || ())
        .map_err(|_| ConnectionsError::new("identityChanged", false))?;
    // The worker owns both slots through the picker, revalidation and write.
    // There is no timeout/cancellation claim while a file can still publish.
    tauri::async_runtime::spawn_blocking(move || {
        let _request_permit = request_permit;
        let _file_permit = file_permit;
        let selected = app
            .dialog()
            .file()
            .set_parent(&window)
            .set_title("Export connection review — choose a new file")
            .set_file_name(format!("connection-review-{}.json", &proposal_id[..12]))
            .add_filter("Connection review package", &["json"])
            .blocking_save_file();
        let receipt = |result| ReviewExportReceipt {
            authority_revision: revision.clone(),
            proposal_id: proposal_id.clone(),
            generation_sha256: generation_sha256.clone(),
            result,
        };
        let Some(selected) = selected else {
            return Ok(receipt(ReviewExport::Cancelled));
        };
        let selected = selected
            .into_path()
            .map_err(|_| ConnectionsError::new("destination", true))?;
        let destination = export_destination(
            &selected,
            &crate::paths::app_data_dir(),
            ExportKind::ConnectionReview,
        )
        .map_err(|_| ConnectionsError::new("destination", true))?;
        let current = tauri::async_runtime::block_on(current_package(
            lease.client(),
            &request,
            &generation_sha256,
        ))?;
        app.state::<ServerConnector>()
            .with_current_knowledge_connections_lease(&lease, || {
                publish_package(&admitted, &current, &destination).map(receipt)
            })
            .map_err(|_| ConnectionsError::new("identityChanged", false))?
    })
    .await
    .map_err(|_| ConnectionsError::new("exportUnconfirmed", true))?
}
