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

    fn reconcile_terminal(
        &self,
        owned: &OwnedArchivistIngestion,
        view: ArchivistIngestionJobView,
    ) -> Result<ArchivistIngestionJobView, String> {
        if view.status.is_active()
            || view.request_id != owned.latest.request_id
            || !view.matches_request(&owned.request)
        {
            return Err("The knowledge staging terminal response is invalid.".into());
        }
        let mut state = self.state.lock().expect("archivist owner poisoned");
        let current = state.requests.get_mut(&view.request_id).ok_or_else(|| {
            "This device no longer owns that knowledge staging request.".to_string()
        })?;
        if current.request != owned.request || current.latest.request_id != owned.latest.request_id
        {
            return Err("The knowledge staging owner changed before commit.".into());
        }
        if !current.latest.status.is_active() {
            return if current.latest == view {
                Ok(current.latest.clone())
            } else {
                Err("The knowledge staging terminal response changed.".into())
            };
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
            .cloned()
            .collect::<Vec<_>>();
        let total = active.len();
        let mut failures = 0_usize;
        let deadline = Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT;
        for owned in active {
            let terminal = contain_submitted_ingestion_before(
                owned.lease.client(),
                &owned.latest.request_id,
                &owned.request,
                deadline,
            )
            .await;
            if terminal
                .and_then(|view| self.reconcile_terminal(&owned, view))
                .is_err()
            {
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
        .with_current_archivist_lease(&lease, || {
            submission.commit(request.clone(), lease.clone(), view)
        })
        .and_then(|result| result);
    match commit {
        Ok(committed) => Ok(committed),
        Err(error) => {
            if contain_submitted_ingestion_before(
                lease.client(),
                &request_id,
                &request,
                Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT,
            )
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
    let view =
        contain_submitted_ingestion(owned.lease.client(), &request_id, &owned.request).await?;
    connector
        .with_current_archivist_lease(&owned.lease, || owner.reconcile_terminal(&owned, view))?
}

async fn contain_submitted_ingestion(
    client: &ArchivistApiClient,
    request_id: &str,
    request: &ArchivistIngestionRequest,
) -> Result<ArchivistIngestionJobView, String> {
    contain_submitted_ingestion_before(
        client,
        request_id,
        request,
        Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT,
    )
    .await
}

async fn contain_submitted_ingestion_before(
    client: &ArchivistApiClient,
    request_id: &str,
    request: &ArchivistIngestionRequest,
    deadline: Instant,
) -> Result<ArchivistIngestionJobView, String> {
    let mut view = exact_containment_view(
        match client.cancel(request_id).await {
            Ok(view) => view,
            Err(_) => client
                .status(request_id)
                .await
                .map_err(|_| "accepted knowledge staging request could not be found".to_string())?,
        },
        request_id,
        request,
    )?;
    while view.status.is_active() {
        if Instant::now() >= deadline {
            return Err("accepted knowledge staging request did not stop".into());
        }
        tokio::time::sleep(UNOWNED_REQUEST_POLL_INTERVAL).await;
        view = exact_containment_view(
            client
                .status(request_id)
                .await
                .map_err(|_| "accepted knowledge staging status was lost".to_string())?,
            request_id,
            request,
        )?;
    }
    Ok(view)
}

fn exact_containment_view(
    view: ArchivistIngestionJobView,
    request_id: &str,
    request: &ArchivistIngestionRequest,
) -> Result<ArchivistIngestionJobView, String> {
    if view.request_id != request_id || !view.matches_request(request) {
        return Err("accepted knowledge staging response changed source identity".into());
    }
    Ok(view)
}

#[cfg(test)]
mod tests;
