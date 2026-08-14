use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use crate::server_connector::{
    coordinator::{
        CoordinatorApiClient, CoordinatorBundleJobView, CoordinatorBundleStatus, CoordinatorRequest,
    },
    CoordinatorConnectionLease, ServerConnector,
};

const MAXIMUM_OWNED_REQUESTS: usize = 64;
const UNOWNED_REQUEST_CONTAINMENT_TIMEOUT: Duration = Duration::from_secs(5);
const UNOWNED_REQUEST_POLL_INTERVAL: Duration = Duration::from_millis(25);

#[derive(Clone)]
struct OwnedCoordinatorBundle {
    request: CoordinatorRequest,
    lease: CoordinatorConnectionLease,
    latest: CoordinatorBundleJobView,
}

#[derive(Clone)]
pub(crate) struct CoordinatorBundleOwner {
    state: Arc<Mutex<CoordinatorBundleOwnerState>>,
}

#[derive(Default)]
struct CoordinatorBundleOwnerState {
    requests: HashMap<String, OwnedCoordinatorBundle>,
    submissions: usize,
}

struct CoordinatorBundleSubmissionPermit {
    owner: CoordinatorBundleOwner,
    active: bool,
}

impl CoordinatorBundleOwner {
    pub(crate) fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(CoordinatorBundleOwnerState::default())),
        }
    }

    fn reserve_submission(&self) -> Result<CoordinatorBundleSubmissionPermit, String> {
        let mut state = self
            .state
            .lock()
            .expect("coordinator bundle owner poisoned");
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            reclaim_terminal_requests(&mut state.requests);
        }
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            return Err(
                "Too many coordination-bundle requests are still active on this device.".into(),
            );
        }
        state.submissions += 1;
        Ok(CoordinatorBundleSubmissionPermit {
            owner: self.clone(),
            active: true,
        })
    }

    fn request(&self, request_id: &str) -> Result<OwnedCoordinatorBundle, String> {
        self.state
            .lock()
            .expect("coordinator bundle owner poisoned")
            .requests
            .get(request_id)
            .cloned()
            .ok_or_else(|| "This device does not own that coordination-bundle request.".to_string())
    }

    fn update(
        &self,
        owned: &OwnedCoordinatorBundle,
        view: CoordinatorBundleJobView,
    ) -> Result<CoordinatorBundleJobView, String> {
        if view.request_id != owned.latest.request_id || !view.matches_request(&owned.request) {
            return Err("The coordination-bundle response changed request identity.".into());
        }
        let mut state = self
            .state
            .lock()
            .expect("coordinator bundle owner poisoned");
        let current = state.requests.get_mut(&view.request_id).ok_or_else(|| {
            "This device no longer owns that coordination-bundle request.".to_string()
        })?;
        if current.request != owned.request || current.latest.request_id != owned.latest.request_id
        {
            return Err("The coordination-bundle owner changed before commit.".into());
        }
        if current.latest != owned.latest {
            return Ok(current.latest.clone());
        }
        if !valid_status_transition(&current.latest, &view) {
            return Err("The coordination-bundle response regressed its lifecycle.".into());
        }
        current.latest = view.clone();
        Ok(view)
    }

    pub(crate) async fn cancel_active_requests(&self) -> Result<usize, String> {
        let active = self
            .state
            .lock()
            .expect("coordinator bundle owner poisoned")
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
                "{failures} of {total} active coordination-bundle requests could not be cancelled"
            ))
        }
    }

    #[cfg(test)]
    fn insert_for_test(
        &self,
        request: CoordinatorRequest,
        lease: CoordinatorConnectionLease,
        view: CoordinatorBundleJobView,
    ) -> Result<CoordinatorBundleJobView, String> {
        self.reserve_submission()?.commit(request, lease, view)
    }
}

impl CoordinatorBundleSubmissionPermit {
    fn commit(
        mut self,
        request: CoordinatorRequest,
        lease: CoordinatorConnectionLease,
        view: CoordinatorBundleJobView,
    ) -> Result<CoordinatorBundleJobView, String> {
        let mut state = self
            .owner
            .state
            .lock()
            .expect("coordinator bundle owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("coordinator bundle submission reservation missing");
        self.active = false;
        if state.requests.contains_key(&view.request_id) {
            return Err("The coordination-bundle identity was reused.".into());
        }
        if !view.matches_request(&request) {
            return Err("The coordination-bundle response changed request identity.".into());
        }
        state.requests.insert(
            view.request_id.clone(),
            OwnedCoordinatorBundle {
                request,
                lease,
                latest: view.clone(),
            },
        );
        Ok(view)
    }
}

impl Drop for CoordinatorBundleSubmissionPermit {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        let mut state = self
            .owner
            .state
            .lock()
            .expect("coordinator bundle owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("coordinator bundle submission reservation missing");
    }
}

fn reclaim_terminal_requests(requests: &mut HashMap<String, OwnedCoordinatorBundle>) {
    requests.retain(|_, request| request.latest.status.is_active());
}

fn valid_status_transition(
    current: &CoordinatorBundleJobView,
    next: &CoordinatorBundleJobView,
) -> bool {
    match current.status {
        CoordinatorBundleStatus::Queued => true,
        CoordinatorBundleStatus::Running => next.status != CoordinatorBundleStatus::Queued,
        CoordinatorBundleStatus::CancellationRequested => matches!(
            next.status,
            CoordinatorBundleStatus::CancellationRequested
                | CoordinatorBundleStatus::Complete
                | CoordinatorBundleStatus::EvidenceUnavailable
                | CoordinatorBundleStatus::Cancelled
                | CoordinatorBundleStatus::Failed
        ),
        CoordinatorBundleStatus::Complete
        | CoordinatorBundleStatus::EvidenceUnavailable
        | CoordinatorBundleStatus::Cancelled
        | CoordinatorBundleStatus::Failed => next == current,
    }
}

impl Default for CoordinatorBundleOwner {
    fn default() -> Self {
        Self::new()
    }
}

#[tauri::command]
pub(crate) async fn start_coordinator_bundle(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, CoordinatorBundleOwner>,
    objective: String,
    maximum_items: u8,
    expected_generation_sha256: Option<String>,
) -> Result<CoordinatorBundleJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let request = CoordinatorRequest::new(objective, maximum_items, expected_generation_sha256)
        .map_err(|error| error.to_string())?;
    let lease = connector.coordinator_connection_lease()?.ok_or_else(|| {
        "Coordination bundles require a connected organization server with Coordinator enabled."
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
        .with_current_coordinator_lease(&lease, || submission.commit(request, lease.clone(), view))
        .and_then(|result| result);
    match commit {
        Ok(committed) => Ok(committed),
        Err(error) => {
            if contain_unowned_submitted_bundle(lease.client(), &request_id)
                .await
                .is_err()
            {
                return Err(
                    "Coordination-bundle request could not be contained after local ownership failed."
                        .into(),
                );
            }
            Err(error)
        }
    }
}

#[tauri::command]
pub(crate) async fn coordinator_bundle_status(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, CoordinatorBundleOwner>,
    request_id: String,
) -> Result<CoordinatorBundleJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .status(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_coordinator_lease(&owned.lease, || owner.update(&owned, view))?
}

#[tauri::command]
pub(crate) async fn cancel_coordinator_bundle(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, CoordinatorBundleOwner>,
    request_id: String,
) -> Result<CoordinatorBundleJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .cancel(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_coordinator_lease(&owned.lease, || owner.update(&owned, view))?
}

async fn contain_unowned_submitted_bundle(
    client: &CoordinatorApiClient,
    request_id: &str,
) -> Result<(), String> {
    let deadline = Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT;
    let mut view = match client.cancel(request_id).await {
        Ok(view) => view,
        Err(_) => client
            .status(request_id)
            .await
            .map_err(|_| "accepted coordination-bundle request could not be found".to_string())?,
    };
    while view.status.is_active() {
        if Instant::now() >= deadline {
            return Err("accepted coordination-bundle request did not stop".into());
        }
        tokio::time::sleep(UNOWNED_REQUEST_POLL_INTERVAL).await;
        view = client
            .status(request_id)
            .await
            .map_err(|_| "accepted coordination-bundle request status was lost".to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server_connector::{
        coordinator::CoordinatorBundleStatus, coordinator_connection_lease_for_test,
    };

    fn request() -> CoordinatorRequest {
        CoordinatorRequest::new(
            "Coordinate reviewed proposals.".into(),
            3,
            Some("a".repeat(64)),
        )
        .unwrap()
    }

    fn view(status: CoordinatorBundleStatus, reason: Option<&str>) -> CoordinatorBundleJobView {
        CoordinatorBundleJobView::for_test(
            format!("coordinator-bundle-{}", "1".repeat(32)),
            status,
            reason.map(str::to_owned),
        )
    }

    #[test]
    fn owner_preserves_request_identity_and_monotonic_lifecycle() {
        let owner = CoordinatorBundleOwner::new();
        owner
            .insert_for_test(
                request(),
                coordinator_connection_lease_for_test(),
                view(CoordinatorBundleStatus::Queued, None),
            )
            .unwrap();
        let owned = owner
            .request(&format!("coordinator-bundle-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(&owned, view(CoordinatorBundleStatus::Running, None))
                .unwrap()
                .status,
            CoordinatorBundleStatus::Running
        );
        let running = owner.request(&owned.latest.request_id).unwrap();
        assert!(owner
            .update(&running, view(CoordinatorBundleStatus::Queued, None))
            .is_err());
    }

    #[test]
    fn terminal_owner_state_is_exact_and_reclaimable() {
        let owner = CoordinatorBundleOwner::new();
        owner
            .insert_for_test(
                request(),
                coordinator_connection_lease_for_test(),
                view(CoordinatorBundleStatus::Cancelled, Some("client-cancelled")),
            )
            .unwrap();
        let owned = owner
            .request(&format!("coordinator-bundle-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(
                    &owned,
                    view(CoordinatorBundleStatus::Cancelled, Some("client-cancelled")),
                )
                .unwrap(),
            owned.latest
        );
        assert!(owner
            .update(
                &owned,
                view(CoordinatorBundleStatus::Failed, Some("invalid-output")),
            )
            .is_err());
    }
}
