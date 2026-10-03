//! Export an explicitly selected accepted, current source-bound correction.

use std::path::Path;

use serde::Serialize;
use tauri_plugin_dialog::DialogExt;

use crate::transcript_correction::{
    recover_accepted_transcript_correction, RecoveredTranscriptCorrection,
};

#[derive(Debug, PartialEq, Eq, Serialize)]
#[serde(
    tag = "status",
    rename_all = "camelCase",
    rename_all_fields = "camelCase"
)]
pub(crate) enum AcceptedCorrectionExport {
    Cancelled,
    Saved {
        path: String,
        revision: u64,
        corrected_sha256: String,
    },
}

#[tauri::command]
pub(crate) async fn export_accepted_transcript_correction(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    output_path: String,
    revision: u64,
    corrected_sha256: String,
) -> Result<AcceptedCorrectionExport, String> {
    super::super::ensure_main_window(&window)?;
    let permit = super::export_permit()?;
    // The worker owns admission through the dialog and write. It cannot be
    // timed out while a publication can still complete after a reported failure.
    tauri::async_runtime::spawn_blocking(move || {
        let _permit = permit;
        let source = Path::new(&output_path);
        let accepted = require_displayed_revision(
            recover_accepted_transcript_correction(source, Some(revision))?,
            revision,
            &corrected_sha256,
        )?;
        let selected = app
            .dialog()
            .file()
            .set_parent(&window)
            .set_title("Export saved correction — choose a new file")
            .set_file_name(format!("transcript-corrected-r{revision}.txt"))
            .add_filter("UTF-8 corrected transcript text", &["txt"])
            .blocking_save_file();
        let Some(selected) = selected else {
            return Ok(AcceptedCorrectionExport::Cancelled);
        };
        let selected = selected
            .into_path()
            .map_err(|_| "Choose a local destination for the saved correction.".to_string())?;
        export_selected_accepted_correction(
            &accepted,
            &selected,
            &crate::paths::app_data_dir(),
            || recover_accepted_transcript_correction(source, Some(revision)),
        )
    })
    .await
    .map_err(|_| super::EXPORT_UNCONFIRMED.to_string())?
}

pub(crate) fn require_displayed_revision(
    accepted: RecoveredTranscriptCorrection,
    revision: u64,
    corrected_sha256: &str,
) -> Result<RecoveredTranscriptCorrection, String> {
    let current = accepted
        .accepted_revision
        .as_ref()
        .ok_or_else(|| "No accepted correction is saved for this transcript.".to_string())?;
    if current.revision != revision || current.corrected_sha256 != corrected_sha256 {
        return Err("The saved correction changed. Refresh its history and retry.".into());
    }
    Ok(accepted)
}

pub(crate) fn export_selected_accepted_correction(
    accepted: &RecoveredTranscriptCorrection,
    selected: &Path,
    app_data: &Path,
    read_current: impl FnOnce() -> Result<RecoveredTranscriptCorrection, String>,
) -> Result<AcceptedCorrectionExport, String> {
    let revision = accepted
        .accepted_revision
        .as_ref()
        .ok_or_else(|| "No accepted correction is saved for this transcript.".to_string())?;
    let result = super::export_selected_transcript(
        &revision.corrected_text,
        selected,
        app_data,
        || {
            if &read_current()? != accepted {
                return Err("The saved correction changed while choosing a destination. Refresh its history and retry.".into());
            }
            Ok(revision.corrected_text.clone())
        },
    )?;
    match result {
        super::TranscriptExport::Saved { path } => Ok(AcceptedCorrectionExport::Saved {
            path,
            revision: revision.revision,
            corrected_sha256: revision.corrected_sha256.clone(),
        }),
        super::TranscriptExport::Cancelled => {
            unreachable!("selected destination always saves or fails")
        }
    }
}
