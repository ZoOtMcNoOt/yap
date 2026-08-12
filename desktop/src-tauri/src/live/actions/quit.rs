use std::{sync::Mutex, time::Duration};

use tauri::Manager;

use crate::{authorization, live};

use super::{
    completion::{append_error, CompletionMode},
    stop::finalize_live_runtime_with_mode,
};

pub(crate) struct QuitCoordinator {
    state: Mutex<QuitState>,
}

enum QuitState {
    Ready,
    PublishingShutdown,
    Finalizing,
    /// A shutdown failed and the user has not been told yet. `claim()` refuses
    /// to start another one from here, which is the property that stops a
    /// second Quit from silently succeeding and losing an unsaved recording.
    Failed(String),
    /// The failure is on screen, waiting for the user to dismiss it. Distinct
    /// from `Failed` so that a run of tray clicks coalesces onto the dialog
    /// already asking, rather than stacking dialogs or starting a shutdown
    /// behind one. Carries no text: the presenter holds the message it is
    /// showing, and losing it here costs nothing because the next quit re-runs
    /// shutdown and produces its own.
    AwaitingAcknowledgement,
    ExitAuthorized,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum QuitClaim {
    BeginShutdown,
    Coalesced,
    Blocked(String),
    ExitAuthorized,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum QuitRunError {
    Finalization(String),
    Shutdown(String),
}

impl QuitRunError {
    fn detail(&self) -> &str {
        match self {
            Self::Finalization(error) | Self::Shutdown(error) => error,
        }
    }
}

impl QuitCoordinator {
    pub(crate) fn new() -> Self {
        Self {
            state: Mutex::new(QuitState::Ready),
        }
    }

    pub(super) fn claim(&self) -> QuitClaim {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        match &*state {
            QuitState::Ready => {
                *state = QuitState::PublishingShutdown;
                QuitClaim::BeginShutdown
            }
            QuitState::PublishingShutdown
            | QuitState::Finalizing
            | QuitState::AwaitingAcknowledgement => QuitClaim::Coalesced,
            QuitState::Failed(error) => QuitClaim::Blocked(error.clone()),
            QuitState::ExitAuthorized => QuitClaim::ExitAuthorized,
        }
    }

    /// Take the pending failure in order to show it. Returns `None` when there
    /// is nothing to acknowledge, or when another presenter already holds it.
    ///
    /// `Failed` is the state `claim()` calls *unacknowledged*, and until now
    /// nothing in the crate said what acknowledging one was. Every route back
    /// to `Ready` came from `PublishingShutdown`, so the first failed shutdown
    /// blocked Quit for the rest of the process while the quit path re-created
    /// the island on each attempt.
    pub(super) fn begin_acknowledgement(&self) -> Option<String> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let QuitState::Failed(error) = &*state else {
            return None;
        };
        let error = error.clone();
        *state = QuitState::AwaitingAcknowledgement;
        Some(error)
    }

    /// The user dismissed the failure. Quit becomes attemptable again -- not
    /// authorized: the next claim runs the whole shutdown from the start,
    /// including another attempt to save whatever failed to save.
    pub(super) fn finish_acknowledgement(&self) -> bool {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if !matches!(*state, QuitState::AwaitingAcknowledgement) {
            return false;
        }
        *state = QuitState::Ready;
        true
    }

    pub(super) fn begin_finalizing(
        &self,
        begin_shutdown: impl FnOnce() -> Result<(), String>,
        reopen_activation: impl FnOnce() -> Result<(), String>,
    ) -> Result<(), String> {
        if !matches!(
            *self
                .state
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()),
            QuitState::PublishingShutdown
        ) {
            return Err("quit shutdown transition does not own the coordinator".into());
        }

        let transition = begin_shutdown();
        let (result, next_state) = match transition {
            Ok(()) => (Ok(()), QuitState::Finalizing),
            Err(error) => match reopen_activation() {
                Ok(()) => (Err(error), QuitState::Ready),
                Err(reopen_error) => {
                    let detail = format!(
                        "{error}; could not reopen activation after the failed shutdown transition: {reopen_error}"
                    );
                    (Err(detail.clone()), QuitState::Failed(detail))
                }
            },
        };

        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if !matches!(*state, QuitState::PublishingShutdown) {
            return Err("quit shutdown transition lost coordinator ownership".into());
        }
        *state = next_state;
        result
    }

    pub(super) fn finish(&self, result: Result<(), String>) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        *state = match result {
            Ok(()) => QuitState::ExitAuthorized,
            Err(error) => QuitState::Failed(error),
        };
    }

    fn worker_start_failed(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if matches!(*state, QuitState::PublishingShutdown) {
            *state = QuitState::Ready;
        }
    }

    pub(crate) fn exit_authorized(&self) -> bool {
        matches!(
            *self
                .state
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()),
            QuitState::ExitAuthorized
        )
    }

    #[cfg(test)]
    pub(super) fn finalization_started(&self) -> bool {
        matches!(
            *self
                .state
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()),
            QuitState::Finalizing
        )
    }
}

pub(crate) fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window(authorization::MAIN_WINDOW_LABEL) {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

pub(crate) fn quit_from_app(app: &tauri::AppHandle) {
    let quit = app.state::<QuitCoordinator>();
    match quit.claim() {
        QuitClaim::BeginShutdown => {}
        QuitClaim::Coalesced => return,
        QuitClaim::Blocked(error) => {
            crate::diagnostics::log(&format!(
                "quit remains blocked by an unacknowledged shutdown failure: {error}"
            ));
            // Deliberately not `present_quit_failure` any more. Re-showing the
            // window and re-creating the island on every blocked click is the
            // "island I cannot get rid of" symptom, and it never explained
            // itself: the message goes into `LiveSessionView.error`, which the
            // next start or stop clears, and the only surface that renders it
            // is a detail line inside Settings.
            ask_to_acknowledge_quit_failure(app);
            return;
        }
        QuitClaim::ExitAuthorized => {
            app.exit(0);
            return;
        }
    }

    let worker_app = app.clone();
    if let Err(error) = std::thread::Builder::new()
        .name("live-semantic-quit".into())
        .spawn(move || {
            let quit = worker_app.state::<QuitCoordinator>();
            if let Err(error) = quit.begin_finalizing(
                || {
                    crate::app::begin_instance_activation_shutdown().map_err(|error| {
                        format!("could not publish the instance shutdown handoff: {error}")
                    })
                },
                reopen_activation_after_abandoned_quit,
            ) {
                crate::diagnostics::log(&format!(
                    "quit stayed open because the shutdown transition could not start: {error}"
                ));
                present_quit_failure(&worker_app, Some(&QuitRunError::Shutdown(error)));
                return;
            }
            let result = run_quit_with(
                || finalize_owned_work_before_quit(&worker_app),
                || {
                    let lifecycle = worker_app.state::<crate::runtime::DesktopLifecycle>();
                    for error in lifecycle.shutdown() {
                        crate::diagnostics::log(&format!(
                            "desktop background shutdown failed: {error}"
                        ));
                    }
                },
                reopen_activation_after_abandoned_quit,
            );
            match result {
                Ok(()) => {
                    worker_app.state::<QuitCoordinator>().finish(Ok(()));
                    worker_app.exit(0);
                }
                Err(error) => {
                    let detail = error.detail().to_string();
                    worker_app
                        .state::<QuitCoordinator>()
                        .finish(Err(detail.clone()));
                    crate::diagnostics::log(&format!(
                        "quit deferred because shutdown could not complete: {detail}"
                    ));
                    present_quit_failure(&worker_app, Some(&error));
                    // Ask on the first failure too. Otherwise the user's only
                    // signal is that Quit did nothing, and they learn why only
                    // by clicking it a second time.
                    ask_to_acknowledge_quit_failure(&worker_app);
                }
            }
        })
    {
        let detail = format!("quit worker failed to start: {error}");
        app.state::<QuitCoordinator>().worker_start_failed();
        crate::diagnostics::log(&detail);
        present_quit_failure(app, Some(&QuitRunError::Shutdown(detail)));
    }
}

pub(super) fn run_quit_with(
    finalize: impl FnOnce() -> Result<(), String>,
    prepare_exit: impl FnOnce(),
    reopen_activation: impl FnOnce() -> Result<(), String>,
) -> Result<(), QuitRunError> {
    if let Err(error) = finalize() {
        return match reopen_activation() {
            Ok(()) => Err(QuitRunError::Finalization(error)),
            Err(reopen_error) => Err(QuitRunError::Shutdown(format!(
                "{error}; could not reopen activation after the abandoned quit: {reopen_error}"
            ))),
        };
    }
    prepare_exit();
    Ok(())
}

fn reopen_activation_after_abandoned_quit() -> Result<(), String> {
    crate::app::reopen_instance_activation_after_abandoned_shutdown()
        .map_err(|error| format!("could not reopen the instance activation handoff: {error}"))
}

fn finalize_owned_work_before_quit(app: &tauri::AppHandle) -> Result<(), String> {
    let live = app.state::<live::LiveSessionState>();
    let live_runtime = app.state::<live::runtime::LiveRuntime>();
    live_runtime.cancel_pending_start();
    let outcome = live_runtime.run_stop_lifecycle(|| {
        finalize_live_runtime_with_mode(
            app.clone(),
            &live,
            &live_runtime,
            None,
            None,
            CompletionMode::Quit,
        )
    });
    outcome.save_error.map_or(Ok(()), Err)?;

    let correction_owner = app.state::<crate::transcript_correction::TranscriptCorrectionOwner>();
    let cancellation = tauri::async_runtime::block_on(tokio::time::timeout(
        Duration::from_secs(5),
        correction_owner.cancel_active_requests(),
    ));
    match cancellation {
        Ok(Ok(_)) => {}
        Ok(Err(error)) => crate::diagnostics::log(&format!(
            "transcript correction shutdown cancellation was incomplete: {error}"
        )),
        Err(_) => crate::diagnostics::log(
            "transcript correction shutdown cancellation exceeded its bounded wait",
        ),
    }
    Ok(())
}

/// Show the pending shutdown failure and wait for the user to dismiss it.
///
/// Off the calling thread on purpose: the blocked path runs on the tray menu
/// handler, and a modal that pumps its own message loop there is the shape of
/// the tao session-lock freeze in #92. The two existing confirmation dialogs in
/// this crate move the same way.
fn ask_to_acknowledge_quit_failure(app: &tauri::AppHandle) {
    let dialog_app = app.clone();
    if let Err(spawn_error) = std::thread::Builder::new()
        .name("live-quit-acknowledge".into())
        .spawn(move || {
            // Taken here rather than before the spawn, so a thread that never
            // starts cannot consume a failure it will not show. If two tray
            // clicks race, one takes it and the other finds nothing to present.
            let Some(error) = dialog_app
                .state::<QuitCoordinator>()
                .begin_acknowledgement()
            else {
                return;
            };
            // Drop-guarded so a panicking presenter cannot park the app in
            // AwaitingAcknowledgement -- that would be this same defect again,
            // one state along.
            let release = AcknowledgementRelease(dialog_app.clone());
            if confirm_quit_failure(&dialog_app, &error) {
                drop(release);
                quit_from_app(&dialog_app);
            }
        })
    {
        crate::diagnostics::log(&format!(
            "quit acknowledgement dialog could not start: {spawn_error}"
        ));
        // The failure is untouched and still blocks quit, which is right:
        // nothing was shown, so nothing was acknowledged.
        present_quit_failure(app, None);
    }
}

struct AcknowledgementRelease(tauri::AppHandle);

impl Drop for AcknowledgementRelease {
    fn drop(&mut self) {
        self.0.state::<QuitCoordinator>().finish_acknowledgement();
    }
}

fn confirm_quit_failure(app: &tauri::AppHandle, error: &str) -> bool {
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

    app.dialog()
        .message(format!(
            "Yap stayed open because shutdown could not finish safely.\n\n{error}\n\nQuitting again runs shutdown from the start, including another attempt to save the current recording."
        ))
        .title("Yap could not quit")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Try Quitting Again".into(),
            "Keep Yap Open".into(),
        ))
        .blocking_show()
}

fn present_quit_failure(app: &tauri::AppHandle, failure: Option<&QuitRunError>) {
    let message = match failure {
        Some(QuitRunError::Finalization(_)) => {
            "Yap stayed open because the current recording could not be saved."
        }
        Some(QuitRunError::Shutdown(_)) | None => {
            "Yap stayed open because shutdown could not be completed safely."
        }
    };
    let live = app.state::<live::LiveSessionState>();
    let view = live.update(|view| {
        view.error = Some(append_error(view.error.take(), message));
    });
    show_main_window(app);
    // No `ensure_active` here. Forcing the island to its active surface is what
    // made a failed quit look like an island that reappears on its own, and it
    // forced the *recording* surface onto a session that is idle-with-an-error,
    // so the native frame briefly disagreed with the pill being drawn. Emitting
    // is enough: the overlay reads the error off this view and picks its own
    // surface, and the periodic recovery pass restores it if it is missing.
    live::events::emit_session(app, &view);
}
