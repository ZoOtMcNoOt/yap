//! Append-only desktop preprocessing and language-decision stage evidence.

mod codec;

use rusqlite::{params, OptionalExtension, Transaction, TransactionBehavior};
use sha2::{Digest, Sha256};

use crate::jobs::{
    AsrCatalogBinding, ClientStageAttemptRecord, ClientStageFinish, ClientStageName,
    ClientStageStart, ClientStageState, JobLedgerError, RecordingJobRecord, RecordingJobStatus,
    RecordingLanguageDecision,
};

use super::{
    records::{sqlite_integer, validate_catalog_binding},
    row_mapping::{query_job, stored_bool, stored_unsigned},
    JobLedger,
};
#[cfg(test)]
use codec::query_client_stage_attempt;
use codec::{
    encode_evidence, validate_finish, validate_start, MAX_STAGE_ATTEMPTS,
    MAX_STAGE_HISTORY_EVIDENCE_BYTES,
};

impl JobLedger {
    #[cfg(test)]
    pub(crate) fn start_client_stage(
        &self,
        job_id: &str,
        start: &ClientStageStart,
    ) -> Result<ClientStageAttemptRecord, JobLedgerError> {
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let attempt = start_client_stage_in_transaction(&transaction, job_id, start)?;
        let record = query_client_stage_attempt(&transaction, job_id, start.stage, attempt)?
            .expect("started client stage exists");
        transaction.commit()?;
        Ok(record)
    }

    #[cfg(test)]
    pub(crate) fn finish_client_stage(
        &self,
        job_id: &str,
        finish: &ClientStageFinish,
    ) -> Result<ClientStageAttemptRecord, JobLedgerError> {
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        finish_client_stage_in_transaction(&transaction, job_id, finish)?;
        let record =
            query_client_stage_attempt(&transaction, job_id, finish.stage, finish.attempt)?
                .expect("finished client stage exists");
        transaction.commit()?;
        Ok(record)
    }

    pub fn list_client_stage_attempts(
        &self,
        job_id: &str,
    ) -> Result<Vec<ClientStageAttemptRecord>, JobLedgerError> {
        let connection = self.lock()?;
        codec::list_client_stage_attempts(&connection, job_id)
    }

    pub fn confirm_language_decision(
        &self,
        job_id: &str,
        decision: &RecordingLanguageDecision,
        input_fingerprint_sha256: &str,
        confirmed_at_ms: u64,
        user_evidence: Option<serde_json::Value>,
        catalog_binding: Option<&AsrCatalogBinding>,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        decision
            .validate()
            .map_err(|_| JobLedgerError::InvalidRecord("confirmed language decision is invalid"))?;
        if decision.is_legacy_implicit_english_default() {
            return Err(JobLedgerError::InvalidRecord(
                "legacy defaults cannot be recorded as user confirmation",
            ));
        }
        let output_fingerprint_sha256 = sha256_hex(
            &serde_json::to_vec(decision)
                .map_err(|_| JobLedgerError::InvalidRecord("language decision is not JSON"))?,
        );
        let evidence = serde_json::json!({
            "schemaVersion": 1,
            "decision": decision,
            "userEvidence": user_evidence,
        });
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        if current.language_decision_locked
            || !matches!(
                current.status,
                RecordingJobStatus::Accepted
                    | RecordingJobStatus::Preflighting
                    | RecordingJobStatus::QueuedServer
            )
            || current.cancellation_requested
        {
            return Err(JobLedgerError::InvalidRecord(
                "language confirmation is only valid before preprocessing admission",
            ));
        }
        let completes_client_preflight = current.status == RecordingJobStatus::Preflighting;
        if completes_client_preflight {
            let binding = catalog_binding.ok_or(JobLedgerError::InvalidRecord(
                "client preflight confirmation requires a current ASR catalog binding",
            ))?;
            validate_catalog_binding(binding)?;
            let artifact_fingerprint: Option<String> = transaction
                .query_row(
                    "SELECT source_pcm_sha256 FROM client_preflight_artifacts WHERE job_id = ?1 AND lid_request_id IS NULL",
                    [job_id],
                    |row| row.get(0),
                )
                .optional()?;
            if artifact_fingerprint.as_deref() != Some(input_fingerprint_sha256)
                || !has_completed_client_preflight_stages(&transaction, job_id, false)?
            {
                return Err(JobLedgerError::InvalidRecord(
                    "language confirmation differs from the completed client preflight",
                ));
            }
        }
        let attempt = start_client_stage_in_transaction(
            &transaction,
            job_id,
            &ClientStageStart {
                stage: ClientStageName::UserConfirmation,
                input_fingerprint_sha256: input_fingerprint_sha256.into(),
                component_id: "yap-language-confirmation".into(),
                component_revision: "language-confirmation-v1".into(),
                started_at_ms: confirmed_at_ms,
            },
        )?;
        finish_client_stage_in_transaction(
            &transaction,
            job_id,
            &ClientStageFinish {
                stage: ClientStageName::UserConfirmation,
                attempt,
                state: ClientStageState::Succeeded,
                output_fingerprint_sha256: Some(output_fingerprint_sha256),
                completed_at_ms: confirmed_at_ms,
                retryable: false,
                reason: None,
                evidence: Some(evidence),
            },
        )?;
        let updated_at_ms = sqlite_integer(confirmed_at_ms, "updated_at_ms")?;
        let changed = if completes_client_preflight {
            let binding = catalog_binding.expect("validated preflight binding");
            transaction.execute(
                "UPDATE recording_jobs SET language_mode = ?1, language_bcp47 = ?2, language_disposition = ?3, language_decision_locked = 1, client_stage_history_complete = 1, asr_catalog_origin = ?4, asr_catalog_revision = ?5, next_attempt_at_ms = NULL, error_code = NULL, error_message = NULL, updated_at_ms = ?6 WHERE job_id = ?7 AND language_decision_locked = 0 AND status = 'preflighting' AND cancellation_requested = 0",
                params![
                    decision.mode.as_db(),
                    decision.language_bcp47,
                    decision.disposition.as_db(),
                    binding.origin(),
                    binding.catalog_revision(),
                    updated_at_ms,
                    job_id,
                ],
            )?
        } else {
            transaction.execute(
                "UPDATE recording_jobs SET language_mode = ?1, language_bcp47 = ?2, language_disposition = ?3, language_decision_locked = 1, updated_at_ms = ?4 WHERE job_id = ?5 AND language_decision_locked = 0 AND status IN ('accepted', 'queued_server') AND cancellation_requested = 0",
                params![
                    decision.mode.as_db(),
                    decision.language_bcp47,
                    decision.disposition.as_db(),
                    updated_at_ms,
                    job_id,
                ],
            )?
        };
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "language confirmation lost its pre-admission job state",
            ));
        }
        let updated = query_job(&transaction, job_id)?.expect("confirmed language job exists");
        transaction.commit()?;
        updated.try_into()
    }
}

pub(super) fn has_completed_client_preflight_stages(
    transaction: &Transaction<'_>,
    job_id: &str,
    require_user_confirmation: bool,
) -> Result<bool, JobLedgerError> {
    let completed_stages: i64 = transaction.query_row(
        "WITH latest AS (
            SELECT stage, MAX(attempt) AS attempt
            FROM job_stage_attempts
            WHERE job_id = ?1
            GROUP BY stage
        )
        SELECT COUNT(*)
        FROM job_stage_attempts AS stage_attempt
        JOIN latest
          ON latest.stage = stage_attempt.stage
         AND latest.attempt = stage_attempt.attempt
        WHERE stage_attempt.job_id = ?1
          AND stage_attempt.retryable = 0
          AND (
            (stage_attempt.stage = 'normalization' AND stage_attempt.state = 'succeeded')
            OR (stage_attempt.stage = 'vad' AND stage_attempt.state IN ('succeeded', 'unavailable', 'failed'))
            OR (stage_attempt.stage = 'lid_preflight' AND stage_attempt.state IN ('succeeded', 'unavailable', 'failed'))
            OR (stage_attempt.stage = 'user_confirmation' AND stage_attempt.state = 'succeeded')
          )",
        [job_id],
        |row| row.get(0),
    )?;
    let expected = if require_user_confirmation { 4 } else { 3 };
    let running_stages: bool = transaction.query_row(
        "SELECT EXISTS(SELECT 1 FROM job_stage_attempts WHERE job_id = ?1 AND state = 'running')",
        [job_id],
        |row| row.get(0),
    )?;
    Ok(completed_stages == expected && !running_stages)
}

pub(super) fn start_client_stage_in_transaction(
    transaction: &Transaction<'_>,
    job_id: &str,
    start: &ClientStageStart,
) -> Result<u64, JobLedgerError> {
    validate_start(start)?;
    let job: Option<(String, bool)> = transaction
        .query_row(
            "SELECT status, cancellation_requested FROM recording_jobs WHERE job_id = ?1",
            [job_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    let Some((status, cancellation_requested)) = job else {
        return Err(JobLedgerError::NotFound(job_id.into()));
    };
    if cancellation_requested || matches!(status.as_str(), "complete" | "partial" | "cancelled") {
        return Err(JobLedgerError::InvalidRecord(
            "client stages cannot start after cancellation or terminal publication",
        ));
    }
    let latest: Option<(i64, String, Option<i64>)> = transaction
        .query_row(
            "SELECT attempt, state, retryable FROM job_stage_attempts WHERE job_id = ?1 AND stage = ?2 ORDER BY attempt DESC LIMIT 1",
            params![job_id, start.stage.as_db()],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()?;
    let attempt = match latest {
        None => 1,
        Some((attempt, state, retryable)) => {
            let attempt = stored_unsigned(attempt, "client_stage_attempt")?;
            let state = ClientStageState::from_db(&state)?;
            let retryable = retryable
                .map(|value| stored_bool(value, "client_stage_retryable"))
                .transpose()?;
            if !matches!(
                state,
                ClientStageState::Failed | ClientStageState::Unavailable
            ) || retryable != Some(true)
            {
                return Err(JobLedgerError::InvalidRecord(
                    "client stage has no retryable terminal attempt",
                ));
            }
            attempt.checked_add(1).ok_or(JobLedgerError::InvalidRecord(
                "client stage attempt limit reached",
            ))?
        }
    };
    if attempt > MAX_STAGE_ATTEMPTS {
        return Err(JobLedgerError::InvalidRecord(
            "client stage attempt limit reached",
        ));
    }
    transaction.execute(
        "INSERT INTO job_stage_attempts (job_id, stage, attempt, state, input_fingerprint_sha256, component_id, component_revision, started_at_ms) VALUES (?1, ?2, ?3, 'running', ?4, ?5, ?6, ?7)",
        params![
            job_id,
            start.stage.as_db(),
            sqlite_integer(attempt, "client_stage_attempt")?,
            start.input_fingerprint_sha256,
            start.component_id,
            start.component_revision,
            sqlite_integer(start.started_at_ms, "client_stage_started_at_ms")?,
        ],
    )?;
    Ok(attempt)
}

pub(super) fn finish_client_stage_in_transaction(
    transaction: &Transaction<'_>,
    job_id: &str,
    finish: &ClientStageFinish,
) -> Result<(), JobLedgerError> {
    validate_finish(finish)?;
    let attempt = sqlite_integer(finish.attempt, "client_stage_attempt")?;
    let started_at_ms: i64 = transaction
        .query_row(
            "SELECT started_at_ms FROM job_stage_attempts WHERE job_id = ?1 AND stage = ?2 AND attempt = ?3 AND state = 'running'",
            params![job_id, finish.stage.as_db(), attempt],
            |row| row.get(0),
        )
        .optional()?
        .ok_or(JobLedgerError::InvalidRecord(
            "client stage completion does not match a running attempt",
        ))?;
    let completed_at_ms = sqlite_integer(finish.completed_at_ms, "client_stage_completed_at_ms")?;
    if completed_at_ms < started_at_ms {
        return Err(JobLedgerError::InvalidRecord(
            "client stage completion precedes its start",
        ));
    }
    let (evidence_json, evidence_sha256) = encode_evidence(finish.evidence.as_ref())?;
    enforce_history_evidence_bound(transaction, job_id, evidence_json.as_deref())?;
    let changed = transaction.execute(
        "UPDATE job_stage_attempts SET state = ?1, output_fingerprint_sha256 = ?2, completed_at_ms = ?3, retryable = ?4, reason = ?5, evidence_json = ?6, evidence_sha256 = ?7 WHERE job_id = ?8 AND stage = ?9 AND attempt = ?10 AND state = 'running'",
        params![
            finish.state.as_db(),
            finish.output_fingerprint_sha256,
            completed_at_ms,
            i64::from(finish.retryable),
            finish.reason,
            evidence_json,
            evidence_sha256,
            job_id,
            finish.stage.as_db(),
            attempt,
        ],
    )?;
    if changed != 1 {
        return Err(JobLedgerError::InvalidRecord(
            "client stage completion lost its running attempt",
        ));
    }
    Ok(())
}

fn enforce_history_evidence_bound(
    transaction: &Transaction<'_>,
    job_id: &str,
    evidence_json: Option<&str>,
) -> Result<(), JobLedgerError> {
    let Some(encoded) = evidence_json else {
        return Ok(());
    };
    let prior_bytes: i64 = transaction.query_row(
        "SELECT COALESCE(SUM(length(CAST(evidence_json AS BLOB))), 0) FROM job_stage_attempts WHERE job_id = ?1",
        [job_id],
        |row| row.get(0),
    )?;
    let prior_bytes = usize::try_from(prior_bytes).map_err(|_| JobLedgerError::CorruptValue {
        field: "client_stage_evidence",
        value: prior_bytes.to_string(),
    })?;
    if prior_bytes
        .checked_add(encoded.len())
        .is_none_or(|total| total > MAX_STAGE_HISTORY_EVIDENCE_BYTES)
    {
        return Err(JobLedgerError::InvalidRecord(
            "client stage evidence exceeds the per-job history bound",
        ));
    }
    Ok(())
}

fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[cfg(test)]
mod tests;
