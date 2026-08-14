use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use crate::server_connector::{
    analyst::{AnalystAnswerJobView, AnalystAnswerStatus, AnalystApiClient, AnalystRequest},
    AnalystConnectionLease, ServerConnector,
};

const MAXIMUM_OWNED_REQUESTS: usize = 64;
const UNOWNED_REQUEST_CONTAINMENT_TIMEOUT: Duration = Duration::from_secs(5);
const UNOWNED_REQUEST_POLL_INTERVAL: Duration = Duration::from_millis(25);

#[derive(Clone)]
struct OwnedAnalystAnswer {
    request: AnalystRequest,
    lease: AnalystConnectionLease,
    latest: AnalystAnswerJobView,
}

#[derive(Clone)]
pub(crate) struct AnalystAnswerOwner {
    state: Arc<Mutex<AnalystAnswerOwnerState>>,
}

#[derive(Default)]
struct AnalystAnswerOwnerState {
    requests: HashMap<String, OwnedAnalystAnswer>,
    submissions: usize,
}

struct AnalystAnswerSubmissionPermit {
    owner: AnalystAnswerOwner,
    active: bool,
}

impl AnalystAnswerOwner {
    pub(crate) fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(AnalystAnswerOwnerState::default())),
        }
    }

    fn reserve_submission(&self) -> Result<AnalystAnswerSubmissionPermit, String> {
        let mut state = self.state.lock().expect("analyst answer owner poisoned");
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            reclaim_terminal_requests(&mut state.requests);
        }
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            return Err("Too many cited-answer requests are still active on this device.".into());
        }
        state.submissions += 1;
        Ok(AnalystAnswerSubmissionPermit {
            owner: self.clone(),
            active: true,
        })
    }

    fn request(&self, request_id: &str) -> Result<OwnedAnalystAnswer, String> {
        self.state
            .lock()
            .expect("analyst answer owner poisoned")
            .requests
            .get(request_id)
            .cloned()
            .ok_or_else(|| "This device does not own that cited-answer request.".to_string())
    }

    fn update(
        &self,
        owned: &OwnedAnalystAnswer,
        view: AnalystAnswerJobView,
    ) -> Result<AnalystAnswerJobView, String> {
        if view.request_id != owned.latest.request_id || !view.matches_request(&owned.request) {
            return Err("The cited-answer response changed request identity.".into());
        }
        let mut state = self.state.lock().expect("analyst answer owner poisoned");
        let current = state
            .requests
            .get_mut(&view.request_id)
            .ok_or_else(|| "This device no longer owns that cited-answer request.".to_string())?;
        if current.request != owned.request || current.latest.request_id != owned.latest.request_id
        {
            return Err("The cited-answer owner changed before commit.".into());
        }
        if current.latest != owned.latest {
            return Ok(current.latest.clone());
        }
        if !valid_status_transition(&current.latest, &view) {
            return Err("The cited-answer response regressed its lifecycle.".into());
        }
        current.latest = view.clone();
        Ok(view)
    }

    pub(crate) async fn cancel_active_requests(&self) -> Result<usize, String> {
        let active = self
            .state
            .lock()
            .expect("analyst answer owner poisoned")
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
                "{failures} of {total} active cited-answer requests could not be cancelled"
            ))
        }
    }

    #[cfg(test)]
    fn insert_for_test(
        &self,
        request: AnalystRequest,
        lease: AnalystConnectionLease,
        view: AnalystAnswerJobView,
    ) -> Result<AnalystAnswerJobView, String> {
        self.reserve_submission()?.commit(request, lease, view)
    }
}

impl AnalystAnswerSubmissionPermit {
    fn commit(
        mut self,
        request: AnalystRequest,
        lease: AnalystConnectionLease,
        view: AnalystAnswerJobView,
    ) -> Result<AnalystAnswerJobView, String> {
        let mut state = self
            .owner
            .state
            .lock()
            .expect("analyst answer owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("analyst answer submission reservation missing");
        self.active = false;
        if state.requests.contains_key(&view.request_id) {
            return Err("The cited-answer identity was reused.".into());
        }
        if !view.matches_request(&request) {
            return Err("The cited-answer response changed request identity.".into());
        }
        state.requests.insert(
            view.request_id.clone(),
            OwnedAnalystAnswer {
                request,
                lease,
                latest: view.clone(),
            },
        );
        Ok(view)
    }
}

impl Drop for AnalystAnswerSubmissionPermit {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        let mut state = self
            .owner
            .state
            .lock()
            .expect("analyst answer owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("analyst answer submission reservation missing");
    }
}

fn reclaim_terminal_requests(requests: &mut HashMap<String, OwnedAnalystAnswer>) {
    requests.retain(|_, request| request.latest.status.is_active());
}

fn valid_status_transition(current: &AnalystAnswerJobView, next: &AnalystAnswerJobView) -> bool {
    match current.status {
        AnalystAnswerStatus::Queued => true,
        AnalystAnswerStatus::Running => next.status != AnalystAnswerStatus::Queued,
        AnalystAnswerStatus::CancellationRequested => matches!(
            next.status,
            AnalystAnswerStatus::CancellationRequested
                | AnalystAnswerStatus::Complete
                | AnalystAnswerStatus::EvidenceUnavailable
                | AnalystAnswerStatus::Cancelled
                | AnalystAnswerStatus::Failed
        ),
        AnalystAnswerStatus::Complete
        | AnalystAnswerStatus::EvidenceUnavailable
        | AnalystAnswerStatus::Cancelled
        | AnalystAnswerStatus::Failed => next == current,
    }
}

impl Default for AnalystAnswerOwner {
    fn default() -> Self {
        Self::new()
    }
}

#[tauri::command]
pub(crate) async fn start_analyst_answer(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, AnalystAnswerOwner>,
    question: String,
    maximum_results: u8,
    expected_generation_sha256: Option<String>,
) -> Result<AnalystAnswerJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let request = AnalystRequest::new(question, maximum_results, expected_generation_sha256)
        .map_err(|error| error.to_string())?;
    let lease = connector.analyst_connection_lease()?.ok_or_else(|| {
        "Cited answers require a connected organization server with Analyst enabled.".to_string()
    })?;
    let submission = owner.reserve_submission()?;
    let view = lease
        .client()
        .submit(&request)
        .await
        .map_err(|error| error.to_string())?;
    let request_id = view.request_id.clone();
    let commit = connector
        .with_current_analyst_lease(&lease, || submission.commit(request, lease.clone(), view))
        .and_then(|result| result);
    match commit {
        Ok(committed) => Ok(committed),
        Err(error) => {
            if contain_unowned_submitted_answer(lease.client(), &request_id)
                .await
                .is_err()
            {
                return Err(
                    "Cited-answer request could not be contained after local ownership failed."
                        .into(),
                );
            }
            Err(error)
        }
    }
}

#[tauri::command]
pub(crate) async fn analyst_answer_status(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, AnalystAnswerOwner>,
    request_id: String,
) -> Result<AnalystAnswerJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .status(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_analyst_lease(&owned.lease, || owner.update(&owned, view))?
}

#[tauri::command]
pub(crate) async fn cancel_analyst_answer(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, AnalystAnswerOwner>,
    request_id: String,
) -> Result<AnalystAnswerJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .cancel(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_analyst_lease(&owned.lease, || owner.update(&owned, view))?
}

async fn contain_unowned_submitted_answer(
    client: &AnalystApiClient,
    request_id: &str,
) -> Result<(), String> {
    let deadline = Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT;
    let mut view = match client.cancel(request_id).await {
        Ok(view) => view,
        Err(_) => client
            .status(request_id)
            .await
            .map_err(|_| "accepted cited-answer request could not be found".to_string())?,
    };
    while view.status.is_active() {
        if Instant::now() >= deadline {
            return Err("accepted cited-answer request did not stop".into());
        }
        tokio::time::sleep(UNOWNED_REQUEST_POLL_INTERVAL).await;
        view = client
            .status(request_id)
            .await
            .map_err(|_| "accepted cited-answer request status was lost".to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server_connector::{
        analyst::AnalystAnswerStatus, analyst_connection_lease_for_test,
    };

    fn request() -> AnalystRequest {
        AnalystRequest::new("What was approved?".into(), 3, Some("a".repeat(64))).unwrap()
    }

    fn view(status: AnalystAnswerStatus, reason: Option<&str>) -> AnalystAnswerJobView {
        AnalystAnswerJobView::for_test(
            format!("analyst-answer-{}", "1".repeat(32)),
            status,
            reason.map(str::to_owned),
        )
    }

    #[test]
    fn owner_preserves_request_identity_and_monotonic_lifecycle() {
        let owner = AnalystAnswerOwner::new();
        owner
            .insert_for_test(
                request(),
                analyst_connection_lease_for_test(),
                view(AnalystAnswerStatus::Queued, None),
            )
            .unwrap();
        let owned = owner
            .request(&format!("analyst-answer-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(&owned, view(AnalystAnswerStatus::Running, None))
                .unwrap()
                .status,
            AnalystAnswerStatus::Running
        );

        let running = owner.request(&owned.latest.request_id).unwrap();
        assert!(owner
            .update(&running, view(AnalystAnswerStatus::Queued, None))
            .is_err());
    }

    #[test]
    fn terminal_owner_state_is_exact_and_reclaimable() {
        let owner = AnalystAnswerOwner::new();
        owner
            .insert_for_test(
                request(),
                analyst_connection_lease_for_test(),
                view(AnalystAnswerStatus::Cancelled, Some("client-cancelled")),
            )
            .unwrap();
        let owned = owner
            .request(&format!("analyst-answer-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(
                    &owned,
                    view(AnalystAnswerStatus::Cancelled, Some("client-cancelled")),
                )
                .unwrap(),
            owned.latest
        );
        assert!(owner
            .update(
                &owned,
                view(AnalystAnswerStatus::Failed, Some("invalid-output")),
            )
            .is_err());
    }
}
