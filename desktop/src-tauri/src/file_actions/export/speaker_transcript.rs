//! Export the original persisted speaker projection, retaining its source identity.

use std::{io::Write, path::Path};

use serde::Serialize;
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;

use crate::jobs::commands::{PublishedSpeakerTranscript, RecordingJobs};

const SOURCE_UNAVAILABLE: &str =
    "The saved timed speaker transcript could not be verified. Refresh history and retry.";
const OUTPUT_TOO_LARGE: &str =
    "The timed speaker transcript exceeds the 2 MiB export limit. No file was saved.";
const MAX_EXPORT_BYTES: usize = 2 * 1024 * 1024;

#[derive(Debug, PartialEq, Eq, Serialize)]
#[serde(
    tag = "status",
    rename_all = "camelCase",
    rename_all_fields = "camelCase"
)]
pub(crate) enum SpeakerTranscriptExport {
    Cancelled,
    Saved {
        path: String,
        session_id: String,
        source_result_sha256: String,
    },
}

#[tauri::command]
pub(crate) async fn export_speaker_transcript(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    output_path: String,
    session_id: String,
    source_result_sha256: String,
) -> Result<SpeakerTranscriptExport, String> {
    super::super::ensure_main_window(&window)?;
    let permit = super::export_permit()?;
    tauri::async_runtime::spawn_blocking(move || {
        let _permit = permit;
        let jobs = app.state::<RecordingJobs>();
        let read_current = || load_source(&jobs, &output_path, &session_id, &source_result_sha256);
        let original = read_current()?;
        // Refuse oversized output before asking the user for a destination.
        let json = serialize(&original)?;
        let selected = app
            .dialog()
            .file()
            .set_parent(&window)
            .set_title("Export timed speaker transcript — choose a new file")
            .set_file_name("transcript-timed-speakers.json")
            .add_filter("Timed speaker transcript JSON", &["json"])
            .blocking_save_file();
        let Some(selected) = selected else {
            return Ok(SpeakerTranscriptExport::Cancelled);
        };
        let selected = selected.into_path().map_err(|_| {
            "Choose a local destination for the timed speaker transcript.".to_string()
        })?;
        export_selected(
            &original,
            &json,
            &selected,
            &crate::paths::app_data_dir(),
            read_current,
        )
    })
    .await
    .map_err(|_| super::EXPORT_UNCONFIRMED.to_string())?
}

pub(crate) fn load_source(
    jobs: &RecordingJobs,
    output_path: &str,
    session_id: &str,
    source_result_sha256: &str,
) -> Result<PublishedSpeakerTranscript, String> {
    if session_id.is_empty()
        || session_id.len() > 128
        || source_result_sha256.len() != 64
        || !source_result_sha256
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(SOURCE_UNAVAILABLE.into());
    }
    let source = jobs
        .published_speaker_transcript(session_id, output_path)
        .map_err(|_| SOURCE_UNAVAILABLE.to_string())?
        .ok_or_else(|| SOURCE_UNAVAILABLE.to_string())?;
    if source.session_id != session_id || source.source_result_sha256 != source_result_sha256 {
        return Err(SOURCE_UNAVAILABLE.into());
    }
    Ok(source)
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ExportDocument<'a> {
    schema_version: u8,
    #[serde(flatten)]
    transcript: &'a PublishedSpeakerTranscript,
}

// JSON escaping can expand source text: cap serialized bytes without allocating
// an unbounded intermediate string or truncating the published projection.
struct BoundedOutput(Vec<u8>);
impl Write for BoundedOutput {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > MAX_EXPORT_BYTES.saturating_sub(self.0.len()) {
            return Err(std::io::Error::other(OUTPUT_TOO_LARGE));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

pub(crate) fn serialize(source: &PublishedSpeakerTranscript) -> Result<String, String> {
    let mut output = BoundedOutput(Vec::new());
    serde_json::to_writer_pretty(
        &mut output,
        &ExportDocument {
            schema_version: 1,
            transcript: source,
        },
    )
    .map_err(|_| OUTPUT_TOO_LARGE.to_string())?;
    output
        .write_all(b"\n")
        .map_err(|_| OUTPUT_TOO_LARGE.to_string())?;
    String::from_utf8(output.0).map_err(|_| SOURCE_UNAVAILABLE.to_string())
}

pub(crate) fn export_selected(
    original: &PublishedSpeakerTranscript,
    json: &str,
    selected: &Path,
    app_data: &Path,
    read_current: impl FnOnce() -> Result<PublishedSpeakerTranscript, String>,
) -> Result<SpeakerTranscriptExport, String> {
    if json.len() > MAX_EXPORT_BYTES {
        return Err(OUTPUT_TOO_LARGE.into());
    }
    let destination =
        super::export_destination(selected, app_data, super::ExportKind::SpeakerTranscript)?;
    if &read_current()? != original {
        return Err("The timed speaker transcript changed while choosing a destination. Refresh history and retry.".into());
    }
    crate::atomic_text::write_new(&destination, json).map_err(|error| {
        if error.kind() == std::io::ErrorKind::AlreadyExists {
            "That file already exists. Choose a new filename; existing files are preserved.".into()
        } else {
            super::EXPORT_UNCONFIRMED.to_string()
        }
    })?;
    Ok(SpeakerTranscriptExport::Saved {
        path: destination.path().to_string_lossy().into_owned(),
        session_id: original.session_id.clone(),
        source_result_sha256: original.source_result_sha256.clone(),
    })
}

#[cfg(test)]
mod tests;
