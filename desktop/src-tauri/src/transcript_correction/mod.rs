use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use crate::server_connector::{
    transcript_correction::{
        TranscriptCorrectionApiClient, TranscriptCorrectionJobView, TranscriptCorrectionRequest,
    },
    ServerConnector, TranscriptCorrectionConnectionLease,
};

mod revision;
mod source;

#[cfg(test)]
mod tests;

pub(crate) use revision::live_transcript_correction_artifacts_for_deletion;
#[cfg(test)]
pub(crate) use revision::publish_transcript_correction_revision_for_test;
pub(crate) use revision::PublishedTranscriptCorrection;
pub(crate) use source::{
    read_trusted_transcript_correction_source, TranscriptCorrectionSourceKind,
    TrustedTranscriptCorrectionSource,
};

const MAXIMUM_OWNED_REQUESTS: usize = 64;
const SOURCE_READ_TIMEOUT: Duration = Duration::from_secs(8);
const UNOWNED_REQUEST_CONTAINMENT_TIMEOUT: Duration = Duration::from_secs(5);
const UNOWNED_REQUEST_POLL_INTERVAL: Duration = Duration::from_millis(25);

#[derive(Clone)]
struct OwnedTranscriptCorrection {
    source: TrustedTranscriptCorrectionSource,
    lease: TranscriptCorrectionConnectionLease,
    latest: TranscriptCorrectionJobView,
    published: Option<PublishedTranscriptCorrection>,
}

#[derive(Clone)]
pub(crate) struct TranscriptCorrectionOwner {
    state: Arc<Mutex<TranscriptCorrectionOwnerState>>,
}

#[derive(Default)]
struct TranscriptCorrectionOwnerState {
    requests: HashMap<String, OwnedTranscriptCorrection>,
    submissions: usize,
}

struct TranscriptCorrectionSubmissionPermit {
    owner: TranscriptCorrectionOwner,
    active: bool,
}

impl TranscriptCorrectionOwner {
    pub(crate) fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(TranscriptCorrectionOwnerState::default())),
        }
    }

    fn reserve_submission(&self) -> Result<TranscriptCorrectionSubmissionPermit, String> {
        let mut state = self.state.lock().expect("correction owner poisoned");
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            reclaim_terminal_requests(&mut state.requests);
        }
        if state.requests.len() + state.submissions >= MAXIMUM_OWNED_REQUESTS {
            return Err("Too many transcript corrections are still active on this device.".into());
        }
        state.submissions += 1;
        Ok(TranscriptCorrectionSubmissionPermit {
            owner: self.clone(),
            active: true,
        })
    }

    #[cfg(test)]
    fn insert_for_test(
        &self,
        source: TrustedTranscriptCorrectionSource,
        lease: TranscriptCorrectionConnectionLease,
        view: TranscriptCorrectionJobView,
    ) -> Result<TranscriptCorrectionJobView, String> {
        self.reserve_submission()?.commit(source, lease, view)
    }

    fn request(&self, request_id: &str) -> Result<OwnedTranscriptCorrection, String> {
        self.state
            .lock()
            .expect("correction owner poisoned")
            .requests
            .get(request_id)
            .cloned()
            .ok_or_else(|| "This device does not own that transcript correction.".to_string())
    }

    fn update(
        &self,
        owned: &OwnedTranscriptCorrection,
        view: TranscriptCorrectionJobView,
    ) -> Result<TranscriptCorrectionJobView, String> {
        if view.request_id != owned.latest.request_id
            || view.source_revision_sha256 != owned.source.source_revision_sha256
            || view.source_sha256 != owned.latest.source_sha256
            || view.terminology_snapshot_sha256 != owned.latest.terminology_snapshot_sha256
        {
            return Err("The transcript correction response changed source identity.".into());
        }
        let mut state = self.state.lock().expect("correction owner poisoned");
        let current = state
            .requests
            .get_mut(&view.request_id)
            .ok_or_else(|| "This device no longer owns that transcript correction.".to_string())?;
        if current.source != owned.source || current.latest.request_id != owned.latest.request_id {
            return Err("The transcript correction owner changed before commit.".into());
        }
        if current.latest != owned.latest {
            return Ok(current.latest.clone());
        }
        if !valid_status_transition(&current.latest, &view) {
            return Err("The transcript correction response regressed its lifecycle.".into());
        }
        current.latest = view.clone();
        Ok(view)
    }

    fn publish(
        &self,
        owned: &OwnedTranscriptCorrection,
    ) -> Result<PublishedTranscriptCorrection, String> {
        if let Some(published) = owned.published.clone() {
            return Ok(published);
        }
        if owned.latest.status
            != crate::server_connector::transcript_correction::TranscriptCorrectionStatus::Complete
            || !owned.latest.applied
        {
            return Err("Only a completed, source-changing correction can be saved.".into());
        }
        let corrected_text = owned
            .latest
            .corrected_text
            .as_deref()
            .ok_or_else(|| "The completed transcript correction has no text.".to_string())?;
        let published = revision::publish_transcript_correction_revision(
            &owned.source,
            &owned.latest.request_id,
            &owned.latest.terminology_snapshot_sha256,
            corrected_text,
        )?;
        let mut state = self.state.lock().expect("correction owner poisoned");
        let current = state
            .requests
            .get_mut(&owned.latest.request_id)
            .ok_or_else(|| "This device no longer owns that transcript correction.".to_string())?;
        if current.source != owned.source || current.latest != owned.latest {
            return Err("The transcript correction changed before publication commit.".into());
        }
        current.published = Some(published.clone());
        Ok(published)
    }

    pub(crate) async fn cancel_active_requests(&self) -> Result<usize, String> {
        let active = self
            .state
            .lock()
            .expect("correction owner poisoned")
            .requests
            .values()
            .filter(|request| correction_is_active(&request.latest))
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
                "{failures} of {total} active transcript corrections could not be cancelled"
            ))
        }
    }

    #[cfg(test)]
    fn active_request_count(&self) -> usize {
        self.state
            .lock()
            .expect("correction owner poisoned")
            .requests
            .values()
            .filter(|request| correction_is_active(&request.latest))
            .count()
    }
}

impl TranscriptCorrectionSubmissionPermit {
    fn commit(
        mut self,
        source: TrustedTranscriptCorrectionSource,
        lease: TranscriptCorrectionConnectionLease,
        view: TranscriptCorrectionJobView,
    ) -> Result<TranscriptCorrectionJobView, String> {
        let mut state = self.owner.state.lock().expect("correction owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("correction submission reservation missing");
        self.active = false;
        if state.requests.contains_key(&view.request_id) {
            return Err("The transcript correction request identity was reused.".into());
        }
        state.requests.insert(
            view.request_id.clone(),
            OwnedTranscriptCorrection {
                source,
                lease,
                latest: view.clone(),
                published: None,
            },
        );
        Ok(view)
    }
}

impl Drop for TranscriptCorrectionSubmissionPermit {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        let mut state = self.owner.state.lock().expect("correction owner poisoned");
        state.submissions = state
            .submissions
            .checked_sub(1)
            .expect("correction submission reservation missing");
    }
}

fn reclaim_terminal_requests(requests: &mut HashMap<String, OwnedTranscriptCorrection>) {
    requests.retain(|_, request| {
        correction_is_active(&request.latest)
            || (request.latest.status
                == crate::server_connector::transcript_correction::TranscriptCorrectionStatus::Complete
                && request.latest.applied
                && request.published.is_none())
    });
}

fn correction_is_active(view: &TranscriptCorrectionJobView) -> bool {
    use crate::server_connector::transcript_correction::TranscriptCorrectionStatus;
    matches!(
        view.status,
        TranscriptCorrectionStatus::Queued
            | TranscriptCorrectionStatus::Running
            | TranscriptCorrectionStatus::CancellationRequested
    )
}

fn valid_status_transition(
    current: &TranscriptCorrectionJobView,
    next: &TranscriptCorrectionJobView,
) -> bool {
    use crate::server_connector::transcript_correction::TranscriptCorrectionStatus;
    match current.status {
        TranscriptCorrectionStatus::Queued => true,
        TranscriptCorrectionStatus::Running => next.status != TranscriptCorrectionStatus::Queued,
        TranscriptCorrectionStatus::CancellationRequested => matches!(
            next.status,
            TranscriptCorrectionStatus::CancellationRequested
                | TranscriptCorrectionStatus::Cancelled
                | TranscriptCorrectionStatus::Complete
                | TranscriptCorrectionStatus::Failed
        ),
        TranscriptCorrectionStatus::Cancelled
        | TranscriptCorrectionStatus::Complete
        | TranscriptCorrectionStatus::Failed => next == current,
    }
}

impl Default for TranscriptCorrectionOwner {
    fn default() -> Self {
        Self::new()
    }
}

#[tauri::command]
pub(crate) async fn start_transcript_correction(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, TranscriptCorrectionOwner>,
    output_path: String,
) -> Result<TranscriptCorrectionJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let source = read_source(PathBuf::from(output_path)).await?;
    let request = TranscriptCorrectionRequest::from_finalized_segments(
        source.source_revision_sha256.clone(),
        source.segments.clone(),
    )
    .map_err(|error| error.to_string())?;
    let lease = connector
        .transcript_correction_connection_lease()?
        .ok_or_else(|| {
            "Transcript correction requires a connected organization server with the correction capability."
                .to_string()
        })?;
    let submission = owner.reserve_submission()?;
    let view = lease
        .client()
        .submit(&request)
        .await
        .map_err(|error| error.to_string())?;
    let request_id = view.request_id.clone();
    let commit = if view.source_revision_sha256 != request.source_revision_sha256()
        || view.source_sha256 != request.source_sha256()
    {
        Err("The transcript correction response changed source identity.".to_string())
    } else {
        connector
            .with_current_transcript_correction_lease(&lease, || {
                submission.commit(source, lease.clone(), view)
            })
            .and_then(|result| result)
    };
    match commit {
        Ok(committed) => Ok(committed),
        Err(error) => {
            if contain_unowned_submitted_correction(lease.client(), &request_id)
                .await
                .is_err()
            {
                return Err(
                    "Transcript correction could not be contained after local ownership failed."
                        .into(),
                );
            }
            Err(error)
        }
    }
}

#[tauri::command]
pub(crate) async fn transcript_correction_status(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, TranscriptCorrectionOwner>,
    request_id: String,
) -> Result<TranscriptCorrectionJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .status(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector
        .with_current_transcript_correction_lease(&owned.lease, || owner.update(&owned, view))?
}

#[tauri::command]
pub(crate) async fn cancel_transcript_correction(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    owner: tauri::State<'_, TranscriptCorrectionOwner>,
    request_id: String,
) -> Result<TranscriptCorrectionJobView, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let view = owned
        .lease
        .client()
        .cancel(&request_id)
        .await
        .map_err(|error| error.to_string())?;
    connector
        .with_current_transcript_correction_lease(&owned.lease, || owner.update(&owned, view))?
}

#[tauri::command]
pub(crate) async fn publish_transcript_correction(
    window: tauri::WebviewWindow,
    owner: tauri::State<'_, TranscriptCorrectionOwner>,
    request_id: String,
) -> Result<PublishedTranscriptCorrection, String> {
    crate::authorization::ensure_main(&window)?;
    let owned = owner.request(&request_id)?;
    let owner = owner.inner().clone();
    let task = tauri::async_runtime::spawn_blocking(move || owner.publish(&owned));
    match task.await {
        Ok(result) => result,
        Err(error) => Err(format!(
            "Transcript correction publication worker failed: {error}"
        )),
    }
}

async fn contain_unowned_submitted_correction(
    client: &TranscriptCorrectionApiClient,
    request_id: &str,
) -> Result<(), String> {
    let deadline = Instant::now() + UNOWNED_REQUEST_CONTAINMENT_TIMEOUT;
    let mut view = match client.cancel(request_id).await {
        Ok(view) => view,
        Err(_) => client
            .status(request_id)
            .await
            .map_err(|_| "accepted transcript correction could not be found".to_string())?,
    };
    while correction_is_active(&view) {
        if Instant::now() >= deadline {
            return Err("accepted transcript correction did not stop".into());
        }
        tokio::time::sleep(UNOWNED_REQUEST_POLL_INTERVAL).await;
        view = client
            .status(request_id)
            .await
            .map_err(|_| "accepted transcript correction status was lost".to_string())?;
    }
    Ok(())
}

async fn read_source(path: PathBuf) -> Result<TrustedTranscriptCorrectionSource, String> {
    let task = tauri::async_runtime::spawn_blocking(move || {
        read_trusted_transcript_correction_source(&path)
    });
    match tokio::time::timeout(SOURCE_READ_TIMEOUT, task).await {
        Ok(Ok(result)) => result,
        Ok(Err(error)) => Err(format!(
            "Transcript correction source worker failed: {error}"
        )),
        Err(_) => Err("Transcript correction source read timed out.".into()),
    }
}
