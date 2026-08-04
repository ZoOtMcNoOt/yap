use crate::{
    jobs::{JobLedgerError, RecordingJobResources, RecordingJobView},
    media_protocol::MediaOwner,
    recording_access::{
        RecordingJobSourceAdmission, RecordingJobSourceError, ValidatedRecordingJobSource,
    },
};
use sha2::{Digest, Sha256};
#[cfg(test)]
use std::collections::VecDeque;
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
};
use tauri::{Emitter, Manager};
use tauri_plugin_dialog::DialogExt;

mod catalog;
mod imports;
pub(crate) mod language_confirmation;
mod language_label_corrections;
mod lifecycle;
mod native_import_dispatcher;
mod playback;
mod state;

use native_import_dispatcher::begin_native_import_selection;
pub(crate) use native_import_dispatcher::{
    enqueue_native_import, install_native_import_dispatcher,
};
#[cfg(test)]
use native_import_dispatcher::{
    native_import_channel, queue_native_import_batch, NativeImportSelectionGate,
};

const PENDING_JOB_LIFETIME_MS: u64 = 7 * 24 * 60 * 60 * 1_000;
const MAX_RECORDING_JOBS: usize = 200;
// Canonical WAV plus the compressed containers this build can decode into it.
const REMOTE_IMPORT_AUDIO_EXTENSIONS: &[&str] = &["wav", "mp3"];
static NEXT_JOB_NONCE: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct JobCommandError {
    pub code: String,
    pub message: String,
}

#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PublishedRemoteTranscriptCatalog {
    pub sessions: Vec<PublishedRemoteTranscriptSummary>,
    pub maintenance_warnings: Vec<String>,
}

#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PublishedRemoteTranscriptSummary {
    pub session_id: String,
    pub name: String,
    pub source_path: String,
    pub output_path: String,
    pub created_at_ms: u64,
    pub speaker_transcript_available: bool,
    pub(crate) result_summary: TranscriptResultSummary,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub warning: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PublishedSpeakerTranscript {
    pub session_id: String,
    pub source_result_sha256: String,
    pub turns: Vec<PublishedSpeakerTranscriptTurn>,
}

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PublishedSpeakerTranscriptTurn {
    pub turn_id: String,
    pub speaker_id: Option<String>,
    pub start_ms: u64,
    pub end_ms: u64,
    pub text: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub overlap_group_id: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) enum TranscriptLanguageStatus {
    Fixed,
    Dynamic,
    UnknownSegments,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) enum TranscriptTimingStatus {
    Available,
    Unavailable,
}

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct TranscriptResultSummary {
    pub(crate) language_bcp47: String,
    pub(crate) language_status: TranscriptLanguageStatus,
    pub(crate) timing_status: TranscriptTimingStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) active_language_correction_count: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) language_review_required_count: Option<u64>,
}

impl From<JobLedgerError> for JobCommandError {
    fn from(error: JobLedgerError) -> Self {
        Self {
            code: "JOB_LEDGER_ERROR".into(),
            message: error.to_string(),
        }
    }
}

#[doc(hidden)]
pub struct RecordingJobs {
    resources: Arc<RecordingJobResources>,
    playback: Mutex<HashMap<String, CachedPlayback>>,
    #[cfg(test)]
    projection_failures: Mutex<VecDeque<JobCommandError>>,
    registry_path: PathBuf,
    selection_registry_path: PathBuf,
}

struct CachedPlayback {
    source: ValidatedRecordingJobSource,
    playback_path: String,
}

#[tauri::command]
pub(crate) fn recording_jobs_snapshot(
    window: tauri::WebviewWindow,
    jobs: tauri::State<'_, RecordingJobs>,
    media: tauri::State<'_, MediaOwner>,
) -> Result<Vec<RecordingJobView>, JobCommandError> {
    ensure_main(&window)?;
    jobs.snapshot(&media, now_ms()?)
}

#[cfg(feature = "wdio")]
#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct WdioRemoteJobLifecycle {
    client_job_id: String,
    server_job_id: String,
    remote_status: String,
    asr_stage_state: Option<String>,
    cancellation_acknowledged_at_ms: Option<u64>,
}

#[cfg(feature = "wdio")]
#[tauri::command]
pub(crate) async fn wdio_recording_job_remote_lifecycle(
    window: tauri::WebviewWindow,
    jobs: tauri::State<'_, RecordingJobs>,
    connector: tauri::State<'_, crate::server_connector::ServerConnector>,
    job_id: String,
) -> Result<WdioRemoteJobLifecycle, JobCommandError> {
    ensure_main(&window)?;
    let prepared = jobs
        .ledger()
        .get_prepared_remote_job(&job_id)?
        .ok_or_else(|| command_error("JOB_NOT_FOUND", "Remote recording job was not found."))?;
    let server_job_id = prepared.server_job_id.clone().ok_or_else(|| {
        command_error(
            "REMOTE_JOB_NOT_BOUND",
            "Remote recording job has not been bound to the server.",
        )
    })?;
    let server_base_url = prepared.server_base_url.as_deref().ok_or_else(|| {
        command_error(
            "REMOTE_JOB_NOT_BOUND",
            "Remote recording job has not been bound to the server.",
        )
    })?;
    let client = connector
        .persisted_cleanup_client(server_base_url)
        .map_err(|message| command_error("SERVER_CONNECTION_UNAVAILABLE", message))?;
    let request = crate::server_connector::batch::CreateRecordingJobRequest::decode_persisted(
        &prepared.create_request_json,
    )
    .map_err(|error| command_error("REMOTE_JOB_INCOMPATIBLE", error.to_string()))?;
    let remote = client
        .status(&server_job_id)
        .await
        .map_err(|error| command_error("REMOTE_STATUS_UNAVAILABLE", error.to_string()))?;
    super::drain::validate_job_projection(
        &remote,
        &request,
        Some(&server_job_id),
        &[
            "server_processing",
            "complete",
            "partial",
            "failed",
            "cancelled",
        ],
    )
    .map_err(|error| command_error("REMOTE_STATUS_INCOMPATIBLE", error))?;
    let stages = client
        .stages(&server_job_id)
        .await
        .map_err(|error| command_error("REMOTE_STAGES_UNAVAILABLE", error.to_string()))?;
    let asr_stage_state = stages
        .stages
        .iter()
        .find(|stage| stage.stage == crate::server_connector::batch::ServerStageName::Asr)
        .map(|stage| match stage.state {
            crate::server_connector::batch::ServerStageState::Running => "running",
            crate::server_connector::batch::ServerStageState::Succeeded => "succeeded",
            crate::server_connector::batch::ServerStageState::Unavailable => "unavailable",
            crate::server_connector::batch::ServerStageState::Failed => "failed",
            crate::server_connector::batch::ServerStageState::Cancelled => "cancelled",
        })
        .map(str::to_owned);
    let cancellation_acknowledged_at_ms = jobs
        .ledger()
        .get_prepared_remote_job(&job_id)?
        .and_then(|current| current.server_cancellation_acknowledged_at_ms);
    Ok(WdioRemoteJobLifecycle {
        client_job_id: job_id,
        server_job_id,
        remote_status: remote.status,
        asr_stage_state,
        cancellation_acknowledged_at_ms,
    })
}

#[tauri::command]
pub(crate) async fn recording_jobs_pick_imports(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, crate::server_connector::ServerConnector>,
    language_mode: Option<crate::jobs::RecordingLanguageMode>,
    language_bcp47: Option<String>,
    catalog_revision: Option<String>,
) -> Result<Vec<RecordingJobView>, JobCommandError> {
    ensure_main(&window)?;
    let _selection = begin_native_import_selection(&app)?;
    #[cfg(feature = "wdio")]
    if let Some(paths) = wdio_picker_override()? {
        return import_picked_paths(
            &app,
            connector.inner(),
            paths,
            language_mode,
            language_bcp47,
            catalog_revision,
        )
        .await;
    }
    let picker_app = app.clone();
    let selected = tauri::async_runtime::spawn_blocking(move || {
        picker_app
            .dialog()
            .file()
            .set_title("Choose recordings")
            .add_filter("Audio recordings", REMOTE_IMPORT_AUDIO_EXTENSIONS)
            .blocking_pick_files()
    })
    .await
    .map_err(|error| command_error("PICKER_UNAVAILABLE", error.to_string()))?;
    let Some(selected) = selected else {
        return Ok(Vec::new());
    };
    let paths = selected
        .into_iter()
        .map(|path| {
            path.into_path().map_err(|error| {
                command_error(
                    "PICKER_PATH_UNAVAILABLE",
                    format!("The selected recording path is unavailable: {error}"),
                )
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    import_picked_paths(
        &app,
        connector.inner(),
        paths,
        language_mode,
        language_bcp47,
        catalog_revision,
    )
    .await
}

async fn import_picked_paths(
    app: &tauri::AppHandle,
    connector: &crate::server_connector::ServerConnector,
    paths: Vec<PathBuf>,
    language_mode: Option<crate::jobs::RecordingLanguageMode>,
    language_bcp47: Option<String>,
    catalog_revision: Option<String>,
) -> Result<Vec<RecordingJobView>, JobCommandError> {
    let jobs = app.state::<RecordingJobs>();
    let media = app.state::<MediaOwner>();
    let prepared = jobs.prepare_imports(paths)?;
    let now_ms = now_ms()?;
    let committed =
        crate::server_connector::with_current_asr_capabilities(app, connector, |current| {
            crate::language_preferences::with_recording_language_decision(
                language_mode,
                language_bcp47.as_deref(),
                catalog_revision.as_deref(),
                current.catalog(),
                |decision| {
                    jobs.commit_prepared_imports(prepared, now_ms, decision, current.binding())
                },
            )
        })
        .await
        .map_err(|message| command_error("LANGUAGE_CAPABILITIES_UNAVAILABLE", message))?
        .ok_or_else(|| {
            command_error(
                "LANGUAGE_CAPABILITIES_UNAVAILABLE",
                "Current ASR language capabilities are unavailable.",
            )
        })?;
    let committed = committed.map_err(|error| command_error(error.code(), error.to_string()))?;
    notify_after_durable_import_commit(
        committed,
        |committed| jobs.project_committed_imports(&media, committed, now_ms),
        || emit_jobs_changed(app),
    )
}

#[cfg(feature = "wdio")]
fn wdio_picker_override() -> Result<Option<Vec<PathBuf>>, JobCommandError> {
    let Some(path) = std::env::var_os("YAP_WDIO_PICKER_PATH") else {
        return Ok(None);
    };
    let run_root = std::env::var_os("YAP_WDIO_RUN_ROOT").ok_or_else(|| {
        command_error(
            "WDIO_PICKER_SCOPE_MISSING",
            "The WDIO picker override requires an isolated run root.",
        )
    })?;
    let run_root = PathBuf::from(run_root)
        .canonicalize()
        .map_err(|error| command_error("WDIO_PICKER_SCOPE_INVALID", error.to_string()))?;
    let path = PathBuf::from(path)
        .canonicalize()
        .map_err(|error| command_error("WDIO_PICKER_PATH_INVALID", error.to_string()))?;
    if !path.starts_with(&run_root) {
        return Err(command_error(
            "WDIO_PICKER_PATH_OUTSIDE_RUN",
            "The WDIO picker path is outside the isolated run root.",
        ));
    }
    Ok(Some(vec![path]))
}

#[tauri::command]
pub(crate) fn recording_job_cancel(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    jobs: tauri::State<'_, RecordingJobs>,
    media: tauri::State<'_, MediaOwner>,
    job_id: String,
) -> Result<RecordingJobView, JobCommandError> {
    ensure_main(&window)?;
    mutate_then_notify(
        || jobs.cancel(&media, &job_id, now_ms()?, || {}),
        || emit_jobs_changed(&app),
    )
}

#[tauri::command]
pub(crate) fn recording_job_dismiss(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    jobs: tauri::State<'_, RecordingJobs>,
    media: tauri::State<'_, MediaOwner>,
    job_id: String,
) -> Result<RecordingJobView, JobCommandError> {
    ensure_main(&window)?;
    mutate_then_notify(
        || jobs.dismiss(&media, &job_id, now_ms()?, || {}),
        || emit_jobs_changed(&app),
    )
}

#[tauri::command]
pub(crate) fn recording_job_retry(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    jobs: tauri::State<'_, RecordingJobs>,
    media: tauri::State<'_, MediaOwner>,
    job_id: String,
) -> Result<RecordingJobView, JobCommandError> {
    ensure_main(&window)?;
    mutate_then_notify(
        || jobs.retry(&media, &job_id, now_ms()?, || {}),
        || emit_jobs_changed(&app),
    )
}

fn ensure_main(window: &tauri::WebviewWindow) -> Result<(), JobCommandError> {
    crate::authorization::ensure_main(window)
        .map_err(|message| command_error("UNAUTHORIZED_WINDOW", message))
}

fn now_ms() -> Result<u64, JobCommandError> {
    crate::live::recordings::unix_millis_now()
        .map_err(|message| command_error("CLOCK_UNAVAILABLE", message))
}

pub(crate) fn emit_jobs_changed(app: &tauri::AppHandle) {
    if let Err(error) = app.emit_to(
        crate::authorization::MAIN_WINDOW_LABEL,
        "recording-jobs-changed",
        (),
    ) {
        crate::diagnostics::log(&format!(
            "recording jobs event failed after commit: {error}"
        ));
    }
}

pub(crate) async fn import_native_paths(
    app: &tauri::AppHandle,
    paths: Vec<PathBuf>,
) -> Result<Vec<RecordingJobView>, JobCommandError> {
    let connector = app.state::<crate::server_connector::ServerConnector>();
    import_picked_paths(app, connector.inner(), paths, None, None, None).await
}

pub(crate) fn emit_native_import_error(app: &tauri::AppHandle, error: &JobCommandError) {
    let _ = app.emit_to(
        crate::authorization::MAIN_WINDOW_LABEL,
        "recording-jobs-import-error",
        &error.message,
    );
}

enum RetryKind {
    Accepted,
    Retry,
    Unchanged,
}

fn project_with_admission(
    record: crate::jobs::RecordingJobRecord,
    admission: RecordingJobSourceAdmission,
) -> RecordingJobView {
    let mut view = RecordingJobView::from_record(&record);
    view.source_path = Some(admission.canonical_path.display().to_string());
    view.playback_path = Some(admission.playback_path);
    view
}

fn source_error(error: RecordingJobSourceError) -> JobCommandError {
    match error {
        RecordingJobSourceError::Missing => {
            command_error("SOURCE_MISSING", "Recording source no longer exists.")
        }
        RecordingJobSourceError::Unsafe(message) => command_error("SOURCE_UNSAFE", message),
    }
}

fn mint_job_id(path: &Path, now_ms: u64) -> String {
    let nonce = NEXT_JOB_NONCE.fetch_add(1, Ordering::Relaxed);
    let mut hash = Sha256::new();
    hash.update(path.to_string_lossy().as_bytes());
    hash.update(now_ms.to_le_bytes());
    hash.update(nonce.to_le_bytes());
    format!("job-{}", hex_prefix(&hash.finalize(), 24))
}

fn hex_prefix(bytes: &[u8], digits: usize) -> String {
    bytes
        .iter()
        .flat_map(|byte| [byte >> 4, byte & 0x0f])
        .take(digits)
        .map(|nibble| char::from_digit(u32::from(nibble), 16).expect("hex nibble"))
        .collect()
}

fn command_error(code: impl Into<String>, message: impl Into<String>) -> JobCommandError {
    JobCommandError {
        code: code.into(),
        message: message.into(),
    }
}

fn renewed_expiry(now_ms: u64) -> Result<u64, JobCommandError> {
    now_ms.checked_add(PENDING_JOB_LIFETIME_MS).ok_or_else(|| {
        command_error(
            "JOB_TIME_OUT_OF_RANGE",
            "Recording job expiry is outside the supported time range.",
        )
    })
}

fn log_registry_cleanup_failure(action: &str, error: &str) {
    crate::diagnostics::log(&format!(
        "recording job playback registry {action} failed; snapshot reconciliation will retry: {error}"
    ));
}

fn mutate_then_notify<T, E>(
    mutation: impl FnOnce() -> Result<T, E>,
    notify: impl FnOnce(),
) -> Result<T, E> {
    let result = mutation();
    notify();
    result
}

fn notify_after_durable_import_commit<C, T, E>(
    committed: Result<C, E>,
    projection: impl FnOnce(C) -> Result<T, E>,
    notify: impl FnOnce(),
) -> Result<T, E> {
    let committed = committed?;
    let result = projection(committed);
    notify();
    result
}

#[cfg(test)]
mod tests;
