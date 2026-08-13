use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use crate::{
    jobs::commands::RecordingJobs,
    server_connector::{
        archivist::{
            ArchivistApiClient, ArchivistIngestionJobView, ArchivistIngestionRequest,
            ArchivistIngestionStatus,
        },
        ArchivistConnectionLease, ServerConnector,
    },
};

const MAXIMUM_OWNED_REQUESTS: usize = 64;
const UNOWNED_REQUEST_CONTAINMENT_TIMEOUT: Duration = Duration::from_secs(5);
const UNOWNED_REQUEST_POLL_INTERVAL: Duration = Duration::from_millis(25);

#[derive(Clone)]
struct OwnedArchivistIngestion {
    request: ArchivistIngestionRequest,
    lease: ArchivistConnectionLease,
    latest: ArchivistIngestionJobView,
}

#[derive(Clone)]
pub(crate) struct ArchivistIngestionOwner {
    state: Arc<Mutex<ArchivistIngestionOwnerState>>,
}

#[derive(Default)]
struct ArchivistIngestionOwnerState {
    requests: HashMap<String, OwnedArchivistIngestion>,
    submissions: usize,
}

struct ArchivistIngestionSubmissionPermit {
    owner: ArchivistIngestionOwner,
    active: bool,
}

impl ArchivistIngestionOwner {
    pub(crate) fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(ArchivistIngestionOwnerState::default())),
        }
    }

    fn reserve_submission(&self) -> Result<ArchivistIngestionSubmissionPermit, String> {
        let mut state = self.state.lock().expect("archivist owner poisoned");
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            reclaim_terminal_requests(&mut state.requests);
        }
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            return Err("Too many knowledge staging requests are active on this device.".into());
        }
        state.submissions += 1;
        Ok(ArchivistIngestionSubmissionPermit {
            owner: self.clone(),
            active: true,
        })
    }

    fn request(&self, request_id: &str) -> Result<OwnedArchivistIngestion, String> {
        self.state
            .lock()
            .expect("archivist owner poisoned")
            .requests
            .get(request_id)
            .cloned()
            .ok_or_else(|| "This device does not own that knowledge staging request.".to_string())
    }

    fn update(
        &self,
        owned: &OwnedArchivistIngestion,
        view: ArchivistIngestionJobView,
    ) -> Result<ArchivistIngestionJobView, String> {
        if view.request_id != owned.latest.request_id || !view.matches_request(&owned.request) {
            return Err("The knowledge staging response changed source identity.".into());
        }
        let mut state = self.state.lock().expect("archivist owner poisoned");
        let current = state.requests.get_mut(&view.request_id).ok_or_else(|| {
            "This device no longer owns that knowledge staging request.".to_string()
        })?;
        if current.request != owned.request || current.latest.request_id != owned.latest.request_id
        {
            return Err("The knowledge staging owner changed before commit.".into());
        }
        if current.latest != owned.latest {
            return Ok(current.latest.clone());
        }
        if !valid_status_transition(&current.latest, &view) {
            return Err("The knowledge staging response regressed its lifecycle.".into());
        }
        current.latest = view.clone();
        Ok(view)
    }

    pub(crate) async fn cancel_active_requests(&self) -> Result<usize, String> {
        let active = self
            .state
            .lock()
            .expect("archivist owner poisoned")
            .requests
            .values()
            .filter(|request| request.latest.status.is_active())
            .map(|request| {
                (
                    request.latest.request_id.clone(),
                    request.lease.client().clone(),
                )
            })
            .collect::<Vec<_>>();
        let total = active.len();
        let mut failures = 0_usize;
        for (request_id, client) in active {
            if client.cancel(&request_id).await.is_err() {
                failures += 1;
            }
        }
        if failures == 0 {
            Ok(total)
        } else {
            Err(format!(
                "{failures} of {total} active knowledge staging requests could not be cancelled"
            ))
        }
    }

    #[cfg(test)]
    fn insert_for_test(
        &self,
        request: ArchivistIngestionRequest,
        lease: ArchivistConnectionLease,
        view: ArchivistIngestionJobView,
    ) -> Result<ArchivistIngestionJobView, String> {
        self.reserve_submission()?.commit(request, lease, view)
    }
}

impl ArchivistIngestionSubmissionPermit {
    fn commit(
        mut self,
        request: ArchivistIngestionRequest,
        lease: ArchivistConnectionLease,
        view: ArchivistIngestionJobView,
    ) -> Result<ArchivistIngestionJobView, String> {
        let mut state = self.owner.state.lock().expect("archivist owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("archivist submission reservation missing");
        self.active = false;
        if state.requests.contains_key(&view.request_id) {
            return Err("The knowledge staging identity was reused.".into());
        }
        if !view.matches_request(&request) {
            return Err("The knowledge staging response changed source identity.".into());
        }
        state.requests.insert(
            view.request_id.clone(),
            OwnedArchivistIngestion {
                request,
                lease,
                latest: view.clone(),
            },
        );
        Ok(view)
    }
}

impl Drop for ArchivistIngestionSubmissionPermit {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        let mut state = self.owner.state.lock().expect("archivist owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("archivist submission reservation missing");
    }
}

fn reclaim_terminal_requests(requests: &mut HashMap<String, OwnedArchivistIngestion>) {
    requests.retain(|_, request| request.latest.status.is_active());
}

fn valid_status_transition(
    current: &ArchivistIngestionJobView,
    next: &ArchivistIngestionJobView,
) -> bool {
    match current.status {
        ArchivistIngestionStatus::Queued => true,
        ArchivistIngestionStatus::Running => next.status != ArchivistIngestionStatus::Queued,
        ArchivistIngestionStatus::CancellationRequested => matches!(
            next.status,
            ArchivistIngestionStatus::CancellationRequested
                | ArchivistIngestionStatus::Staged
                | ArchivistIngestionStatus::Cancelled
                | ArchivistIngestionStatus::Failed
        ),
        ArchivistIngestionStatus::Staged
        | ArchivistIngestionStatus::Cancelled
        | ArchivistIngestionStatus::Failed => next == current,
    }
}

impl Default for ArchivistIngestionOwner {
    fn default() -> Self {
        Self::new()
    }
}

#[tauri::command]
pub(crate) async fn start_archivist_ingestion(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    jobs: tauri::State<'_, RecordingJobs>,
    owner: tauri::State<'_, ArchivistIngestionOwner>,
    recording_id: String,
) -> Result<ArchivistIngestionJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let lease = connector.archivist_connection_lease()?.ok_or_else(|| {
        "Knowledge staging requires a connected organization server with Archivist enabled."
            .to_string()
    })?;
    let source = jobs.archivist_ingestion_source(&recording_id)?;
    if source.server_base_url != lease.client().base_url_identity() {
        return Err("The selected transcript belongs to a different organization server.".into());
    }
    let request = ArchivistIngestionRequest::new(source.server_job_id, source.result_sha256)
        .map_err(|error| error.to_string())?;
    let submission = owner.reserve_submission()?;
    let view = lease
        .client()
        .submit(&request)
        .await
        .map_err(|error| error.to_string())?;
    let request_id = view.request_id.clone();
    let commit = connector
        .with_current_archivist_lease(&lease, || submission.commit(request, lease.clone(), view))
        .and_then(|result| result);
    match commit {
        Ok(committed) => Ok(committed),
        Err(error) => {
            if contain_unowned_submitted_ingestion(lease.client(), &request_id)
                .await
                .is_err()
            {
                return Err(
                    "Knowledge staging could not be contained after local ownership failed.".into(),
                );
            }
            Err(error)
        }
    }
}

#[tauri::command]
pub(crate) async fn archivist_ingestion_status(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, ArchivistIngestionOwner>,
    request_id: String,
) -> Result<ArchivistIngestionJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .status(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_archivist_lease(&owned.lease, || owner.update(&owned, view))?
}

#[tauri::command]
pub(crate) async fn cancel_archivist_ingestion(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, ArchivistIngestionOwner>,
    request_id: String,
) -> Result<ArchivistIngestionJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .cancel(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_archivist_lease(&owned.lease, || owner.update(&owned, view))?
}

async fn contain_unowned_submitted_ingestion(
    client: &ArchivistApiClient,
    request_id: &str,
) -> Result<(), String> {
    let deadline = Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT;
    let mut view = match client.cancel(request_id).await {
        Ok(view) => view,
        Err(_) => client
            .status(request_id)
            .await
            .map_err(|_| "accepted knowledge staging request could not be found".to_string())?,
    };
    while view.status.is_active() {
        if Instant::now() >= deadline {
            return Err("accepted knowledge staging request did not stop".into());
        }
        tokio::time::sleep(UNOWNED_REQUEST_POLL_INTERVAL).await;
        view = client
            .status(request_id)
            .await
            .map_err(|_| "accepted knowledge staging status was lost".to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server_connector::archivist_connection_lease_for_test;

    fn request() -> ArchivistIngestionRequest {
        ArchivistIngestionRequest::new("server-job-1".into(), "a".repeat(64)).unwrap()
    }

    fn view(status: ArchivistIngestionStatus, reason: Option<&str>) -> ArchivistIngestionJobView {
        ArchivistIngestionJobView::for_test(
            format!("archivist-ingestion-{}", "1".repeat(32)),
            status,
            "server-job-1".into(),
            "a".repeat(64),
            reason.map(str::to_owned),
        )
    }

    #[test]
    fn owner_preserves_source_identity_and_monotonic_lifecycle() {
        let owner = ArchivistIngestionOwner::new();
        owner
            .insert_for_test(
                request(),
                archivist_connection_lease_for_test(),
                view(ArchivistIngestionStatus::Queued, None),
            )
            .unwrap();
        let owned = owner
            .request(&format!("archivist-ingestion-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(&owned, view(ArchivistIngestionStatus::Running, None))
                .unwrap()
                .status,
            ArchivistIngestionStatus::Running
        );
        let running = owner.request(&owned.latest.request_id).unwrap();
        assert!(owner
            .update(&running, view(ArchivistIngestionStatus::Queued, None))
            .is_err());
    }

    #[test]
    fn terminal_owner_state_is_exact_and_reclaimable() {
        let owner = ArchivistIngestionOwner::new();
        owner
            .insert_for_test(
                request(),
                archivist_connection_lease_for_test(),
                view(
                    ArchivistIngestionStatus::Cancelled,
                    Some("client-cancelled"),
                ),
            )
            .unwrap();
        let owned = owner
            .request(&format!("archivist-ingestion-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(
                    &owned,
                    view(
                        ArchivistIngestionStatus::Cancelled,
                        Some("client-cancelled"),
                    ),
                )
                .unwrap(),
            owned.latest
        );
        assert!(owner
            .update(
                &owned,
                view(
                    ArchivistIngestionStatus::Failed,
                    Some("storage-unavailable")
                ),
            )
            .is_err());
    }
}
