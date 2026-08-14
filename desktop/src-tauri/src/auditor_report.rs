use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use crate::server_connector::{
    auditor::{AuditorApiClient, AuditorReportJobView, AuditorReportStatus, AuditorRequest},
    AuditorConnectionLease, ServerConnector,
};

const MAXIMUM_OWNED_REQUESTS: usize = 64;
const UNOWNED_REQUEST_CONTAINMENT_TIMEOUT: Duration = Duration::from_secs(5);
const UNOWNED_REQUEST_POLL_INTERVAL: Duration = Duration::from_millis(25);

#[derive(Clone)]
struct OwnedAuditorReport {
    request: AuditorRequest,
    lease: AuditorConnectionLease,
    latest: AuditorReportJobView,
}

#[derive(Clone)]
pub(crate) struct AuditorReportOwner {
    state: Arc<Mutex<AuditorReportOwnerState>>,
}

#[derive(Default)]
struct AuditorReportOwnerState {
    requests: HashMap<String, OwnedAuditorReport>,
    submissions: usize,
}

struct AuditorReportSubmissionPermit {
    owner: AuditorReportOwner,
    active: bool,
}

impl AuditorReportOwner {
    pub(crate) fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(AuditorReportOwnerState::default())),
        }
    }

    fn reserve_submission(&self) -> Result<AuditorReportSubmissionPermit, String> {
        let mut state = self.state.lock().expect("auditor report owner poisoned");
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            reclaim_terminal_requests(&mut state.requests);
        }
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            return Err("Too many audit-report requests are still active on this device.".into());
        }
        state.submissions += 1;
        Ok(AuditorReportSubmissionPermit {
            owner: self.clone(),
            active: true,
        })
    }

    fn request(&self, request_id: &str) -> Result<OwnedAuditorReport, String> {
        self.state
            .lock()
            .expect("auditor report owner poisoned")
            .requests
            .get(request_id)
            .cloned()
            .ok_or_else(|| "This device does not own that audit-report request.".to_string())
    }

    fn update(
        &self,
        owned: &OwnedAuditorReport,
        view: AuditorReportJobView,
    ) -> Result<AuditorReportJobView, String> {
        if view.request_id != owned.latest.request_id || !view.matches_request(&owned.request) {
            return Err("The audit-report response changed request identity.".into());
        }
        let mut state = self.state.lock().expect("auditor report owner poisoned");
        let current = state
            .requests
            .get_mut(&view.request_id)
            .ok_or_else(|| "This device no longer owns that audit-report request.".to_string())?;
        if current.request != owned.request || current.latest.request_id != owned.latest.request_id
        {
            return Err("The audit-report owner changed before commit.".into());
        }
        if current.latest != owned.latest {
            return Ok(current.latest.clone());
        }
        if !valid_status_transition(&current.latest, &view) {
            return Err("The audit-report response regressed its lifecycle.".into());
        }
        current.latest = view.clone();
        Ok(view)
    }

    pub(crate) async fn cancel_active_requests(&self) -> Result<usize, String> {
        let active = self
            .state
            .lock()
            .expect("auditor report owner poisoned")
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
                "{failures} of {total} active audit-report requests could not be cancelled"
            ))
        }
    }

    #[cfg(test)]
    fn insert_for_test(
        &self,
        request: AuditorRequest,
        lease: AuditorConnectionLease,
        view: AuditorReportJobView,
    ) -> Result<AuditorReportJobView, String> {
        self.reserve_submission()?.commit(request, lease, view)
    }
}

impl AuditorReportSubmissionPermit {
    fn commit(
        mut self,
        request: AuditorRequest,
        lease: AuditorConnectionLease,
        view: AuditorReportJobView,
    ) -> Result<AuditorReportJobView, String> {
        let mut state = self
            .owner
            .state
            .lock()
            .expect("auditor report owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("auditor report submission reservation missing");
        self.active = false;
        if state.requests.contains_key(&view.request_id) {
            return Err("The audit-report identity was reused.".into());
        }
        if !view.matches_request(&request) {
            return Err("The audit-report response changed request identity.".into());
        }
        state.requests.insert(
            view.request_id.clone(),
            OwnedAuditorReport {
                request,
                lease,
                latest: view.clone(),
            },
        );
        Ok(view)
    }
}

impl Drop for AuditorReportSubmissionPermit {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        let mut state = self
            .owner
            .state
            .lock()
            .expect("auditor report owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("auditor report submission reservation missing");
    }
}

fn reclaim_terminal_requests(requests: &mut HashMap<String, OwnedAuditorReport>) {
    requests.retain(|_, request| request.latest.status.is_active());
}

fn valid_status_transition(current: &AuditorReportJobView, next: &AuditorReportJobView) -> bool {
    match current.status {
        AuditorReportStatus::Queued => true,
        AuditorReportStatus::Running => next.status != AuditorReportStatus::Queued,
        AuditorReportStatus::CancellationRequested => matches!(
            next.status,
            AuditorReportStatus::CancellationRequested
                | AuditorReportStatus::Complete
                | AuditorReportStatus::EvidenceUnavailable
                | AuditorReportStatus::Cancelled
                | AuditorReportStatus::Failed
        ),
        AuditorReportStatus::Complete
        | AuditorReportStatus::EvidenceUnavailable
        | AuditorReportStatus::Cancelled
        | AuditorReportStatus::Failed => next == current,
    }
}

impl Default for AuditorReportOwner {
    fn default() -> Self {
        Self::new()
    }
}

#[tauri::command]
pub(crate) async fn start_auditor_report(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, AuditorReportOwner>,
    focus: String,
    maximum_findings: u8,
    expected_generation_sha256: Option<String>,
) -> Result<AuditorReportJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let request = AuditorRequest::new(focus, maximum_findings, expected_generation_sha256)
        .map_err(|error| error.to_string())?;
    let lease = connector.auditor_connection_lease()?.ok_or_else(|| {
        "Audit reports require a connected organization server with Auditor enabled.".to_string()
    })?;
    let submission = owner.reserve_submission()?;
    let view = lease
        .client()
        .submit(&request)
        .await
        .map_err(|error| error.to_string())?;
    let request_id = view.request_id.clone();
    let commit = connector
        .with_current_auditor_lease(&lease, || submission.commit(request, lease.clone(), view))
        .and_then(|result| result);
    match commit {
        Ok(committed) => Ok(committed),
        Err(error) => {
            if contain_unowned_submitted_report(lease.client(), &request_id)
                .await
                .is_err()
            {
                return Err(
                    "Audit-report request could not be contained after local ownership failed."
                        .into(),
                );
            }
            Err(error)
        }
    }
}

#[tauri::command]
pub(crate) async fn auditor_report_status(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, AuditorReportOwner>,
    request_id: String,
) -> Result<AuditorReportJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .status(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_auditor_lease(&owned.lease, || owner.update(&owned, view))?
}

#[tauri::command]
pub(crate) async fn cancel_auditor_report(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, AuditorReportOwner>,
    request_id: String,
) -> Result<AuditorReportJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .cancel(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector.with_current_auditor_lease(&owned.lease, || owner.update(&owned, view))?
}

async fn contain_unowned_submitted_report(
    client: &AuditorApiClient,
    request_id: &str,
) -> Result<(), String> {
    let deadline = Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT;
    let mut view = match client.cancel(request_id).await {
        Ok(view) => view,
        Err(_) => client
            .status(request_id)
            .await
            .map_err(|_| "accepted audit-report request could not be found".to_string())?,
    };
    while view.status.is_active() {
        if Instant::now() >= deadline {
            return Err("accepted audit-report request did not stop".into());
        }
        tokio::time::sleep(UNOWNED_REQUEST_POLL_INTERVAL).await;
        view = client
            .status(request_id)
            .await
            .map_err(|_| "accepted audit-report request status was lost".to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server_connector::{
        auditor::AuditorReportStatus, auditor_connection_lease_for_test,
    };

    fn request() -> AuditorRequest {
        AuditorRequest::new("Helios release limit".into(), 3, Some("a".repeat(64))).unwrap()
    }

    fn view(status: AuditorReportStatus, reason: Option<&str>) -> AuditorReportJobView {
        AuditorReportJobView::for_test(
            format!("auditor-report-{}", "1".repeat(32)),
            status,
            reason.map(str::to_owned),
        )
    }

    #[test]
    fn owner_preserves_request_identity_and_monotonic_lifecycle() {
        let owner = AuditorReportOwner::new();
        owner
            .insert_for_test(
                request(),
                auditor_connection_lease_for_test(),
                view(AuditorReportStatus::Queued, None),
            )
            .unwrap();
        let owned = owner
            .request(&format!("auditor-report-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(&owned, view(AuditorReportStatus::Running, None))
                .unwrap()
                .status,
            AuditorReportStatus::Running
        );
        let running = owner.request(&owned.latest.request_id).unwrap();
        assert!(owner
            .update(&running, view(AuditorReportStatus::Queued, None))
            .is_err());
    }

    #[test]
    fn terminal_owner_state_is_exact_and_reclaimable() {
        let owner = AuditorReportOwner::new();
        owner
            .insert_for_test(
                request(),
                auditor_connection_lease_for_test(),
                view(AuditorReportStatus::Cancelled, Some("client-cancelled")),
            )
            .unwrap();
        let owned = owner
            .request(&format!("auditor-report-{}", "1".repeat(32)))
            .unwrap();
        assert_eq!(
            owner
                .update(
                    &owned,
                    view(AuditorReportStatus::Cancelled, Some("client-cancelled")),
                )
                .unwrap(),
            owned.latest
        );
        assert!(owner
            .update(
                &owned,
                view(AuditorReportStatus::Failed, Some("invalid-output")),
            )
            .is_err());
    }
}
