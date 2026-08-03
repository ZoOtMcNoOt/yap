use super::*;
use rusqlite::Connection;
use std::{
    fs,
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};

static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

#[test]
fn fresh_database_installs_the_current_owned_schema() {
    let connection = open_in_memory().unwrap();
    let identity: (i64, i64) = connection
        .query_row(
            "SELECT (SELECT application_id FROM pragma_application_id), (SELECT user_version FROM pragma_user_version)",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
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

    assert_eq!(identity, (CURRENT_APPLICATION_ID, CURRENT_SCHEMA_VERSION));
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

    connection
        .execute(
            "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, route, created_at_ms, updated_at_ms, language_mode, language_bcp47) VALUES ('current', 'meeting', 'imported_file', 'C:/current.wav', 'current.wav', 'queued_server', 'server_batch', 1, 1, 'fixed', 'en-US')",
            [],
        )
        .unwrap();
    let defaults: (String, i64) = connection
        .query_row(
            "SELECT language_disposition, remote_authority_version FROM recording_jobs WHERE job_id = 'current'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    assert_eq!(defaults, ("primary".into(), 2));
    let write_probe_generation: i64 = connection
        .query_row(
            "SELECT generation FROM job_ledger_write_probe WHERE singleton = 1",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(write_probe_generation, 0);
    assert!(connection.execute(
        "INSERT INTO job_chunks (job_id, owner_namespace, session_id, track_id, sequence_start, sequence_end, content_sha256, artifact_path) VALUES ('missing', 'local:test', 'session', 'mic', 0, 1, 'hash', 'artifact')",
        [],
    ).is_err());
}

#[test]
fn obsolete_language_dispositions_are_rejected() {
    let connection = open_in_memory().unwrap();

    for disposition in ["legacy_phase5_default", "legacy_implicit_english_default"] {
        let error = connection
            .execute(
                "INSERT INTO recording_jobs (job_id, session_mode, session_origin, source_path, display_name, status, route, created_at_ms, updated_at_ms, language_mode, language_bcp47, language_disposition) VALUES (?1, 'meeting', 'imported_file', 'C:/legacy.wav', 'legacy.wav', 'queued_server', 'server_batch', 1, 1, 'fixed', 'en-US', ?2)",
                [disposition, disposition],
            )
            .unwrap_err();
        assert!(error.to_string().contains("CHECK constraint failed"));
    }
}

#[test]
fn obsolete_schema_is_rejected_without_rewriting_owned_data() {
    let mut connection = Connection::open_in_memory().unwrap();
    configure_connection(&connection, false).unwrap();
    connection
        .execute_batch(
            "CREATE TABLE obsolete_owned_data (value TEXT NOT NULL); \
             INSERT INTO obsolete_owned_data VALUES ('preserve'); \
             PRAGMA user_version = 14;",
        )
        .unwrap();

    let error = initialize_or_validate_current_schema(&mut connection).unwrap_err();

    assert!(matches!(
        error,
        JobLedgerError::UnsupportedDatabaseIdentity {
            application_id: 0,
            schema_version: 14,
        }
    ));
    let preserved: (i64, i64, String) = connection
        .query_row(
            "SELECT (SELECT application_id FROM pragma_application_id), (SELECT user_version FROM pragma_user_version), value FROM obsolete_owned_data",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!(preserved, (0, 14, "preserve".into()));
}

#[test]
fn nonempty_unowned_database_is_rejected_without_claiming_or_rewriting_it() {
    let mut connection = Connection::open_in_memory().unwrap();
    configure_connection(&connection, false).unwrap();
    connection
        .execute_batch(
            "CREATE TABLE unowned_data (value TEXT NOT NULL); \
             INSERT INTO unowned_data VALUES ('preserve');",
        )
        .unwrap();

    let error = initialize_or_validate_current_schema(&mut connection).unwrap_err();

    assert!(matches!(error, JobLedgerError::DatabaseOwnershipConflict));
    let preserved: (i64, i64, String) = connection
        .query_row(
            "SELECT (SELECT application_id FROM pragma_application_id), (SELECT user_version FROM pragma_user_version), value FROM unowned_data",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!(preserved, (0, 0, "preserve".into()));
}

#[test]
fn another_app_database_is_rejected_even_at_the_current_version() {
    let mut connection = Connection::open_in_memory().unwrap();
    configure_connection(&connection, false).unwrap();
    connection
        .execute_batch(
            "CREATE TABLE foreign_owned_data (value TEXT NOT NULL); \
             INSERT INTO foreign_owned_data VALUES ('preserve'); \
             PRAGMA application_id = 42; \
             PRAGMA user_version = 1;",
        )
        .unwrap();

    let error = initialize_or_validate_current_schema(&mut connection).unwrap_err();

    assert!(matches!(
        error,
        JobLedgerError::UnsupportedDatabaseIdentity {
            application_id: 42,
            schema_version: 1,
        }
    ));
    let preserved: String = connection
        .query_row("SELECT value FROM foreign_owned_data", [], |row| row.get(0))
        .unwrap();
    assert_eq!(preserved, "preserve");
}

#[test]
fn reopening_an_initialized_database_is_idempotent() {
    let dir = temp_dir("reopen");
    let path = dir.join("jobs.sqlite3");
    drop(open_file(&path).unwrap());

    let connection = open_file(&path).unwrap();
    let identity: (i64, i64, i64) = connection
        .query_row(
            "SELECT (SELECT application_id FROM pragma_application_id), (SELECT user_version FROM pragma_user_version), (SELECT COUNT(*) FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%')",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!(
        identity,
        (CURRENT_APPLICATION_ID, CURRENT_SCHEMA_VERSION, 8)
    );

    drop(connection);
    fs::remove_dir_all(dir).unwrap();
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
fn failed_schema_install_rolls_back_every_change() {
    let mut connection = Connection::open_in_memory().unwrap();
    configure_connection(&connection, false).unwrap();
    let error = execute_schema_sql(
        &mut connection,
        "CREATE TABLE should_rollback (id INTEGER); THIS IS NOT SQL; PRAGMA user_version = 1;",
    )
    .unwrap_err();

    assert!(error.to_string().contains("syntax"));
    let state: (i64, i64) = connection
        .query_row(
            "SELECT (SELECT COUNT(*) FROM sqlite_schema WHERE name = 'should_rollback'), (SELECT user_version FROM pragma_user_version)",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    assert_eq!(state, (0, 0));
}

#[test]
fn locking_a_detected_language_requires_confirmation_evidence() {
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
fn concurrent_first_openers_share_one_atomic_schema_install() {
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
                open_file_with_schema_hook(&path, || {
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
        "both first openers must observe one atomic schema install: {connections:?}"
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
