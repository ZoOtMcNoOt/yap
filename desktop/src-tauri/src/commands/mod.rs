#[cfg(feature = "wdio")]
mod build_identity;
mod history;
mod live;
mod setup;

pub(crate) fn register(builder: tauri::Builder<tauri::Wry>) -> tauri::Builder<tauri::Wry> {
    let job_resources = std::sync::Arc::new(
        crate::jobs::RecordingJobResources::open_default()
            .expect("recording job resources must open before commands are registered"),
    );
    let recording_jobs = crate::jobs::commands::RecordingJobs::from_default_resources(
        std::sync::Arc::clone(&job_resources),
    );
    let remote_job_drain = crate::jobs::RemoteJobDrain::from_resources(job_resources)
        .expect("remote recording drain must initialize before commands are registered");
    let builder = builder
        .manage(crate::media_protocol::MediaOwner::new())
        .manage(crate::live::hotkey_commands::HotkeyEnrollmentGate::default())
        .manage(history::HistoryCatalogOwner::open_default())
        .manage(recording_jobs)
        .manage(remote_job_drain)
        .manage(crate::server_connector::ServerConnector::new());
    builder.invoke_handler(tauri::generate_handler![
        setup::setup_status,
        crate::language_preferences::desktop::primary_language_status,
        crate::language_preferences::desktop::confirm_primary_language,
        crate::language_preferences::desktop::local_dictation_languages,
        crate::language_preferences::live_routing::desktop::live_language_routing_status,
        crate::language_preferences::live_routing::desktop::set_live_language_routing,
        history::history_catalog,
        history::history_hide_native,
        history::history_language_label_review,
        history::history_append_language_label_correction,
        history::history_migrate_hidden_paths,
        crate::server_connector::server_connection_status,
        crate::server_connector::refresh_server_connection,
        crate::server_connector::server_asr_capabilities,
        crate::server_connector::probe_local_server,
        crate::server_connector::server_settings,
        crate::server_connector::set_server_settings,
        crate::server_connector::server_identity_status,
        crate::server_connector::sign_in_to_server,
        crate::server_connector::sign_out_of_server,
        crate::jobs::commands::recording_jobs_snapshot,
        crate::jobs::commands::recording_jobs_pick_imports,
        crate::jobs::commands::recording_job_cancel,
        crate::jobs::commands::recording_job_dismiss,
        crate::jobs::commands::recording_job_retry,
        crate::jobs::commands::language_confirmation::recording_job_confirm_language,
        setup::fallback_model_status,
        setup::fallback_model_install,
        setup::fallback_model_cancel_install,
        setup::fallback_model_verify,
        setup::fallback_model_remove,
        setup::fallback_model_set_enabled,
        setup::fallback_model_open_folder,
        setup::silero_vad_status,
        setup::silero_vad_install,
        setup::silero_vad_import_file,
        setup::silero_vad_cancel_install,
        setup::silero_vad_verify,
        setup::silero_vad_remove,
        setup::acoustic_language_detector_status,
        setup::acoustic_language_detector_import,
        setup::acoustic_language_detector_cancel_import,
        setup::acoustic_language_detector_verify,
        setup::acoustic_language_detector_remove,
        setup::list_local_compute_targets,
        setup::set_local_compute_target,
        live::live_status,
        live::live_overlay_status,
        live::show_live_overlay,
        live::hide_live_overlay,
        live::set_live_overlay_surface,
        live::set_live_overlay_enabled,
        crate::live::hotkey_commands::record_live_hotkey,
        crate::live::hotkey_commands::clear_live_hotkey,
        crate::live::hotkey_commands::reset_live_hotkey,
        crate::live::hotkey_commands::record_live_paste_hotkey,
        crate::live::hotkey_commands::clear_live_paste_hotkey,
        crate::live::hotkey_commands::reset_live_paste_hotkey,
        live::set_live_capture_mode,
        live::list_input_devices,
        live::set_input_device,
        live::preflight_input_device,
        live::start_live_session,
        live::start_live_overlay_session,
        live::stop_live_session,
        live::stop_live_overlay_session,
        live::recover_live_session,
        live::delete_recoverable_live_session,
        live::delete_saved_live_session,
        live::show_main_workspace,
        setup::polish_num_gpu,
        crate::file_actions::restore_recording_playback_path,
        crate::file_actions::release_recording_playback,
        crate::file_actions::transcripts::resolve_owned_live_transcript_paths,
        crate::file_actions::transcripts::read_text_file,
        crate::file_actions::transcripts::read_text_preview,
        crate::file_actions::transcripts::write_polished_text,
        crate::file_actions::open_app_path,
        crate::file_actions::reveal_app_path,
        #[cfg(feature = "wdio")]
        crate::tray::wdio_dispatch_tray_action,
        #[cfg(feature = "wdio")]
        build_identity::wdio_build_git_sha
    ])
}
