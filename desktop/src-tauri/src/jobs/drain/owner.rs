use std::sync::Arc;

use crate::{
    audio::session::OwnerNamespace,
    jobs::{
        language_preflight::{language_preflight_outcome, LanguagePreflightOutcome},
        JobLedgerError, RecordingJobResources, RecordingJobStatus,
    },
};

use super::error::{remote_retry_plan, DrainStepError};

#[derive(Debug)]
pub(super) struct DrainRetentionError {
    detail: String,
    durable_state_unavailable: bool,
}

impl DrainRetentionError {
    fn durable(error: impl ToString) -> Self {
        Self {
            detail: error.to_string(),
            durable_state_unavailable: true,
        }
    }

    fn cleanup(error: impl ToString) -> Self {
        Self {
            detail: error.to_string(),
            durable_state_unavailable: false,
        }
    }

    pub(super) fn durable_state_unavailable(&self) -> bool {
        self.durable_state_unavailable
    }
}

impl std::fmt::Display for DrainRetentionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.detail)
    }
}

pub(crate) struct RemoteJobDrain {
    pub(super) resources: Arc<RecordingJobResources>,
    pub(super) owner_namespace: OwnerNamespace,
}

impl RemoteJobDrain {
    pub(crate) fn from_resources(resources: Arc<RecordingJobResources>) -> Result<Self, String> {
        Ok(Self {
            resources,
            owner_namespace: crate::install_identity::load_or_create()?,
        })
    }

    #[cfg(test)]
    pub(in crate::jobs) fn from_resources_for_test(
        resources: Arc<RecordingJobResources>,
        owner_namespace: OwnerNamespace,
    ) -> Self {
        Self {
            resources,
            owner_namespace,
        }
    }

    #[cfg(test)]
    pub(in crate::jobs) fn resources_for_test(&self) -> &Arc<RecordingJobResources> {
        &self.resources
    }

    pub(super) fn has_pending_work(&self) -> Result<bool, String> {
        let jobs = self
            .resources
            .ledger()
            .list_recoverable_jobs()
            .map_err(|error| error.to_string())?;
        let mut active_job = false;
        for job in jobs {
            if matches!(
                job.status,
                RecordingJobStatus::QueuedServer
                    | RecordingJobStatus::Preprocessing
                    | RecordingJobStatus::Uploading
                    | RecordingJobStatus::ServerProcessing
                    | RecordingJobStatus::Saving
            ) {
                active_job = true;
                break;
            }
            if job.status == RecordingJobStatus::Preflighting
                && (job.language_decision_locked
                    || !matches!(
                        language_preflight_outcome(self.resources.ledger(), &job.job_id)
                            .map_err(|error| error.to_string())?,
                        LanguagePreflightOutcome::Review { .. }
                    ))
            {
                active_job = true;
                break;
            }
        }
        Ok(active_job
            || self
                .resources
                .ledger()
                .has_remote_reconciliation_work()
                .map_err(|error| error.to_string())?)
    }

    pub(super) fn enforce_retention(&self, now_ms: u64) -> Result<bool, DrainRetentionError> {
        let _mutation = self.resources.mutation().lock().map_err(|_| {
            DrainRetentionError::durable("recording job mutation gate is unavailable")
        })?;
        let expired_pending = self
            .resources
            .ledger()
            .expire_pending_jobs(now_ms)
            .map_err(DrainRetentionError::durable)?;
        let (expired_remote_job_ids, changed_remote_jobs) = self
            .resources
            .ledger()
            .enforce_remote_retention(now_ms)
            .map_err(DrainRetentionError::durable)?;
        let mut cleanup_error = None;
        for job_id in expired_remote_job_ids {
            self.resources.cancel_preprocessing(&job_id);
            if let Err(error) = self.resources.reset_remote_spool(&job_id) {
                cleanup_error.get_or_insert(error);
            }
        }
        if let Some(error) = cleanup_error {
            return Err(DrainRetentionError::cleanup(error));
        }
        let mut pruned_spools = 0_usize;
        for job_id in self
            .resources
            .ledger()
            .list_pending_remote_spool_cleanup()
            .map_err(DrainRetentionError::durable)?
        {
            self.resources
                .reset_remote_spool(&job_id)
                .map_err(DrainRetentionError::cleanup)?;
            if self
                .resources
                .ledger()
                .acknowledge_remote_spool_cleanup(&job_id)
                .map_err(DrainRetentionError::durable)?
            {
                pruned_spools = pruned_spools.saturating_add(1);
            }
        }
        Ok(expired_pending > 0 || changed_remote_jobs > 0 || pruned_spools > 0)
    }

    pub(super) fn fail_preprocessing_job(
        &self,
        job_id: &str,
        updated_at_ms: u64,
    ) -> Result<(), JobLedgerError> {
        self.resources
            .ledger()
            .record_remote_error(
                job_id,
                "PREPROCESSING_FAILED",
                "The selected recording could not be prepared for private-server transcription.",
                None,
                updated_at_ms,
            )
            .map(|_| ())
    }

    pub(super) fn schedule_remote_retry_for_job(
        &self,
        job_id: &str,
        statuses: &[RecordingJobStatus],
        error: &DrainStepError,
        updated_at_ms: u64,
    ) -> Result<bool, JobLedgerError> {
        let candidate = self.resources.ledger().get_job(job_id)?.filter(|job| {
            statuses.contains(&job.status)
                && job
                    .next_attempt_at_ms
                    .is_none_or(|retry_at| retry_at <= updated_at_ms)
        });
        let Some(candidate) = candidate else {
            return Ok(false);
        };
        if let Some(retry_at_ms) = error.durable_retry_at(updated_at_ms) {
            return self
                .resources
                .ledger()
                .defer_remote_retry(
                    job_id,
                    error.code,
                    error.user_message,
                    retry_at_ms,
                    updated_at_ms,
                )
                .map(|_| true);
        }
        let (retry_at_ms, code, message) =
            remote_retry_plan(error, candidate.attempt_count, updated_at_ms);
        self.resources
            .ledger()
            .record_remote_error(job_id, code, message, retry_at_ms, updated_at_ms)
            .map(|_| true)
    }

    pub(super) fn handle_upload_error(
        &self,
        job_id: &str,
        error: &DrainStepError,
        updated_at_ms: u64,
        catalog_retry_at_ms: u64,
    ) -> Result<bool, JobLedgerError> {
        if error.requires_catalog_revalidation() {
            self.resources
                .ledger()
                .defer_for_catalog_capability(job_id, catalog_retry_at_ms, updated_at_ms)
                .map(|_| true)
        } else {
            self.schedule_remote_retry_for_job(
                job_id,
                &[RecordingJobStatus::Uploading],
                error,
                updated_at_ms,
            )
        }
    }
}
