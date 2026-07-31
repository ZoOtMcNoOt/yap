//! Two-stage local start: establish durable capture before waiting for ASR warmup.

use std::sync::{atomic::Ordering, Arc};
use std::time::Instant;

use tauri::Manager;

use crate::audio::capture::CaptureAdapter;
use crate::audio::coordinator::{bounded_sink, SinkKind, RECORDING_QUEUE_CAPACITY};
use crate::audio::recording::RecordingSinkHandle;
use crate::audio::session::{SessionMetadata, SessionMode, SessionOrigin, TriggerMode};

use super::super::{
    devices, events, overlay_window, recordings,
    state::{LiveCaptureMode, LiveOverlayVisibility, LiveSessionState},
};
use super::asr_adapter::PendingAsrAdapter;
use super::capture_installation::CaptureInstallation;
use super::capture_worker::{run_capture_worker, CaptureWorkerContext};
use super::level_channel::level_channel;
use super::{LiveRuntime, LiveStartFailure, StartIntent};

pub(crate) struct LocalCaptureStart {
    pub(super) session: u64,
    capture_start_requested: Instant,
}

impl LiveRuntime {
    pub(crate) fn start_local_capture(
        &self,
        app: tauri::AppHandle,
        selected_device_id: Option<String>,
        capture_mode: LiveCaptureMode,
        intent: StartIntent,
    ) -> Result<Option<LocalCaptureStart>, LiveStartFailure> {
        let session = {
            let inner = self.inner.lock().expect("live runtime poisoned");
            if inner.is_capturing() {
                return Ok(None);
            }
            drop(inner);
            self.ensure_recording_ready_to_start()
                .map_err(|message| LiveStartFailure::new(0, message))?;
            let mut inner = self.inner.lock().expect("live runtime poisoned");
            let Some(session) = inner.begin_capture_session() else {
                return Ok(None);
            };
            self.active_session.store(session, Ordering::SeqCst);
            session
        };

        if !self.start_intent_is_current(intent) {
            self.unwind_cancelled_uninstalled_start(&app, session);
            return Ok(None);
        }

        let resolved = match devices::resolve_capture_device(selected_device_id.as_deref()) {
            Ok(resolved) => resolved,
            Err(error) => return Err(LiveStartFailure::new(session, error)),
        };
        let stream_config = resolved.config.config();
        let sample_format = resolved.config.sample_format();
        let (level_tx, level) = level_channel();
        let pending_asr = PendingAsrAdapter::new();
        let local_asr = pending_asr.sink();
        let capture_runtime = self.clone();
        let capture_app = app.clone();
        let capture_active_session = Arc::clone(&self.active_session);
        let (recording_sink, recording_rx) =
            bounded_sink(SinkKind::Recording, RECORDING_QUEUE_CAPACITY);
        let recording_directory = recordings::recordings_dir();
        let recording_reservation =
            crate::audio::recording::allocate_recording_session(&recording_directory)
                .map_err(|message| LiveStartFailure::new(session, message))?;
        let recording_session_id = recording_reservation.session_id().clone();
        let trigger_mode = match capture_mode {
            LiveCaptureMode::PushToTalk => TriggerMode::PushToTalk,
            LiveCaptureMode::Toggle => TriggerMode::Toggle,
        };
        let session_metadata = SessionMetadata::new(
            recording_session_id.clone(),
            SessionMode::Dictation,
            SessionOrigin::LiveCapture,
            trigger_mode,
            std::time::SystemTime::now(),
            None,
            None,
            None,
            Vec::new(),
            None,
        )
        .map_err(|message| LiveStartFailure::new(session, message))?;
        let recording_reservation = recording_reservation
            .with_session_metadata(session_metadata)
            .map_err(|message| LiveStartFailure::new(session, message))?;
        let recording_handle = RecordingSinkHandle::spawn_reserved(
            recording_reservation,
            recording_sink,
            recording_rx,
        );
        let recording_for_capture = recording_handle.sink();
        if !self.start_intent_is_current(intent)
            || self.active_session.load(Ordering::Acquire) != session
        {
            discard_cancelled_recording(&recording_directory, &recording_handle, session)?;
            self.unwind_cancelled_uninstalled_start(&app, session);
            return Ok(None);
        }
        let capture_start_requested = Instant::now();
        let capture = match CaptureAdapter::open(
            resolved.device,
            stream_config,
            sample_format,
            move |ports, errors| {
                run_capture_worker(
                    ports,
                    errors,
                    CaptureWorkerContext {
                        runtime: capture_runtime,
                        app: capture_app,
                        session,
                        recording_session_id,
                        active_session: capture_active_session,
                        recording: recording_for_capture,
                        local_asr,
                        level_tx,
                    },
                );
            },
        ) {
            Ok(capture) => capture,
            Err(error) => {
                if let Err(finalize_error) =
                    recording_handle.abort(format!("capture adapter failed to open: {error}"))
                {
                    crate::diagnostics::log(&format!(
                        "live recording abort after capture-open failure failed: {finalize_error}"
                    ));
                }
                return Err(LiveStartFailure::new(session, error));
            }
        };
        let mut inner = self.inner.lock().expect("live runtime poisoned");
        if !self.start_intent_is_current(intent)
            || !inner.can_install_capture(session, self.active_session.load(Ordering::SeqCst))
        {
            inner.mark_used();
            drop(inner);
            if let Err(error) = capture.shutdown() {
                crate::diagnostics::log(&format!("live capture shutdown failed: {error}"));
            }
            discard_cancelled_recording(&recording_directory, &recording_handle, session)?;
            self.unwind_cancelled_uninstalled_start(&app, session);
            drop(level);
            return Ok(None);
        }
        inner.install_capture(CaptureInstallation {
            capture,
            recording: recording_handle,
            pending_asr,
            app: app.clone(),
            level,
            session,
            active_session: Arc::clone(&self.active_session),
        });
        drop(inner);

        let state = app.state::<LiveSessionState>();
        let Some(view) = state.try_begin_listening_from_armed() else {
            let mut inner = self.inner.lock().expect("live runtime poisoned");
            let (shutdown_errors, _) = inner.stop_capture();
            drop(inner);
            super::log_worker_shutdown_errors(shutdown_errors);
            let _ = self.finalize_recording();
            return Ok(None);
        };
        events::emit_session(&app, &view);
        Ok(Some(LocalCaptureStart {
            session,
            capture_start_requested,
        }))
    }

    pub(crate) fn complete_local_start(
        &self,
        app: tauri::AppHandle,
        start: LocalCaptureStart,
        intent: StartIntent,
    ) -> Result<bool, LiveStartFailure> {
        let LocalCaptureStart {
            session,
            capture_start_requested,
        } = start;
        let reused = self.run_installed_capture_lifecycle(intent, || {
            let mut inner = self.inner.lock().expect("live runtime poisoned");
            if !inner
                .capture_session_is_current(session, self.active_session.load(Ordering::Acquire))
            {
                return Ok(false);
            }
            if inner.reuse_stream(session)? {
                inner.start_pending_asr_adapter(session)?;
                log_asr_adapter_spawned(session, capture_start_requested);
                return Ok(true);
            }
            Ok(false)
        });
        match reused {
            None => return Ok(false),
            Some(Ok(true)) => return Ok(true),
            Some(Ok(false)) => {}
            Some(Err(message)) => return Err(LiveStartFailure::new(session, message)),
        }

        self.request_model_warmup()
            .map_err(|message| LiveStartFailure::new(session, message))?;
        let Some(inference) = self
            .model_warmup
            .wait_cancellable(|| !self.start_intent_is_current(intent))
            .map_err(|message| LiveStartFailure::new(session, message))?
        else {
            return Ok(false);
        };
        let model_warmup = Arc::clone(&self.model_warmup);
        self.run_installed_capture_lifecycle(intent, move || {
            let mut inner = self.inner.lock().expect("live runtime poisoned");
            if !inner
                .capture_session_is_current(session, self.active_session.load(Ordering::Acquire))
            {
                return Ok(false);
            }
            if !inner.reuse_stream(session)? {
                inner.install_stream(
                    app,
                    session,
                    inference.commit(),
                    model_warmup,
                    Arc::clone(&self.active_session),
                );
            }
            inner.start_pending_asr_adapter(session)?;
            log_asr_adapter_spawned(session, capture_start_requested);
            Ok(true)
        })
        .unwrap_or(Ok(false))
        .map_err(|message| LiveStartFailure::new(session, message))
    }

    fn unwind_cancelled_uninstalled_start(&self, app: &tauri::AppHandle, session: u64) {
        let state = app.state::<LiveSessionState>();
        let Some(view) = self.cancel_uninstalled_capture_start(&state, session) else {
            return;
        };
        if view.visibility == LiveOverlayVisibility::Enabled {
            if let Err(error) = overlay_window::ensure_idle(app) {
                crate::diagnostics::log(&format!(
                    "live overlay cancelled-start reset failed: {error}"
                ));
            }
        } else if let Some(window) = app.get_webview_window(overlay_window::WINDOW_LABEL) {
            let _ = window.hide();
        }
        events::emit_session(app, &view);
    }
}

fn log_asr_adapter_spawned(session: u64, capture_start_requested: Instant) {
    crate::diagnostics::log(&format!(
        "live ASR adapter spawned session={session} capture_start_request_to_adapter_spawn_ms={}",
        capture_start_requested.elapsed().as_millis()
    ));
}

fn discard_cancelled_recording(
    recording_directory: &std::path::Path,
    recording: &RecordingSinkHandle,
    session: u64,
) -> Result<(), LiveStartFailure> {
    let capture = recording
        .finalize()
        .map_err(|message| LiveStartFailure::new(session, message))?;
    recordings::discard_cancelled_capture_in_dir(recording_directory, &capture)
        .map_err(|message| LiveStartFailure::new(session, message))?;
    Ok(())
}
