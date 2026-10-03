//! Shared file ownership and destination rules for explicit native exports.

use std::{
    path::{Path, PathBuf},
    sync::{Arc, OnceLock},
};

use serde::Serialize;
use tauri_plugin_dialog::DialogExt;
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

pub(crate) mod accepted_correction;

const EXPORT_UNCONFIRMED: &str = "Export could not be confirmed. Check the selected destination before trying again; the file may already have been saved.";

pub(crate) fn export_permit() -> Result<OwnedSemaphorePermit, String> {
    static LIMITER: OnceLock<Arc<Semaphore>> = OnceLock::new();
    Arc::clone(LIMITER.get_or_init(|| Arc::new(Semaphore::new(1))))
        .try_acquire_owned()
        .map_err(|_| "Finish the current export before starting another.".to_string())
}

#[derive(Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "status", rename_all = "camelCase")]
pub(crate) enum TranscriptExport {
    Cancelled,
    Saved { path: String },
}

#[tauri::command]
pub(crate) async fn export_transcript(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    path: String,
) -> Result<TranscriptExport, String> {
    super::ensure_main_window(&window)?;
    let permit = export_permit()?;

    // Keep admission owned by the blocking worker even if its caller goes away.
    // Writes are byte-bounded; a timeout must not report failure while a write
    // continues and publishes a file after the user has started retrying.
    tauri::async_runtime::spawn_blocking(move || {
        let _permit = permit;
        let original = super::transcripts::read_text_file_at(path.clone())?;
        validate_text(&original)?;
        let selected = app
            .dialog()
            .file()
            .set_parent(&window)
            .set_title("Export original transcript — choose a new file")
            .set_file_name("transcript-export.txt")
            .add_filter("UTF-8 transcript text", &["txt"])
            .blocking_save_file();
        let Some(selected) = selected else {
            return Ok(TranscriptExport::Cancelled);
        };
        let selected = selected
            .into_path()
            .map_err(|_| "Choose a local destination for the transcript.".to_string())?;
        export_selected_transcript(&original, &selected, &crate::paths::app_data_dir(), || {
            super::transcripts::read_text_file_at(path)
        })
    })
    .await
    .map_err(|_| EXPORT_UNCONFIRMED.to_string())?
}

fn export_selected_transcript(
    original: &str,
    selected: &Path,
    app_data: &Path,
    read_current: impl FnOnce() -> Result<String, String>,
) -> Result<TranscriptExport, String> {
    validate_text(original)?;
    let destination = export_destination(selected, app_data, ExportKind::Transcript)?;
    let current = read_current()?;
    if current != original {
        return Err(
            "The transcript changed while choosing a destination. Review it and retry.".into(),
        );
    }
    crate::atomic_text::write_new(&destination, original).map_err(|error| {
        if error.kind() == std::io::ErrorKind::AlreadyExists {
            "That file already exists. Choose a new filename; existing files are preserved."
                .to_string()
        } else {
            // Directory sync can fail after the new file was committed.
            EXPORT_UNCONFIRMED.to_string()
        }
    })?;
    Ok(TranscriptExport::Saved {
        path: destination.to_string_lossy().into_owned(),
    })
}

fn validate_text(text: &str) -> Result<(), String> {
    if text.len() as u64 > super::transcripts::MAX_TRANSCRIPT_READ_BYTES {
        return Err(
            "This transcript exceeds the export size limit. Open the saved file instead.".into(),
        );
    }
    Ok(())
}

pub(crate) enum ExportKind {
    Transcript,
    ConnectionReview,
}

pub(crate) fn export_destination(
    selected: &Path,
    app_data: &Path,
    kind: ExportKind,
) -> Result<PathBuf, String> {
    let (extension, description) = match kind {
        ExportKind::Transcript => ("txt", "transcript"),
        ExportKind::ConnectionReview => ("json", "review package"),
    };
    if !selected.is_absolute() {
        return Err(format!(
            "Choose an absolute local destination for the {description}."
        ));
    }
    let mut selected = selected.to_path_buf();
    if selected.extension().is_none() {
        selected.set_extension(extension);
    }
    if !selected
        .extension()
        .is_some_and(|ext| ext.eq_ignore_ascii_case(extension))
    {
        return Err(format!(
            "Export uses UTF-8 text. Choose a .{extension} filename."
        ));
    }
    let name = selected
        .file_name()
        .ok_or_else(|| format!("Choose a filename for the {description}."))?;
    let parent = selected
        .parent()
        .and_then(|path| path.canonicalize().ok())
        .filter(|path| path.is_dir())
        .ok_or_else(|| {
            "The export folder is unavailable. Choose another destination.".to_string()
        })?;
    let protected = app_data.canonicalize().map_err(|_| {
        "Yap data could not be verified. Retry after reopening the workspace.".to_string()
    })?;
    if parent.starts_with(protected) {
        return Err("Choose a destination outside Yap's internal data folder.".into());
    }
    Ok(parent.join(name))
}

#[cfg(test)]
mod tests;
