mod analyst_answer;
mod app;
mod archivist_ingestion;
mod atomic_file;
mod atomic_text;
pub mod audio;
mod auditor_report;
mod authorization;
mod bounded_file;
mod commands;
mod coordinator_bundle;
mod curator_proposal;
mod diagnostics;
mod exclusive_file_lease;
mod file_actions;
mod install_identity;
pub mod jobs;
pub mod language;
pub mod language_preferences;
mod librarian_query;
pub mod live;
pub(crate) mod media_protocol;
mod paths;
#[cfg(test)]
mod private_evidence;
pub(crate) mod recording_access;
pub mod runtime;
mod runtime_policy;
pub mod server_connector;
pub mod stt;
mod student_question;
mod transcript_correction;
mod tray;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    app::run();
}
