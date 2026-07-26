//! Binds remote work to one local development authority or one signed-in account.

use rusqlite::{params, OptionalExtension, TransactionBehavior};

use crate::jobs::{JobLedgerError, RecordingRoute};

use super::JobLedger;

const DEVELOPMENT_AUTHORITY: &str = "development-loopback";

impl JobLedger {
    pub(crate) fn bind_remote_authority(
        &self,
        job_id: &str,
        authority: &str,
        authentication: &str,
    ) -> Result<(), JobLedgerError> {
        validate_remote_authority(authority, authentication)?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: (String, Option<String>, Option<String>, i64) = transaction
            .query_row(
                "SELECT route, remote_authority_binding, remote_authentication_binding, remote_authority_version FROM recording_jobs WHERE job_id = ?1",
                [job_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?;
        if RecordingRoute::from_db(&current.0)? != RecordingRoute::ServerBatch {
            return Err(JobLedgerError::InvalidRecord(
                "remote authority belongs only to server-batch work",
            ));
        }
        if current.3 != 2 {
            return Err(JobLedgerError::InvalidRecord(
                "legacy remote authority without authentication binding is quarantined",
            ));
        }
        match (current.1.as_deref(), current.2.as_deref()) {
            (Some(existing_authority), Some(existing_authentication)) => {
                validate_remote_authority(existing_authority, existing_authentication)?;
                if existing_authority == authority && existing_authentication == authentication {
                    return Ok(());
                }
                return Err(JobLedgerError::InvalidRecord(
                    "remote work is bound to a different server account or authentication configuration",
                ));
            }
            (None, None) => {}
            _ => {
                return Err(JobLedgerError::InvalidRecord(
                    "remote authority binding is incomplete",
                ));
            }
        }

        let legacy_remote_activity: bool = transaction.query_row(
            "SELECT \
                EXISTS(SELECT 1 FROM prepared_remote_jobs WHERE job_id = ?1 AND (server_job_id IS NOT NULL OR create_attempt_base_url IS NOT NULL)) \
                OR EXISTS(SELECT 1 FROM client_preflight_artifacts WHERE job_id = ?1 AND lid_started_at_ms IS NOT NULL) \
                OR EXISTS(SELECT 1 FROM job_stage_attempts WHERE job_id = ?1 AND stage = 'lid_preflight')",
            [job_id],
            |row| row.get(0),
        )?;
        if legacy_remote_activity && authority != DEVELOPMENT_AUTHORITY {
            return Err(JobLedgerError::InvalidRecord(
                "legacy remote work has no recoverable server-account binding",
            ));
        }
        let changed = transaction.execute(
            "UPDATE recording_jobs SET remote_authority_binding = ?1, remote_authentication_binding = ?2, remote_authority_version = 2 WHERE job_id = ?3 AND remote_authority_binding IS NULL AND remote_authentication_binding IS NULL AND remote_authority_version = 2",
            params![authority, authentication, job_id],
        )?;
        if changed != 1 {
            return Err(JobLedgerError::InvalidRecord(
                "remote authority binding lost its durable update race",
            ));
        }
        transaction.commit()?;
        Ok(())
    }

    pub(crate) fn remote_authority(
        &self,
        job_id: &str,
    ) -> Result<(String, String), JobLedgerError> {
        let connection = self.lock()?;
        let (authority, authentication, version): (Option<String>, Option<String>, i64) = connection
            .query_row(
                "SELECT remote_authority_binding, remote_authentication_binding, remote_authority_version FROM recording_jobs WHERE job_id = ?1",
                [job_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .optional()?
            .ok_or_else(|| JobLedgerError::NotFound(job_id.into()))?;
        if version != 2 {
            return Err(JobLedgerError::InvalidRecord(
                "legacy remote authority without authentication binding is quarantined",
            ));
        }
        let (authority, authentication) = match (authority, authentication) {
            (Some(authority), Some(authentication)) => (authority, authentication),
            (None, None) => {
                return Err(JobLedgerError::InvalidRecord(
                    "remote work has no server authority binding",
                ));
            }
            _ => {
                return Err(JobLedgerError::InvalidRecord(
                    "remote authority binding is incomplete",
                ));
            }
        };
        validate_remote_authority(&authority, &authentication)?;
        Ok((authority, authentication))
    }
}

pub(super) fn validate_remote_authority(
    authority: &str,
    authentication: &str,
) -> Result<(), JobLedgerError> {
    if (authority == DEVELOPMENT_AUTHORITY && authentication == DEVELOPMENT_AUTHORITY)
        || (valid_digest(authority) && valid_digest(authentication))
    {
        return Ok(());
    }
    Err(JobLedgerError::InvalidRecord(
        "remote server authority binding is invalid",
    ))
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}
