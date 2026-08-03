use crate::jobs::model::JobLedgerError;
use rusqlite::{Connection, OpenFlags, OptionalExtension, TransactionBehavior};
use std::{path::Path, time::Duration};

const CURRENT_SCHEMA_VERSION: i64 = 1;
const CURRENT_APPLICATION_ID: i64 = 1_497_452_618;
const CURRENT_SCHEMA_SQL: &str = include_str!("../../migrations/0001_current_job_ledger.sql");

pub(super) fn open_file(path: &Path) -> Result<Connection, JobLedgerError> {
    open_file_with_schema_hook(path, || {})
}

fn open_file_with_schema_hook(
    path: &Path,
    before_schema_transaction: impl FnOnce(),
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
    initialize_or_validate_current_schema_with_hook(&mut connection, before_schema_transaction)?;
    Ok(connection)
}

#[cfg(test)]
pub(super) fn open_in_memory() -> Result<Connection, JobLedgerError> {
    let mut connection = Connection::open_in_memory()?;
    configure_connection(&connection, false)?;
    initialize_or_validate_current_schema(&mut connection)?;
    Ok(connection)
}

#[cfg(test)]
fn initialize_or_validate_current_schema(
    connection: &mut Connection,
) -> Result<(), JobLedgerError> {
    initialize_or_validate_current_schema_with_hook(connection, || {})
}

fn initialize_or_validate_current_schema_with_hook(
    connection: &mut Connection,
    before_schema_transaction: impl FnOnce(),
) -> Result<(), JobLedgerError> {
    before_schema_transaction();
    connection.pragma_update(None, "foreign_keys", false)?;
    let schema_result = (|| {
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let version: i64 = transaction.query_row("PRAGMA user_version", [], |row| row.get(0))?;
        let application_id: i64 =
            transaction.query_row("PRAGMA application_id", [], |row| row.get(0))?;

        match (application_id, version) {
            (CURRENT_APPLICATION_ID, CURRENT_SCHEMA_VERSION) => {}
            (0, 0) => {
                let existing_object: Option<i64> = transaction
                    .query_row(
                        "SELECT 1 FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' LIMIT 1",
                        [],
                        |row| row.get(0),
                    )
                    .optional()?;
                if existing_object.is_some() {
                    return Err(JobLedgerError::DatabaseOwnershipConflict);
                }
                transaction.execute_batch(CURRENT_SCHEMA_SQL)?;
            }
            (application_id, schema_version) => {
                return Err(JobLedgerError::UnsupportedDatabaseIdentity {
                    application_id,
                    schema_version,
                });
            }
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
                "job ledger schema contains invalid foreign-key references",
            ));
        }
        transaction.commit()?;
        Ok(())
    })();
    let foreign_keys_result = connection.pragma_update(None, "foreign_keys", true);
    schema_result?;
    foreign_keys_result?;
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
fn execute_schema_sql(connection: &mut Connection, sql: &str) -> Result<(), JobLedgerError> {
    let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    transaction.execute_batch(sql)?;
    transaction.commit()?;
    Ok(())
}

#[cfg(test)]
mod tests;
