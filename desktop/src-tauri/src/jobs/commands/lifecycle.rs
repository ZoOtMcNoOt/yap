use super::{
    command_error, log_registry_cleanup_failure, renewed_expiry, JobCommandError, RecordingJobs,
    RetryKind,
};
use crate::{
    jobs::{RecordingJobStatus, RecordingJobView, RecordingRoute, SessionOrigin},
    media_protocol::MediaOwner,
};
use std::collections::HashSet;

impl RecordingJobs {
    pub(super) fn snapshot(
        &self,
        media: &MediaOwner,
        now_ms: u64,
    ) -> Result<Vec<RecordingJobView>, JobCommandError> {
        let _mutation = self.mutation().lock().map_err(|_| {
            command_error(
                "JOB_STATE_UNAVAILABLE",
                "Recording job state is unavailable.",
            )
        })?;
        self.ledger().expire_pending_jobs(now_ms)?;
        let (expired_remote_job_ids, _) = self.ledger().enforce_remote_retention(now_ms)?;
        for job_id in expired_remote_job_ids {
            self.resources.cancel_preprocessing(&job_id);
            self.remove_remote_spool_best_effort(&job_id, "retention");
        }
        let mut views = Vec::new();
        let mut recoverable_ids = HashSet::new();
        let mut authorized_paths = Vec::new();
        let mut recoverable_paths = Vec::new();
        for record in self.ledger().list_recoverable_jobs()? {
            recoverable_ids.insert(record.job_id.clone());
            let has_client_preflight = self
                .ledger()
                .get_client_preflight_artifact(&record.job_id)?
                .is_some();
            let has_owned_capture =
                record.capture_manifest_sha256.is_some() || has_client_preflight;
            let projection = if record.status == RecordingJobStatus::Accepted
                && record.session_origin == SessionOrigin::ImportedFile
                && record.route == Some(RecordingRoute::ServerBatch)
                && record.asr_catalog_binding.is_some()
            {
                record
                    .source_path
                    .as_deref()
                    .ok_or_else(|| {
                        command_error("SOURCE_UNSAFE", "Imported recording has no source path.")
                    })
                    .and_then(|source_path| self.validate_source(source_path))
                    .and_then(|source| {
                        let expires_at_ms = record.expires_at_ms.ok_or_else(|| {
                            command_error(
                                "JOB_TIME_OUT_OF_RANGE",
                                "Accepted recording has no bounded retention deadline.",
                            )
                        })?;
                        self.project_and_activate_accepted_import(
                            record.clone(),
                            source,
                            media,
                            now_ms,
                            expires_at_ms,
                        )
                    })
            } else if has_owned_capture {
                Ok(self.project_prepared_without_external_playback(record.clone(), media))
            } else {
                self.project_with_playback(record.clone(), media)
            };
            match projection {
                Ok(view) => {
                    let view = self.attach_language_review(&record, view)?;
                    if view.playback_path.is_some() {
                        if let Some(source_path) = record.source_path.clone() {
                            authorized_paths.push(source_path.clone());
                            recoverable_paths.push(source_path);
                        }
                    } else if !has_owned_capture {
                        if let Some(source_path) = record.source_path.clone() {
                            recoverable_paths.push(source_path);
                        }
                    }
                    views.push(view);
                }
                Err(error) if error.code == "SOURCE_MISSING" || error.code == "SOURCE_UNSAFE" => {
                    let failed = self.ledger().fail_source_validation(
                        &record.job_id,
                        &error.code,
                        now_ms,
                    )?;
                    self.resources.cancel_preprocessing(&record.job_id);
                    if record.capture_manifest_sha256.is_none() {
                        if let Some(source_path) = record.source_path.clone() {
                            recoverable_paths.push(source_path);
                        }
                    }
                    views.push(self.project_failed_capability_free(&failed, media));
                }
                Err(error) => return Err(error),
            }
        }
        self.reconcile_playback(&recoverable_ids, media)?;
        if let Err(error) = crate::recording_access::reconcile_recording_job_playback_paths_at(
            &authorized_paths,
            &self.registry_path,
        ) {
            log_registry_cleanup_failure("snapshot reconciliation", &error);
        }
        if let Err(error) = crate::recording_access::reconcile_recording_job_playback_paths_at(
            &recoverable_paths,
            &self.selection_registry_path,
        ) {
            log_registry_cleanup_failure("native selection reconciliation", &error);
        }
        Ok(views)
    }

    pub(super) fn cancel(
        &self,
        media: &MediaOwner,
        job_id: &str,
        now_ms: u64,
        notify: impl FnOnce(),
    ) -> Result<RecordingJobView, JobCommandError> {
        self.cancel_after_acquiring_mutation(media, job_id, now_ms, || {}, notify)
    }

    fn cancel_after_acquiring_mutation(
        &self,
        media: &MediaOwner,
        job_id: &str,
        now_ms: u64,
        after_acquiring_mutation: impl FnOnce(),
        notify: impl FnOnce(),
    ) -> Result<RecordingJobView, JobCommandError> {
        let mutation = self.mutation().lock().map_err(|_| {
            command_error(
                "JOB_STATE_UNAVAILABLE",
                "Recording job state is unavailable.",
            )
        })?;
        after_acquiring_mutation();
        let record = self.ledger().request_cancellation(job_id, now_ms)?;
        self.resources.cancel_preprocessing(job_id);
        self.release_playback(job_id, media);
        self.remove_all_job_authority_best_effort(record.source_path.as_deref(), "cancellation");
        self.remove_remote_spool_best_effort(job_id, "cancellation");
        let view = RecordingJobView::from_record(&record);
        drop(mutation);
        notify();
        Ok(view)
    }

    #[cfg(test)]
    pub(in crate::jobs) fn cancel_with_mutation_observer_for_test(
        &self,
        media: &MediaOwner,
        job_id: &str,
        now_ms: u64,
        after_acquiring_mutation: impl FnOnce(),
    ) -> Result<RecordingJobView, JobCommandError> {
        self.cancel_after_acquiring_mutation(media, job_id, now_ms, after_acquiring_mutation, || {})
    }

    pub(super) fn retry(
        &self,
        media: &MediaOwner,
        job_id: &str,
        now_ms: u64,
        notify: impl FnOnce(),
    ) -> Result<RecordingJobView, JobCommandError> {
        let mutation = self.mutation().lock().map_err(|_| {
            command_error(
                "JOB_STATE_UNAVAILABLE",
                "Recording job state is unavailable.",
            )
        })?;
        let current = self.ledger().get_job(job_id)?.ok_or_else(|| {
            command_error(
                "JOB_NOT_FOUND",
                format!("Recording job {job_id:?} was not found."),
            )
        })?;
        let retry_kind = match current.status {
            RecordingJobStatus::Accepted => RetryKind::Accepted,
            RecordingJobStatus::BlockedSetupRequired
            | RecordingJobStatus::BlockedServerUnavailable
            | RecordingJobStatus::BlockedSignInRequired
            | RecordingJobStatus::Failed => RetryKind::Retry,
            RecordingJobStatus::QueuedServer => RetryKind::Unchanged,
            _ => {
                return Err(command_error(
                    "INVALID_JOB_TRANSITION",
                    format!("Recording job {job_id:?} cannot be retried from its current state."),
                ));
            }
        };
        let prepared_remote = if matches!(&retry_kind, RetryKind::Retry) {
            self.ledger().get_prepared_remote_job(job_id)?
        } else {
            None
        };
        let client_preflight =
            if matches!(&retry_kind, RetryKind::Retry) && prepared_remote.is_none() {
                self.ledger().get_client_preflight_artifact(job_id)?
            } else {
                None
            };
        let has_prepared_capture = prepared_remote.is_some();
        let has_client_preflight = client_preflight.is_some();
        let has_bound_server_job = prepared_remote
            .as_ref()
            .is_some_and(|prepared| prepared.server_job_id.is_some());
        if matches!(&retry_kind, RetryKind::Retry)
            && current.error_code.as_deref() == Some("PENDING_EXPIRED")
            && current.language_decision_locked
            && current.client_stage_history_complete
        {
            return Err(command_error(
                "RECORDING_DATA_EXPIRED",
                "Yap already removed this recording's private preprocessing data. Dismiss this item and add the original recording again.",
            ));
        }
        let removes_prior_remote_spool = matches!(&retry_kind, RetryKind::Retry)
            && !has_prepared_capture
            && !has_client_preflight;
        let source = if has_prepared_capture || has_client_preflight {
            None
        } else {
            let source = current.source_path.as_deref().ok_or_else(|| {
                command_error("SOURCE_UNSAFE", "Imported recording has no source path.")
            })?;
            Some(self.validate_source(source)?)
        };

        let (record, changed, activate_accepted) = match retry_kind {
            RetryKind::Accepted => (current, true, true),
            RetryKind::Retry => {
                let record = if has_bound_server_job {
                    self.ledger().request_bound_server_stage_retry(
                        job_id,
                        now_ms,
                        Some(renewed_expiry(now_ms)?),
                    )?
                } else if has_client_preflight || !current.language_decision_locked {
                    self.ledger().retry_with_expiry(
                        job_id,
                        now_ms,
                        Some(renewed_expiry(now_ms)?),
                    )?
                } else {
                    self.ledger().retry_to_queued_server(
                        job_id,
                        now_ms,
                        Some(renewed_expiry(now_ms)?),
                    )?
                };
                (record, true, false)
            }
            RetryKind::Unchanged => (current, false, false),
        };
        if removes_prior_remote_spool {
            self.remove_remote_spool_best_effort(job_id, "retry");
        }
        let view = if activate_accepted {
            self.project_and_activate_accepted_import(
                record,
                source.expect("accepted retry validated its external source"),
                media,
                now_ms,
                renewed_expiry(now_ms)?,
            )?
        } else if record.capture_manifest_sha256.is_some() || has_client_preflight {
            self.project_prepared_without_external_playback(record, media)
        } else {
            self.project_committed_or_fail(
                record,
                source.expect("unprepared retry validated its external source"),
                media,
                now_ms,
            )?
        };
        let current = self.ledger().get_job(job_id)?.ok_or_else(|| {
            command_error(
                "JOB_NOT_FOUND",
                "The recording disappeared after its retry was committed.",
            )
        })?;
        let view = self.attach_language_review(&current, view)?;
        drop(mutation);
        if changed {
            notify();
        }
        Ok(view)
    }

    pub(super) fn dismiss(
        &self,
        media: &MediaOwner,
        job_id: &str,
        now_ms: u64,
        notify: impl FnOnce(),
    ) -> Result<RecordingJobView, JobCommandError> {
        let mutation = self.mutation().lock().map_err(|_| {
            command_error(
                "JOB_STATE_UNAVAILABLE",
                "Recording job state is unavailable.",
            )
        })?;
        let record = self.ledger().dismiss_failed(job_id, now_ms)?;
        self.release_playback(job_id, media);
        self.remove_all_job_authority_best_effort(record.source_path.as_deref(), "dismissal");
        self.remove_remote_spool_best_effort(job_id, "dismissal");
        let view = RecordingJobView::from_record(&record);
        drop(mutation);
        notify();
        Ok(view)
    }
}
