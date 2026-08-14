use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use crate::server_connector::{
    student::{StudentApiClient, StudentQuestionJobView, StudentQuestionStatus, StudentRequest},
    ServerConnector, StudentConnectionLease,
};

const MAXIMUM_OWNED_REQUESTS: usize = 64;
const UNOWNED_REQUEST_CONTAINMENT_TIMEOUT: Duration = Duration::from_secs(5);
const UNOWNED_REQUEST_POLL_INTERVAL: Duration = Duration::from_millis(25);

#[derive(Clone)]
struct OwnedStudentQuestion {
    request: StudentRequest,
    lease: StudentConnectionLease,
    latest: StudentQuestionJobView,
}

#[derive(Clone)]
pub(crate) struct StudentQuestionOwner {
    state: Arc<Mutex<StudentQuestionOwnerState>>,
}

#[derive(Default)]
struct StudentQuestionOwnerState {
    requests: HashMap<String, OwnedStudentQuestion>,
    submissions: usize,
}

struct StudentQuestionSubmissionPermit {
    owner: StudentQuestionOwner,
    active: bool,
}

impl StudentQuestionOwner {
    pub(crate) fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(StudentQuestionOwnerState::default())),
        }
    }

    fn reserve_submission(&self) -> Result<StudentQuestionSubmissionPermit, String> {
        let mut state = self.state.lock().expect("student question owner poisoned");
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            reclaim_terminal_requests(&mut state.requests);
        }
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            return Err("Too many learning-question requests are active on this device.".into());
        }
        state.submissions += 1;
        Ok(StudentQuestionSubmissionPermit {
            owner: self.clone(),
            active: true,
        })
    }

    fn request(&self, request_id: &str) -> Result<OwnedStudentQuestion, String> {
        self.state
            .lock()
            .expect("student question owner poisoned")
            .requests
            .get(request_id)
            .cloned()
            .ok_or_else(|| "This device does not own that learning-question request.".to_string())
    }

    fn update(
        &self,
        owned: &OwnedStudentQuestion,
        view: StudentQuestionJobView,
    ) -> Result<StudentQuestionJobView, String> {
        if view.request_id != owned.latest.request_id || !view.matches_request(&owned.request) {
            return Err("The learning-question response changed request identity.".into());
        }
        let mut state = self.state.lock().expect("student question owner poisoned");
        let current = state.requests.get_mut(&view.request_id).ok_or_else(|| {
            "This device no longer owns that learning-question request.".to_string()
        })?;
        if current.request != owned.request || current.latest.request_id != owned.latest.request_id
        {
            return Err("The learning-question owner changed before commit.".into());
        }
        if current.latest != owned.latest {
            return Ok(current.latest.clone());
        }
        if !valid_status_transition(&current.latest, &view) {
            return Err("The learning-question response regressed its lifecycle.".into());
        }
        current.latest = view.clone();
        Ok(view)
    }

    pub(crate) async fn cancel_active_requests(&self) -> Result<usize, String> {
        let active = self
            .state
            .lock()
            .expect("student question owner poisoned")
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
                "{failures} of {total} active learning-question requests could not be cancelled"
            ))
        }
    }

    #[cfg(test)]
    fn insert_for_test(
        &self,
        request: StudentRequest,
        lease: StudentConnectionLease,
        view: StudentQuestionJobView,
    ) -> Result<StudentQuestionJobView, String> {
        self.reserve_submission()?.commit(request, lease, view)
    }
}

impl StudentQuestionSubmissionPermit {
    fn commit(
        mut self,
        request: StudentRequest,
        lease: StudentConnectionLease,
        view: StudentQuestionJobView,
    ) -> Result<StudentQuestionJobView, String> {
        let mut state = self
            .owner
            .state
            .lock()
            .expect("student question owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("student question submission reservation missing");
        self.active = false;
        if state.requests.contains_key(&view.request_id) {
            return Err("The learning-question identity was reused.".into());
        }
        if !view.matches_request(&request) {
            return Err("The learning-question response changed request identity.".into());
        }
        state.requests.insert(
            view.request_id.clone(),
            OwnedStudentQuestion {
                request,
                lease,
                latest: view.clone(),
            },
        );
        Ok(view)
    }
}

impl Drop for StudentQuestionSubmissionPermit {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        let mut state = self
            .owner
            .state
            .lock()
            .expect("student question owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("student question submission reservation missing");
    }
}

fn reclaim_terminal_requests(requests: &mut HashMap<String, OwnedStudentQuestion>) {
    requests.retain(|_, request| request.latest.status.is_active());
}

fn valid_status_transition(
    current: &StudentQuestionJobView,
    next: &StudentQuestionJobView,
) -> bool {
    match current.status {
        StudentQuestionStatus::Queued => true,
        StudentQuestionStatus::Running => next.status != StudentQuestionStatus::Queued,
        StudentQuestionStatus::CancellationRequested => matches!(
            next.status,
            StudentQuestionStatus::CancellationRequested
                | StudentQuestionStatus::Complete
                | StudentQuestionStatus::EvidenceUnavailable
                | StudentQuestionStatus::Cancelled
                | StudentQuestionStatus::Failed
        ),
        StudentQuestionStatus::Complete
        | StudentQuestionStatus::EvidenceUnavailable
        | StudentQuestionStatus::Cancelled
        | StudentQuestionStatus::Failed => next == current,
    }
}

impl Default for StudentQuestionOwner {
    fn default() -> Self {
        Self::new()
    }
}

#[tauri::command]
pub(crate) async fn start_student_question(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, StudentQuestionOwner>,
    conversation_concept_id: String,
    expected_generation_sha256: String,
    topic: String,
) -> Result<StudentQuestionJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let request = StudentRequest::new(conversation_concept_id, expected_generation_sha256, topic)
        .map_err(|error| error.to_string())?;
    let lease = connector.student_connection_lease()?.ok_or_else(|| {
        "Learning questions require a connected organization server with Student enabled."
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
        .with_current_student_lease(&lease, || submission.commit(request, lease.clone(), view))
        .and_then(|result| result);
    match commit {
        Ok(committed) => Ok(committed),
        Err(error) => {
            if contain_unowned_submitted_question(lease.client(), &request_id)
                .await
                .is_err()
            {
                return Err(
                    "Learning-question request could not be contained after local ownership failed."
                        .into(),
                );
            }
            Err(error)
        }
    }
}

#[tauri::command]
pub(crate) async fn student_question_status(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, StudentQuestionOwner>,
    request_id: String,
) -> Result<StudentQuestionJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .status(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_student_lease(&owned.lease, || owner.update(&owned, view))?
}

#[tauri::command]
pub(crate) async fn cancel_student_question(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, StudentQuestionOwner>,
    request_id: String,
) -> Result<StudentQuestionJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .cancel(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_student_lease(&owned.lease, || owner.update(&owned, view))?
}

async fn contain_unowned_submitted_question(
    client: &StudentApiClient,
    request_id: &str,
) -> Result<(), String> {
    let deadline = Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT;
    let mut view = match client.cancel(request_id).await {
        Ok(view) => view,
        Err(_) => client
            .status(request_id)
            .await
            .map_err(|_| "accepted learning-question request could not be found".to_string())?,
    };
    while view.status.is_active() {
        if Instant::now() >= deadline {
            return Err("accepted learning-question request did not stop".into());
        }
        tokio::time::sleep(UNOWNED_REQUEST_POLL_INTERVAL).await;
        view = client
            .status(request_id)
            .await
            .map_err(|_| "accepted learning-question request status was lost".to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server_connector::{
        student::StudentQuestionStatus, student_connection_lease_for_test,
    };

    fn request() -> StudentRequest {
        StudentRequest::new(
            "meetings/job-1".into(),
            "a".repeat(64),
            "crash safety".into(),
        )
        .unwrap()
    }

    fn view(status: StudentQuestionStatus, reason: Option<&str>) -> StudentQuestionJobView {
        StudentQuestionJobView::for_test(
            format!("student-question-{}", "1".repeat(32)),
            status,
            reason.map(str::to_owned),
        )
    }

    #[test]
    fn owner_preserves_request_identity_and_monotonic_lifecycle() {
        let owner = StudentQuestionOwner::new();
        owner
            .insert_for_test(
                request(),
                student_connection_lease_for_test(),
                view(StudentQuestionStatus::Queued, None),
            )
            .unwrap();
        let owned = owner
            .request(&format!("student-question-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(&owned, view(StudentQuestionStatus::Running, None))
                .unwrap()
                .status,
            StudentQuestionStatus::Running
        );

        let running = owner.request(&owned.latest.request_id).unwrap();
        assert!(owner
            .update(&running, view(StudentQuestionStatus::Queued, None))
            .is_err());
    }

    #[test]
    fn terminal_owner_state_is_exact_and_reclaimable() {
        let owner = StudentQuestionOwner::new();
        owner
            .insert_for_test(
                request(),
                student_connection_lease_for_test(),
                view(StudentQuestionStatus::Cancelled, Some("client-cancelled")),
            )
            .unwrap();
        let owned = owner
            .request(&format!("student-question-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(
                    &owned,
                    view(StudentQuestionStatus::Cancelled, Some("client-cancelled")),
                )
                .unwrap(),
            owned.latest
        );
        assert!(owner
            .update(
                &owned,
                view(StudentQuestionStatus::Failed, Some("invalid-output")),
            )
            .is_err());
    }
}
