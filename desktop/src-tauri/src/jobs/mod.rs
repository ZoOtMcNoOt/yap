pub mod commands;
mod drain;
mod language_preflight;
mod ledger;
mod model;
mod remote;
mod resources;
mod schema;

pub use ledger::JobLedger;
pub(crate) use ledger::{LidPreflightDispatchFailure, LidPreflightDispatchStart};
pub use model::{
    AsrCatalogBinding, ClientPreflightArtifactRecord, ClientStageAttemptRecord, ClientStageName,
    ClientStageState, DetachedRemoteCancellationRecord, JobChunkRecord, JobLedgerError,
    NewClientPreflightArtifact, NewJobChunk, NewPreparedRemoteJob, NewRecordingJob,
    PreparedRemoteJobRecord, RecordingJobRecord, RecordingJobStatus, RecordingJobView,
    RecordingLanguageDecision, RecordingLanguageDisposition, RecordingLanguageMode,
    RecordingLanguageReview, RecordingLanguageReviewKind, RecordingRoute, SessionMode,
    SessionOrigin, SourceOwnership,
};

pub(crate) use drain::RemoteJobDrain;
pub(crate) use model::{ClientStageFinish, ClientStageStart};
pub(crate) use remote::LanguageLabelReview;
pub(crate) use resources::RecordingJobResources;

pub(crate) const REMOTE_STAGE_RETRY_REQUESTED: &str = "REMOTE_STAGE_RETRY_REQUESTED";

pub(crate) fn start_remote_job_drain(
    app: &tauri::AppHandle,
    lifecycle: &crate::runtime::DesktopLifecycle,
) -> std::io::Result<()> {
    drain::start(app, lifecycle)
}

fn remote_jobs_directory() -> std::path::PathBuf {
    crate::paths::app_data_dir().join("remote-jobs")
}

pub(crate) fn read_published_remote_transcript_text(
    path: &std::path::Path,
) -> Result<String, String> {
    remote::read_published_remote_result_bundle(path, &remote_jobs_directory())
        .map(|bundle| bundle.text)
}

pub(crate) fn authorize_published_remote_transcript(
    path: &std::path::Path,
) -> Result<std::path::PathBuf, String> {
    remote::read_published_remote_result_bundle(path, &remote_jobs_directory())?;
    Ok(path.to_path_buf())
}
