//! STT runtime: dispatcher, error contract, and local fallback artifacts.

use std::path::PathBuf;
use std::time::Duration;

pub fn stt_log_path() -> PathBuf {
    crate::diagnostics::logs_dir().join("asr.log")
}

pub(crate) fn log_stt(message: &str) {
    crate::diagnostics::append_log(&stt_log_path(), message);
}

pub(crate) fn log_stt_timed(phase: &str, elapsed: Duration, detail: &str) {
    log_stt(&format!("[{phase}] +{}ms {detail}", elapsed.as_millis()));
}

pub mod ambernet_language_detector;
pub mod dispatch;
pub mod error;
pub mod fallback_model;
pub mod model;
pub mod nemotron;
pub mod parity;
pub mod settings;
pub mod silero_vad;
