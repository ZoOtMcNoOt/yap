use std::sync::Mutex;

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
    Finalizing,
    Failed(String),
    ExitAuthorized,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum QuitClaim {
    Finalize,
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
                *state = QuitState::Finalizing;
                QuitClaim::Finalize
            }
            QuitState::Finalizing => QuitClaim::Coalesced,
            QuitState::Failed(error) => QuitClaim::Blocked(error.clone()),
            QuitState::ExitAuthorized => QuitClaim::ExitAuthorized,
        }
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
        if matches!(*state, QuitState::Finalizing) {
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
        QuitClaim::Finalize => {}
        QuitClaim::Coalesced => return,
        QuitClaim::Blocked(error) => {
            crate::diagnostics::log(&format!(
                "quit remains blocked by an unacknowledged shutdown failure: {error}"
            ));
            present_quit_failure(app, None);
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
            let result = run_quit_with(
                || finalize_live_before_quit(&worker_app),
                || {
                    crate::app::begin_instance_activation_shutdown().map_err(|error| {
                        format!("could not publish the instance shutdown handoff: {error}")
                    })?;
                    let lifecycle = worker_app.state::<crate::runtime::DesktopLifecycle>();
                    for error in lifecycle.shutdown() {
                        crate::diagnostics::log(&format!(
                            "desktop background shutdown failed: {error}"
                        ));
                    }
                    Ok(())
                },
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
                }
            }
        })
    {
        app.state::<QuitCoordinator>().worker_start_failed();
        crate::diagnostics::log(&format!("quit worker failed to start: {error}"));
        present_quit_failure(app, None);
    }
}

pub(super) fn run_quit_with(
    finalize: impl FnOnce() -> Result<(), String>,
    prepare_exit: impl FnOnce() -> Result<(), String>,
) -> Result<(), QuitRunError> {
    finalize().map_err(QuitRunError::Finalization)?;
    prepare_exit().map_err(QuitRunError::Shutdown)
}

fn finalize_live_before_quit(app: &tauri::AppHandle) -> Result<(), String> {
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
    outcome.save_error.map_or(Ok(()), Err)
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
    if let Err(error) = live::overlay_window::ensure_active(app) {
        crate::diagnostics::log(&format!("quit failure overlay show failed: {error}"));
    }
    live::events::emit_session(app, &view);
}
