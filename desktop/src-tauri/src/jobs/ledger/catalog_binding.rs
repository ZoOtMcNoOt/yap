//! Revalidates mutable pre-dispatch catalog evidence without changing the
//! immutable per-job language decision.

use std::collections::HashSet;

use rusqlite::{params, OptionalExtension, TransactionBehavior};

use crate::jobs::{
    AsrCatalogBinding, JobLedgerError, NewRecordingJob, RecordingJobRecord, RecordingJobStatus,
    RecordingLanguageDecision, RecordingRoute,
};

use super::{
    insert_validated_job,
    records::{sqlite_integer, validate_catalog_binding, ValidatedJob},
    row_mapping::query_job,
    JobLedger,
};

impl JobLedger {
    pub(crate) fn commit_catalog_imports(
        &self,
        existing_job_ids: &[String],
        new_jobs: &[NewRecordingJob],
        language_decision: &RecordingLanguageDecision,
        binding: &AsrCatalogBinding,
        updated_at_ms: u64,
        maximum_jobs: usize,
    ) -> Result<Vec<RecordingJobRecord>, JobLedgerError> {
        validate_catalog_binding(binding)?;
        language_decision
            .validate()
            .map_err(|_| JobLedgerError::InvalidRecord("language_decision is inconsistent"))?;
        if new_jobs.iter().any(|job| {
            job.language_decision != *language_decision
                || job.asr_catalog_binding.as_ref() != Some(binding)
                || job.status != RecordingJobStatus::Accepted
                || job.route != Some(RecordingRoute::ServerBatch)
        }) {
            return Err(JobLedgerError::InvalidRecord(
                "catalog import batch contains inconsistent language or catalog evidence",
            ));
        }
        let new_jobs = new_jobs
            .iter()
            .map(ValidatedJob::try_from)
            .collect::<Result<Vec<_>, _>>()?;
        let unique_existing = existing_job_ids.iter().collect::<HashSet<_>>();
        if unique_existing.len() != existing_job_ids.len() {
            return Err(JobLedgerError::InvalidRecord(
                "catalog import batch contains duplicate existing jobs",
            ));
        }
        let updated_at_ms = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let stored_jobs: i64 = transaction.query_row(
            "SELECT COUNT(*) FROM recording_jobs WHERE status NOT IN ('complete', 'partial', 'cancelled')",
            [],
            |row| row.get(0),
        )?;
        let stored_jobs = usize::try_from(stored_jobs).map_err(|_| {
            JobLedgerError::InvalidRecord("recording job count is outside the supported range")
        })?;
        if stored_jobs
            .checked_add(new_jobs.len())
            .is_none_or(|total| total > maximum_jobs)
        {
            return Err(JobLedgerError::InvalidRecord(
                "recording job capacity is exhausted",
            ));
        }

        let mut committed = Vec::with_capacity(existing_job_ids.len() + new_jobs.len());
        for job_id in existing_job_ids {
            let current: RecordingJobRecord = query_job(&transaction, job_id)?
                .ok_or_else(|| JobLedgerError::NotFound(job_id.clone()))?
                .try_into()?;
            if current.language_decision != *language_decision {
                return Err(JobLedgerError::InvalidRecord(
                    "existing recording language decision changed during catalog import",
                ));
            }
            if current.route != Some(RecordingRoute::ServerBatch)
                || current.cancellation_requested
                || matches!(
                    current.status,
                    RecordingJobStatus::Complete
                        | RecordingJobStatus::Partial
                        | RecordingJobStatus::Cancelled
                )
            {
                return Err(JobLedgerError::InvalidRecord(
                    "existing recording is no longer eligible for catalog import",
                ));
            }
            let catalog_is_still_mutable = matches!(
                current.status,
                RecordingJobStatus::Accepted
                    | RecordingJobStatus::Preflighting
                    | RecordingJobStatus::QueuedServer
                    | RecordingJobStatus::Preprocessing
                    | RecordingJobStatus::Uploading
            );
            if catalog_is_still_mutable && current.asr_catalog_binding.as_ref() != Some(binding) {
                let dispatch_started = transaction
                    .query_row(
                        "SELECT create_attempt_base_url IS NOT NULL OR server_job_id IS NOT NULL FROM prepared_remote_jobs WHERE job_id = ?1",
                        [job_id],
                        |row| row.get::<_, bool>(0),
                    )
                    .optional()?
                    .unwrap_or(false);
                if !dispatch_started {
                    let changed = transaction.execute(
                        "UPDATE recording_jobs SET asr_catalog_origin = ?1, asr_catalog_revision = ?2, updated_at_ms = ?3 WHERE job_id = ?4 AND route = 'server_batch' AND status IN ('accepted', 'preflighting', 'queued_server', 'preprocessing', 'uploading') AND cancellation_requested = 0",
                        params![
                            binding.origin(),
                            binding.catalog_revision(),
                            updated_at_ms,
                            job_id,
                        ],
                    )?;
                    if changed != 1 {
                        return Err(JobLedgerError::InvalidRecord(
                            "catalog import lost its existing recording",
                        ));
                    }
                }
            }
            committed.push(
                query_job(&transaction, job_id)?
                    .expect("validated existing catalog import job exists")
                    .try_into()?,
            );
        }
        for job in &new_jobs {
            insert_validated_job(&transaction, job)?;
            committed.push(
                query_job(&transaction, &job.job_id)?
                    .expect("inserted catalog import job exists")
                    .try_into()?,
            );
        }
        transaction.commit()?;
        Ok(committed)
    }

    pub(crate) fn bind_and_claim_preprocessing(
        &self,
        job_id: &str,
        binding: &AsrCatalogBinding,
        updated_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        validate_catalog_binding(binding)?;
        let updated_at_ms_sql = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        if current.route != Some(RecordingRoute::ServerBatch)
            || !current.language_decision_locked
            || !matches!(
                current.status,
                RecordingJobStatus::QueuedServer | RecordingJobStatus::Preprocessing
            )
            || current.cancellation_requested
            || current
                .next_attempt_at_ms
                .is_some_and(|retry_at| retry_at > updated_at_ms)
        {
            return Err(JobLedgerError::InvalidRecord(
                "catalog claim requires a due active server-batch preprocessing job",
            ));
        }
        if transaction.query_row(
            "SELECT EXISTS(SELECT 1 FROM prepared_remote_jobs WHERE job_id = ?1)",
            [job_id],
            |row| row.get::<_, bool>(0),
        )? {
            return Err(JobLedgerError::InvalidRecord(
                "catalog claim cannot replace existing prepared remote state",
            ));
        }
        let changed = transaction.execute(
            "UPDATE recording_jobs SET status = 'preprocessing', asr_catalog_origin = ?1, asr_catalog_revision = ?2, error_code = CASE WHEN error_code = 'ASR_CAPABILITY_UNAVAILABLE' THEN NULL ELSE error_code END, error_message = CASE WHEN error_code = 'ASR_CAPABILITY_UNAVAILABLE' THEN NULL ELSE error_message END, next_attempt_at_ms = CASE WHEN error_code = 'ASR_CAPABILITY_UNAVAILABLE' THEN NULL ELSE next_attempt_at_ms END, updated_at_ms = ?3 WHERE job_id = ?4 AND route = 'server_batch' AND status IN ('queued_server', 'preprocessing') AND language_decision_locked = 1 AND cancellation_requested = 0 AND (next_attempt_at_ms IS NULL OR next_attempt_at_ms <= ?3)",
            params![
                binding.origin(),
                binding.catalog_revision(),
                updated_at_ms_sql,
                job_id,
            ],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "catalog claim lost its durable preprocessing job",
            ));
        }
        let claimed = query_job(&transaction, job_id)?.expect("claimed job exists");
        transaction.commit()?;
        claimed.try_into()
    }

    pub(crate) fn rebind_unstarted_server_job(
        &self,
        job_id: &str,
        binding: &AsrCatalogBinding,
        updated_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        validate_catalog_binding(binding)?;
        let updated_at_ms = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        if current.route != Some(RecordingRoute::ServerBatch)
            || !current.language_decision_locked
            || !matches!(
                current.status,
                RecordingJobStatus::Preflighting
                    | RecordingJobStatus::QueuedServer
                    | RecordingJobStatus::Preprocessing
                    | RecordingJobStatus::Uploading
            )
        {
            return Err(JobLedgerError::InvalidRecord(
                "only an active unbound server-batch job can be catalog-revalidated",
            ));
        }
        let remote_binding: Option<(Option<String>, Option<String>)> = transaction
            .query_row(
                "SELECT create_attempt_base_url, server_job_id FROM prepared_remote_jobs WHERE job_id = ?1",
                [job_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        if remote_binding
            .is_some_and(|(attempt, server_job)| attempt.is_some() || server_job.is_some())
        {
            return Err(JobLedgerError::InvalidRecord(
                "ASR catalog binding cannot change after remote dispatch begins",
            ));
        }
        if current.asr_catalog_binding.as_ref() == Some(binding) {
            return Ok(current);
        }
        let changed = transaction.execute(
            "UPDATE recording_jobs SET asr_catalog_origin = ?1, asr_catalog_revision = ?2, error_code = CASE WHEN error_code = 'ASR_CAPABILITY_UNAVAILABLE' THEN NULL ELSE error_code END, error_message = CASE WHEN error_code = 'ASR_CAPABILITY_UNAVAILABLE' THEN NULL ELSE error_message END, next_attempt_at_ms = CASE WHEN error_code = 'ASR_CAPABILITY_UNAVAILABLE' THEN NULL ELSE next_attempt_at_ms END, updated_at_ms = ?3 WHERE job_id = ?4 AND route = 'server_batch' AND status IN ('preflighting', 'queued_server', 'preprocessing', 'uploading')",
            params![
                binding.origin(),
                binding.catalog_revision(),
                updated_at_ms,
                job_id,
            ],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "ASR catalog revalidation lost its durable job",
            ));
        }
        let updated = query_job(&transaction, job_id)?.expect("revalidated job exists");
        transaction.commit()?;
        updated.try_into()
    }

    pub(crate) fn defer_for_catalog_capability(
        &self,
        job_id: &str,
        retry_at_ms: u64,
        updated_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let retry_at_ms = sqlite_integer(retry_at_ms, "next_attempt_at_ms")?;
        let updated_at_ms = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        if current.route != Some(RecordingRoute::ServerBatch)
            || !matches!(
                current.status,
                RecordingJobStatus::Preflighting
                    | RecordingJobStatus::QueuedServer
                    | RecordingJobStatus::Preprocessing
                    | RecordingJobStatus::Uploading
            )
            || (current.status == RecordingJobStatus::Preflighting
                && !current.language_decision_locked)
        {
            return Err(JobLedgerError::InvalidRecord(
                "catalog deferral requires an active server-batch job",
            ));
        }
        transaction.execute(
            "UPDATE recording_jobs SET error_code = 'ASR_CAPABILITY_UNAVAILABLE', error_message = 'The current private server does not advertise this recording language and mode. Yap will retry after capabilities change.', next_attempt_at_ms = ?1, updated_at_ms = ?2 WHERE job_id = ?3 AND status IN ('preflighting', 'queued_server', 'preprocessing', 'uploading')",
            params![retry_at_ms, updated_at_ms, job_id],
        )?;
        let updated = query_job(&transaction, job_id)?.expect("deferred job exists");
        transaction.commit()?;
        updated.try_into()
    }
}
