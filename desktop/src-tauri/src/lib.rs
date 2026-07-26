mod app;
mod atomic_text;
pub mod audio;
mod authorization;
mod bounded_file;
mod commands;
mod diagnostics;
mod exclusive_file_lease;
mod file_actions;
mod install_identity;
pub mod jobs;
pub mod language;
pub mod language_preferences;
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
mod tray;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    app::run();
}
