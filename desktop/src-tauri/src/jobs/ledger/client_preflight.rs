//! Durable authority for immutable client preprocessing artifacts that exist
//! before a recording's language decision is locked.

use std::path::PathBuf;

use rusqlite::{params, OptionalExtension, TransactionBehavior};

use crate::{
    jobs::{
        ClientPreflightArtifactRecord, ClientStageFinish, ClientStageName, ClientStageStart,
        ClientStageState, JobLedgerError, NewClientPreflightArtifact, RecordingJobRecord,
        RecordingJobStatus, RecordingRoute,
    },
    server_connector::{batch::PreprocessingEvidence, lid::LidPreflightResult},
};

use super::{
    client_stages::{finish_client_stage_in_transaction, start_client_stage_in_transaction},
    records::{
        optional_sqlite_integer, path_text, sqlite_integer, valid_sha256,
        validate_opaque_identifier,
    },
    remote_state::append_client_preprocessing_stages,
    row_mapping::{query_job, stored_optional_unsigned, stored_unsigned},
    JobLedger,
};

const MAX_SOURCE_SAMPLES: u64 = 16_000 * 4 * 60 * 60;

pub(crate) struct LidPreflightDispatchFailure<'a> {
    pub(crate) job_id: &'a str,
    pub(crate) request_id: &'a str,
    pub(crate) attempt: u64,
    pub(crate) reason: &'a str,
    pub(crate) retryable: bool,
    pub(crate) retry_at_ms: Option<u64>,
    pub(crate) completed_at_ms: u64,
}

impl JobLedger {
    pub(crate) fn attach_client_preflight_artifact(
        &self,
        job_id: &str,
        artifact: &NewClientPreflightArtifact,
        preprocessing: &PreprocessingEvidence,
        completed_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let manifest_path = path_text(&artifact.manifest_path, "client_preflight_manifest_path")?;
        if !artifact.manifest_path.is_absolute()
            || !valid_sha256(&artifact.manifest_sha256)
            || !valid_sha256(&artifact.source_pcm_sha256)
            || !(1..=MAX_SOURCE_SAMPLES).contains(&artifact.source_sample_count)
            || preprocessing.normalization().source_pcm_sha256() != artifact.source_pcm_sha256
            || preprocessing.normalization().source_sample_count() != artifact.source_sample_count
            || !preprocessing
                .is_valid_for_output_samples(preprocessing.normalization().output_sample_count())
        {
            return Err(JobLedgerError::InvalidRecord(
                "client preflight artifact is outside the durable contract",
            ));
        }
        let completed_at_ms_sql = sqlite_integer(completed_at_ms, "updated_at_ms")?;
        let source_sample_count = sqlite_integer(
            artifact.source_sample_count,
            "client_preflight_source_samples",
        )?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        if current.status != RecordingJobStatus::Preflighting
            || current.route != Some(RecordingRoute::ServerBatch)
            || current.language_decision_locked
            || current.cancellation_requested
        {
            return Err(JobLedgerError::InvalidRecord(
                "client preflight attachment requires an active unlocked preflight",
            ));
        }
        let conflicting_state: bool = transaction.query_row(
            "SELECT EXISTS(SELECT 1 FROM client_preflight_artifacts WHERE job_id = ?1) OR EXISTS(SELECT 1 FROM prepared_remote_jobs WHERE job_id = ?1) OR EXISTS(SELECT 1 FROM job_chunks WHERE job_id = ?1)",
            [job_id],
            |row| row.get(0),
        )?;
        if conflicting_state {
            return Err(JobLedgerError::InvalidRecord(
                "recording job already has client or remote preparation state",
            ));
        }

        append_client_preprocessing_stages(
            &transaction,
            job_id,
            current.updated_at_ms,
            completed_at_ms,
            preprocessing,
        )?;
        transaction.execute(
            "INSERT INTO client_preflight_artifacts (job_id, manifest_path, manifest_sha256, source_pcm_sha256, source_sample_count) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                job_id,
                manifest_path,
                artifact.manifest_sha256,
                artifact.source_pcm_sha256,
                source_sample_count,
            ],
        )?;
        transaction.execute(
            "UPDATE recording_jobs SET updated_at_ms = ?1 WHERE job_id = ?2 AND status = 'preflighting' AND language_decision_locked = 0 AND cancellation_requested = 0",
            params![completed_at_ms_sql, job_id],
        )?;
        let updated = query_job(&transaction, job_id)?.expect("preflight job exists");
        transaction.commit()?;
        updated.try_into()
    }

    pub(crate) fn get_client_preflight_artifact(
        &self,
        job_id: &str,
    ) -> Result<Option<ClientPreflightArtifactRecord>, JobLedgerError> {
        let connection = self.lock()?;
        connection
            .query_row(
                "SELECT job_id, manifest_path, manifest_sha256, source_pcm_sha256, source_sample_count, lid_request_id, lid_server_base_url, lid_catalog_revision, lid_policy_revision, lid_started_at_ms FROM client_preflight_artifacts WHERE job_id = ?1",
                [job_id],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, i64>(4)?,
                        row.get::<_, Option<String>>(5)?,
                        row.get::<_, Option<String>>(6)?,
                        row.get::<_, Option<String>>(7)?,
                        row.get::<_, Option<String>>(8)?,
                        row.get::<_, Option<i64>>(9)?,
                    ))
                },
            )
            .optional()?
            .map(
                |(
                    job_id,
                    manifest_path,
                    manifest_sha256,
                    source_pcm_sha256,
                    source_sample_count,
                    lid_request_id,
                    lid_server_base_url,
                    lid_catalog_revision,
                    lid_policy_revision,
                    lid_started_at_ms,
                )| {
                    if !valid_sha256(&manifest_sha256)
                        || !valid_sha256(&source_pcm_sha256)
                        || lid_catalog_revision
                            .as_deref()
                            .is_some_and(|value| !valid_sha256(value))
                    {
                        return Err(JobLedgerError::CorruptValue {
                            field: "client_preflight_artifact",
                            value: "invalid digest".into(),
                        });
                    }
                    let dispatch_fields = [
                        lid_request_id.is_some(),
                        lid_server_base_url.is_some(),
                        lid_catalog_revision.is_some(),
                        lid_policy_revision.is_some(),
                        lid_started_at_ms.is_some(),
                    ];
                    if dispatch_fields.iter().any(|value| *value)
                        && !dispatch_fields.iter().all(|value| *value)
                    {
                        return Err(JobLedgerError::CorruptValue {
                            field: "client_preflight_artifact",
                            value: "incomplete LID dispatch identity".into(),
                        });
                    }
                    Ok(ClientPreflightArtifactRecord {
                        job_id,
                        manifest_path: PathBuf::from(manifest_path),
                        manifest_sha256,
                        source_pcm_sha256,
                        source_sample_count: stored_unsigned(
                            source_sample_count,
                            "client_preflight_source_samples",
                        )?,
                        lid_request_id,
                        lid_server_base_url,
                        lid_catalog_revision,
                        lid_policy_revision,
                        lid_started_at_ms: stored_optional_unsigned(
                            lid_started_at_ms,
                            "client_preflight_lid_started_at_ms",
                        )?,
                    })
                },
            )
            .transpose()
    }

    pub(crate) fn record_manual_lid_preflight(
        &self,
        job_id: &str,
        reason: &str,
        catalog_revision: &str,
        policy_revision: &str,
        completed_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let stage_reason = stage_reason_code(reason)?;
        if !valid_sha256(catalog_revision) {
            return Err(JobLedgerError::InvalidRecord(
                "manual LID catalog revision is invalid",
            ));
        }
        validate_opaque_identifier(policy_revision, 128, "manual LID policy revision")?;
        let completed_at_ms_sql = sqlite_integer(completed_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        let artifact = query_client_preflight_artifact(&transaction, job_id)?.ok_or(
            JobLedgerError::InvalidRecord(
                "manual LID outcome requires a durable client preflight artifact",
            ),
        )?;
        if current.status != RecordingJobStatus::Preflighting
            || current.language_decision_locked
            || current.cancellation_requested
            || artifact.lid_request_id.is_some()
        {
            return Err(JobLedgerError::InvalidRecord(
                "manual LID outcome requires an idle unlocked preflight",
            ));
        }
        let attempt = start_client_stage_in_transaction(
            &transaction,
            job_id,
            &ClientStageStart {
                stage: ClientStageName::LidPreflight,
                input_fingerprint_sha256: artifact.source_pcm_sha256.clone(),
                component_id: "yap-lid-window-policy".into(),
                component_revision: policy_revision.into(),
                started_at_ms: completed_at_ms,
            },
        )?;
        finish_client_stage_in_transaction(
            &transaction,
            job_id,
            &ClientStageFinish {
                stage: ClientStageName::LidPreflight,
                attempt,
                state: ClientStageState::Unavailable,
                output_fingerprint_sha256: None,
                completed_at_ms,
                retryable: false,
                reason: Some(stage_reason),
                evidence: Some(serde_json::json!({
                    "schemaVersion": 1,
                    "outcome": "manual",
                    "reason": reason,
                    "catalogRevision": catalog_revision,
                    "policyRevision": policy_revision,
                    "sourceSamples": artifact.source_sample_count,
                    "sourcePcmSha256": artifact.source_pcm_sha256,
                })),
            },
        )?;
        transaction.execute(
            "UPDATE recording_jobs SET next_attempt_at_ms = NULL, error_code = NULL, error_message = NULL, updated_at_ms = ?1 WHERE job_id = ?2 AND status = 'preflighting' AND language_decision_locked = 0",
            params![completed_at_ms_sql, job_id],
        )?;
        let updated = query_job(&transaction, job_id)?.expect("manual preflight job exists");
        transaction.commit()?;
        updated.try_into()
    }

    pub(crate) fn begin_lid_preflight_dispatch(
        &self,
        job_id: &str,
        request_id: &str,
        server_base_url: &str,
        catalog_revision: &str,
        policy_revision: &str,
        started_at_ms: u64,
    ) -> Result<u64, JobLedgerError> {
        validate_opaque_identifier(request_id, 128, "LID preflight request ID")?;
        validate_opaque_identifier(policy_revision, 128, "LID preflight policy revision")?;
        super::records::validate_server_base_url(server_base_url)?;
        if !valid_sha256(catalog_revision) {
            return Err(JobLedgerError::InvalidRecord(
                "LID preflight catalog revision is invalid",
            ));
        }
        let started_at_ms_sql =
            sqlite_integer(started_at_ms, "client_preflight_lid_started_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        let artifact = query_client_preflight_artifact(&transaction, job_id)?.ok_or(
            JobLedgerError::InvalidRecord(
                "LID dispatch requires a durable client preflight artifact",
            ),
        )?;
        if current.status != RecordingJobStatus::Preflighting
            || current.language_decision_locked
            || current.cancellation_requested
            || artifact.lid_request_id.is_some()
        {
            return Err(JobLedgerError::InvalidRecord(
                "LID dispatch requires an idle unlocked preflight",
            ));
        }
        let attempt = start_client_stage_in_transaction(
            &transaction,
            job_id,
            &ClientStageStart {
                stage: ClientStageName::LidPreflight,
                input_fingerprint_sha256: artifact.source_pcm_sha256,
                component_id: "speechbrain-language-id".into(),
                component_revision: policy_revision.into(),
                started_at_ms,
            },
        )?;
        let changed = transaction.execute(
            "UPDATE client_preflight_artifacts SET lid_request_id = ?1, lid_server_base_url = ?2, lid_catalog_revision = ?3, lid_policy_revision = ?4, lid_started_at_ms = ?5 WHERE job_id = ?6 AND lid_request_id IS NULL",
            params![
                request_id,
                server_base_url,
                catalog_revision,
                policy_revision,
                started_at_ms_sql,
                job_id,
            ],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "LID dispatch lost its durable preflight race",
            ));
        }
        transaction.execute(
            "UPDATE recording_jobs SET next_attempt_at_ms = NULL, error_code = NULL, error_message = NULL, updated_at_ms = ?1 WHERE job_id = ?2 AND status = 'preflighting' AND language_decision_locked = 0",
            params![started_at_ms_sql, job_id],
        )?;
        transaction.commit()?;
        Ok(attempt)
    }

    pub(crate) fn finish_lid_preflight_dispatch(
        &self,
        job_id: &str,
        request_id: &str,
        attempt: u64,
        result: &LidPreflightResult,
        completed_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let evidence = serde_json::to_value(result)
            .map_err(|_| JobLedgerError::InvalidRecord("LID result is not JSON"))?;
        let encoded = serde_json::to_vec(result)
            .map_err(|_| JobLedgerError::InvalidRecord("LID result is not JSON"))?;
        let output_fingerprint_sha256 = sha256_hex(&encoded);
        let completed_at_ms_sql = sqlite_integer(completed_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        let artifact = query_client_preflight_artifact(&transaction, job_id)?.ok_or(
            JobLedgerError::InvalidRecord(
                "LID completion requires a durable client preflight artifact",
            ),
        )?;
        if current.status != RecordingJobStatus::Preflighting
            || current.language_decision_locked
            || current.cancellation_requested
            || artifact.lid_request_id.as_deref() != Some(request_id)
            || result.request_id != request_id
            || result.source_samples != artifact.source_sample_count
            || result.source_pcm_sha256 != artifact.source_pcm_sha256
            || Some(result.catalog_revision.as_str()) != artifact.lid_catalog_revision.as_deref()
            || Some(result.component.policy_revision.as_str())
                != artifact.lid_policy_revision.as_deref()
        {
            return Err(JobLedgerError::InvalidRecord(
                "LID result differs from its durable dispatch identity",
            ));
        }
        finish_client_stage_in_transaction(
            &transaction,
            job_id,
            &ClientStageFinish {
                stage: ClientStageName::LidPreflight,
                attempt,
                state: ClientStageState::Succeeded,
                output_fingerprint_sha256: Some(output_fingerprint_sha256),
                completed_at_ms,
                retryable: false,
                reason: None,
                evidence: Some(evidence),
            },
        )?;
        let changed = transaction.execute(
            "UPDATE client_preflight_artifacts SET lid_request_id = NULL, lid_server_base_url = NULL, lid_catalog_revision = NULL, lid_policy_revision = NULL, lid_started_at_ms = NULL WHERE job_id = ?1 AND lid_request_id = ?2",
            params![job_id, request_id],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "LID completion lost its durable dispatch identity",
            ));
        }
        transaction.execute(
            "UPDATE recording_jobs SET next_attempt_at_ms = NULL, error_code = NULL, error_message = NULL, updated_at_ms = ?1 WHERE job_id = ?2 AND status = 'preflighting' AND language_decision_locked = 0",
            params![completed_at_ms_sql, job_id],
        )?;
        let updated = query_job(&transaction, job_id)?.expect("completed LID preflight job exists");
        transaction.commit()?;
        updated.try_into()
    }

    pub(crate) fn fail_lid_preflight_dispatch(
        &self,
        failure: LidPreflightDispatchFailure<'_>,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        let LidPreflightDispatchFailure {
            job_id,
            request_id,
            attempt,
            reason,
            retryable,
            retry_at_ms,
            completed_at_ms,
        } = failure;
        let stage_reason = stage_reason_code(reason)?;
        if retryable != retry_at_ms.is_some() {
            return Err(JobLedgerError::InvalidRecord(
                "LID retryability and retry deadline must agree",
            ));
        }
        let retry_at_ms = optional_sqlite_integer(retry_at_ms, "next_attempt_at_ms")?;
        let completed_at_ms_sql = sqlite_integer(completed_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        let artifact = query_client_preflight_artifact(&transaction, job_id)?.ok_or(
            JobLedgerError::InvalidRecord(
                "LID failure requires a durable client preflight artifact",
            ),
        )?;
        if current.status != RecordingJobStatus::Preflighting
            || current.language_decision_locked
            || current.cancellation_requested
            || artifact.lid_request_id.as_deref() != Some(request_id)
        {
            return Err(JobLedgerError::InvalidRecord(
                "LID failure differs from its durable dispatch identity",
            ));
        }
        finish_client_stage_in_transaction(
            &transaction,
            job_id,
            &ClientStageFinish {
                stage: ClientStageName::LidPreflight,
                attempt,
                state: ClientStageState::Failed,
                output_fingerprint_sha256: None,
                completed_at_ms,
                retryable,
                reason: Some(stage_reason),
                evidence: Some(serde_json::json!({
                    "schemaVersion": 1,
                    "outcome": "failed",
                    "reason": reason,
                    "requestId": request_id,
                    "serverBaseUrl": artifact.lid_server_base_url,
                    "catalogRevision": artifact.lid_catalog_revision,
                    "policyRevision": artifact.lid_policy_revision,
                })),
            },
        )?;
        let changed = transaction.execute(
            "UPDATE client_preflight_artifacts SET lid_request_id = NULL, lid_server_base_url = NULL, lid_catalog_revision = NULL, lid_policy_revision = NULL, lid_started_at_ms = NULL WHERE job_id = ?1 AND lid_request_id = ?2",
            params![job_id, request_id],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "LID failure lost its durable dispatch identity",
            ));
        }
        transaction.execute(
            "UPDATE recording_jobs SET next_attempt_at_ms = ?1, error_code = CASE WHEN ?1 IS NULL THEN NULL ELSE 'LID_PREFLIGHT_RETRY' END, error_message = CASE WHEN ?1 IS NULL THEN NULL ELSE 'Language preflight will retry after a bounded server error.' END, updated_at_ms = ?2 WHERE job_id = ?3 AND status = 'preflighting' AND language_decision_locked = 0",
            params![retry_at_ms, completed_at_ms_sql, job_id],
        )?;
        let updated = query_job(&transaction, job_id)?.expect("failed LID preflight job exists");
        transaction.commit()?;
        updated.try_into()
    }

    pub(crate) fn next_terminal_lid_preflight_dispatch(
        &self,
    ) -> Result<Option<ClientPreflightArtifactRecord>, JobLedgerError> {
        let job_id = {
            let connection = self.lock()?;
            connection
                .query_row(
                    "SELECT artifact.job_id FROM client_preflight_artifacts AS artifact JOIN recording_jobs AS job ON job.job_id = artifact.job_id WHERE artifact.lid_request_id IS NOT NULL AND (job.status = 'failed' OR (job.status = 'cancelled' AND job.cancellation_requested = 1)) ORDER BY job.updated_at_ms, artifact.job_id LIMIT 1",
                    [],
                    |row| row.get::<_, String>(0),
                )
                .optional()?
        };
        job_id
            .map(|job_id| {
                self.get_client_preflight_artifact(&job_id)?
                    .ok_or(JobLedgerError::InvalidRecord(
                        "terminal LID dispatch lost its durable artifact",
                    ))
            })
            .transpose()
    }

    pub(crate) fn acknowledge_terminal_lid_preflight_dispatch(
        &self,
        job_id: &str,
        request_id: &str,
        completed_at_ms: u64,
    ) -> Result<(), JobLedgerError> {
        validate_opaque_identifier(request_id, 128, "LID preflight request ID")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        if !matches!(
            current.status,
            RecordingJobStatus::Failed | RecordingJobStatus::Cancelled
        ) || (current.status == RecordingJobStatus::Cancelled && !current.cancellation_requested)
        {
            return Err(JobLedgerError::InvalidRecord(
                "LID cancellation acknowledgement requires a terminal job",
            ));
        }
        let artifact = query_client_preflight_artifact(&transaction, job_id)?.ok_or(
            JobLedgerError::InvalidRecord(
                "LID cancellation acknowledgement requires a durable artifact",
            ),
        )?;
        if artifact.lid_request_id.as_deref() != Some(request_id) {
            return Err(JobLedgerError::InvalidRecord(
                "LID cancellation acknowledgement differs from its durable request",
            ));
        }
        let running: Option<(i64, i64)> = transaction
            .query_row(
                "SELECT attempt, started_at_ms FROM job_stage_attempts WHERE job_id = ?1 AND stage = 'lid_preflight' AND state = 'running' ORDER BY attempt DESC LIMIT 1",
                [job_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        let (attempt, started_at_ms) = running.ok_or(JobLedgerError::InvalidRecord(
            "terminal LID dispatch has no running stage",
        ))?;
        let attempt = stored_unsigned(attempt, "client_stage_attempt")?;
        let started_at_ms = stored_unsigned(started_at_ms, "client_stage_started_at_ms")?;
        let completed_at_ms = completed_at_ms.max(started_at_ms);
        finish_client_stage_in_transaction(
            &transaction,
            job_id,
            &ClientStageFinish {
                stage: ClientStageName::LidPreflight,
                attempt,
                state: ClientStageState::Cancelled,
                output_fingerprint_sha256: None,
                completed_at_ms,
                retryable: false,
                reason: Some("CANCELLED".into()),
                evidence: Some(serde_json::json!({
                    "schemaVersion": 1,
                    "outcome": "cancelled",
                    "requestId": request_id,
                    "serverBaseUrl": artifact.lid_server_base_url,
                    "catalogRevision": artifact.lid_catalog_revision,
                    "policyRevision": artifact.lid_policy_revision,
                })),
            },
        )?;
        let changed = transaction.execute(
            "UPDATE client_preflight_artifacts SET lid_request_id = NULL, lid_server_base_url = NULL, lid_catalog_revision = NULL, lid_policy_revision = NULL, lid_started_at_ms = NULL WHERE job_id = ?1 AND lid_request_id = ?2",
            params![job_id, request_id],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "LID cancellation acknowledgement lost its durable request",
            ));
        }
        transaction.commit()?;
        Ok(())
    }

    pub(crate) fn fail_client_preflight(
        &self,
        job_id: &str,
        error_code: &str,
        error_message: &str,
        completed_at_ms: u64,
    ) -> Result<RecordingJobRecord, JobLedgerError> {
        validate_opaque_identifier(error_code, 64, "client preflight error code")?;
        if error_message.is_empty()
            || error_message.len() > 512
            || error_message
                .chars()
                .any(|character| character.is_control() && !character.is_whitespace())
        {
            return Err(JobLedgerError::InvalidRecord(
                "client preflight error message is outside its bound",
            ));
        }
        let completed_at_ms = sqlite_integer(completed_at_ms, "updated_at_ms")?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: RecordingJobRecord = query_job(&transaction, job_id)?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?
            .try_into()?;
        if current.status != RecordingJobStatus::Preflighting || current.cancellation_requested {
            return Err(JobLedgerError::InvalidRecord(
                "client preflight failure requires an active preflight",
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
            "UPDATE recording_jobs SET status = 'failed', attempt_count = ?1, next_attempt_at_ms = NULL, error_code = ?2, error_message = ?3, updated_at_ms = ?4 WHERE job_id = ?5 AND status = 'preflighting' AND cancellation_requested = 0",
            params![
                next_attempt_count,
                error_code,
                error_message,
                completed_at_ms,
                job_id,
            ],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "client preflight failure lost its durable state",
            ));
        }
        let updated = query_job(&transaction, job_id)?.expect("failed preflight job exists");
        transaction.commit()?;
        updated.try_into()
    }
}

fn query_client_preflight_artifact(
    connection: &rusqlite::Connection,
    job_id: &str,
) -> Result<Option<ClientPreflightArtifactRecord>, JobLedgerError> {
    connection
        .query_row(
            "SELECT job_id, manifest_path, manifest_sha256, source_pcm_sha256, source_sample_count, lid_request_id, lid_server_base_url, lid_catalog_revision, lid_policy_revision, lid_started_at_ms FROM client_preflight_artifacts WHERE job_id = ?1",
            [job_id],
            |row| {
                Ok(ClientPreflightArtifactRecord {
                    job_id: row.get(0)?,
                    manifest_path: PathBuf::from(row.get::<_, String>(1)?),
                    manifest_sha256: row.get(2)?,
                    source_pcm_sha256: row.get(3)?,
                    source_sample_count: stored_unsigned(
                        row.get(4)?,
                        "client_preflight_source_samples",
                    )
                    .map_err(|error| rusqlite::Error::ToSqlConversionFailure(Box::new(error)))?,
                    lid_request_id: row.get(5)?,
                    lid_server_base_url: row.get(6)?,
                    lid_catalog_revision: row.get(7)?,
                    lid_policy_revision: row.get(8)?,
                    lid_started_at_ms: stored_optional_unsigned(
                        row.get(9)?,
                        "client_preflight_lid_started_at_ms",
                    )
                    .map_err(|error| rusqlite::Error::ToSqlConversionFailure(Box::new(error)))?,
                })
            },
        )
        .optional()
        .map_err(Into::into)
}

fn stage_reason_code(reason: &str) -> Result<String, JobLedgerError> {
    if reason.is_empty()
        || reason.len() > 64
        || !reason
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
    {
        return Err(JobLedgerError::InvalidRecord(
            "LID reason is outside the stage contract",
        ));
    }
    Ok(reason.to_ascii_uppercase())
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};

    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
