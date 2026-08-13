use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use crate::server_connector::{
    librarian::{
        LibrarianApiClient, LibrarianQueryJobView, LibrarianQueryStatus, LibrarianRequest,
    },
    LibrarianConnectionLease, ServerConnector,
};

const MAXIMUM_OWNED_REQUESTS: usize = 64;
const UNOWNED_REQUEST_CONTAINMENT_TIMEOUT: Duration = Duration::from_secs(5);
const UNOWNED_REQUEST_POLL_INTERVAL: Duration = Duration::from_millis(25);

#[derive(Clone)]
struct OwnedLibrarianQuery {
    request: LibrarianRequest,
    lease: LibrarianConnectionLease,
    latest: LibrarianQueryJobView,
}

#[derive(Clone)]
pub(crate) struct LibrarianQueryOwner {
    state: Arc<Mutex<LibrarianQueryOwnerState>>,
}

#[derive(Default)]
struct LibrarianQueryOwnerState {
    requests: HashMap<String, OwnedLibrarianQuery>,
    submissions: usize,
}

struct LibrarianQuerySubmissionPermit {
    owner: LibrarianQueryOwner,
    active: bool,
}

impl LibrarianQueryOwner {
    pub(crate) fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(LibrarianQueryOwnerState::default())),
        }
    }

    fn reserve_submission(&self) -> Result<LibrarianQuerySubmissionPermit, String> {
        let mut state = self.state.lock().expect("librarian owner poisoned");
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            reclaim_terminal_requests(&mut state.requests);
        }
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            return Err("Too many knowledge queries are still active on this device.".into());
        }
        state.submissions += 1;
        Ok(LibrarianQuerySubmissionPermit {
            owner: self.clone(),
            active: true,
        })
    }

    fn request(&self, request_id: &str) -> Result<OwnedLibrarianQuery, String> {
        self.state
            .lock()
            .expect("librarian owner poisoned")
            .requests
            .get(request_id)
            .cloned()
            .ok_or_else(|| "This device does not own that knowledge query.".to_string())
    }

    fn update(
        &self,
        owned: &OwnedLibrarianQuery,
        view: LibrarianQueryJobView,
    ) -> Result<LibrarianQueryJobView, String> {
        if view.request_id != owned.latest.request_id || !view.matches_request(&owned.request) {
            return Err("The knowledge query response changed request identity.".into());
        }
        let mut state = self.state.lock().expect("librarian owner poisoned");
        let current = state
            .requests
            .get_mut(&view.request_id)
            .ok_or_else(|| "This device no longer owns that knowledge query.".to_string())?;
        if current.request != owned.request || current.latest.request_id != owned.latest.request_id
        {
            return Err("The knowledge query owner changed before commit.".into());
        }
        if current.latest != owned.latest {
            return Ok(current.latest.clone());
        }
        if !valid_status_transition(&current.latest, &view) {
            return Err("The knowledge query response regressed its lifecycle.".into());
        }
        current.latest = view.clone();
        Ok(view)
    }

    pub(crate) async fn cancel_active_requests(&self) -> Result<usize, String> {
        let active = self
            .state
            .lock()
            .expect("librarian owner poisoned")
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
                "{failures} of {total} active knowledge queries could not be cancelled"
            ))
        }
    }

    #[cfg(test)]
    fn insert_for_test(
        &self,
        request: LibrarianRequest,
        lease: LibrarianConnectionLease,
        view: LibrarianQueryJobView,
    ) -> Result<LibrarianQueryJobView, String> {
        self.reserve_submission()?.commit(request, lease, view)
    }
}

impl LibrarianQuerySubmissionPermit {
    fn commit(
        mut self,
        request: LibrarianRequest,
        lease: LibrarianConnectionLease,
        view: LibrarianQueryJobView,
    ) -> Result<LibrarianQueryJobView, String> {
        let mut state = self.owner.state.lock().expect("librarian owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("librarian submission reservation missing");
        self.active = false;
        if state.requests.contains_key(&view.request_id) {
            return Err("The knowledge query identity was reused.".into());
        }
        if !view.matches_request(&request) {
            return Err("The knowledge query response changed request identity.".into());
        }
        state.requests.insert(
            view.request_id.clone(),
            OwnedLibrarianQuery {
                request,
                lease,
                latest: view.clone(),
            },
        );
        Ok(view)
    }
}

impl Drop for LibrarianQuerySubmissionPermit {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        let mut state = self.owner.state.lock().expect("librarian owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("librarian submission reservation missing");
    }
}

fn reclaim_terminal_requests(requests: &mut HashMap<String, OwnedLibrarianQuery>) {
    requests.retain(|_, request| request.latest.status.is_active());
}

fn valid_status_transition(current: &LibrarianQueryJobView, next: &LibrarianQueryJobView) -> bool {
    match current.status {
        LibrarianQueryStatus::Queued => true,
        LibrarianQueryStatus::Running => next.status != LibrarianQueryStatus::Queued,
        LibrarianQueryStatus::CancellationRequested => matches!(
            next.status,
            LibrarianQueryStatus::CancellationRequested
                | LibrarianQueryStatus::Complete
                | LibrarianQueryStatus::EvidenceUnavailable
                | LibrarianQueryStatus::Cancelled
                | LibrarianQueryStatus::Failed
        ),
        LibrarianQueryStatus::Complete
        | LibrarianQueryStatus::EvidenceUnavailable
        | LibrarianQueryStatus::Cancelled
        | LibrarianQueryStatus::Failed => next == current,
    }
}

impl Default for LibrarianQueryOwner {
    fn default() -> Self {
        Self::new()
    }
}

#[tauri::command]
pub(crate) async fn start_librarian_query(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, LibrarianQueryOwner>,
    search_text: String,
    maximum_results: u8,
    expected_generation_sha256: Option<String>,
) -> Result<LibrarianQueryJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let request = LibrarianRequest::new(search_text, maximum_results, expected_generation_sha256)
        .map_err(|error| error.to_string())?;
    let lease = connector.librarian_connection_lease()?.ok_or_else(|| {
        "Knowledge queries require a connected organization server with Librarian enabled."
            .to_string()
    })?;
    let submission = owner.reserve_submission()?;
    let view = lease
        .client()
        .submit(&request)
        .await
        .map_err(|error| error.to_string())?;
    let request_id = view.request_id.clone();
    let commit = connector
        .with_current_librarian_lease(&lease, || submission.commit(request, lease.clone(), view))
        .and_then(|result| result);
    match commit {
        Ok(committed) => Ok(committed),
        Err(error) => {
            if contain_unowned_submitted_query(lease.client(), &request_id)
                .await
                .is_err()
            {
                return Err(
                    "Knowledge query could not be contained after local ownership failed.".into(),
                );
            }
            Err(error)
        }
    }
}

#[tauri::command]
pub(crate) async fn librarian_query_status(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, LibrarianQueryOwner>,
    request_id: String,
) -> Result<LibrarianQueryJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .status(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_librarian_lease(&owned.lease, || owner.update(&owned, view))?
}

#[tauri::command]
pub(crate) async fn cancel_librarian_query(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, LibrarianQueryOwner>,
    request_id: String,
) -> Result<LibrarianQueryJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .cancel(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_librarian_lease(&owned.lease, || owner.update(&owned, view))?
}

async fn contain_unowned_submitted_query(
    client: &LibrarianApiClient,
    request_id: &str,
) -> Result<(), String> {
    let deadline = Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT;
    let mut view = match client.cancel(request_id).await {
        Ok(view) => view,
        Err(_) => client
            .status(request_id)
            .await
            .map_err(|_| "accepted knowledge query could not be found".to_string())?,
    };
    while view.status.is_active() {
        if Instant::now() >= deadline {
            return Err("accepted knowledge query did not stop".into());
        }
        tokio::time::sleep(UNOWNED_REQUEST_POLL_INTERVAL).await;
        view = client
            .status(request_id)
            .await
            .map_err(|_| "accepted knowledge query status was lost".to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server_connector::{
        librarian::LibrarianQueryStatus, librarian_connection_lease_for_test,
    };

    fn request() -> LibrarianRequest {
        LibrarianRequest::new("reviewed launch".into(), 3, Some("a".repeat(64))).unwrap()
    }

    fn view(status: LibrarianQueryStatus, reason: Option<&str>) -> LibrarianQueryJobView {
        LibrarianQueryJobView::for_test(
            format!("librarian-query-{}", "1".repeat(32)),
            status,
            reason.map(str::to_owned),
        )
    }

    #[test]
    fn owner_preserves_request_identity_and_monotonic_lifecycle() {
        let owner = LibrarianQueryOwner::new();
        owner
            .insert_for_test(
                request(),
                librarian_connection_lease_for_test(),
                view(LibrarianQueryStatus::Queued, None),
            )
            .unwrap();
        let owned = owner
            .request(&format!("librarian-query-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(&owned, view(LibrarianQueryStatus::Running, None))
                .unwrap()
                .status,
            LibrarianQueryStatus::Running
        );

        let running = owner.request(&owned.latest.request_id).unwrap();
        assert!(owner
            .update(&running, view(LibrarianQueryStatus::Queued, None))
            .is_err());
    }

    #[test]
    fn terminal_owner_state_is_exact_and_reclaimable() {
        let owner = LibrarianQueryOwner::new();
        owner
            .insert_for_test(
                request(),
                librarian_connection_lease_for_test(),
                view(LibrarianQueryStatus::Cancelled, Some("client-cancelled")),
            )
            .unwrap();
        let owned = owner
            .request(&format!("librarian-query-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(
                    &owned,
                    view(LibrarianQueryStatus::Cancelled, Some("client-cancelled")),
                )
                .unwrap(),
            owned.latest
        );
        assert!(owner
            .update(
                &owned,
                view(LibrarianQueryStatus::Failed, Some("invalid-output")),
            )
            .is_err());
    }
}
