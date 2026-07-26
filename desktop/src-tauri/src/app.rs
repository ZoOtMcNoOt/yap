use tauri::Manager;

use crate::{authorization, commands, exclusive_file_lease, jobs, live, paths, runtime, stt, tray};

const INSTANCE_LEASE_FILE: &str = ".yap-instance.lock";
const INSTANCE_ACTIVATION_REQUEST_PREFIX: &str = "Yap-existing-instance-activation";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ExitRequestDisposition {
    PreventAndFinalize,
    Allow,
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
        lifecycle.spawn_periodic(
            "live-overlay-monitor",
            std::time::Duration::from_millis(125),
            move || {
                if take_existing_instance_activation_request() {
                    live::actions::show_main_window(&overlay_app);
                }
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
    use std::io::Write;

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

fn acquire_instance_lease_at(
    app_data_directory: &std::path::Path,
) -> std::io::Result<exclusive_file_lease::ExclusiveFileLease> {
    std::fs::create_dir_all(app_data_directory)?;
    let lease_path = app_data_directory.join(INSTANCE_LEASE_FILE);
    match exclusive_file_lease::try_acquire(&lease_path) {
        Ok(lease) => Ok(lease),
        Err(exclusive_file_lease::TryAcquireExclusiveFileLeaseError::Contended) => {
            Err(std::io::Error::new(
                std::io::ErrorKind::WouldBlock,
                format!(
                    "another Yap process owns the application-data directory: {}",
                    app_data_directory.display()
                ),
            ))
        }
        Err(exclusive_file_lease::TryAcquireExclusiveFileLeaseError::Io(error)) => {
            Err(std::io::Error::new(
                error.kind(),
                format!(
                    "could not acquire the Yap instance lease at {}: {error}",
                    lease_path.display()
                ),
            ))
        }
    }
}

fn instance_activation_request_path() -> std::path::PathBuf {
    let app_data_directory = paths::app_data_dir();
    let identity = app_data_directory
        .as_os_str()
        .as_encoded_bytes()
        .iter()
        .fold(0xcbf2_9ce4_8422_2325_u64, |hash, byte| {
            (hash ^ u64::from(*byte)).wrapping_mul(0x0000_0100_0000_01b3)
        });
    std::env::temp_dir().join(format!(
        "{INSTANCE_ACTIVATION_REQUEST_PREFIX}-{:016x}.request",
        identity
    ))
}

fn request_existing_instance_activation_at(path: &std::path::Path) -> std::io::Result<()> {
    match std::fs::create_dir(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => Ok(()),
        Err(error) => Err(error),
    }
}

fn take_existing_instance_activation_request_at(path: &std::path::Path) -> bool {
    match std::fs::remove_dir(path) {
        Ok(()) => true,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
        Err(error) => {
            crate::diagnostics::log(&format!(
                "existing instance activation request could not be consumed: {error}"
            ));
            false
        }
    }
}

fn request_existing_instance_activation() -> std::io::Result<()> {
    request_existing_instance_activation_at(&instance_activation_request_path())
}

fn take_existing_instance_activation_request() -> bool {
    take_existing_instance_activation_request_at(&instance_activation_request_path())
}

fn instance_lease_startup_message(error: &std::io::Error) -> String {
    if error.kind() == std::io::ErrorKind::WouldBlock {
        return format!(
            "Yap is already running. Use the existing Yap tray app, or close the other Yap process before trying again.\n\nReason: {error}"
        );
    }
    format!(
        "Yap did not start because it could not establish exclusive access to its application data. Yap stopped before migration and runtime startup. Resolve the access problem before trying again.\n\nReason: {error}"
    )
}

fn stop_for_instance_lease_error(error: &std::io::Error) -> ! {
    let message = instance_lease_startup_message(error);

    #[cfg(windows)]
    show_startup_error_dialog(&message);
    #[cfg(not(windows))]
    eprintln!("{message}");

    std::process::exit(1)
}

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
    // This guard remains in this stack frame until Tauri's blocking event loop returns.
    let _instance_lease = match acquire_instance_lease_at(&paths::app_data_dir()) {
        Ok(lease) => lease,
        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
            if let Err(signal_error) = request_existing_instance_activation() {
                stop_for_instance_lease_error(&std::io::Error::new(
                    signal_error.kind(),
                    format!(
                        "{error}; could not ask the existing Yap process to show its window: {signal_error}"
                    ),
                ));
            }
            std::process::exit(0);
        }
        Err(error) => stop_for_instance_lease_error(&error),
    };
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
                }
                // Authorized quit finalizes the active capture, but the runtime
                // can still own resident warmup models. Always retire it before
                // process exit so model-load snapshots release deterministically.
                live_runtime_for_exit.shutdown();
                let lifecycle = app_handle.state::<runtime::DesktopLifecycle>();
                log_lifecycle_shutdown_errors(lifecycle.shutdown());
            }
            _ => {}
        });
}

#[cfg(test)]
mod tests {
    use super::{
        acquire_instance_lease_at, exit_request_disposition, instance_lease_startup_message,
        is_allowed_app_navigation, request_existing_instance_activation_at,
        take_existing_instance_activation_request_at, write_startup_migration_diagnostic,
        ExitRequestDisposition,
    };

    #[test]
    fn exit_request_requires_semantic_quit_authorization() {
        assert_eq!(
            exit_request_disposition(false),
            ExitRequestDisposition::PreventAndFinalize
        );
        assert_eq!(
            exit_request_disposition(true),
            ExitRequestDisposition::Allow
        );
    }

    #[test]
    fn navigation_guard_allows_only_application_origins() {
        for allowed in [
            "tauri://localhost/index.html",
            "http://tauri.localhost/index.html",
            "https://tauri.localhost/live-overlay.html",
            "about:blank",
        ] {
            assert!(is_allowed_app_navigation(
                &tauri::Url::parse(allowed).unwrap()
            ));
        }
        for blocked in [
            "https://example.com/",
            "https://tauri.localhost.example.com/",
            "https://user@tauri.localhost/",
            "data:text/html,blocked",
            "file:///C:/private.txt",
        ] {
            assert!(!is_allowed_app_navigation(
                &tauri::Url::parse(blocked).unwrap()
            ));
        }
    }

    #[test]
    fn startup_migration_diagnostic_is_created_outside_app_data() {
        let root = std::env::temp_dir().join(format!(
            "yap-startup-diagnostic-test-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();

        let path = write_startup_migration_diagnostic(&root, "migration conflict").unwrap();

        assert_eq!(path.parent(), Some(root.as_path()));
        assert!(std::fs::read_to_string(&path)
            .unwrap()
            .contains("migration conflict"));
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn startup_instance_lease_maps_contention_to_a_clear_existing_app_message() {
        let root = std::env::temp_dir().join(format!(
            "yap-instance-lease-app-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let first = acquire_instance_lease_at(&root).unwrap();

        let error = match acquire_instance_lease_at(&root) {
            Ok(_) => panic!("a second app startup acquired the instance lease"),
            Err(error) => error,
        };

        assert_eq!(error.kind(), std::io::ErrorKind::WouldBlock);
        let message = instance_lease_startup_message(&error);
        assert!(message.contains("Yap is already running"));
        assert!(message.contains("existing Yap tray app"));
        drop(first);
        acquire_instance_lease_at(&root).unwrap();
        std::fs::remove_dir_all(root).ok();
    }

    #[test]
    fn startup_instance_lease_reports_access_errors_without_claiming_contention() {
        let error = std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "application data is not writable",
        );

        let message = instance_lease_startup_message(&error);

        assert!(message.contains("could not establish exclusive access"));
        assert!(message.contains("stopped before migration and runtime startup"));
        assert!(!message.contains("already running"));
    }

    #[test]
    fn second_instance_activation_request_is_coalesced_and_consumed_once() {
        let request = std::env::temp_dir().join(format!(
            "yap-instance-activation-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));

        assert!(!take_existing_instance_activation_request_at(&request));
        request_existing_instance_activation_at(&request).unwrap();
        request_existing_instance_activation_at(&request).unwrap();
        assert!(take_existing_instance_activation_request_at(&request));
        assert!(!take_existing_instance_activation_request_at(&request));
    }
}
