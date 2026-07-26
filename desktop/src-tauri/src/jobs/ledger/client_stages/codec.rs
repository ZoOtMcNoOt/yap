#[cfg(test)]
use rusqlite::{params, OptionalExtension};
use rusqlite::{Connection, Row};
use sha2::{Digest, Sha256};

use crate::jobs::{
    ClientStageAttemptRecord, ClientStageFinish, ClientStageName, ClientStageStart,
    ClientStageState, JobLedgerError,
};

use super::super::{
    records::{sqlite_integer, valid_sha256},
    row_mapping::{stored_bool, stored_optional_unsigned, stored_unsigned},
};

pub(super) const MAX_STAGE_ATTEMPTS: u64 = 64;
pub(super) const MAX_STAGE_HISTORY_EVIDENCE_BYTES: usize = 64 * 1024;
const MAX_STAGE_EVIDENCE_BYTES: usize = 64 * 1024;
const MAX_COMPONENT_BYTES: usize = 128;
const MAX_REASON_BYTES: usize = 64;

pub(super) fn list_client_stage_attempts(
    connection: &Connection,
    job_id: &str,
) -> Result<Vec<ClientStageAttemptRecord>, JobLedgerError> {
    let exists = connection.query_row(
        "SELECT EXISTS(SELECT 1 FROM recording_jobs WHERE job_id = ?1)",
        [job_id],
        |row| row.get::<_, bool>(0),
    )?;
    if !exists {
        return Err(JobLedgerError::NotFound(job_id.into()));
    }
    let mut statement = connection.prepare(
        "SELECT job_id, stage, attempt, state, input_fingerprint_sha256, output_fingerprint_sha256, component_id, component_revision, started_at_ms, completed_at_ms, retryable, reason, evidence_json, evidence_sha256 FROM job_stage_attempts WHERE job_id = ?1 ORDER BY stage, attempt",
    )?;
    let rows = statement.query_map([job_id], raw_client_stage_attempt)?;
    let mut evidence_bytes = 0_usize;
    let mut records = Vec::new();
    for row in rows {
        let raw = row?;
        evidence_bytes = evidence_bytes
            .checked_add(raw.evidence_json.as_ref().map_or(0, String::len))
            .ok_or(JobLedgerError::CorruptValue {
                field: "client_stage_evidence",
                value: "history byte count overflow".into(),
            })?;
        if evidence_bytes > MAX_STAGE_HISTORY_EVIDENCE_BYTES {
            return Err(JobLedgerError::CorruptValue {
                field: "client_stage_evidence",
                value: "history exceeds the bounded evidence contract".into(),
            });
        }
        records.push(decode_client_stage_attempt(raw)?);
    }
    Ok(records)
}

#[cfg(test)]
pub(super) fn query_client_stage_attempt(
    connection: &Connection,
    job_id: &str,
    stage: ClientStageName,
    attempt: u64,
) -> Result<Option<ClientStageAttemptRecord>, JobLedgerError> {
    connection
        .query_row(
            "SELECT job_id, stage, attempt, state, input_fingerprint_sha256, output_fingerprint_sha256, component_id, component_revision, started_at_ms, completed_at_ms, retryable, reason, evidence_json, evidence_sha256 FROM job_stage_attempts WHERE job_id = ?1 AND stage = ?2 AND attempt = ?3",
            params![job_id, stage.as_db(), sqlite_integer(attempt, "client_stage_attempt")?],
            raw_client_stage_attempt,
        )
        .optional()?
        .map(decode_client_stage_attempt)
        .transpose()
}

pub(super) fn validate_start(start: &ClientStageStart) -> Result<(), JobLedgerError> {
    if !valid_sha256(&start.input_fingerprint_sha256)
        || !valid_component(&start.component_id)
        || !valid_component(&start.component_revision)
    {
        return Err(JobLedgerError::InvalidRecord(
            "client stage start is outside the bounded evidence contract",
        ));
    }
    sqlite_integer(start.started_at_ms, "client_stage_started_at_ms")?;
    Ok(())
}

pub(super) fn validate_finish(finish: &ClientStageFinish) -> Result<(), JobLedgerError> {
    if finish.attempt == 0 || finish.attempt > MAX_STAGE_ATTEMPTS {
        return Err(JobLedgerError::InvalidRecord(
            "client stage attempt is outside its bound",
        ));
    }
    if finish
        .output_fingerprint_sha256
        .as_deref()
        .is_some_and(|value| !valid_sha256(value))
        || finish
            .reason
            .as_deref()
            .is_some_and(|value| !valid_reason(value))
    {
        return Err(JobLedgerError::InvalidRecord(
            "client stage completion is outside the bounded evidence contract",
        ));
    }
    let valid_semantics = match finish.state {
        ClientStageState::Running => false,
        ClientStageState::Succeeded => {
            finish.output_fingerprint_sha256.is_some()
                && !finish.retryable
                && finish.reason.is_none()
        }
        ClientStageState::Unavailable | ClientStageState::Failed => {
            finish.output_fingerprint_sha256.is_none() && finish.reason.is_some()
        }
        ClientStageState::Cancelled => {
            finish.output_fingerprint_sha256.is_none()
                && !finish.retryable
                && finish.reason.is_some()
        }
    };
    if !valid_semantics {
        return Err(JobLedgerError::InvalidRecord(
            "client stage terminal fields are inconsistent",
        ));
    }
    sqlite_integer(finish.completed_at_ms, "client_stage_completed_at_ms")?;
    Ok(())
}

pub(super) fn encode_evidence(
    evidence: Option<&serde_json::Value>,
) -> Result<(Option<String>, Option<String>), JobLedgerError> {
    let Some(evidence) = evidence else {
        return Ok((None, None));
    };
    let encoded = serde_json::to_vec(evidence)
        .map_err(|_| JobLedgerError::InvalidRecord("client stage evidence is not JSON"))?;
    if encoded.is_empty() || encoded.len() > MAX_STAGE_EVIDENCE_BYTES {
        return Err(JobLedgerError::InvalidRecord(
            "client stage evidence exceeds its byte bound",
        ));
    }
    let digest = sha256_hex(&encoded);
    let encoded = String::from_utf8(encoded)
        .map_err(|_| JobLedgerError::InvalidRecord("client stage evidence is not UTF-8"))?;
    Ok((Some(encoded), Some(digest)))
}

struct RawClientStageAttempt {
    job_id: String,
    stage: String,
    attempt: i64,
    state: String,
    input_fingerprint_sha256: String,
    output_fingerprint_sha256: Option<String>,
    component_id: String,
    component_revision: String,
    started_at_ms: i64,
    completed_at_ms: Option<i64>,
    retryable: Option<i64>,
    reason: Option<String>,
    evidence_json: Option<String>,
    evidence_sha256: Option<String>,
}

fn raw_client_stage_attempt(row: &Row<'_>) -> rusqlite::Result<RawClientStageAttempt> {
    Ok(RawClientStageAttempt {
        job_id: row.get(0)?,
        stage: row.get(1)?,
        attempt: row.get(2)?,
        state: row.get(3)?,
        input_fingerprint_sha256: row.get(4)?,
        output_fingerprint_sha256: row.get(5)?,
        component_id: row.get(6)?,
        component_revision: row.get(7)?,
        started_at_ms: row.get(8)?,
        completed_at_ms: row.get(9)?,
        retryable: row.get(10)?,
        reason: row.get(11)?,
        evidence_json: row.get(12)?,
        evidence_sha256: row.get(13)?,
    })
}

fn decode_client_stage_attempt(
    raw: RawClientStageAttempt,
) -> Result<ClientStageAttemptRecord, JobLedgerError> {
    validate_raw_fields(&raw)?;
    let (evidence, evidence_sha256) = decode_evidence(raw.evidence_json, raw.evidence_sha256)?;
    let record = ClientStageAttemptRecord {
        job_id: raw.job_id,
        stage: ClientStageName::from_db(&raw.stage)?,
        attempt: stored_unsigned(raw.attempt, "client_stage_attempt")?,
        state: ClientStageState::from_db(&raw.state)?,
        input_fingerprint_sha256: raw.input_fingerprint_sha256,
        output_fingerprint_sha256: raw.output_fingerprint_sha256,
        component_id: raw.component_id,
        component_revision: raw.component_revision,
        started_at_ms: stored_unsigned(raw.started_at_ms, "client_stage_started_at_ms")?,
        completed_at_ms: stored_optional_unsigned(
            raw.completed_at_ms,
            "client_stage_completed_at_ms",
        )?,
        retryable: raw
            .retryable
            .map(|value| stored_bool(value, "client_stage_retryable"))
            .transpose()?,
        reason: raw.reason,
        evidence,
        evidence_sha256,
    };
    validate_decoded_semantics(&record)?;
    Ok(record)
}

fn validate_raw_fields(raw: &RawClientStageAttempt) -> Result<(), JobLedgerError> {
    if !valid_sha256(&raw.input_fingerprint_sha256)
        || raw
            .output_fingerprint_sha256
            .as_deref()
            .is_some_and(|value| !valid_sha256(value))
        || !valid_component(&raw.component_id)
        || !valid_component(&raw.component_revision)
        || raw
            .reason
            .as_deref()
            .is_some_and(|value| !valid_reason(value))
    {
        return Err(JobLedgerError::CorruptValue {
            field: "client_stage_attempt",
            value: "invalid bounded field".into(),
        });
    }
    Ok(())
}

fn decode_evidence(
    encoded: Option<String>,
    digest: Option<String>,
) -> Result<(Option<serde_json::Value>, Option<String>), JobLedgerError> {
    match (encoded, digest) {
        (None, None) => Ok((None, None)),
        (Some(encoded), Some(digest)) => {
            if encoded.len() > MAX_STAGE_EVIDENCE_BYTES
                || !valid_sha256(&digest)
                || sha256_hex(encoded.as_bytes()) != digest
            {
                return Err(corrupt_evidence("invalid evidence identity"));
            }
            let value: serde_json::Value =
                serde_json::from_str(&encoded).map_err(|_| corrupt_evidence("invalid JSON"))?;
            if serde_json::to_string(&value).ok().as_deref() != Some(encoded.as_str()) {
                return Err(corrupt_evidence("non-canonical JSON"));
            }
            Ok((Some(value), Some(digest)))
        }
        _ => Err(corrupt_evidence("incomplete evidence identity")),
    }
}

fn validate_decoded_semantics(record: &ClientStageAttemptRecord) -> Result<(), JobLedgerError> {
    let valid = match record.state {
        ClientStageState::Running => {
            record.output_fingerprint_sha256.is_none()
                && record.completed_at_ms.is_none()
                && record.retryable.is_none()
                && record.reason.is_none()
                && record.evidence.is_none()
                && record.evidence_sha256.is_none()
        }
        ClientStageState::Succeeded => {
            record.output_fingerprint_sha256.is_some()
                && record.completed_at_ms.is_some()
                && record.retryable == Some(false)
                && record.reason.is_none()
        }
        ClientStageState::Unavailable | ClientStageState::Failed => {
            record.output_fingerprint_sha256.is_none()
                && record.completed_at_ms.is_some()
                && record.retryable.is_some()
                && record.reason.is_some()
        }
        ClientStageState::Cancelled => {
            record.output_fingerprint_sha256.is_none()
                && record.completed_at_ms.is_some()
                && record.retryable == Some(false)
                && record.reason.is_some()
        }
    };
    if !valid || record.attempt == 0 || record.attempt > MAX_STAGE_ATTEMPTS {
        return Err(JobLedgerError::CorruptValue {
            field: "client_stage_attempt",
            value: "inconsistent stage semantics".into(),
        });
    }
    Ok(())
}

fn valid_component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_COMPONENT_BYTES
        && value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'/' | b':')
        })
}

fn valid_reason(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_REASON_BYTES
        && value
            .bytes()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
}

fn corrupt_evidence(value: &str) -> JobLedgerError {
    JobLedgerError::CorruptValue {
        field: "client_stage_evidence",
        value: value.into(),
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
