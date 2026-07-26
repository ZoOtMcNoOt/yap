//! Owns legal job transitions, retry preflight, and durable cancellation intent.

use rusqlite::{params, OptionalExtension, TransactionBehavior};

use crate::jobs::{
    model::{transition_policy, TransitionPolicy},
    JobLedgerError, RecordingJobRecord, RecordingJobStatus, RecordingRoute,
    REMOTE_STAGE_RETRY_REQUESTED,
};

use super::{
    records::{optional_sqlite_integer, sqlite_integer},
    retention::prune_terminal_history,
    row_mapping::query_job,
    JobLedger,
};

const REMOTE_STAGE_RETRY_MESSAGE: &str =
    "Yap is retrying the failed ASR stage against the already uploaded recording.";

struct BoundServerRetryState {
    capture_manifest_sha256: String,
    server_base_url: Option<String>,
    server_job_id: Option<String>,
    cancellation_acknowledged_at_ms: Option<i64>,
    create_attempt_base_url: Option<String>,
}

struct PreparedServerRetryState {
    server_base_url: Option<String>,
    server_job_id: Option<String>,
    cancellation_acknowledged_at_ms: Option<i64>,
    create_attempt_base_url: Option<String>,
}

impl JobLedger {
    #[cfg(test)]
    pub fn transition(
        &self,
        job_id: &str,
        to: RecordingJobStatus,
        updated_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let updated_at_ms = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let raw = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?;
        let current: RecordingJobRecord = raw.try_into()?;
        match transition_policy(current.status, to) {
            TransitionPolicy::Ordinary => {}
            TransitionPolicy::Retry => return Err(JobLedgerError::RetryRequired),
            TransitionPolicy::Cancellation => return Err(JobLedgerError::CancellationRequired),
            TransitionPolicy::Dismiss => return Err(JobLedgerError::DismissRequired),
            TransitionPolicy::Forbidden => {
                return Err(JobLedgerError::InvalidTransition {
                    from: current.status,
                    to,
                });
            }
        }
        transaction.execute(
            "UPDATE recording_jobs SET status = ?1, updated_at_ms = ?2 WHERE job_id = ?3",
            params![to.as_db(), updated_at_ms, job_id],
        )?;
        let updated = query_job(&transaction, job_id)?.expect("updated job exists");
        if matches!(
            to,
            RecordingJobStatus::Complete
                | RecordingJobStatus::Partial
                | RecordingJobStatus::Cancelled
        ) {
            prune_terminal_history(&transaction, Some(job_id))?;
        }
        transaction.commit()?;
        updated.try_into()
    }

    pub(crate) fn begin_remote_preprocessing(
        &self,
        job_id: &str,
        updated_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let updated_at_ms = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        if current.status != RecordingJobStatus::QueuedServer
            || current.route != Some(RecordingRoute::ServerBatch)
            || !current.language_decision_locked
            || current.cancellation_requested
            || transition_policy(current.status, RecordingJobStatus::Preprocessing)
                != TransitionPolicy::Ordinary
        {
            return Err(JobLedgerError::InvalidTransition {
                from: current.status,
                to: RecordingJobStatus::Preprocessing,
            });
        }
        let changed = transaction.execute(
            "UPDATE recording_jobs SET status = 'preprocessing', updated_at_ms = ?1 WHERE job_id = ?2 AND status = 'queued_server' AND route = 'server_batch' AND language_decision_locked = 1 AND cancellation_requested = 0",
            params![updated_at_ms, job_id],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "server preprocessing claim lost its durable admission state",
            ));
        }
        let updated = query_job(&transaction, job_id)?.expect("claimed preprocessing job exists");
        transaction.commit()?;
        updated.try_into()
    }

    pub fn accept_to_queued_server(
        &self,
        job_id: &str,
        updated_at_ms: u64,
        expires_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let updated_at_ms = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let expires_at_ms = sqlite_integer(expires_at_ms, "expires_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let raw = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?;
        let current: RecordingJobRecord = raw.try_into()?;
        if current.status != RecordingJobStatus::Accepted
            || transition_policy(current.status, RecordingJobStatus::Preflighting)
                != TransitionPolicy::Ordinary
            || transition_policy(
                RecordingJobStatus::Preflighting,
                RecordingJobStatus::QueuedServer,
            ) != TransitionPolicy::Ordinary
        {
            return Err(JobLedgerError::InvalidTransition {
                from: current.status,
                to: RecordingJobStatus::QueuedServer,
            });
        }
        transaction.execute(
            "UPDATE recording_jobs SET status = 'queued_server', route = 'server_batch', updated_at_ms = ?1, expires_at_ms = ?2 WHERE job_id = ?3",
            params![updated_at_ms, expires_at_ms, job_id],
        )?;
        let updated = query_job(&transaction, job_id)?.expect("accepted queued job exists");
        transaction.commit()?;
        updated.try_into()
    }

    pub fn accept_to_preflighting(
        &self,
        job_id: &str,
        updated_at_ms: u64,
        expires_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let updated_at_ms = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let expires_at_ms = sqlite_integer(expires_at_ms, "expires_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        if current.status != RecordingJobStatus::Accepted
            || current.language_decision_locked
            || transition_policy(current.status, RecordingJobStatus::Preflighting)
                != TransitionPolicy::Ordinary
        {
            return Err(JobLedgerError::InvalidTransition {
                from: current.status,
                to: RecordingJobStatus::Preflighting,
            });
        }
        let changed = transaction.execute(
            "UPDATE recording_jobs SET status = 'preflighting', route = 'server_batch', updated_at_ms = ?1, expires_at_ms = ?2 WHERE job_id = ?3 AND status = 'accepted' AND language_decision_locked = 0 AND cancellation_requested = 0",
            params![updated_at_ms, expires_at_ms, job_id],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "accepted preflight activation lost its durable state",
            ));
        }
        let updated = query_job(&transaction, job_id)?.expect("activated preflight job exists");
        transaction.commit()?;
        updated.try_into()
    }

    pub fn retry(
        &self,
        job_id: &str,
        updated_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        self.retry_with_expiry(job_id, updated_at_ms, None)
    }

    pub fn retry_with_expiry(
        &self,
        job_id: &str,
        updated_at_ms: u64,
        expires_at_ms: Option<u64>,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        self.retry_to_status(
            job_id,
            updated_at_ms,
            expires_at_ms,
            RecordingJobStatus::Preflighting,
        )
    }

    pub fn retry_to_queued_server(
        &self,
        job_id: &str,
        updated_at_ms: u64,
        expires_at_ms: Option<u64>,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        self.retry_to_status(
            job_id,
            updated_at_ms,
            expires_at_ms,
            RecordingJobStatus::QueuedServer,
        )
    }

    pub fn request_bound_server_stage_retry(
        &self,
        job_id: &str,
        updated_at_ms: u64,
        expires_at_ms: Option<u64>,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let updated_at_ms = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let expires_at_ms = optional_sqlite_integer(expires_at_ms, "expires_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        if current.status != RecordingJobStatus::Failed
            || current.cancellation_requested
            || transition_policy(current.status, RecordingJobStatus::Preflighting)
                != TransitionPolicy::Retry
        {
            return Err(JobLedgerError::InvalidTransition {
                from: current.status,
                to: RecordingJobStatus::ServerProcessing,
            });
        }

        let binding: Option<BoundServerRetryState> = transaction
            .query_row(
                "SELECT capture_manifest_sha256, server_base_url, server_job_id, server_cancellation_acknowledged_at_ms, create_attempt_base_url FROM prepared_remote_jobs WHERE job_id = ?1",
                [job_id],
                |row| {
                    Ok(BoundServerRetryState {
                        capture_manifest_sha256: row.get(0)?,
                        server_base_url: row.get(1)?,
                        server_job_id: row.get(2)?,
                        cancellation_acknowledged_at_ms: row.get(3)?,
                        create_attempt_base_url: row.get(4)?,
                    })
                },
            )
            .optional()?;
        let Some(BoundServerRetryState {
            capture_manifest_sha256: prepared_capture_sha256,
            server_base_url: Some(server_base_url),
            server_job_id: Some(server_job_id),
            cancellation_acknowledged_at_ms,
            create_attempt_base_url,
        }) = binding
        else {
            return Err(JobLedgerError::InvalidRecord(
                "bound server retry requires a consistent prepared server binding",
            ));
        };
        if server_base_url.is_empty()
            || server_job_id.is_empty()
            || cancellation_acknowledged_at_ms.is_some()
            || create_attempt_base_url.is_some()
            || current.capture_manifest_sha256.as_deref() != Some(prepared_capture_sha256.as_str())
        {
            return Err(JobLedgerError::InvalidRecord(
                "prepared server work has an inconsistent retry binding",
            ));
        }

        let (chunk_count, inconsistent_chunks): (i64, i64) = transaction.query_row(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN content_byte_length <= 0 OR upload_offset <> content_byte_length OR acknowledged_at_ms IS NULL OR acknowledged_object_id IS NULL OR acknowledged_object_id <> ?2 THEN 1 ELSE 0 END), 0) FROM job_chunks WHERE job_id = ?1",
            params![job_id, server_job_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?;
        if chunk_count == 0 || inconsistent_chunks != 0 {
            return Err(JobLedgerError::InvalidRecord(
                "bound server retry requires every prepared chunk to remain acknowledged by the same server job",
            ));
        }

        let next_attempt_count =
            current
                .attempt_count
                .checked_add(1)
                .ok_or(JobLedgerError::OutOfRange {
                    field: "attempt_count",
                    value: u64::MAX,
                })?;
        let next_attempt_count = sqlite_integer(next_attempt_count, "attempt_count")?;
        let changed = transaction.execute(
            "UPDATE recording_jobs SET status = 'server_processing', attempt_count = ?1, next_attempt_at_ms = NULL, cancellation_requested = 0, error_code = ?2, error_message = ?3, updated_at_ms = ?4, expires_at_ms = COALESCE(?5, expires_at_ms) WHERE job_id = ?6 AND status = 'failed' AND attempt_count = ?7 AND attempt_count < ?8",
            params![
                next_attempt_count,
                REMOTE_STAGE_RETRY_REQUESTED,
                REMOTE_STAGE_RETRY_MESSAGE,
                updated_at_ms,
                expires_at_ms,
                job_id,
                sqlite_integer(current.attempt_count, "attempt_count")?,
                i64::MAX,
            ],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "bound server retry lost its durable state race",
            ));
        }
        let updated = query_job(&transaction, job_id)?.expect("stage-retry job exists");
        transaction.commit()?;
        updated.try_into()
    }

    fn retry_to_status(
        &self,
        job_id: &str,
        updated_at_ms: u64,
        expires_at_ms: Option<u64>,
        final_status: RecordingJobStatus,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let updated_at_ms = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let expires_at_ms = optional_sqlite_integer(expires_at_ms, "expires_at_ms")?;
        loop {
            let mut connection = self.lock()?;
            let raw = query_job(&connection, job_id)?
                .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?;
            let current: RecordingJobRecord = raw.try_into()?;
            if transition_policy(current.status, RecordingJobStatus::Preflighting)
                != TransitionPolicy::Retry
            {
                return Err(JobLedgerError::InvalidTransition {
                    from: current.status,
                    to: RecordingJobStatus::Preflighting,
                });
            }
            let active_lid_dispatch: bool = connection.query_row(
                "SELECT EXISTS(SELECT 1 FROM client_preflight_artifacts WHERE job_id = ?1 AND lid_request_id IS NOT NULL)",
                [job_id],
                |row| row.get(0),
            )?;
            if active_lid_dispatch {
                return Err(JobLedgerError::InvalidRecord(
                    "recording retry must wait for terminal LID cancellation",
                ));
            }
            let expected_attempt_count = sqlite_integer(current.attempt_count, "attempt_count")?;
            let next_attempt_count =
                current
                    .attempt_count
                    .checked_add(1)
                    .ok_or(JobLedgerError::OutOfRange {
                        field: "attempt_count",
                        value: u64::MAX,
                    })?;
            let next_attempt_count = sqlite_integer(next_attempt_count, "attempt_count")?;

            let transaction =
                connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
            let prepared_remote: Option<PreparedServerRetryState> = transaction
                .query_row(
                    "SELECT server_base_url, server_job_id, server_cancellation_acknowledged_at_ms, create_attempt_base_url FROM prepared_remote_jobs WHERE job_id = ?1",
                    [job_id],
                    |row| {
                        Ok(PreparedServerRetryState {
                            server_base_url: row.get(0)?,
                            server_job_id: row.get(1)?,
                            cancellation_acknowledged_at_ms: row.get(2)?,
                            create_attempt_base_url: row.get(3)?,
                        })
                    },
                )
                .optional()?;
            if prepared_remote.is_some() && final_status != RecordingJobStatus::QueuedServer {
                return Err(JobLedgerError::InvalidRecord(
                    "prepared server work requires an identity-preserving server retry",
                ));
            }

            let target_status = if prepared_remote.is_some() {
                RecordingJobStatus::Uploading
            } else {
                final_status
            };
            if let Some(PreparedServerRetryState {
                server_base_url,
                server_job_id,
                cancellation_acknowledged_at_ms,
                create_attempt_base_url,
            }) = prepared_remote
            {
                match (server_base_url.as_deref(), server_job_id.as_deref()) {
                    (Some(_), Some(_)) => {
                        return Err(JobLedgerError::InvalidRecord(
                            "bound server work must use durable stage retry",
                        ));
                    }
                    (None, None)
                        if cancellation_acknowledged_at_ms.is_none()
                            && create_attempt_base_url.is_none() => {}
                    _ => {
                        return Err(JobLedgerError::InvalidRecord(
                            "prepared server work has an inconsistent retry binding",
                        ))
                    }
                }
                transaction.execute(
                    "UPDATE job_chunks SET upload_offset = 0, acknowledged_object_id = NULL, acknowledged_at_ms = NULL WHERE job_id = ?1",
                    [job_id],
                )?;
            }
            let changed = if target_status == RecordingJobStatus::Uploading {
                transaction.execute(
                    "UPDATE recording_jobs SET status = ?1, attempt_count = ?2, next_attempt_at_ms = NULL, cancellation_requested = 0, output_path = NULL, capture_commit_path = NULL, error_code = NULL, error_message = NULL, updated_at_ms = ?3, expires_at_ms = COALESCE(?4, expires_at_ms) WHERE job_id = ?5 AND status = ?6 AND attempt_count = ?7 AND attempt_count < ?8",
                    params![
                        target_status.as_db(),
                        next_attempt_count,
                        updated_at_ms,
                        expires_at_ms,
                        job_id,
                        current.status.as_db(),
                        expected_attempt_count,
                        i64::MAX,
                    ],
                )?
            } else {
                transaction.execute(
                    "UPDATE recording_jobs SET status = ?1, attempt_count = ?2, next_attempt_at_ms = NULL, cancellation_requested = 0, output_path = NULL, capture_commit_path = NULL, capture_manifest_sha256 = NULL, error_code = NULL, error_message = NULL, updated_at_ms = ?3, expires_at_ms = COALESCE(?4, expires_at_ms) WHERE job_id = ?5 AND status = ?6 AND attempt_count = ?7 AND attempt_count < ?8",
                    params![
                        target_status.as_db(),
                        next_attempt_count,
                        updated_at_ms,
                        expires_at_ms,
                        job_id,
                        current.status.as_db(),
                        expected_attempt_count,
                        i64::MAX,
                    ],
                )?
            };
            if changed == 0 {
                transaction.rollback()?;
                continue;
            }
            let updated = query_job(&transaction, job_id)?.expect("retried job exists");
            transaction.commit()?;
            return updated.try_into();
        }
    }

    pub fn request_cancellation(
        &self,
        job_id: &str,
        updated_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let updated_at_ms = sqlite_integer(updated_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let raw = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?;
        let current: RecordingJobRecord = raw.try_into()?;
        if transition_policy(current.status, RecordingJobStatus::Cancelled)
            != TransitionPolicy::Cancellation
        {
            return Err(JobLedgerError::InvalidTransition {
                from: current.status,
                to: RecordingJobStatus::Cancelled,
            });
        }
        transaction.execute(
            "UPDATE recording_jobs SET status = 'cancelled', cancellation_requested = 1, updated_at_ms = ?1 WHERE job_id = ?2",
            params![updated_at_ms, job_id],
        )?;
        let updated = query_job(&transaction, job_id)?.expect("cancelled job exists");
        prune_terminal_history(&transaction, Some(job_id))?;
        transaction.commit()?;
        updated.try_into()
    }
}
