use std::{
    io::Write,
    sync::atomic::{AtomicBool, Ordering},
};

use tauri::Manager;

use crate::{authorization, commands, exclusive_file_lease, jobs, live, paths, runtime, stt, tray};

const INSTANCE_LEASE_FILE: &str = ".yap-instance.lock";
// Every request mutation, shutdown transition, and secondary ack/promotion
// decision is ordered by this lease. The shutdown marker remains until a new
// process owns INSTANCE_LEASE_FILE and clears both protocol markers.
const INSTANCE_ACTIVATION_HANDOFF_LEASE_FILE: &str = ".yap-instance-activation-handoff.lock";
const INSTANCE_ACTIVATION_REQUEST_FILE: &str = ".yap-instance-activation.request";
const INSTANCE_ACTIVATION_REQUEST: &[u8] = b"yap-instance-activation-v1\n";
const INSTANCE_SHUTDOWN_FILE: &str = ".yap-instance-shutdown";
const INSTANCE_SHUTDOWN: &[u8] = b"yap-instance-shutdown-v1\n";
const INSTANCE_ACTIVATION_TEMP_ATTEMPTS: u8 = 32;
const INSTANCE_ACTIVATION_QUARANTINE_ATTEMPTS: u8 = 32;
const INSTANCE_ACTIVATION_HANDOFF_POLLS: usize = 200;
const INSTANCE_ACTIVATION_HANDOFF_POLL_INTERVAL: std::time::Duration =
    std::time::Duration::from_millis(25);
static ACTIVATION_REQUEST_ERROR_LOGGED: AtomicBool = AtomicBool::new(false);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ExitRequestDisposition {
    PreventAndFinalize,
    Allow,
}

#[derive(Debug, PartialEq, Eq)]
enum InstanceActivationHandoff<T> {
    Acknowledged,
    Acquired(T),
}

fn exit_request_disposition(exit_authorized: bool) -> ExitRequestDisposition {
    if exit_authorized {
        ExitRequestDisposition::Allow
    } else {
        ExitRequestDisposition::PreventAndFinalize
    }
}

fn is_allowed_app_navigation(url: &tauri::Url) -> bool {
    if !url.username().is_empty() || url.password().is_some() {
        return false;
    }
    match (url.scheme(), url.host_str(), url.port()) {
        ("tauri", Some("localhost"), None) => true,
        ("http" | "https", Some("tauri.localhost"), None) => true,
        ("http", Some("localhost"), Some(1420)) if cfg!(debug_assertions) => true,
        ("about", None, None) => url.path() == "blank" && url.query().is_none(),
        _ => false,
    }
}

fn navigation_guard<R: tauri::Runtime>() -> tauri::plugin::TauriPlugin<R> {
    tauri::plugin::Builder::new("navigation-guard")
        .on_navigation(|_, url| is_allowed_app_navigation(url))
        .build()
}

fn log_lifecycle_shutdown_errors(errors: Vec<String>) {
    for error in errors {
        crate::diagnostics::log(&format!("desktop background shutdown failed: {error}"));
    }
}

fn start_owned_background_work(
    app: &tauri::AppHandle,
    lifecycle: &runtime::DesktopLifecycle,
    live_runtime: live::runtime::LiveRuntime,
) -> std::io::Result<()> {
    let result = (|| {
        lifecycle.spawn_periodic(
            "live-model-idle-monitor",
            std::time::Duration::from_secs(60),
            move || live_runtime.unload_if_idle(std::time::Duration::from_secs(600)),
        )?;
        jobs::start_remote_job_drain(app, lifecycle)?;
        let overlay_app = app.clone();
        let mut recovery_ticks = 0_u8;
        // 40 ms because this poll now drives the bezel reveal, and a reveal is
        // a direct response to the pointer: at 125 ms the pill visibly lags the
        // hand. The other two passes stay on their original cadence by counting
        // ticks rather than by running more often.
        let mut activation_ticks = 0_u8;
        lifecycle.spawn_periodic(
            "live-overlay-monitor",
            std::time::Duration::from_millis(40),
            move || {
                live::overlay_window::sync_reveal(&overlay_app);
                activation_ticks = activation_ticks.saturating_add(1);
                if activation_ticks < 3 {
                    return;
                }
                activation_ticks = 0;
                consume_existing_instance_activation_request(&overlay_app);
                live::overlay_window::follow_cursor_if_idle(&overlay_app);
                recovery_ticks = recovery_ticks.saturating_add(1);
                if recovery_ticks >= 16 {
                    live::overlay_window::recover(&overlay_app);
                    recovery_ticks = 0;
                }
            },
        )
    })();
    if result.is_err() {
        log_lifecycle_shutdown_errors(lifecycle.shutdown());
    }
    result
}

fn write_startup_migration_diagnostic(
    directory: &std::path::Path,
    detail: &str,
) -> std::io::Result<std::path::PathBuf> {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    for attempt in 0..100_u8 {
        let path = directory.join(format!(
            "Yap-startup-migration-error-{}-{nonce}-{attempt}.log",
            std::process::id()
        ));
        match std::fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&path)
        {
            Ok(mut file) => {
                writeln!(file, "Yap stopped before startup to protect existing data.")?;
                writeln!(file, "Migration error: {detail}")?;
                file.flush()?;
                file.sync_all()?;
                return Ok(path);
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::AlreadyExists,
        "could not allocate a unique Yap startup diagnostic",
    ))
}

fn stop_for_migration_error(error: &std::io::Error) -> ! {
    let diagnostic =
        write_startup_migration_diagnostic(&std::env::temp_dir(), &error.to_string()).ok();
    let diagnostic_detail = diagnostic
        .as_ref()
        .map(|path| format!("\n\nDiagnostic: {}", path.display()))
        .unwrap_or_else(|| "\n\nA diagnostic file could not be created.".to_string());
    let message = format!(
        "Yap did not start because its existing data could not be migrated safely. No source data was intentionally deleted. Close any other Yap process and inspect the conflict before trying again.\n\nReason: {error}{diagnostic_detail}"
    );

    #[cfg(windows)]
    show_startup_error_dialog(&message);
    #[cfg(not(windows))]
    eprintln!("{message}");

    std::process::exit(1)
}

mod instance_activation;
use instance_activation::*;
// These two are the only members reached from outside `app`; the rest of
// the module stays internal to it.
pub(crate) use instance_activation::{
    begin_instance_activation_shutdown, reopen_instance_activation_after_abandoned_shutdown,
};

#[cfg(windows)]
fn show_startup_error_dialog(message: &str) {
    use std::{ffi::OsStr, os::windows::ffi::OsStrExt};
    use windows::{
        core::PCWSTR,
        Win32::UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR, MB_OK},
    };

    let message = OsStr::new(message)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let title = OsStr::new("Yap startup stopped")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    unsafe {
        let _ = MessageBoxW(
            None,
            PCWSTR(message.as_ptr()),
            PCWSTR(title.as_ptr()),
            MB_OK | MB_ICONERROR,
        );
    }
}

pub(crate) fn run() {
    // Every branch below announces itself. A second launch that starts a rival
    // process instead of raising the running window has been reported and is
    // not reproducible on demand, and each link in the handoff fails
    // differently: the lease not being exclusive, the request never being
    // written, or the running instance never consuming it. Naming the branch
    // and the directory it resolved turns the next occurrence into evidence
    // rather than another report.
    let app_data_directory = paths::app_data_dir();

    // This guard remains in this stack frame until Tauri's blocking event loop returns.
    let _instance_lease = match acquire_instance_lease_at(&app_data_directory) {
        Ok(lease) => {
            crate::diagnostics::log(&format!(
                "single instance: took the lease in {}",
                app_data_directory.display()
            ));
            lease
        }
        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
            crate::diagnostics::log(&format!(
                "single instance: lease in {} is held, asking the running Yap to show itself",
                app_data_directory.display()
            ));
            match request_existing_instance_activation_or_acquire_lease() {
                Ok(InstanceActivationHandoff::Acknowledged) => {
                    crate::diagnostics::log(
                        "single instance: the running Yap took the request, this launch is exiting",
                    );
                    std::process::exit(0)
                }
                Ok(InstanceActivationHandoff::Acquired(lease)) => {
                    crate::diagnostics::log(
                        "single instance: the previous Yap released its lease mid-handoff, this launch is taking over",
                    );
                    lease
                }
                Err(handoff_error) => {
                    stop_for_instance_lease_error(&std::io::Error::new(
                        handoff_error.kind(),
                        format!(
                            "{error}; could not complete the existing-instance activation handoff: {handoff_error}"
                        ),
                    ));
                }
            }
        }
        Err(error) => stop_for_instance_lease_error(&error),
    };
    if let Err(error) = prepare_primary_instance_activation_state_at(
        &paths::app_data_dir(),
        INSTANCE_ACTIVATION_HANDOFF_POLLS,
        INSTANCE_ACTIVATION_HANDOFF_POLL_INTERVAL,
        std::thread::sleep,
    ) {
        stop_for_instance_lease_error(&std::io::Error::new(
            error.kind(),
            format!("could not prepare the primary activation state: {error}"),
        ));
    }
    if let Err(error) = paths::migrate_legacy_app_data() {
        stop_for_migration_error(&error);
    }
    std::panic::set_hook(Box::new(|panic| {
        crate::diagnostics::log(&format!("panic: {panic}"));
    }));
    crate::diagnostics::log("app start");

    let stt_state = stt::dispatch::SttState::new();
    let live_settings = live::settings::load();
    let live_shortcuts = live::shortcut_runtime::prepare(&live_settings);
    let live_runtime = live::runtime::LiveRuntime::new();
    let live_state = live::LiveSessionState::new(live_settings);
    let fallback_model_install_state = stt::fallback_model::FallbackModelInstallState::new();
    let silero_vad_install_state = stt::silero_vad::SileroVadInstallState::new();
    let acoustic_language_detector_install_state =
        stt::ambernet_language_detector::AcousticLanguageDetectorInstallState::new();
    let live_runtime_for_monitor = live_runtime.clone();
    let live_runtime_for_exit = live_runtime.clone();
    let desktop_lifecycle = runtime::DesktopLifecycle::new();

    let builder = tauri::Builder::default()
        .plugin(navigation_guard())
        .plugin(tauri_plugin_dialog::init());

    #[cfg(feature = "wdio")]
    let builder = builder
        .plugin(tauri_plugin_wdio::init())
        .plugin(tauri_plugin_wdio_webdriver::init());

    let builder = builder
        .manage(stt_state)
        .manage(live_state)
        .manage(live_runtime)
        .manage(live::actions::QuitCoordinator::new())
        .manage(fallback_model_install_state)
        .manage(silero_vad_install_state)
        .manage(acoustic_language_detector_install_state)
        .manage(desktop_lifecycle)
        .setup(move |app| {
            // Import installer-bundled models before anything can want them.
            // Off the setup thread: the Nemotron copy is ~650 MB, and a first
            // launch must not stare at a frozen window while it lands. The
            // download flow stays available behind this, so a build without
            // bundled resources is byte-for-byte today's behavior.
            if let Ok(resource_dir) = app.path().resource_dir() {
                let models_root = crate::stt::model::models_dir();
                tauri::async_runtime::spawn_blocking(move || {
                    crate::stt::bundled_models::import_all(&resource_dir, &models_root);
                });
            }
            live::shortcut_runtime::install(app, live_shortcuts)?;
            jobs::commands::install_native_import_dispatcher(app)?;
            tray::install(app.handle())?;
            let lifecycle = app.state::<runtime::DesktopLifecycle>();
            start_owned_background_work(app.handle(), lifecycle.inner(), live_runtime_for_monitor)?;
            let startup_live = app.state::<live::LiveSessionState>().snapshot();
            if startup_live.visibility == live::state::LiveOverlayVisibility::Enabled {
                let result = if startup_live.status == live::state::LiveSessionStatus::Idle {
                    live::overlay_window::ensure_idle(app.handle())
                } else {
                    live::overlay_window::ensure_active(app.handle())
                };
                if let Err(error) = result {
                    crate::diagnostics::log(&format!("live overlay startup failed: {error}"));
                }
            }
            let live_runtime = app.state::<live::runtime::LiveRuntime>();
            live::actions::warm_on_intent(app.handle(), &live_runtime);
            Ok(())
        });

    commands::register(builder)
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(move |app_handle, event| match event {
            tauri::RunEvent::WebviewEvent {
                label,
                event: tauri::WebviewEvent::DragDrop(tauri::DragDropEvent::Drop { paths, .. }),
                ..
            } if label == authorization::MAIN_WINDOW_LABEL => {
                jobs::commands::enqueue_native_import(app_handle, paths);
            }
            tauri::RunEvent::WindowEvent {
                label,
                event: tauri::WindowEvent::CloseRequested { api, .. },
                ..
            } if label == authorization::MAIN_WINDOW_LABEL => {
                api.prevent_close();
                if let Some(window) =
                    app_handle.get_webview_window(authorization::MAIN_WINDOW_LABEL)
                {
                    let _ = window.hide();
                }
            }
            tauri::RunEvent::WindowEvent {
                label,
                event: tauri::WindowEvent::CloseRequested { api, .. },
                ..
            } if label == authorization::LIVE_OVERLAY_WINDOW_LABEL => {
                api.prevent_close();
            }
            tauri::RunEvent::ExitRequested { api, .. } => {
                let quit = app_handle.state::<live::actions::QuitCoordinator>();
                if exit_request_disposition(quit.exit_authorized())
                    == ExitRequestDisposition::PreventAndFinalize
                {
                    api.prevent_exit();
                    live::actions::quit_from_app(app_handle);
                }
            }
            tauri::RunEvent::Exit => {
                let quit = app_handle.state::<live::actions::QuitCoordinator>();
                if !quit.exit_authorized() {
                    crate::diagnostics::log("process exit reached degraded live shutdown fallback");
                    if let Err(error) = begin_instance_activation_shutdown() {
                        crate::diagnostics::log(&format!(
                            "degraded exit could not publish the instance shutdown handoff: {error}"
                        ));
                    }
                }
                // Authorized quit finalizes the active capture, but the runtime
                // can still own resident warmup models. Always retire it before
                // process exit so model-load snapshots release deterministically.
                live_runtime_for_exit.shutdown();
                let lifecycle = app_handle.state::<runtime::DesktopLifecycle>();
                // Exit callbacks run on Tauri's event loop. Some owned workers
                // can be waiting for that loop while reading or moving a
                // window, so this last-resort path must signal without joining.
                lifecycle.request_shutdown();
            }
            _ => {}
        });
}

#[cfg(test)]
mod tests;
