use crate::live::runtime::LiveRuntime;
use crate::{authorization, live, runtime_policy, stt};
use tauri::Emitter;
use tauri_plugin_dialog::DialogExt;

#[tauri::command]
pub(super) fn setup_status(
    window: tauri::WebviewWindow,
    _state: tauri::State<'_, stt::dispatch::SttState>,
) -> Result<runtime_policy::SetupStatus, String> {
    authorization::ensure_main(&window)?;
    Ok(runtime_policy::current_setup_status())
}

#[tauri::command]
pub(super) fn fallback_model_status(
    window: tauri::WebviewWindow,
    install_state: tauri::State<'_, stt::fallback_model::FallbackModelInstallState>,
) -> Result<stt::nemotron::FallbackModelView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    Ok(stt::fallback_model::status(install_state.inner()))
}

#[tauri::command]
pub(super) async fn fallback_model_install(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    install_state: tauri::State<'_, stt::fallback_model::FallbackModelInstallState>,
    live_state: tauri::State<'_, live::LiveSessionState>,
    live_runtime: tauri::State<'_, LiveRuntime>,
    force: Option<bool>,
) -> Result<stt::nemotron::FallbackModelView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    let model_mutation = begin_fallback_model_mutation(&live_state, &live_runtime)?;
    stt::fallback_model::install(
        app,
        install_state.inner().clone(),
        force.unwrap_or(false),
        model_mutation,
    )
    .await
}

#[tauri::command]
pub(super) fn fallback_model_cancel_install(
    window: tauri::WebviewWindow,
    install_state: tauri::State<'_, stt::fallback_model::FallbackModelInstallState>,
) -> Result<stt::nemotron::FallbackModelView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    stt::fallback_model::cancel_install(install_state.inner())
}

#[tauri::command]
pub(super) async fn fallback_model_verify(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    install_state: tauri::State<'_, stt::fallback_model::FallbackModelInstallState>,
    live_state: tauri::State<'_, live::LiveSessionState>,
    live_runtime: tauri::State<'_, LiveRuntime>,
) -> Result<stt::nemotron::FallbackModelView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    ensure_fallback_setup_idle(&live_state, &live_runtime)?;
    stt::fallback_model::verify(app, install_state.inner().clone()).await
}

#[tauri::command]
pub(super) fn fallback_model_remove(
    window: tauri::WebviewWindow,
    install_state: tauri::State<'_, stt::fallback_model::FallbackModelInstallState>,
    live_state: tauri::State<'_, live::LiveSessionState>,
    live_runtime: tauri::State<'_, LiveRuntime>,
) -> Result<stt::nemotron::FallbackModelView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    let _model_mutation = begin_fallback_model_mutation(&live_state, &live_runtime)?;
    stt::fallback_model::remove(install_state.inner())
}

#[tauri::command]
pub(super) fn fallback_model_set_enabled(
    window: tauri::WebviewWindow,
    install_state: tauri::State<'_, stt::fallback_model::FallbackModelInstallState>,
    live_state: tauri::State<'_, live::LiveSessionState>,
    live_runtime: tauri::State<'_, LiveRuntime>,
    enabled: bool,
) -> Result<stt::nemotron::FallbackModelView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    let _model_mutation = if enabled {
        ensure_fallback_setup_idle(&live_state, &live_runtime)?;
        None
    } else {
        Some(begin_fallback_model_mutation(&live_state, &live_runtime)?)
    };
    stt::fallback_model::set_enabled(install_state.inner(), enabled)
}

#[tauri::command]
pub(super) fn fallback_model_open_folder(
    window: tauri::WebviewWindow,
    _app: tauri::AppHandle,
) -> Result<(), stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    stt::fallback_model::open_folder()
}

#[tauri::command]
pub(super) fn silero_vad_status(
    window: tauri::WebviewWindow,
    install_state: tauri::State<'_, stt::silero_vad::SileroVadInstallState>,
) -> Result<stt::silero_vad::SileroVadView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    let mut view = stt::silero_vad::status();
    view.install_active = install_state.is_active();
    Ok(view)
}

#[tauri::command]
pub(super) async fn silero_vad_install(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    live_state: tauri::State<'_, live::LiveSessionState>,
    live_runtime: tauri::State<'_, LiveRuntime>,
    install_state: tauri::State<'_, stt::silero_vad::SileroVadInstallState>,
) -> Result<stt::silero_vad::SileroVadView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    let _model_mutation = begin_language_support_mutation(&live_state, &live_runtime)?;
    let operation = install_state
        .begin()
        .map_err(stt::dispatch::SttCommandError::from)?;
    let worker_operation = operation.clone();
    let joined = tauri::async_runtime::spawn_blocking(move || {
        stt::silero_vad::install(&worker_operation, |progress| {
            let _ = app.emit("silero-vad-progress", progress);
        })
    })
    .await;
    install_state.finish(&operation);
    let result = joined
        .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::SidecarCrash))?;
    if operation.take_cleanup_failure().is_some() {
        return Err(stt::dispatch::SttCommandError::from(
            stt::error::SttError::ModelMissing,
        ));
    }
    result.map_err(stt::dispatch::SttCommandError::from)
}

#[tauri::command]
pub(super) async fn silero_vad_import_file(
    window: tauri::WebviewWindow,
    live_state: tauri::State<'_, live::LiveSessionState>,
    live_runtime: tauri::State<'_, LiveRuntime>,
    install_state: tauri::State<'_, stt::silero_vad::SileroVadInstallState>,
    source_path: String,
) -> Result<stt::silero_vad::SileroVadView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    let _model_mutation = begin_language_support_mutation(&live_state, &live_runtime)?;
    let source_path = std::path::PathBuf::from(source_path);
    if !source_path.is_absolute() {
        return Err(stt::dispatch::SttCommandError::from(
            stt::error::SttError::ModelMissing,
        ));
    }
    let operation = install_state
        .begin()
        .map_err(stt::dispatch::SttCommandError::from)?;
    let worker_operation = operation.clone();
    let joined = tauri::async_runtime::spawn_blocking(move || {
        stt::silero_vad::import_from_file(&source_path, &worker_operation)
    })
    .await;
    install_state.finish(&operation);
    let result = joined
        .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::SidecarCrash))?;
    if operation.take_cleanup_failure().is_some() {
        return Err(stt::dispatch::SttCommandError::from(
            stt::error::SttError::ModelMissing,
        ));
    }
    result.map_err(stt::dispatch::SttCommandError::from)
}

#[tauri::command]
pub(super) fn silero_vad_cancel_install(
    window: tauri::WebviewWindow,
    install_state: tauri::State<'_, stt::silero_vad::SileroVadInstallState>,
) -> Result<stt::silero_vad::SileroVadView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    install_state.cancel();
    let mut view = stt::silero_vad::status();
    view.install_active = install_state.is_active();
    Ok(view)
}

#[tauri::command]
pub(super) async fn silero_vad_verify(
    window: tauri::WebviewWindow,
    install_state: tauri::State<'_, stt::silero_vad::SileroVadInstallState>,
) -> Result<stt::silero_vad::SileroVadView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    let operation = install_state
        .begin()
        .map_err(stt::dispatch::SttCommandError::from)?;
    let joined = tauri::async_runtime::spawn_blocking(stt::silero_vad::verify).await;
    install_state.finish(&operation);
    let result = joined
        .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::SidecarCrash))?;
    result.map_err(stt::dispatch::SttCommandError::from)
}

#[tauri::command]
pub(super) async fn silero_vad_remove(
    window: tauri::WebviewWindow,
    live_state: tauri::State<'_, live::LiveSessionState>,
    live_runtime: tauri::State<'_, LiveRuntime>,
    install_state: tauri::State<'_, stt::silero_vad::SileroVadInstallState>,
) -> Result<stt::silero_vad::SileroVadView, stt::dispatch::SttCommandError> {
    authorization::ensure_main_stt(&window)?;
    let _model_mutation = begin_language_support_mutation(&live_state, &live_runtime)?;
    let operation = install_state
        .begin()
        .map_err(stt::dispatch::SttCommandError::from)?;
    let joined = tauri::async_runtime::spawn_blocking(stt::silero_vad::remove).await;
    install_state.finish(&operation);
    let result = joined
        .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::SidecarCrash))?;
    result.map_err(stt::dispatch::SttCommandError::from)
}

#[tauri::command]
pub(super) async fn acoustic_language_detector_status(
    window: tauri::WebviewWindow,
    install_state: tauri::State<
        '_,
        stt::ambernet_language_detector::AcousticLanguageDetectorInstallState,
    >,
) -> Result<
    stt::ambernet_language_detector::AcousticLanguageDetectorView,
    stt::dispatch::SttCommandError,
> {
    authorization::ensure_main_stt(&window)?;
    let mut view = tauri::async_runtime::spawn_blocking(stt::ambernet_language_detector::status)
        .await
        .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::SidecarCrash))?;
    view.install_active = install_state.is_active();
    Ok(view)
}

#[tauri::command]
pub(super) async fn acoustic_language_detector_import(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    live_state: tauri::State<'_, live::LiveSessionState>,
    live_runtime: tauri::State<'_, LiveRuntime>,
    install_state: tauri::State<
        '_,
        stt::ambernet_language_detector::AcousticLanguageDetectorInstallState,
    >,
) -> Result<
    stt::ambernet_language_detector::AcousticLanguageDetectorView,
    stt::dispatch::SttCommandError,
> {
    authorization::ensure_main_stt(&window)?;
    let picker_app = app.clone();
    let selected = tauri::async_runtime::spawn_blocking(move || {
        picker_app
            .dialog()
            .file()
            .set_title("Choose the verified AmberNet language detector")
            .add_filter("AmberNet ONNX model", &["onnx"])
            .blocking_pick_file()
    })
    .await
    .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::SidecarCrash))?;
    let Some(selected) = selected else {
        return acoustic_language_detector_status(window, install_state).await;
    };
    let source_path = selected
        .into_path()
        .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::ModelMissing))?;
    let _model_mutation = begin_language_support_mutation(&live_state, &live_runtime)?;
    let operation = install_state
        .begin()
        .map_err(stt::dispatch::SttCommandError::from)?;
    let worker_operation = operation.clone();
    let joined = tauri::async_runtime::spawn_blocking(move || {
        stt::ambernet_language_detector::import_from_file(&source_path, &worker_operation)
    })
    .await;
    install_state.finish(&operation);
    finish_auxiliary_model_operation(joined, &operation)
}

#[tauri::command]
pub(super) async fn acoustic_language_detector_cancel_import(
    window: tauri::WebviewWindow,
    install_state: tauri::State<
        '_,
        stt::ambernet_language_detector::AcousticLanguageDetectorInstallState,
    >,
) -> Result<
    stt::ambernet_language_detector::AcousticLanguageDetectorView,
    stt::dispatch::SttCommandError,
> {
    authorization::ensure_main_stt(&window)?;
    install_state.cancel();
    let mut view = tauri::async_runtime::spawn_blocking(stt::ambernet_language_detector::status)
        .await
        .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::SidecarCrash))?;
    view.install_active = install_state.is_active();
    Ok(view)
}

#[tauri::command]
pub(super) async fn acoustic_language_detector_verify(
    window: tauri::WebviewWindow,
    install_state: tauri::State<
        '_,
        stt::ambernet_language_detector::AcousticLanguageDetectorInstallState,
    >,
) -> Result<
    stt::ambernet_language_detector::AcousticLanguageDetectorView,
    stt::dispatch::SttCommandError,
> {
    authorization::ensure_main_stt(&window)?;
    let operation = install_state
        .begin()
        .map_err(stt::dispatch::SttCommandError::from)?;
    let joined =
        tauri::async_runtime::spawn_blocking(stt::ambernet_language_detector::verify).await;
    install_state.finish(&operation);
    let result = joined
        .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::SidecarCrash))?;
    result.map_err(stt::dispatch::SttCommandError::from)
}

#[tauri::command]
pub(super) async fn acoustic_language_detector_remove(
    window: tauri::WebviewWindow,
    live_state: tauri::State<'_, live::LiveSessionState>,
    live_runtime: tauri::State<'_, LiveRuntime>,
    install_state: tauri::State<
        '_,
        stt::ambernet_language_detector::AcousticLanguageDetectorInstallState,
    >,
) -> Result<
    stt::ambernet_language_detector::AcousticLanguageDetectorView,
    stt::dispatch::SttCommandError,
> {
    authorization::ensure_main_stt(&window)?;
    let _model_mutation = begin_language_support_mutation(&live_state, &live_runtime)?;
    let operation = install_state
        .begin()
        .map_err(stt::dispatch::SttCommandError::from)?;
    let joined =
        tauri::async_runtime::spawn_blocking(stt::ambernet_language_detector::remove).await;
    install_state.finish(&operation);
    let result = joined
        .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::SidecarCrash))?;
    result.map_err(stt::dispatch::SttCommandError::from)
}

fn finish_auxiliary_model_operation<T>(
    joined: Result<Result<T, stt::error::SttError>, tauri::Error>,
    operation: &stt::model::DownloadOperation,
) -> Result<T, stt::dispatch::SttCommandError> {
    let result = joined
        .map_err(|_| stt::dispatch::SttCommandError::from(stt::error::SttError::SidecarCrash))?;
    if operation.take_cleanup_failure().is_some() {
        return Err(stt::dispatch::SttCommandError::from(
            stt::error::SttError::ModelMissing,
        ));
    }
    result.map_err(stt::dispatch::SttCommandError::from)
}

#[tauri::command]
pub(super) fn list_local_compute_targets(
    window: tauri::WebviewWindow,
) -> Result<Vec<LocalComputeTargetView>, String> {
    authorization::ensure_main(&window)?;
    Ok(local_compute_targets())
}

#[tauri::command]
pub(super) fn set_local_compute_target(
    window: tauri::WebviewWindow,
    live_state: tauri::State<'_, live::LiveSessionState>,
    target_id: String,
) -> Result<Vec<LocalComputeTargetView>, String> {
    authorization::ensure_main(&window)?;
    if live::state::is_live_session_started(live_state.snapshot().status) {
        return Err("Stop live before changing local compute.".into());
    }
    if !local_compute_targets()
        .iter()
        .any(|target| target.id == target_id)
    {
        return Err("Compute target unavailable.".into());
    }
    stt::settings::set_local_compute_target(&target_id)
        .map_err(|_| "Failed to save compute target.".to_string())?;
    Ok(local_compute_targets())
}

fn ensure_fallback_setup_idle(
    live_state: &live::LiveSessionState,
    live_runtime: &LiveRuntime,
) -> Result<(), stt::dispatch::SttCommandError> {
    if live::state::is_live_session_started(live_state.snapshot().status)
        || live_runtime.is_active()
    {
        return Err(live_setup_busy_error());
    }
    Ok(())
}

fn begin_fallback_model_mutation(
    live_state: &live::LiveSessionState,
    live_runtime: &LiveRuntime,
) -> Result<live::runtime::ModelMutationLease, stt::dispatch::SttCommandError> {
    ensure_fallback_setup_idle(live_state, live_runtime)?;
    live_runtime
        .begin_model_mutation()
        .map_err(|_| live_setup_busy_error())
}

fn begin_language_support_mutation(
    live_state: &live::LiveSessionState,
    live_runtime: &LiveRuntime,
) -> Result<live::runtime::ModelMutationLease, stt::dispatch::SttCommandError> {
    if live::state::is_live_session_started(live_state.snapshot().status)
        || live_runtime.is_active()
    {
        return Err(language_support_busy_error(
            "Stop live before changing local language support.",
        ));
    }
    live_runtime
        .begin_language_support_mutation()
        .map_err(|message| language_support_busy_error(&message))
}

fn language_support_busy_error(message: &str) -> stt::dispatch::SttCommandError {
    stt::dispatch::SttCommandError {
        code: stt::error::SttError::Busy.code().to_string(),
        message: message.into(),
    }
}

fn local_compute_targets() -> Vec<LocalComputeTargetView> {
    let selected_id = stt::settings::saved_compute_target().id();
    let mut targets = vec![
        LocalComputeTargetView {
            id: "auto".into(),
            label: "Auto (CPU)".into(),
            selected: selected_id == "auto",
        },
        LocalComputeTargetView {
            id: "cpu".into(),
            label: "CPU".into(),
            selected: selected_id == "cpu",
        },
    ];
    if !targets.iter().any(|target| target.selected) {
        if let Some(target) = targets.first_mut() {
            target.selected = true;
        }
    }
    targets
}

#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct LocalComputeTargetView {
    id: String,
    label: String,
    selected: bool,
}

fn live_setup_busy_error() -> stt::dispatch::SttCommandError {
    stt::dispatch::SttCommandError {
        code: stt::error::SttError::Busy.code().to_string(),
        message: "Stop live before changing local fallback.".into(),
    }
}
