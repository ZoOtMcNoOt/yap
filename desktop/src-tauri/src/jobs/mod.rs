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

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct PublishedRemoteTranscriptCorrectionSource {
    pub(crate) source_revision_sha256: String,
    pub(crate) text: String,
    pub(crate) language_bcp47: String,
    pub(crate) start_ms: u64,
    pub(crate) end_ms: u64,
}

pub(crate) fn read_published_remote_transcript_correction_source(
    path: &std::path::Path,
) -> Result<PublishedRemoteTranscriptCorrectionSource, String> {
    read_published_remote_transcript_correction_source_from_dir(path, &remote_jobs_directory())
}

pub(crate) fn read_published_remote_transcript_correction_source_from_dir(
    path: &std::path::Path,
    spool_root: &std::path::Path,
) -> Result<PublishedRemoteTranscriptCorrectionSource, String> {
    let bundle = remote::read_published_remote_result_bundle(path, spool_root)?;
    let language_bcp47 = bundle
        .result
        .language
        .as_ref()
        .map(|language| language.language_bcp47.clone())
        .ok_or_else(|| "The published server transcript has no language identity.".to_string())?;
    let first = bundle.result.aligned_words.first().ok_or_else(|| {
        "The published server transcript has no finalized alignment timing.".to_string()
    })?;
    let last = bundle.result.aligned_words.last().ok_or_else(|| {
        "The published server transcript has no finalized alignment timing.".to_string()
    })?;
    let text = bundle.result.transcript.clone();
    Ok(PublishedRemoteTranscriptCorrectionSource {
        source_revision_sha256: bundle.result_sha256,
        text,
        language_bcp47,
        start_ms: first.start_ms,
        end_ms: last.end_ms,
    })
}

pub(crate) fn authorize_published_remote_transcript(
    path: &std::path::Path,
) -> Result<std::path::PathBuf, String> {
    remote::read_published_remote_result_bundle(path, &remote_jobs_directory())?;
    Ok(path.to_path_buf())
}
