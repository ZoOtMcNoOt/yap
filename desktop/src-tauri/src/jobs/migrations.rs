use crate::jobs::model::{JobLedgerError, RecordingLanguageDecision};
use rusqlite::{Connection, OpenFlags, OptionalExtension, Transaction, TransactionBehavior};
use std::{path::Path, time::Duration};

const CURRENT_SCHEMA_VERSION: i64 = 14;
const MIGRATION_1_SQL: &str = include_str!("../../migrations/0001_job_ledger.sql");
const MIGRATION_2_SQL: &str = include_str!("../../migrations/0002_prepared_remote_jobs.sql");
const MIGRATION_3_SQL: &str = include_str!("../../migrations/0003_remote_spool_cleanup.sql");
const MIGRATION_4_SQL: &str = include_str!("../../migrations/0004_remote_create_attempt.sql");
const MIGRATION_5_SQL: &str = include_str!("../../migrations/0005_language_decisions.sql");
const MIGRATION_6_SQL: &str =
    include_str!("../../migrations/0006_immutable_language_decisions.sql");
const MIGRATION_7_SQL: &str = include_str!("../../migrations/0007_asr_catalog_binding.sql");
const MIGRATION_8_SQL: &str = include_str!("../../migrations/0008_job_ledger_write_probe.sql");
const MIGRATION_9_SQL: &str = include_str!("../../migrations/0009_client_stage_authority.sql");
const MIGRATION_10_SQL: &str = include_str!("../../migrations/0010_client_preflight_artifacts.sql");
const MIGRATION_11_SQL: &str =
    include_str!("../../migrations/0011_functional_language_disposition.sql");
const MIGRATION_12_SQL: &str = include_str!("../../migrations/0012_remote_authority_binding.sql");
const MIGRATION_13_SQL: &str = include_str!("../../migrations/0013_tenant_principal_authority.sql");
const MIGRATION_14_SQL: &str =
    include_str!("../../migrations/0014_remote_authentication_binding.sql");
const PRE_FUNCTIONAL_LANGUAGE_DISPOSITION: &str = "legacy_phase5_default";
const FUNCTIONAL_LANGUAGE_DISPOSITION: &str = "legacy_implicit_english_default";

pub(super) fn open_file(path: &Path) -> Result<Connection, JobLedgerError> {
    open_file_with_migration_hook(path, || {})
}

fn open_file_with_migration_hook(
    path: &Path,
    before_migration_transaction: impl FnOnce(),
) -> Result<Connection, JobLedgerError> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE
            | OpenFlags::SQLITE_OPEN_CREATE
            | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    configure_connection(&connection, true)?;
    migrate_with_hook(&mut connection, before_migration_transaction)?;
    Ok(connection)
}

#[cfg(test)]
pub(super) fn open_in_memory() -> Result<Connection, JobLedgerError> {
    let mut connection = Connection::open_in_memory()?;
    configure_connection(&connection, false)?;
    migrate(&mut connection)?;
    Ok(connection)
}

#[cfg(test)]
fn migrate(connection: &mut Connection) -> Result<(), JobLedgerError> {
    migrate_with_hook(connection, || {})
}

fn migrate_with_hook(
    connection: &mut Connection,
    before_migration_transaction: impl FnOnce(),
) -> Result<(), JobLedgerError> {
    before_migration_transaction();
    connection.pragma_update(None, "foreign_keys", false)?;
    let migration_result = (|| {
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let version: i64 = transaction.query_row("PRAGMA user_version", [], |row| row.get(0))?;
        match version {
            CURRENT_SCHEMA_VERSION => {}
            13 => {}
            12 => {}
            11 => {}
            10 => {}
            9 => {}
            8 => {}
            7 => {}
            6 => {}
            5 => {}
            4 => {
                transaction.execute_batch(MIGRATION_5_SQL)?;
            }
            3 => {
                transaction.execute_batch(MIGRATION_4_SQL)?;
                transaction.execute_batch(MIGRATION_5_SQL)?;
            }
            2 => {
                transaction.execute_batch(MIGRATION_3_SQL)?;
                transaction.execute_batch(MIGRATION_4_SQL)?;
                transaction.execute_batch(MIGRATION_5_SQL)?;
            }
            1 => {
                transaction.execute_batch(MIGRATION_2_SQL)?;
                transaction.execute_batch(MIGRATION_3_SQL)?;
                transaction.execute_batch(MIGRATION_4_SQL)?;
                transaction.execute_batch(MIGRATION_5_SQL)?;
            }
            0 => {
                transaction.execute_batch(MIGRATION_1_SQL)?;
                transaction.execute_batch(MIGRATION_2_SQL)?;
                transaction.execute_batch(MIGRATION_3_SQL)?;
                transaction.execute_batch(MIGRATION_4_SQL)?;
                transaction.execute_batch(MIGRATION_5_SQL)?;
            }
            unsupported => return Err(JobLedgerError::UnsupportedSchema(unsupported)),
        }
        if version < 6 {
            validate_existing_language_decisions(&transaction)?;
            transaction.execute_batch(MIGRATION_6_SQL)?;
        }
        if version < 7 {
            transaction.execute_batch(MIGRATION_7_SQL)?;
        }
        if version < 8 {
            transaction.execute_batch(MIGRATION_8_SQL)?;
        }
        if version < 9 {
            transaction.execute_batch(MIGRATION_9_SQL)?;
        }
        if version < 10 {
            transaction.execute_batch(MIGRATION_10_SQL)?;
        }
        if version < 11 {
            transaction.execute_batch(MIGRATION_11_SQL)?;
        }
        if version < 12 {
            transaction.execute_batch(MIGRATION_12_SQL)?;
        }
        if version < 13 {
            transaction.execute_batch(MIGRATION_13_SQL)?;
        }
        if version < 14 {
            transaction.execute_batch(MIGRATION_14_SQL)?;
        }
        let foreign_key_violation: Option<i64> = transaction
            .query_row(
                "SELECT 1 FROM pragma_foreign_key_check LIMIT 1",
                [],
                |row| row.get(0),
            )
            .optional()?;
        if foreign_key_violation.is_some() {
            return Err(JobLedgerError::InvalidRecord(
                "job ledger migration left invalid foreign-key references",
            ));
        }
        transaction.commit()?;
        Ok(())
    })();
    let foreign_keys_result = connection.pragma_update(None, "foreign_keys", true);
    migration_result?;
    foreign_keys_result?;
    Ok(())
}

fn validate_existing_language_decisions(
    transaction: &Transaction<'_>,
) -> Result<(), JobLedgerError> {
    let mut statement = transaction.prepare(
        "SELECT language_mode, language_bcp47, language_disposition FROM recording_jobs",
    )?;
    let decisions = statement.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, Option<String>>(1)?,
            row.get::<_, String>(2)?,
        ))
    })?;
    for decision in decisions {
        let (mode, language_bcp47, disposition) = decision?;
        let disposition = if disposition == PRE_FUNCTIONAL_LANGUAGE_DISPOSITION {
            FUNCTIONAL_LANGUAGE_DISPOSITION
        } else {
            &disposition
        };
        RecordingLanguageDecision::from_db(&mode, language_bcp47, disposition)?;
    }
    Ok(())
}

fn configure_connection(connection: &Connection, file_backed: bool) -> Result<(), JobLedgerError> {
    connection.busy_timeout(Duration::from_secs(5))?;
    connection.pragma_update(None, "foreign_keys", true)?;
    if file_backed {
        let journal_mode: String =
            connection.query_row("PRAGMA journal_mode = WAL", [], |row| row.get(0))?;
        if !journal_mode.eq_ignore_ascii_case("wal") {
            return Err(JobLedgerError::PragmaNotApplied {
                pragma: "journal_mode",
                requested: "WAL",
                actual: journal_mode,
            });
        }
    }
    connection.pragma_update(None, "synchronous", "FULL")?;
    Ok(())
}

#[cfg(test)]
fn migrate_with_sql(connection: &mut Connection, sql: &str) -> Result<(), JobLedgerError> {
    let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    transaction.execute_batch(sql)?;
    transaction.commit()?;
    Ok(())
}

#[cfg(test)]
mod tests;
