use crate::jobs::model::{JobLedgerError, RecordingLanguageDecision};
use rusqlite::{Connection, OpenFlags, OptionalExtension, Transaction, TransactionBehavior};
use std::{path::Path, time::Duration};

const CURRENT_SCHEMA_VERSION: i64 = 12;
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
mod tests {
    use super::*;
    use rusqlite::Connection;
    use std::{
        fs,
        sync::atomic::{AtomicU64, Ordering},
        time::Duration,
    };

    static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

    #[test]
    fn migration_creates_versioned_constrained_schema_and_foreign_keys() {
        let connection = open_in_memory().unwrap();
        let version: i64 = connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .unwrap();
        let foreign_keys: i64 = connection
            .query_row("PRAGMA foreign_keys", [], |row| row.get(0))
            .unwrap();
        let tables: Vec<String> = {
            let mut statement = connection
                .prepare("SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name")
                .unwrap();
            statement
                .query_map([], |row| row.get(0))
                .unwrap()
                .collect::<Result<_, _>>()
                .unwrap()
        };

        assert_eq!(version, CURRENT_SCHEMA_VERSION);
        assert_eq!(foreign_keys, 1);
        assert_eq!(
            tables,
            [
                "client_preflight_artifacts",
                "detached_remote_cancellations",
                "job_chunks",
                "job_ledger_write_probe",
                "job_stage_attempts",
                "prepared_remote_jobs",
                "recording_jobs",
                "remote_spool_cleanup",
            ]
        );
        assert!(connection.execute(
            "INSERT INTO job_chunks (job_id, owner_namespace, session_id, track_id, sequence_start, sequence_end, content_sha256, artifact_path) VALUES ('missing', 'local:test', 'session', 'mic', 0, 1, 'hash', 'artifact')",
            [],
        ).is_err());
        connection.execute(
            "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, created_at_ms, updated_at_ms) VALUES ('language-check', 'meeting', 'imported_file', 'C:/language.wav', 'language.wav', 'queued_server', 1, 1)",
            [],
        ).unwrap();
        let error = connection
            .execute(
                "UPDATE recording_jobs SET language_mode = 'fixed', language_bcp47 = 'fr-FR', language_disposition = 'manual_override' WHERE job_id = 'language-check'",
                [],
            )
            .unwrap_err();
        assert!(error.to_string().contains("confirmation"));
        let language: (String, Option<String>, String) = connection
            .query_row(
                "SELECT language_mode, language_bcp47, language_disposition FROM recording_jobs WHERE job_id = 'language-check'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(
            language,
            (
                "fixed".into(),
                Some("en-US".into()),
                "legacy_implicit_english_default".into()
            )
        );
    }

    #[test]
    fn file_database_uses_wal_full_sync_and_five_second_timeout() {
        let dir = temp_dir("pragmas");
        let path = dir.join("jobs.sqlite3");
        let connection = open_file(&path).unwrap();
        let journal: String = connection
            .query_row("PRAGMA journal_mode", [], |row| row.get(0))
            .unwrap();
        let synchronous: i64 = connection
            .query_row("PRAGMA synchronous", [], |row| row.get(0))
            .unwrap();
        let busy_timeout: i64 = connection
            .query_row("PRAGMA busy_timeout", [], |row| row.get(0))
            .unwrap();

        assert_eq!(journal, "wal");
        assert_eq!(synchronous, 2);
        assert_eq!(busy_timeout, Duration::from_secs(5).as_millis() as i64);
        drop(connection);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn file_configuration_rejects_a_journal_mode_other_than_wal() {
        let connection = Connection::open_in_memory().unwrap();

        let error = configure_connection(&connection, true).unwrap_err();

        assert!(error.to_string().contains("requested WAL"));
        assert!(error.to_string().contains("memory"));
    }

    #[test]
    fn failed_migration_rolls_back_every_schema_change() {
        let mut connection = Connection::open_in_memory().unwrap();
        configure_connection(&connection, false).unwrap();
        let error = migrate_with_sql(
            &mut connection,
            "CREATE TABLE should_rollback (id INTEGER); THIS IS NOT SQL; PRAGMA user_version = 1;",
        )
        .unwrap_err();

        assert!(error.to_string().contains("syntax"));
        let count: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM sqlite_schema WHERE name = 'should_rollback'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        let version: i64 = connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .unwrap();
        assert_eq!(count, 0);
        assert_eq!(version, 0);
    }

    #[test]
    fn reopening_an_initialized_database_is_idempotent() {
        let dir = temp_dir("reopen");
        let path = dir.join("jobs.sqlite3");
        drop(open_file(&path).unwrap());
        let connection = open_file(&path).unwrap();
        let version: i64 = connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .unwrap();
        let table_count: i64 = connection.query_row(
            "SELECT COUNT(*) FROM sqlite_schema WHERE type = 'table' AND name IN ('recording_jobs', 'job_chunks', 'job_ledger_write_probe', 'job_stage_attempts', 'client_preflight_artifacts', 'prepared_remote_jobs', 'detached_remote_cancellations', 'remote_spool_cleanup')",
            [],
            |row| row.get(0),
        ).unwrap();
        assert_eq!((version, table_count), (CURRENT_SCHEMA_VERSION, 8));
        drop(connection);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn future_schema_fails_closed_without_rewriting_the_database() {
        let mut connection = Connection::open_in_memory().unwrap();
        configure_connection(&connection, false).unwrap();
        connection
            .execute_batch(
                "CREATE TABLE future_owned_data (value TEXT NOT NULL); \
                 INSERT INTO future_owned_data VALUES ('preserve'); \
                 PRAGMA user_version = 13;",
            )
            .unwrap();

        let error = migrate(&mut connection).unwrap_err();

        assert!(matches!(error, JobLedgerError::UnsupportedSchema(13)));
        let state: (i64, String) = connection
            .query_row(
                "SELECT (SELECT user_version FROM pragma_user_version), value FROM future_owned_data",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();
        assert_eq!(state, (13, "preserve".into()));
    }

    #[test]
    fn version_one_database_upgrades_without_replacing_existing_jobs() {
        let mut connection = Connection::open_in_memory().unwrap();
        configure_connection(&connection, false).unwrap();
        connection.execute_batch(MIGRATION_1_SQL).unwrap();
        connection.execute(
            "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, created_at_ms, updated_at_ms) VALUES ('existing', 'meeting', 'imported_file', 'C:/existing.wav', 'existing.wav', 'queued_server', 1, 1)",
            [],
        ).unwrap();

        migrate(&mut connection).unwrap();

        let version: i64 = connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .unwrap();
        let existing: String = connection
            .query_row(
                "SELECT display_name FROM recording_jobs WHERE job_id = 'existing'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        let remote_table: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM sqlite_schema WHERE type = 'table' AND name = 'prepared_remote_jobs'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        let language: (String, Option<String>, String) = connection
            .query_row(
                "SELECT language_mode, language_bcp47, language_disposition FROM recording_jobs WHERE job_id = 'existing'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(
            (version, existing.as_str(), remote_table),
            (CURRENT_SCHEMA_VERSION, "existing.wav", 1)
        );
        assert_eq!(
            language,
            (
                "fixed".into(),
                Some("en-US".into()),
                "legacy_implicit_english_default".into()
            )
        );
    }

    #[test]
    fn version_three_database_preserves_prepared_state_and_adds_create_attempt_origin() {
        let mut connection = Connection::open_in_memory().unwrap();
        configure_connection(&connection, false).unwrap();
        connection.execute_batch(MIGRATION_1_SQL).unwrap();
        connection.execute_batch(MIGRATION_2_SQL).unwrap();
        connection.execute_batch(MIGRATION_3_SQL).unwrap();
        connection.execute(
            "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, created_at_ms, updated_at_ms) VALUES ('existing', 'meeting', 'imported_file', 'C:/existing.wav', 'existing.wav', 'uploading', 1, 1)",
            [],
        ).unwrap();
        connection.execute(
            "INSERT INTO prepared_remote_jobs (job_id, create_request_json, capture_manifest_path, capture_manifest_sha256) VALUES ('existing', '{}', 'C:/manifest.json', ?1)",
            ["a".repeat(64)],
        ).unwrap();

        migrate(&mut connection).unwrap();

        let version: i64 = connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .unwrap();
        let prepared: (String, Option<String>) = connection
            .query_row(
                "SELECT create_request_json, create_attempt_base_url FROM prepared_remote_jobs WHERE job_id = 'existing'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();
        assert_eq!(version, CURRENT_SCHEMA_VERSION);
        assert_eq!(prepared, ("{}".into(), None));
    }

    #[test]
    fn version_five_database_preserves_decisions_and_makes_them_immutable() {
        let mut connection = Connection::open_in_memory().unwrap();
        configure_connection(&connection, false).unwrap();
        connection.execute_batch(MIGRATION_1_SQL).unwrap();
        connection.execute_batch(MIGRATION_2_SQL).unwrap();
        connection.execute_batch(MIGRATION_3_SQL).unwrap();
        connection.execute_batch(MIGRATION_4_SQL).unwrap();
        connection.execute_batch(MIGRATION_5_SQL).unwrap();
        connection.execute(
            "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, created_at_ms, updated_at_ms, language_mode, language_bcp47, language_disposition) VALUES ('existing-language', 'meeting', 'imported_file', 'C:/existing.wav', 'existing.wav', 'queued_server', 1, 1, 'fixed', 'fr-FR', 'manual_override')",
            [],
        ).unwrap();

        migrate(&mut connection).unwrap();

        let version: i64 = connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .unwrap();
        assert_eq!(version, CURRENT_SCHEMA_VERSION);
        let error = connection
            .execute(
                "UPDATE recording_jobs SET language_mode = 'fixed', language_bcp47 = 'de-DE', language_disposition = 'primary' WHERE job_id = 'existing-language'",
                [],
            )
            .unwrap_err();
        assert!(error.to_string().contains("confirmation"));
        let language: (String, Option<String>, String) = connection
            .query_row(
                "SELECT language_mode, language_bcp47, language_disposition FROM recording_jobs WHERE job_id = 'existing-language'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(
            language,
            (
                "fixed".into(),
                Some("fr-FR".into()),
                "manual_override".into()
            )
        );
    }

    #[test]
    fn version_five_migration_rejects_invalid_decisions_atomically() {
        let mut connection = Connection::open_in_memory().unwrap();
        configure_connection(&connection, false).unwrap();
        connection.execute_batch(MIGRATION_1_SQL).unwrap();
        connection.execute_batch(MIGRATION_2_SQL).unwrap();
        connection.execute_batch(MIGRATION_3_SQL).unwrap();
        connection.execute_batch(MIGRATION_4_SQL).unwrap();
        connection.execute_batch(MIGRATION_5_SQL).unwrap();
        connection.execute(
            "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, created_at_ms, updated_at_ms, language_mode, language_bcp47, language_disposition) VALUES ('invalid-language', 'meeting', 'imported_file', 'C:/invalid.wav', 'invalid.wav', 'queued_server', 1, 1, 'fixed', 'EN_us', 'primary')",
            [],
        ).unwrap();

        let error = migrate(&mut connection).unwrap_err();

        assert!(error.to_string().contains("invalid language_decision"));
        let version: i64 = connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .unwrap();
        let trigger_count: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM sqlite_schema WHERE type = 'trigger' AND name = 'recording_jobs_language_decision_immutable'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!((version, trigger_count), (5, 0));
        let language: String = connection
            .query_row(
                "SELECT language_bcp47 FROM recording_jobs WHERE job_id = 'invalid-language'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(language, "EN_us");
    }

    #[test]
    fn version_six_jobs_upgrade_with_a_nullable_mutable_pre_dispatch_catalog_binding() {
        let mut connection = Connection::open_in_memory().unwrap();
        configure_connection(&connection, false).unwrap();
        connection.execute_batch(MIGRATION_1_SQL).unwrap();
        connection.execute_batch(MIGRATION_2_SQL).unwrap();
        connection.execute_batch(MIGRATION_3_SQL).unwrap();
        connection.execute_batch(MIGRATION_4_SQL).unwrap();
        connection.execute_batch(MIGRATION_5_SQL).unwrap();
        connection.execute_batch(MIGRATION_6_SQL).unwrap();
        connection.execute(
            "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, route, created_at_ms, updated_at_ms, language_mode, language_bcp47, language_disposition) VALUES ('legacy-six', 'meeting', 'imported_file', 'C:/legacy.wav', 'legacy.wav', 'uploading', 'server_batch', 1, 1, 'fixed', 'en-US', 'legacy_implicit_english_default')",
            [],
        ).unwrap();

        migrate(&mut connection).unwrap();

        let migrated: (i64, Option<String>, Option<String>, String) = connection
            .query_row(
                "SELECT (SELECT user_version FROM pragma_user_version), asr_catalog_origin, asr_catalog_revision, remote_authority_binding FROM recording_jobs WHERE job_id = 'legacy-six'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .unwrap();
        assert_eq!(
            migrated,
            (
                CURRENT_SCHEMA_VERSION,
                None,
                None,
                "development-loopback".into()
            )
        );
        assert!(connection
            .execute(
                "UPDATE recording_jobs SET asr_catalog_origin = 'http://127.0.0.1:18765' WHERE job_id = 'legacy-six'",
                [],
            )
            .is_err());
        connection.execute(
            "UPDATE recording_jobs SET asr_catalog_origin = 'http://127.0.0.1:18765', asr_catalog_revision = ?1 WHERE job_id = 'legacy-six'",
            ["a".repeat(64)],
        ).unwrap();
        connection.execute(
            "INSERT INTO prepared_remote_jobs (job_id, create_request_json, capture_manifest_path, capture_manifest_sha256, create_attempt_base_url) VALUES ('legacy-six', '{}', 'C:/manifest.json', ?1, 'http://127.0.0.1:18765')",
            ["b".repeat(64)],
        ).unwrap();
        let error = connection.execute(
            "UPDATE recording_jobs SET asr_catalog_origin = 'http://127.0.0.1:28765', asr_catalog_revision = ?1 WHERE job_id = 'legacy-six'",
            ["c".repeat(64)],
        ).unwrap_err();
        assert!(error.to_string().contains("frozen after remote dispatch"));
    }

    #[test]
    fn version_eight_jobs_remain_locked_with_an_explicit_incomplete_history_prefix() {
        let mut connection = Connection::open_in_memory().unwrap();
        configure_connection(&connection, false).unwrap();
        for migration in [
            MIGRATION_1_SQL,
            MIGRATION_2_SQL,
            MIGRATION_3_SQL,
            MIGRATION_4_SQL,
            MIGRATION_5_SQL,
            MIGRATION_6_SQL,
            MIGRATION_7_SQL,
            MIGRATION_8_SQL,
        ] {
            connection.execute_batch(migration).unwrap();
        }
        connection.execute(
            "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, created_at_ms, updated_at_ms, language_mode, language_bcp47, language_disposition) VALUES ('legacy-eight', 'meeting', 'imported_file', 'C:/legacy.wav', 'legacy.wav', 'queued_server', 1, 1, 'fixed', 'en-US', 'primary')",
            [],
        ).unwrap();

        migrate(&mut connection).unwrap();

        let migrated: (i64, i64, i64) = connection
            .query_row(
                "SELECT (SELECT user_version FROM pragma_user_version), language_decision_locked, client_stage_history_complete FROM recording_jobs WHERE job_id = 'legacy-eight'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(migrated, (CURRENT_SCHEMA_VERSION, 1, 0));
        assert!(connection
            .execute(
                "UPDATE recording_jobs SET language_decision_locked = 0 WHERE job_id = 'legacy-eight'",
                [],
            )
            .is_err());
    }

    #[test]
    fn intermediate_language_default_is_rewritten_to_functional_vocabulary() {
        let mut connection = Connection::open_in_memory().unwrap();
        configure_connection(&connection, false).unwrap();
        for migration in [
            MIGRATION_1_SQL,
            MIGRATION_2_SQL,
            MIGRATION_3_SQL,
            MIGRATION_4_SQL,
        ] {
            connection.execute_batch(migration).unwrap();
        }
        let intermediate_language_migration = MIGRATION_5_SQL.replace(
            FUNCTIONAL_LANGUAGE_DISPOSITION,
            PRE_FUNCTIONAL_LANGUAGE_DISPOSITION,
        );
        connection
            .execute_batch(&intermediate_language_migration)
            .unwrap();
        for migration in [
            MIGRATION_6_SQL,
            MIGRATION_7_SQL,
            MIGRATION_8_SQL,
            MIGRATION_9_SQL,
            MIGRATION_10_SQL,
        ] {
            connection.execute_batch(migration).unwrap();
        }
        connection
            .execute(
                "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, created_at_ms, updated_at_ms) VALUES ('intermediate-default', 'meeting', 'imported_file', 'C:/legacy.wav', 'legacy.wav', 'queued_server', 1, 1)",
                [],
            )
            .unwrap();
        connection
            .execute(
                "INSERT INTO job_chunks (job_id, owner_namespace, session_id, track_id, sequence_start, sequence_end, content_sha256, artifact_path) VALUES ('intermediate-default', 'local:test', 'session', 'mic', 0, 1, 'hash', 'artifact')",
                [],
            )
            .unwrap();

        migrate(&mut connection).unwrap();

        let migrated: (i64, String, i64) = connection
            .query_row(
                "SELECT (SELECT user_version FROM pragma_user_version), language_disposition, (SELECT COUNT(*) FROM job_chunks WHERE job_id = 'intermediate-default') FROM recording_jobs WHERE job_id = 'intermediate-default'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(
            migrated,
            (
                CURRENT_SCHEMA_VERSION,
                "legacy_implicit_english_default".into(),
                1
            )
        );
        let foreign_key_errors: i64 = connection
            .query_row("SELECT COUNT(*) FROM pragma_foreign_key_check", [], |row| {
                row.get(0)
            })
            .unwrap();
        assert_eq!(foreign_key_errors, 0);
    }

    #[test]
    fn version_five_phase_derived_default_reaches_the_functional_migration() {
        let mut connection = Connection::open_in_memory().unwrap();
        configure_connection(&connection, false).unwrap();
        for migration in [
            MIGRATION_1_SQL,
            MIGRATION_2_SQL,
            MIGRATION_3_SQL,
            MIGRATION_4_SQL,
        ] {
            connection.execute_batch(migration).unwrap();
        }
        connection
            .execute_batch(&MIGRATION_5_SQL.replace(
                FUNCTIONAL_LANGUAGE_DISPOSITION,
                PRE_FUNCTIONAL_LANGUAGE_DISPOSITION,
            ))
            .unwrap();
        connection
            .execute(
                "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, created_at_ms, updated_at_ms) VALUES ('version-five-default', 'meeting', 'imported_file', 'C:/legacy.wav', 'legacy.wav', 'accepted', 1, 1)",
                [],
            )
            .unwrap();

        migrate(&mut connection).unwrap();

        let migrated: (i64, String) = connection
            .query_row(
                "SELECT (SELECT user_version FROM pragma_user_version), language_disposition FROM recording_jobs WHERE job_id = 'version-five-default'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();
        assert_eq!(
            migrated,
            (
                CURRENT_SCHEMA_VERSION,
                FUNCTIONAL_LANGUAGE_DISPOSITION.into()
            )
        );
    }

    #[test]
    fn unlocked_language_decision_requires_same_transaction_confirmation_evidence() {
        let mut connection = open_in_memory().unwrap();
        connection.execute(
            "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, created_at_ms, updated_at_ms, language_mode, language_bcp47, language_disposition, language_decision_locked, client_stage_history_complete) VALUES ('confirmation', 'meeting', 'imported_file', 'C:/confirmation.wav', 'confirmation.wav', 'accepted', 1, 1, 'fixed', 'en-US', 'primary', 0, 1)",
            [],
        ).unwrap();
        assert!(connection
            .execute(
                "UPDATE recording_jobs SET language_bcp47 = 'fr-FR', language_disposition = 'detected_suggestion_confirmed', language_decision_locked = 1 WHERE job_id = 'confirmation'",
                [],
            )
            .is_err());

        let transaction = connection.transaction().unwrap();
        transaction.execute(
            "INSERT INTO job_stage_attempts (job_id, stage, attempt, state, input_fingerprint_sha256, output_fingerprint_sha256, component_id, component_revision, started_at_ms, completed_at_ms, retryable) VALUES ('confirmation', 'user_confirmation', 1, 'succeeded', ?1, ?2, 'yap-language-confirmation', 'language-confirmation-v1', 2, 2, 0)",
            ["a".repeat(64), "b".repeat(64)],
        ).unwrap();
        transaction.execute(
            "UPDATE recording_jobs SET language_bcp47 = 'fr-FR', language_disposition = 'detected_suggestion_confirmed', language_decision_locked = 1 WHERE job_id = 'confirmation'",
            [],
        ).unwrap();
        transaction.commit().unwrap();

        let confirmed: (String, String, i64) = connection
            .query_row(
                "SELECT language_bcp47, language_disposition, language_decision_locked FROM recording_jobs WHERE job_id = 'confirmation'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(
            confirmed,
            ("fr-FR".into(), "detected_suggestion_confirmed".into(), 1)
        );
    }

    #[test]
    fn concurrent_first_openers_share_one_atomic_migration_decision() {
        let dir = temp_dir("concurrent-first-open");
        let path = dir.join("jobs.sqlite3");
        let bootstrap = Connection::open(&path).unwrap();
        configure_connection(&bootstrap, true).unwrap();
        drop(bootstrap);
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
        let openers: Vec<_> = (0..2)
            .map(|_| {
                let path = path.clone();
                let barrier = std::sync::Arc::clone(&barrier);
                std::thread::spawn(move || {
                    open_file_with_migration_hook(&path, || {
                        barrier.wait();
                    })
                })
            })
            .collect();

        let connections: Vec<_> = openers
            .into_iter()
            .map(|opener| opener.join().unwrap())
            .collect();
        assert!(
            connections.iter().all(Result::is_ok),
            "both first openers must observe one idempotent migration: {connections:?}"
        );
        drop(connections);
        fs::remove_dir_all(dir).unwrap();
    }

    fn temp_dir(label: &str) -> std::path::PathBuf {
        let id = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!(
            "yap-job-ledger-{label}-{}-{id}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).unwrap();
        dir
    }
}
