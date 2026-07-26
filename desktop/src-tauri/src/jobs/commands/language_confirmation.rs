use super::{
    command_error, emit_jobs_changed, ensure_main, now_ms, JobCommandError, RecordingJobs,
};
use crate::{
    jobs::{
        language_preflight::{language_preflight_outcome, LanguagePreflightOutcome},
        RecordingJobStatus, RecordingJobView, RecordingLanguageDecision,
        RecordingLanguageDisposition, RecordingLanguageMode, RecordingLanguageReviewKind,
    },
    server_connector::ServerConnector,
};

impl RecordingJobs {
    pub(super) fn attach_language_review(
        &self,
        record: &crate::jobs::RecordingJobRecord,
        mut view: RecordingJobView,
    ) -> Result<RecordingJobView, JobCommandError> {
        if record.status == RecordingJobStatus::Preflighting && !record.language_decision_locked {
            view.language_review = language_preflight_outcome(self.ledger(), &record.job_id)?
                .review()
                .cloned();
        }
        Ok(view)
    }
}

#[tauri::command]
pub(crate) async fn recording_job_confirm_language(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    jobs: tauri::State<'_, RecordingJobs>,
    connector: tauri::State<'_, ServerConnector>,
    job_id: String,
    language_bcp47: String,
    catalog_revision: String,
) -> Result<RecordingJobView, JobCommandError> {
    ensure_main(&window)?;
    let confirmed_at_ms = now_ms()?;
    let result = crate::server_connector::with_current_asr_capabilities(
        &app,
        connector.inner(),
        |current| {
            if current.catalog().catalog_revision != catalog_revision {
                return Err(command_error(
                    "LANGUAGE_CATALOG_CHANGED",
                    "Server language capabilities changed. Review the language again.",
                ));
            }
            if !current.catalog().supports_fixed_batch(&language_bcp47) {
                return Err(command_error(
                    "LANGUAGE_UNAVAILABLE",
                    "The current private server does not support that fixed recording language.",
                ));
            }
            let _mutation = jobs.mutation().lock().map_err(|_| {
                command_error(
                    "JOB_STATE_UNAVAILABLE",
                    "Recording job state is unavailable.",
                )
            })?;
            let record = jobs.ledger().get_job(&job_id)?.ok_or_else(|| {
                command_error(
                    "JOB_NOT_FOUND",
                    format!("Recording job {job_id:?} was not found."),
                )
            })?;
            if record.status != RecordingJobStatus::Preflighting
                || record.language_decision_locked
                || record.cancellation_requested
            {
                return Err(command_error(
                    "LANGUAGE_REVIEW_UNAVAILABLE",
                    "This recording is no longer waiting for language confirmation.",
                ));
            }
            let artifact = jobs
                .ledger()
                .get_client_preflight_artifact(&job_id)?
                .ok_or_else(|| {
                    command_error(
                        "LANGUAGE_REVIEW_UNAVAILABLE",
                        "Language evidence is not ready yet.",
                    )
                })?;
            if artifact.lid_request_id.is_some() {
                return Err(command_error(
                    "LANGUAGE_REVIEW_UNAVAILABLE",
                    "Language evidence is still running.",
                ));
            }
            let LanguagePreflightOutcome::Review { review, .. } =
                language_preflight_outcome(jobs.ledger(), &job_id)?
            else {
                return Err(command_error(
                    "LANGUAGE_REVIEW_UNAVAILABLE",
                    "Language evidence is not ready yet.",
                ));
            };
            let disposition = if review.kind == RecordingLanguageReviewKind::Suggestion
                && review.suggested_language_bcp47.as_deref() == Some(language_bcp47.as_str())
            {
                RecordingLanguageDisposition::DetectedSuggestionConfirmed
            } else if record.language_decision.language_bcp47.as_deref()
                == Some(language_bcp47.as_str())
                && matches!(
                    record.language_decision.disposition,
                    RecordingLanguageDisposition::Primary
                        | RecordingLanguageDisposition::ManualOverride
                )
            {
                record.language_decision.disposition
            } else {
                RecordingLanguageDisposition::ManualOverride
            };
            let decision = RecordingLanguageDecision::try_new(
                RecordingLanguageMode::Fixed,
                Some(language_bcp47.clone()),
                disposition,
            )
            .map_err(|_| {
                command_error(
                    "LANGUAGE_SELECTION_INVALID",
                    "The selected recording language is invalid.",
                )
            })?;
            let evidence = serde_json::json!({
                "action": if disposition == RecordingLanguageDisposition::DetectedSuggestionConfirmed {
                    "accepted_suggestion"
                } else {
                    "confirmed_manual_selection"
                },
                "reviewCatalogRevision": review.catalog_revision,
                "reviewReason": review.reason,
                "suggestedLanguageBcp47": review.suggested_language_bcp47,
            });
            jobs.ledger()
                .confirm_language_decision(
                    &job_id,
                    &decision,
                    &artifact.source_pcm_sha256,
                    confirmed_at_ms,
                    Some(evidence),
                    Some(current.binding()),
                )
                .map(|record| RecordingJobView::from_record(&record))
                .map_err(JobCommandError::from)
        },
    )
    .await
    .map_err(|detail| {
        crate::diagnostics::log(&format!(
            "language confirmation could not refresh the current ASR catalog: {detail}"
        ));
        command_error(
            "LANGUAGE_CAPABILITIES_UNAVAILABLE",
            "Current ASR language capabilities are unavailable.",
        )
    })?
    .ok_or_else(|| {
        command_error(
            "LANGUAGE_CAPABILITIES_UNAVAILABLE",
            "Current ASR language capabilities are unavailable.",
        )
    })??;
    emit_jobs_changed(&app);
    Ok(result)
}
