use std::{
    collections::HashMap,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use crate::server_connector::{
    curator::{
        CuratorApiClient, CuratorProposalJobView, CuratorProposalStatus, CuratorRequest,
        CuratorReviewedStudentQuestion,
    },
    CuratorConnectionLease, ServerConnector,
};

const MAXIMUM_OWNED_REQUESTS: usize = 64;
const UNOWNED_REQUEST_CONTAINMENT_TIMEOUT: Duration = Duration::from_secs(5);
const UNOWNED_REQUEST_POLL_INTERVAL: Duration = Duration::from_millis(25);
static NEXT_SUBMISSION: AtomicU64 = AtomicU64::new(0);

#[derive(Clone)]
struct OwnedCuratorProposal {
    request: CuratorRequest,
    lease: CuratorConnectionLease,
    latest: CuratorProposalJobView,
}

#[derive(Clone)]
pub(crate) struct CuratorProposalOwner {
    state: Arc<Mutex<CuratorProposalOwnerState>>,
}

#[derive(Default)]
struct CuratorProposalOwnerState {
    requests: HashMap<String, OwnedCuratorProposal>,
    submissions: usize,
}

struct CuratorProposalSubmissionPermit {
    owner: CuratorProposalOwner,
    active: bool,
}

impl CuratorProposalOwner {
    pub(crate) fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(CuratorProposalOwnerState::default())),
        }
    }

    fn reserve_submission(&self) -> Result<CuratorProposalSubmissionPermit, String> {
        let mut state = self.state.lock().expect("curator proposal owner poisoned");
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            reclaim_terminal_requests(&mut state.requests);
        }
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            return Err("Too many knowledge-proposal requests are active on this device.".into());
        }
        state.submissions += 1;
        Ok(CuratorProposalSubmissionPermit {
            owner: self.clone(),
            active: true,
        })
    }

    fn request(&self, request_id: &str) -> Result<OwnedCuratorProposal, String> {
        self.state
            .lock()
            .expect("curator proposal owner poisoned")
            .requests
            .get(request_id)
            .cloned()
            .ok_or_else(|| "This device does not own that knowledge-proposal request.".to_string())
    }

    fn update(
        &self,
        owned: &OwnedCuratorProposal,
        view: CuratorProposalJobView,
    ) -> Result<CuratorProposalJobView, String> {
        if view.request_id != owned.latest.request_id || !view.matches_request(&owned.request) {
            return Err("The knowledge-proposal response changed request identity.".into());
        }
        let mut state = self.state.lock().expect("curator proposal owner poisoned");
        let current = state.requests.get_mut(&view.request_id).ok_or_else(|| {
            "This device no longer owns that knowledge-proposal request.".to_string()
        })?;
        if current.request != owned.request || current.latest.request_id != owned.latest.request_id
        {
            return Err("The knowledge-proposal owner changed before commit.".into());
        }
        if current.latest != owned.latest {
            return Ok(current.latest.clone());
        }
        if !valid_status_transition(&current.latest, &view) {
            return Err("The knowledge-proposal response regressed its lifecycle.".into());
        }
        current.latest = view.clone();
        Ok(view)
    }

    pub(crate) async fn cancel_active_requests(&self) -> Result<usize, String> {
        let active = self
            .state
            .lock()
            .expect("curator proposal owner poisoned")
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
                "{failures} of {total} active knowledge-proposal requests could not be cancelled"
            ))
        }
    }

    #[cfg(test)]
    fn insert_for_test(
        &self,
        request: CuratorRequest,
        lease: CuratorConnectionLease,
        view: CuratorProposalJobView,
    ) -> Result<CuratorProposalJobView, String> {
        self.reserve_submission()?.commit(request, lease, view)
    }
}

impl CuratorProposalSubmissionPermit {
    fn commit(
        mut self,
        request: CuratorRequest,
        lease: CuratorConnectionLease,
        view: CuratorProposalJobView,
    ) -> Result<CuratorProposalJobView, String> {
        let mut state = self
            .owner
            .state
            .lock()
            .expect("curator proposal owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("curator proposal submission reservation missing");
        self.active = false;
        if state.requests.contains_key(&view.request_id) {
            return Err("The knowledge-proposal identity was reused.".into());
        }
        if !view.matches_request(&request) {
            return Err("The knowledge-proposal response changed request identity.".into());
        }
        state.requests.insert(
            view.request_id.clone(),
            OwnedCuratorProposal {
                request,
                lease,
                latest: view.clone(),
            },
        );
        Ok(view)
    }
}

impl Drop for CuratorProposalSubmissionPermit {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        let mut state = self
            .owner
            .state
            .lock()
            .expect("curator proposal owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("curator proposal submission reservation missing");
    }
}

fn reclaim_terminal_requests(requests: &mut HashMap<String, OwnedCuratorProposal>) {
    requests.retain(|_, request| request.latest.status.is_active());
}

fn valid_status_transition(
    current: &CuratorProposalJobView,
    next: &CuratorProposalJobView,
) -> bool {
    match current.status {
        CuratorProposalStatus::Queued => true,
        CuratorProposalStatus::Running => next.status != CuratorProposalStatus::Queued,
        CuratorProposalStatus::CancellationRequested => matches!(
            next.status,
            CuratorProposalStatus::CancellationRequested
                | CuratorProposalStatus::Proposed
                | CuratorProposalStatus::Rejected
                | CuratorProposalStatus::Cancelled
                | CuratorProposalStatus::Failed
        ),
        CuratorProposalStatus::Proposed
        | CuratorProposalStatus::Rejected
        | CuratorProposalStatus::Cancelled
        | CuratorProposalStatus::Failed => next == current,
    }
}

impl Default for CuratorProposalOwner {
    fn default() -> Self {
        Self::new()
    }
}

#[tauri::command]
pub(crate) async fn start_curator_proposal(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, CuratorProposalOwner>,
    expected_generation_sha256: String,
    reviewed_content: String,
    student_question: CuratorReviewedStudentQuestion,
) -> Result<CuratorProposalJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let request = CuratorRequest::reviewed_student_answer(
        next_submission_id(),
        expected_generation_sha256,
        reviewed_content,
        student_question,
    )
    .map_err(|error| error.to_string())?;
    let lease = connector.curator_connection_lease()?.ok_or_else(|| {
        "Knowledge proposals require a connected organization server with Curator enabled."
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
        .with_current_curator_lease(&lease, || submission.commit(request, lease.clone(), view))
        .and_then(|result| result);
    match commit {
        Ok(committed) => Ok(committed),
        Err(error) => {
            if contain_unowned_submitted_proposal(lease.client(), &request_id)
                .await
                .is_err()
            {
                return Err(
                    "Knowledge-proposal request could not be contained after local ownership failed."
                        .into(),
                );
            }
            Err(error)
        }
    }
}

#[tauri::command]
pub(crate) async fn curator_proposal_status(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, CuratorProposalOwner>,
    request_id: String,
) -> Result<CuratorProposalJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .status(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_curator_lease(&owned.lease, || owner.update(&owned, view))?
}

#[tauri::command]
pub(crate) async fn cancel_curator_proposal(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, CuratorProposalOwner>,
    request_id: String,
) -> Result<CuratorProposalJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .cancel(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_curator_lease(&owned.lease, || owner.update(&owned, view))?
}

async fn contain_unowned_submitted_proposal(
    client: &CuratorApiClient,
    request_id: &str,
) -> Result<(), String> {
    let deadline = Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT;
    let mut view = match client.cancel(request_id).await {
        Ok(view) => view,
        Err(_) => client
            .status(request_id)
            .await
            .map_err(|_| "accepted knowledge-proposal request could not be found".to_string())?,
    };
    while view.status.is_active() {
        if Instant::now() >= deadline {
            return Err("accepted knowledge-proposal request did not stop".into());
        }
        tokio::time::sleep(UNOWNED_REQUEST_POLL_INTERVAL).await;
        view = client
            .status(request_id)
            .await
            .map_err(|_| "accepted knowledge-proposal request status was lost".to_string())?;
    }
    Ok(())
}

fn next_submission_id() -> String {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = NEXT_SUBMISSION.fetch_add(1, Ordering::Relaxed);
    format!(
        "curator-{:x}-{timestamp:x}-{sequence:x}",
        std::process::id()
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server_connector::{
        curator::{CuratorSourceCitation, CuratorStudentQuestionSupport},
        curator_connection_lease_for_test,
    };

    fn request() -> CuratorRequest {
        CuratorRequest::reviewed_student_answer(
            "submission-1".into(),
            "a".repeat(64),
            "Contain the worker before retrying.".into(),
            CuratorReviewedStudentQuestion::new(
                "crash safety".into(),
                "What should you remember about crash safety?".into(),
                CuratorStudentQuestionSupport::new(
                    CuratorSourceCitation::new(
                        "meetings/job-1".into(),
                        "b".repeat(64),
                        "c".repeat(64),
                        0,
                        44,
                    )
                    .unwrap(),
                    "crash safety".into(),
                    29,
                    41,
                )
                .unwrap(),
            )
            .unwrap(),
        )
        .unwrap()
    }

    fn view(status: CuratorProposalStatus, reason: Option<&str>) -> CuratorProposalJobView {
        CuratorProposalJobView::for_test(
            format!("curator-proposal-{}", "1".repeat(32)),
            status,
            reason.map(str::to_owned),
        )
    }

    #[test]
    fn owner_preserves_request_identity_and_monotonic_lifecycle() {
        let owner = CuratorProposalOwner::new();
        owner
            .insert_for_test(
                request(),
                curator_connection_lease_for_test(),
                view(CuratorProposalStatus::Queued, None),
            )
            .unwrap();
        let owned = owner
            .request(&format!("curator-proposal-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(&owned, view(CuratorProposalStatus::Running, None))
                .unwrap()
                .status,
            CuratorProposalStatus::Running
        );

        let running = owner.request(&owned.latest.request_id).unwrap();
        assert!(owner
            .update(&running, view(CuratorProposalStatus::Queued, None))
            .is_err());
    }

    #[test]
    fn terminal_owner_state_is_exact_and_submission_ids_are_native_owned() {
        let first = next_submission_id();
        let second = next_submission_id();
        assert_ne!(first, second);
        assert!(first.starts_with("curator-"));

        let owner = CuratorProposalOwner::new();
        owner
            .insert_for_test(
                request(),
                curator_connection_lease_for_test(),
                view(CuratorProposalStatus::Cancelled, Some("client-cancelled")),
            )
            .unwrap();
        let owned = owner
            .request(&format!("curator-proposal-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(
                    &owned,
                    view(CuratorProposalStatus::Cancelled, Some("client-cancelled")),
                )
                .unwrap(),
            owned.latest
        );
        assert!(owner
            .update(
                &owned,
                view(CuratorProposalStatus::Failed, Some("invalid-output")),
            )
            .is_err());
    }
}
