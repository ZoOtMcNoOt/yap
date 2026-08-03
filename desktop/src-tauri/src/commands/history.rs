//! Owns the native transcript catalog and its durable visibility policy.

mod catalog;
mod visibility;

use std::{collections::HashSet, sync::Mutex};
use tauri::Manager;

use crate::jobs::{
    commands::{
        emit_jobs_changed, JobCommandError, PublishedSpeakerTranscript, RecordingJobs,
        TranscriptResultSummary,
    },
    LanguageLabelReview,
};
use catalog::{collect_history_catalog, project_history_catalog, resolve_current_native_identity};
use visibility::HistoryVisibility;

const RECOVERY_WINDOW_MS: u64 = 24 * 60 * 60 * 1_000;
const MAX_HISTORY_SESSIONS: usize = 500;
const MAX_HISTORY_PATH_CHARS: usize = 32_768;

#[derive(
    Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, serde::Deserialize, serde::Serialize,
)]
#[serde(rename_all = "lowercase")]
pub(crate) enum HistoryOrigin {
    Live,
    Remote,
}

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct HistoryCatalogSession {
    capture_commit_path: Option<String>,
    created_at_ms: u64,
    name: String,
    origin: HistoryOrigin,
    output_path: String,
    recovery_state: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    result_summary: Option<TranscriptResultSummary>,
    speaker_transcript_available: bool,
    session_id: String,
    source_path: String,
    warning: Option<String>,
}

impl HistoryCatalogSession {
    fn identity(&self) -> NativeHistoryIdentity {
        NativeHistoryIdentity {
            origin: self.origin,
            session_id: self.session_id.clone(),
            output_path: self.output_path.clone(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct NativeHistoryIdentity {
    origin: HistoryOrigin,
    session_id: String,
    output_path: String,
}

#[derive(Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct HistoryCatalog {
    maintenance_warnings: Vec<String>,
    sessions: Vec<HistoryCatalogSession>,
}

#[derive(Default)]
struct SpeakerDetailLoadState {
    current_identity: Option<NativeHistoryIdentity>,
    generation: u64,
}

#[derive(Default)]
struct SpeakerDetailLoadCoordinator {
    state: Mutex<SpeakerDetailLoadState>,
}

impl SpeakerDetailLoadCoordinator {
    fn begin(&self, identity: &NativeHistoryIdentity) -> Result<u64, JobCommandError> {
        let mut state = self.state.lock().map_err(|_| {
            speaker_transcript_load_error("Speaker transcript load coordination is unavailable.")
        })?;
        if state.current_identity.as_ref() == Some(identity) {
            return Ok(state.generation);
        }
        state.generation = state.generation.checked_add(1).ok_or_else(|| {
            speaker_transcript_load_error("Speaker transcript request capacity was exhausted.")
        })?;
        state.current_identity = Some(identity.clone());
        Ok(state.generation)
    }

    fn is_current(&self, generation: u64) -> Result<bool, JobCommandError> {
        self.state
            .lock()
            .map(|state| state.generation == generation)
            .map_err(|_| {
                speaker_transcript_load_error(
                    "Speaker transcript load coordination is unavailable.",
                )
            })
    }
}

pub(crate) struct HistoryCatalogOwner {
    speaker_detail_gate: tokio::sync::Semaphore,
    speaker_detail_loads: SpeakerDetailLoadCoordinator,
    visibility: HistoryVisibility,
}

impl HistoryCatalogOwner {
    pub(crate) fn open_default() -> Self {
        Self {
            speaker_detail_gate: tokio::sync::Semaphore::new(1),
            speaker_detail_loads: SpeakerDetailLoadCoordinator::default(),
            visibility: HistoryVisibility::open_default(),
        }
    }

    fn project(&self, mut raw: HistoryCatalog) -> HistoryCatalog {
        match self.visibility.hidden_identities() {
            Ok(hidden) => project_history_catalog(raw, &hidden),
            Err(error) => {
                raw.maintenance_warnings.push(format!(
                    "Hidden history preferences are unavailable: {error}"
                ));
                project_history_catalog(raw, &HashSet::new())
            }
        }
    }

    fn remember_hidden(&self, identities: &[NativeHistoryIdentity]) -> Result<(), String> {
        self.visibility.hide_many(identities)
    }
}

#[tauri::command]
pub(crate) fn history_catalog(
    window: tauri::WebviewWindow,
    jobs: tauri::State<'_, RecordingJobs>,
    owner: tauri::State<'_, HistoryCatalogOwner>,
) -> Result<HistoryCatalog, JobCommandError> {
    ensure_history_authorized(&window)?;
    Ok(owner.project(load_raw_history_catalog(&jobs)?))
}

#[tauri::command]
pub(crate) async fn history_speaker_transcript(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    owner: tauri::State<'_, HistoryCatalogOwner>,
    identity: NativeHistoryIdentity,
) -> Result<PublishedSpeakerTranscript, JobCommandError> {
    ensure_history_authorized(&window)?;
    if !valid_native_identity(&identity) || identity.origin != HistoryOrigin::Remote {
        return Err(stale_history_identity_error());
    }
    let generation = owner.speaker_detail_loads.begin(&identity)?;
    let _permit =
        owner.speaker_detail_gate.acquire().await.map_err(|_| {
            speaker_transcript_load_error("Speaker transcript loading is unavailable.")
        })?;
    if !owner.speaker_detail_loads.is_current(generation)? {
        return Err(stale_history_identity_error());
    }
    let worker_app = app.clone();
    let detail = tauri::async_runtime::spawn_blocking(move || {
        let jobs = worker_app.state::<RecordingJobs>();
        jobs.published_speaker_transcript(&identity.session_id, &identity.output_path)?
            .ok_or_else(stale_history_identity_error)
    })
    .await
    .map_err(|_| {
        speaker_transcript_load_error("The speaker transcript worker stopped unexpectedly.")
    })??;
    if !owner.speaker_detail_loads.is_current(generation)? {
        return Err(stale_history_identity_error());
    }
    Ok(detail)
}

#[tauri::command]
pub(crate) fn history_hide_native(
    window: tauri::WebviewWindow,
    jobs: tauri::State<'_, RecordingJobs>,
    owner: tauri::State<'_, HistoryCatalogOwner>,
    identity: NativeHistoryIdentity,
) -> Result<(), JobCommandError> {
    ensure_history_authorized(&window)?;
    if !valid_native_identity(&identity) {
        return Err(stale_history_identity_error());
    }
    let raw = load_raw_history_catalog(&jobs)?;
    let Some(current) = resolve_current_native_identity(&raw, &identity) else {
        return Err(stale_history_identity_error());
    };
    owner
        .remember_hidden(std::slice::from_ref(&current))
        .map_err(history_visibility_error)
}

#[tauri::command]
pub(crate) fn history_language_label_review(
    window: tauri::WebviewWindow,
    jobs: tauri::State<'_, RecordingJobs>,
    identity: NativeHistoryIdentity,
) -> Result<LanguageLabelReview, JobCommandError> {
    ensure_history_authorized(&window)?;
    let current = resolve_remote_history_identity(&jobs, &identity)?;
    jobs.language_label_review(&current.output_path)
}

#[tauri::command]
pub(crate) fn history_append_language_label_correction(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    jobs: tauri::State<'_, RecordingJobs>,
    identity: NativeHistoryIdentity,
    expected_revision: u64,
    segment_index: u64,
    replacement_language_bcp47: Option<String>,
) -> Result<LanguageLabelReview, JobCommandError> {
    ensure_history_authorized(&window)?;
    let current = resolve_remote_history_identity(&jobs, &identity)?;
    let review = jobs.append_language_label_correction(
        &current.output_path,
        expected_revision,
        segment_index,
        replacement_language_bcp47,
    )?;
    emit_jobs_changed(&app);
    Ok(review)
}

fn resolve_remote_history_identity(
    jobs: &RecordingJobs,
    identity: &NativeHistoryIdentity,
) -> Result<NativeHistoryIdentity, JobCommandError> {
    if !valid_native_identity(identity) || identity.origin != HistoryOrigin::Remote {
        return Err(stale_history_identity_error());
    }
    let remote = jobs.published_remote_transcript_catalog()?;
    remote
        .sessions
        .into_iter()
        .find(|session| {
            session.session_id == identity.session_id && session.output_path == identity.output_path
        })
        .map(|session| NativeHistoryIdentity {
            origin: HistoryOrigin::Remote,
            session_id: session.session_id,
            output_path: session.output_path,
        })
        .ok_or_else(stale_history_identity_error)
}

fn ensure_history_authorized(window: &tauri::WebviewWindow) -> Result<(), JobCommandError> {
    crate::authorization::ensure_main(window).map_err(|message| JobCommandError {
        code: "HISTORY_FORBIDDEN".into(),
        message,
    })
}

fn valid_native_identity(identity: &NativeHistoryIdentity) -> bool {
    !identity.session_id.is_empty()
        && identity.session_id.len() <= 128
        && identity
            .session_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
        && !identity.output_path.is_empty()
        && identity.output_path.chars().count() <= MAX_HISTORY_PATH_CHARS
        && !identity.output_path.contains('\0')
}

fn stale_history_identity_error() -> JobCommandError {
    JobCommandError {
        code: "HISTORY_IDENTITY_STALE".into(),
        message: "History identity is no longer current. Refresh history and try again.".into(),
    }
}

fn speaker_transcript_load_error(message: &str) -> JobCommandError {
    JobCommandError {
        code: "SPEAKER_TRANSCRIPT_LOAD_FAILED".into(),
        message: message.into(),
    }
}

fn history_visibility_error(message: String) -> JobCommandError {
    JobCommandError {
        code: "HISTORY_VISIBILITY_ERROR".into(),
        message,
    }
}

fn load_raw_history_catalog(jobs: &RecordingJobs) -> Result<HistoryCatalog, JobCommandError> {
    let live = crate::live::recordings::list_history_sources().map_err(history_error)?;
    let remote = jobs.published_remote_transcript_catalog()?;
    Ok(collect_history_catalog(
        live.saved,
        live.recoverable,
        remote,
    ))
}

fn history_error(message: String) -> JobCommandError {
    JobCommandError {
        code: "HISTORY_CATALOG_ERROR".into(),
        message,
    }
}

#[cfg(test)]
mod speaker_detail_load_tests {
    use super::*;

    fn remote_identity(session_id: &str, output_path: &str) -> NativeHistoryIdentity {
        NativeHistoryIdentity {
            origin: HistoryOrigin::Remote,
            session_id: session_id.into(),
            output_path: output_path.into(),
        }
    }

    #[test]
    fn identical_speaker_detail_readers_remain_current() {
        let coordinator = SpeakerDetailLoadCoordinator::default();
        let identity = remote_identity("s-shared", "C:\\history\\shared\\transcript.txt");

        let first = coordinator.begin(&identity).unwrap();
        let second = coordinator.begin(&identity).unwrap();

        assert_eq!(first, second);
        assert!(coordinator.is_current(first).unwrap());
        assert!(coordinator.is_current(second).unwrap());
    }

    #[test]
    fn different_speaker_detail_identity_invalidates_older_readers() {
        let coordinator = SpeakerDetailLoadCoordinator::default();
        let first_identity = remote_identity("s-first", "C:\\history\\first\\transcript.txt");
        let second_identity = remote_identity("s-second", "C:\\history\\second\\transcript.txt");

        let first = coordinator.begin(&first_identity).unwrap();
        let second = coordinator.begin(&second_identity).unwrap();

        assert_ne!(first, second);
        assert!(!coordinator.is_current(first).unwrap());
        assert!(coordinator.is_current(second).unwrap());
    }
}
