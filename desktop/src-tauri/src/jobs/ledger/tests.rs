use super::records::validate_server_base_url;
use super::*;
use crate::jobs::model::{transition_policy, TransitionPolicy};
use crate::jobs::{
    NewPreparedRemoteJob, RecordingJobStatus, RecordingRoute, SessionMode, SessionOrigin,
    SourceOwnership,
};
use rusqlite::types::ValueRef;
use std::{
    fs,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Barrier,
    },
    thread,
};

static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

#[test]
fn persisted_unknown_enum_is_reported_as_corruption() {
    let ledger = JobLedger::open_in_memory().unwrap();
    ledger.insert_job(&imported_job("bad-enum")).unwrap();
    {
        let connection = ledger.connection.lock().unwrap();
        connection
            .execute_batch("PRAGMA ignore_check_constraints = ON;")
            .unwrap();
        connection
            .execute(
                "UPDATE recording_jobs SET status = 'invented_ui_state' WHERE job_id = 'bad-enum'",
                [],
            )
            .unwrap();
    }
    assert!(matches!(
        ledger.get_job("bad-enum"),
        Err(JobLedgerError::CorruptValue {
            field: "status",
            ..
        })
    ));
}

#[test]
fn durable_remote_origins_use_the_same_numeric_loopback_contract() {
    assert!(validate_server_base_url("http://127.0.0.1:18765").is_ok());
    assert!(validate_server_base_url("http://[::1]:18765").is_ok());
    assert!(validate_server_base_url("http://localhost:18765").is_err());
    assert!(validate_server_base_url("http://127.0.0.1:18765/alternate").is_err());
}

#[test]
fn restart_recovers_nonterminal_jobs_and_chunks() {
    let dir = temp_dir("restart");
    let path = dir.join("jobs.sqlite3");
    let source = dir.join("interview.wav");
    fs::write(&source, b"RIFF-restart-fixture").unwrap();
    let mut job = imported_job_at("restart-job", source.clone());
    job.status = RecordingJobStatus::QueuedServer;
    job.route = Some(RecordingRoute::ServerBatch);
    job.asr_catalog_binding = Some(crate::jobs::AsrCatalogBinding::for_test());
    let chunk = chunk_at(dir.join("chunk-0.flac"));
    {
        let ledger = JobLedger::open(&path).unwrap();
        ledger.insert_job_with_chunks(&job, &[chunk]).unwrap();
    }

    let ledger = JobLedger::open(&path).unwrap();
    let recovered = ledger.list_recoverable_jobs().unwrap();
    assert_eq!(recovered.len(), 1);
    assert_eq!(recovered[0].job_id, "restart-job");
    assert_eq!(recovered[0].source_path.as_deref(), Some(source.as_path()));
    assert_eq!(
        recovered[0].language_decision,
        crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap()
    );
    assert_eq!(ledger.list_chunks("restart-job").unwrap().len(), 1);
    drop(ledger);
    fs::remove_dir_all(dir).unwrap();
}

mod remote_state;

mod concurrency;

mod lifecycle_retention;

#[test]
fn restart_database_has_exact_metadata_surface_and_no_payload_content() {
    let dir = temp_dir("content-audit");
    let path = dir.join("jobs.sqlite3");
    let source = dir.join("source.wav");
    let output = dir.join("output.txt");
    let artifact = dir.join("chunk.flac");
    let wav_bytes = b"RIFF\x00\x01YAP_PRIVATE_WAV_BYTES";
    let transcript = "YAP_PRIVATE_TRANSCRIPT_SENTENCE";
    fs::write(&source, wav_bytes).unwrap();
    fs::write(&output, transcript).unwrap();
    fs::write(&artifact, b"encoded audio bytes").unwrap();
    let mut job = imported_job_at("audit-job", source);
    job.output_path = Some(output);
    {
        let ledger = JobLedger::open(&path).unwrap();
        ledger
            .insert_job_with_chunks(&job, &[chunk_at(artifact)])
            .unwrap();
    }

    let connection = rusqlite::Connection::open(&path).unwrap();
    let table_names: Vec<String> = {
        let mut statement = connection.prepare(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).unwrap();
        statement
            .query_map([], |row| row.get(0))
            .unwrap()
            .collect::<Result<_, _>>()
            .unwrap()
    };
    assert_eq!(
        table_names,
        [
            "detached_remote_cancellations",
            "job_chunks",
            "job_ledger_write_probe",
            "job_stage_attempts",
            "prepared_remote_jobs",
            "recording_jobs",
            "remote_spool_cleanup",
        ]
    );
    let expected_columns = [
        (
            "detached_remote_cancellations",
            &[
                ("server_base_url", "TEXT"),
                ("server_job_id", "TEXT"),
                ("create_request_json", "TEXT"),
                ("queued_at_ms", "INTEGER"),
            ][..],
        ),
        (
            "job_chunks",
            &[
                ("job_id", "TEXT"),
                ("owner_namespace", "TEXT"),
                ("session_id", "TEXT"),
                ("track_id", "TEXT"),
                ("sequence_start", "INTEGER"),
                ("sequence_end", "INTEGER"),
                ("content_sha256", "TEXT"),
                ("artifact_path", "TEXT"),
                ("upload_offset", "INTEGER"),
                ("acknowledged_object_id", "TEXT"),
                ("acknowledged_at_ms", "INTEGER"),
                ("content_byte_length", "INTEGER"),
            ][..],
        ),
        (
            "job_ledger_write_probe",
            &[("singleton", "INTEGER"), ("generation", "INTEGER")][..],
        ),
        (
            "job_stage_attempts",
            &[
                ("job_id", "TEXT"),
                ("stage", "TEXT"),
                ("attempt", "INTEGER"),
                ("state", "TEXT"),
                ("input_fingerprint_sha256", "TEXT"),
                ("output_fingerprint_sha256", "TEXT"),
                ("component_id", "TEXT"),
                ("component_revision", "TEXT"),
                ("started_at_ms", "INTEGER"),
                ("completed_at_ms", "INTEGER"),
                ("retryable", "INTEGER"),
                ("reason", "TEXT"),
                ("evidence_json", "TEXT"),
                ("evidence_sha256", "TEXT"),
            ][..],
        ),
        (
            "prepared_remote_jobs",
            &[
                ("job_id", "TEXT"),
                ("create_request_json", "TEXT"),
                ("capture_manifest_path", "TEXT"),
                ("capture_manifest_sha256", "TEXT"),
                ("server_job_id", "TEXT"),
                ("server_base_url", "TEXT"),
                ("server_cancellation_acknowledged_at_ms", "INTEGER"),
                ("create_attempt_base_url", "TEXT"),
            ][..],
        ),
        (
            "recording_jobs",
            &[
                ("job_id", "TEXT"),
                ("session_mode", "TEXT"),
                ("session_origin", "TEXT"),
                ("source_path", "TEXT"),
                ("source_ownership", "TEXT"),
                ("output_path", "TEXT"),
                ("display_name", "TEXT"),
                ("status", "TEXT"),
                ("route", "TEXT"),
                ("attempt_count", "INTEGER"),
                ("next_attempt_at_ms", "INTEGER"),
                ("cancellation_requested", "INTEGER"),
                ("capture_commit_path", "TEXT"),
                ("capture_manifest_sha256", "TEXT"),
                ("error_code", "TEXT"),
                ("error_message", "TEXT"),
                ("created_at_ms", "INTEGER"),
                ("updated_at_ms", "INTEGER"),
                ("expires_at_ms", "INTEGER"),
                ("language_mode", "TEXT"),
                ("language_bcp47", "TEXT"),
                ("language_disposition", "TEXT"),
                ("asr_catalog_origin", "TEXT"),
                ("asr_catalog_revision", "TEXT"),
                ("language_decision_locked", "INTEGER"),
                ("client_stage_history_complete", "INTEGER"),
            ][..],
        ),
        (
            "remote_spool_cleanup",
            &[("job_id", "TEXT"), ("queued_at_ms", "INTEGER")][..],
        ),
    ];
    for (table, expected) in expected_columns {
        let actual: Vec<(String, String)> = {
            let mut statement = connection
                .prepare(&format!("PRAGMA table_info(\"{table}\")"))
                .unwrap();
            statement
                .query_map([], |row| Ok((row.get(1)?, row.get(2)?)))
                .unwrap()
                .collect::<Result<_, _>>()
                .unwrap()
        };
        assert_eq!(
            actual,
            expected
                .iter()
                .map(|(name, kind)| ((*name).into(), (*kind).into()))
                .collect::<Vec<(String, String)>>(),
            "{table} added an unapproved payload, credential, or embedding storage surface"
        );

        let mut statement = connection
            .prepare(&format!("SELECT * FROM \"{table}\""))
            .unwrap();
        let column_count = statement.column_count();
        let mut rows = statement.query([]).unwrap();
        while let Some(row) = rows.next().unwrap() {
            for column in 0..column_count {
                match row.get_ref(column).unwrap() {
                    ValueRef::Text(value) | ValueRef::Blob(value) => {
                        assert!(!value
                            .windows(wav_bytes.len())
                            .any(|window| window == wav_bytes));
                        let text = String::from_utf8_lossy(value);
                        assert!(!text.contains(transcript));
                    }
                    ValueRef::Null | ValueRef::Integer(_) | ValueRef::Real(_) => {}
                }
            }
        }
    }
    drop(connection);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn relative_paths_are_rejected_before_persistence() {
    let ledger = JobLedger::open_in_memory().unwrap();
    let mut job = imported_job("relative-path");
    job.source_path = Some("relative.wav".into());
    assert!(matches!(
        ledger.insert_job(&job),
        Err(JobLedgerError::InvalidPath { .. })
    ));
    assert!(ledger.get_job("relative-path").unwrap().is_none());
}

#[test]
fn write_probe_commits_without_mutating_recording_jobs() {
    let ledger = JobLedger::open_in_memory().unwrap();
    let job = imported_job("write-probe-job");
    ledger.insert_job(&job).unwrap();
    let before = ledger.get_job(&job.job_id).unwrap().unwrap();

    ledger.commit_write_probe().unwrap();

    assert_eq!(ledger.get_job(&job.job_id).unwrap().unwrap(), before);
    let connection = ledger.connection.lock().unwrap();
    let generation: i64 = connection
        .query_row(
            "SELECT generation FROM job_ledger_write_probe WHERE singleton = 1",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(generation, 1);
}

#[test]
fn write_probe_rejects_a_read_only_ledger_connection() {
    let dir = temp_dir("read-only-write-probe");
    let path = dir.join("jobs.sqlite3");
    drop(JobLedger::open(&path).unwrap());
    let connection = rusqlite::Connection::open_with_flags(
        &path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .unwrap();
    let ledger = JobLedger {
        connection: std::sync::Mutex::new(connection),
    };

    assert!(ledger.commit_write_probe().is_err());

    drop(ledger);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn invalid_language_decision_rejects_the_entire_batch_before_persistence() {
    let ledger = JobLedger::open_in_memory().unwrap();
    let valid = imported_job("valid-language");
    let mut invalid = imported_job("invalid-language");
    invalid.language_decision.language_bcp47 = Some("EN_us".into());

    assert!(matches!(
        ledger.insert_jobs(&[valid, invalid]),
        Err(JobLedgerError::InvalidRecord(
            "language_decision is inconsistent"
        ))
    ));
    assert!(ledger.list_jobs().unwrap().is_empty());
}

#[test]
fn new_server_batch_job_requires_a_live_catalog_binding() {
    let ledger = JobLedger::open_in_memory().unwrap();
    let mut job = imported_job("missing-catalog-binding");
    job.status = RecordingJobStatus::QueuedServer;
    job.route = Some(RecordingRoute::ServerBatch);

    assert!(matches!(
        ledger.insert_job(&job),
        Err(JobLedgerError::InvalidRecord(
            "new server-batch jobs require a live ASR catalog binding"
        ))
    ));
    assert!(ledger.get_job(&job.job_id).unwrap().is_none());
}

#[test]
fn legacy_unbound_job_is_atomically_bound_when_preprocessing_is_claimed() {
    let ledger = JobLedger::open_in_memory().unwrap();
    let job = server_batch_job("legacy-catalog-claim");
    ledger.insert_job(&job).unwrap();
    {
        let connection = ledger.connection.lock().unwrap();
        connection
            .execute(
                "UPDATE recording_jobs SET asr_catalog_origin = NULL, asr_catalog_revision = NULL WHERE job_id = ?1",
                [&job.job_id],
            )
            .unwrap();
    }
    let replacement =
        crate::jobs::AsrCatalogBinding::try_new("http://127.0.0.1:28765".into(), "b".repeat(64))
            .unwrap();

    let claimed = ledger
        .bind_and_claim_preprocessing(&job.job_id, &replacement, 101)
        .unwrap();

    assert_eq!(claimed.status, RecordingJobStatus::Preprocessing);
    assert_eq!(claimed.asr_catalog_binding, Some(replacement));
    assert_eq!(claimed.attempt_count, 0);
}

#[test]
fn catalog_deferral_preserves_remote_attempt_budget_and_clears_on_due_claim() {
    let ledger = JobLedger::open_in_memory().unwrap();
    let job = server_batch_job("catalog-deferral");
    ledger.insert_job(&job).unwrap();

    let deferred = ledger
        .defer_for_catalog_capability(&job.job_id, 30_100, 100)
        .unwrap();

    assert_eq!(deferred.status, RecordingJobStatus::QueuedServer);
    assert_eq!(deferred.attempt_count, 0);
    assert_eq!(deferred.next_attempt_at_ms, Some(30_100));
    assert_eq!(
        deferred.error_code.as_deref(),
        Some("ASR_CAPABILITY_UNAVAILABLE")
    );
    assert!(ledger
        .bind_and_claim_preprocessing(
            &job.job_id,
            job.asr_catalog_binding.as_ref().unwrap(),
            30_099,
        )
        .is_err());

    let claimed = ledger
        .bind_and_claim_preprocessing(
            &job.job_id,
            job.asr_catalog_binding.as_ref().unwrap(),
            30_100,
        )
        .unwrap();
    assert_eq!(claimed.status, RecordingJobStatus::Preprocessing);
    assert_eq!(claimed.attempt_count, 0);
    assert_eq!(claimed.next_attempt_at_ms, None);
    assert_eq!(claimed.error_code, None);
    assert_eq!(claimed.error_message, None);
}

#[test]
fn catalog_binding_can_change_before_but_not_after_a_remote_attempt() {
    let ledger = JobLedger::open_in_memory().unwrap();
    let job = server_batch_job("catalog-rebind-boundary");
    ledger.insert_job(&job).unwrap();
    let replacement =
        crate::jobs::AsrCatalogBinding::try_new("http://127.0.0.1:28765".into(), "b".repeat(64))
            .unwrap();

    let rebound = ledger
        .rebind_unstarted_server_job(&job.job_id, &replacement, 101)
        .unwrap();
    assert_eq!(rebound.asr_catalog_binding, Some(replacement.clone()));

    {
        let connection = ledger.connection.lock().unwrap();
        connection
            .execute(
                "INSERT INTO prepared_remote_jobs (job_id, create_request_json, capture_manifest_path, capture_manifest_sha256, create_attempt_base_url) VALUES (?1, '{}', ?2, ?3, ?4)",
                rusqlite::params![
                    job.job_id,
                    std::env::temp_dir()
                        .join("catalog-rebind-manifest.json")
                        .to_string_lossy(),
                    "c".repeat(64),
                    replacement.origin(),
                ],
            )
            .unwrap();
    }
    let forbidden =
        crate::jobs::AsrCatalogBinding::try_new("http://127.0.0.1:38765".into(), "d".repeat(64))
            .unwrap();

    assert!(ledger
        .rebind_unstarted_server_job(&job.job_id, &forbidden, 102)
        .is_err());
    assert_eq!(
        ledger
            .get_job(&job.job_id)
            .unwrap()
            .unwrap()
            .asr_catalog_binding,
        Some(replacement)
    );
}

#[test]
fn multi_import_catalog_rebind_rolls_back_when_a_later_existing_job_conflicts() {
    let ledger = JobLedger::open_in_memory().unwrap();
    let first = server_batch_job("catalog-atomic-first");
    let mut conflicting = server_batch_job("catalog-atomic-conflict");
    conflicting.language_decision =
        crate::jobs::RecordingLanguageDecision::manual_override("fr-FR".into()).unwrap();
    ledger.insert_jobs(&[first.clone(), conflicting]).unwrap();
    let replacement =
        crate::jobs::AsrCatalogBinding::try_new("http://127.0.0.1:28765".into(), "b".repeat(64))
            .unwrap();

    let error = ledger
        .commit_catalog_imports(
            &[first.job_id.clone(), "catalog-atomic-conflict".into()],
            &[],
            &first.language_decision,
            &replacement,
            101,
            128,
        )
        .unwrap_err();

    assert!(matches!(error, JobLedgerError::InvalidRecord(_)));
    assert_eq!(
        ledger
            .get_job(&first.job_id)
            .unwrap()
            .unwrap()
            .asr_catalog_binding,
        first.asr_catalog_binding
    );
}

fn imported_job(id: &str) -> NewRecordingJob {
    imported_job_at(id, std::env::temp_dir().join(format!("{id}.wav")))
}

fn imported_job_at(id: &str, source_path: std::path::PathBuf) -> NewRecordingJob {
    NewRecordingJob {
        job_id: id.into(),
        session_mode: SessionMode::Meeting,
        session_origin: SessionOrigin::ImportedFile,
        source_path: Some(source_path),
        source_ownership: SourceOwnership::External,
        output_path: None,
        display_name: format!("{id}.wav"),
        status: RecordingJobStatus::Accepted,
        route: None,
        attempt_count: 0,
        next_attempt_at_ms: None,
        cancellation_requested: false,
        capture_commit_path: None,
        capture_manifest_sha256: None,
        error_code: None,
        error_message: None,
        created_at_ms: 100,
        updated_at_ms: 100,
        expires_at_ms: None,
        language_decision: crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap(),
        language_decision_locked: true,
        client_stage_history_complete: true,
        asr_catalog_binding: None,
    }
}

fn server_batch_job(id: &str) -> NewRecordingJob {
    let mut job = imported_job(id);
    job.status = RecordingJobStatus::QueuedServer;
    job.route = Some(RecordingRoute::ServerBatch);
    job.asr_catalog_binding = Some(crate::jobs::AsrCatalogBinding::for_test());
    job
}

fn chunk_at(artifact_path: std::path::PathBuf) -> NewJobChunk {
    NewJobChunk {
        owner_namespace: "local:test-install".into(),
        session_id: "session-1".into(),
        track_id: "microphone".into(),
        sequence_start: 0,
        sequence_end: 9,
        content_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".into(),
        content_byte_length: 20,
        artifact_path,
        upload_offset: 0,
        acknowledged_object_id: None,
        acknowledged_at_ms: None,
    }
}

fn prepared_remote_job_at(
    capture_manifest_path: std::path::PathBuf,
    chunk_path: std::path::PathBuf,
    capture_manifest_sha256: &str,
) -> NewPreparedRemoteJob {
    let chunk_sha256 = "b".repeat(64);
    let chunk = NewJobChunk {
        owner_namespace: "local:test-install".into(),
        session_id: "session-1".into(),
        track_id: "microphone".into(),
        sequence_start: 0,
        sequence_end: 159,
        content_sha256: chunk_sha256.clone(),
        content_byte_length: 320,
        artifact_path: chunk_path,
        upload_offset: 0,
        acknowledged_object_id: None,
        acknowledged_at_ms: None,
    };
    let request = crate::server_connector::batch::CreateRecordingJobRequest::for_test_single_chunk(
        "interview.wav",
        &chunk.session_id,
        &chunk.track_id,
        capture_manifest_sha256,
        2,
        &chunk_sha256,
        chunk.content_byte_length,
        crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap(),
        &"a".repeat(64),
    );
    NewPreparedRemoteJob {
        create_request_json: serde_json::to_string(&request).unwrap(),
        capture_manifest_path,
        capture_manifest_sha256: capture_manifest_sha256.into(),
        chunks: vec![chunk],
    }
}

fn temp_dir(label: &str) -> std::path::PathBuf {
    let id = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
    let dir = std::env::temp_dir().join(format!("yap-ledger-{label}-{}-{id}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    dir
}
