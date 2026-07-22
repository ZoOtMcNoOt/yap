use super::*;
use crate::jobs::{
    language_preflight::{language_preflight_outcome, LanguagePreflightOutcome},
    AsrCatalogBinding, NewClientPreflightArtifact, NewRecordingJob, RecordingJobStatus,
    RecordingLanguageDecision, RecordingLanguageDisposition, RecordingLanguageMode, SessionMode,
    SessionOrigin, SourceOwnership,
};
use crate::server_connector::batch::{
    NormalizationEvidence, PreprocessingEvidence, SourceVadInterval, VadComponentEvidence,
    VadEvidence,
};

const INPUT_SHA: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
const OUTPUT_SHA: &str = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789";

#[test]
fn stages_are_append_only_and_only_retry_retryable_failures() {
    let ledger = ledger_with_job("stage-retry");
    let first = ledger
        .start_client_stage("stage-retry", &start(ClientStageName::Vad, 10))
        .unwrap();
    assert_eq!(first.attempt, 1);
    assert_eq!(first.state, ClientStageState::Running);
    assert!(ledger
        .start_client_stage("stage-retry", &start(ClientStageName::Vad, 11))
        .is_err());

    let failed = ledger
        .finish_client_stage(
            "stage-retry",
            &ClientStageFinish {
                stage: ClientStageName::Vad,
                attempt: 1,
                state: ClientStageState::Unavailable,
                output_fingerprint_sha256: None,
                completed_at_ms: 12,
                retryable: true,
                reason: Some("ARTIFACT_UNAVAILABLE".into()),
                evidence: Some(serde_json::json!({"status": "unavailable"})),
            },
        )
        .unwrap();
    assert_eq!(failed.retryable, Some(true));
    assert!(failed.evidence_sha256.is_some());

    let second = ledger
        .start_client_stage("stage-retry", &start(ClientStageName::Vad, 13))
        .unwrap();
    assert_eq!(second.attempt, 2);
    ledger
        .finish_client_stage(
            "stage-retry",
            &ClientStageFinish {
                stage: ClientStageName::Vad,
                attempt: 2,
                state: ClientStageState::Succeeded,
                output_fingerprint_sha256: Some(OUTPUT_SHA.into()),
                completed_at_ms: 14,
                retryable: false,
                reason: None,
                evidence: Some(serde_json::json!({"intervalCount": 1})),
            },
        )
        .unwrap();
    assert!(ledger
        .start_client_stage("stage-retry", &start(ClientStageName::Vad, 15))
        .is_err());

    let attempts = ledger.list_client_stage_attempts("stage-retry").unwrap();
    assert_eq!(attempts.len(), 2);
    assert_eq!(attempts[1].state, ClientStageState::Succeeded);
}

#[test]
fn stage_evidence_is_bounded_and_hash_verified_on_read() {
    let ledger = ledger_with_job("stage-evidence");
    ledger
        .start_client_stage("stage-evidence", &start(ClientStageName::Normalization, 20))
        .unwrap();
    let oversized = serde_json::json!({"payload": "x".repeat(MAX_STAGE_HISTORY_EVIDENCE_BYTES)});
    assert!(ledger
        .finish_client_stage(
            "stage-evidence",
            &ClientStageFinish {
                stage: ClientStageName::Normalization,
                attempt: 1,
                state: ClientStageState::Succeeded,
                output_fingerprint_sha256: Some(OUTPUT_SHA.into()),
                completed_at_ms: 21,
                retryable: false,
                reason: None,
                evidence: Some(oversized),
            },
        )
        .is_err());

    ledger
        .finish_client_stage(
            "stage-evidence",
            &ClientStageFinish {
                stage: ClientStageName::Normalization,
                attempt: 1,
                state: ClientStageState::Succeeded,
                output_fingerprint_sha256: Some(OUTPUT_SHA.into()),
                completed_at_ms: 22,
                retryable: false,
                reason: None,
                evidence: Some(serde_json::json!({"method": "identity"})),
            },
        )
        .unwrap();
    ledger
        .connection
        .lock()
        .unwrap()
        .execute(
            "UPDATE job_stage_attempts SET evidence_sha256 = ?1 WHERE job_id = 'stage-evidence'",
            ["0".repeat(64)],
        )
        .unwrap();
    assert!(matches!(
        ledger.list_client_stage_attempts("stage-evidence"),
        Err(JobLedgerError::CorruptValue {
            field: "client_stage_evidence",
            ..
        })
    ));
}

#[test]
fn stage_history_is_deleted_with_its_job() {
    let ledger = ledger_with_job("stage-cascade");
    ledger
        .start_client_stage("stage-cascade", &start(ClientStageName::LidPreflight, 30))
        .unwrap();
    ledger
        .connection
        .lock()
        .unwrap()
        .execute(
            "DELETE FROM recording_jobs WHERE job_id = 'stage-cascade'",
            [],
        )
        .unwrap();
    let count: i64 = ledger
        .connection
        .lock()
        .unwrap()
        .query_row("SELECT COUNT(*) FROM job_stage_attempts", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(count, 0);
}

#[test]
fn language_confirmation_updates_the_decision_and_stage_atomically() {
    let ledger = ledger_with_job_state("language-confirmation", false);
    let decision = RecordingLanguageDecision::try_new(
        RecordingLanguageMode::Fixed,
        Some("fr-FR".into()),
        RecordingLanguageDisposition::DetectedSuggestionConfirmed,
    )
    .unwrap();

    let confirmed = ledger
        .confirm_language_decision(
            "language-confirmation",
            &decision,
            INPUT_SHA,
            40,
            Some(serde_json::json!({"action": "accepted_suggestion"})),
            None,
        )
        .unwrap();

    assert_eq!(confirmed.language_decision, decision);
    assert!(confirmed.language_decision_locked);
    let stages = ledger
        .list_client_stage_attempts("language-confirmation")
        .unwrap();
    assert_eq!(stages.len(), 1);
    assert_eq!(stages[0].stage, ClientStageName::UserConfirmation);
    assert_eq!(stages[0].state, ClientStageState::Succeeded);
    assert!(ledger
        .confirm_language_decision(
            "language-confirmation",
            &RecordingLanguageDecision::primary("de-DE".into()).unwrap(),
            INPUT_SHA,
            41,
            None,
            None,
        )
        .is_err());
    assert_eq!(
        ledger
            .list_client_stage_attempts("language-confirmation")
            .unwrap()
            .len(),
        1
    );
}

#[test]
fn preflight_confirmation_uses_the_latest_nonretryable_lid_attempt() {
    let ledger = ledger_with_client_preflight("latest-lid-attempt", 1_000);
    let attempt = ledger
        .begin_lid_preflight_dispatch(
            "latest-lid-attempt",
            "lid-request-1",
            "http://127.0.0.1:18765",
            &"a".repeat(64),
            "speechbrain-policy-v1",
            30,
        )
        .unwrap();
    ledger
        .fail_lid_preflight_dispatch(super::super::LidPreflightDispatchFailure {
            job_id: "latest-lid-attempt",
            request_id: "lid-request-1",
            attempt,
            reason: "transport_failed",
            retryable: true,
            retry_at_ms: Some(50),
            completed_at_ms: 40,
        })
        .unwrap();

    let retryable = ledger
        .list_client_stage_attempts("latest-lid-attempt")
        .unwrap()
        .into_iter()
        .find(|stage| stage.stage == ClientStageName::LidPreflight)
        .unwrap();
    assert_eq!(retryable.reason.as_deref(), Some("TRANSPORT_FAILED"));
    assert_eq!(retryable.retryable, Some(true));
    assert!(matches!(
        language_preflight_outcome(&ledger, "latest-lid-attempt").unwrap(),
        LanguagePreflightOutcome::RetryableFailure { attempt: 1, .. }
    ));
    assert!(ledger
        .confirm_language_decision(
            "latest-lid-attempt",
            &RecordingLanguageDecision::primary("en-US".into()).unwrap(),
            INPUT_SHA,
            41,
            None,
            Some(&AsrCatalogBinding::for_test()),
        )
        .is_err());

    ledger
        .record_manual_lid_preflight(
            "latest-lid-attempt",
            "server_preflight_unavailable",
            &"a".repeat(64),
            "server-preflight-unavailable-v1",
            51,
        )
        .unwrap();
    let outcome = language_preflight_outcome(&ledger, "latest-lid-attempt").unwrap();
    let LanguagePreflightOutcome::Review { review, .. } = outcome else {
        panic!("manual terminal attempt must require review");
    };
    assert_eq!(review.reason, "server_preflight_unavailable");

    let confirmed = ledger
        .confirm_language_decision(
            "latest-lid-attempt",
            &RecordingLanguageDecision::primary("en-US".into()).unwrap(),
            INPUT_SHA,
            52,
            Some(serde_json::json!({"action": "confirmed_manual_selection"})),
            Some(&AsrCatalogBinding::for_test()),
        )
        .unwrap();
    assert!(confirmed.language_decision_locked);
    assert!(confirmed.client_stage_history_complete);
}

#[test]
fn terminal_lid_dispatch_is_reconciled_before_retry_or_pruning() {
    let ledger = ledger_with_client_preflight("terminal-lid", 60);
    ledger
        .begin_lid_preflight_dispatch(
            "terminal-lid",
            "lid-request-terminal",
            "http://127.0.0.1:18765",
            &"a".repeat(64),
            "speechbrain-policy-v1",
            30,
        )
        .unwrap();

    assert_eq!(ledger.expire_pending_jobs(61).unwrap(), 1);
    let expired = ledger.get_job("terminal-lid").unwrap().unwrap();
    assert_eq!(expired.status, RecordingJobStatus::Cancelled);
    assert!(expired.cancellation_requested);
    assert!(ledger.has_remote_reconciliation_work().unwrap());
    let pending = ledger
        .next_terminal_lid_preflight_dispatch()
        .unwrap()
        .expect("terminal LID identity remains durable");
    assert_eq!(
        pending.lid_request_id.as_deref(),
        Some("lid-request-terminal")
    );

    ledger
        .acknowledge_terminal_lid_preflight_dispatch("terminal-lid", "lid-request-terminal", 20)
        .unwrap();
    let artifact = ledger
        .get_client_preflight_artifact("terminal-lid")
        .unwrap()
        .unwrap();
    assert!(artifact.lid_request_id.is_none());
    assert!(!ledger.has_remote_reconciliation_work().unwrap());
    let lid = ledger
        .list_client_stage_attempts("terminal-lid")
        .unwrap()
        .into_iter()
        .find(|stage| stage.stage == ClientStageName::LidPreflight)
        .unwrap();
    assert_eq!(lid.state, ClientStageState::Cancelled);
    assert_eq!(lid.reason.as_deref(), Some("CANCELLED"));
    assert_eq!(lid.completed_at_ms, Some(30));
}

fn start(stage: ClientStageName, started_at_ms: u64) -> ClientStageStart {
    ClientStageStart {
        stage,
        input_fingerprint_sha256: INPUT_SHA.into(),
        component_id: "test-component".into(),
        component_revision: "test-v1".into(),
        started_at_ms,
    }
}

fn ledger_with_job(job_id: &str) -> JobLedger {
    ledger_with_job_state(job_id, true)
}

fn ledger_with_job_state(job_id: &str, language_decision_locked: bool) -> JobLedger {
    let ledger = JobLedger::open_in_memory().unwrap();
    ledger
        .insert_job(&NewRecordingJob {
            job_id: job_id.into(),
            session_mode: SessionMode::Meeting,
            session_origin: SessionOrigin::ImportedFile,
            source_path: Some(std::env::temp_dir().join(format!("{job_id}.wav"))),
            source_ownership: SourceOwnership::External,
            output_path: None,
            display_name: format!("{job_id}.wav"),
            status: RecordingJobStatus::Accepted,
            route: None,
            attempt_count: 0,
            next_attempt_at_ms: None,
            cancellation_requested: false,
            capture_commit_path: None,
            capture_manifest_sha256: None,
            error_code: None,
            error_message: None,
            created_at_ms: 1,
            updated_at_ms: 1,
            expires_at_ms: None,
            language_decision: RecordingLanguageDecision::primary("en-US".into()).unwrap(),
            language_decision_locked,
            client_stage_history_complete: language_decision_locked,
            asr_catalog_binding: None,
        })
        .unwrap();
    ledger
}

fn ledger_with_client_preflight(job_id: &str, expires_at_ms: u64) -> JobLedger {
    let ledger = ledger_with_job_state(job_id, false);
    ledger
        .accept_to_preflighting(job_id, 10, expires_at_ms)
        .unwrap();
    let normalization = NormalizationEvidence::canonical_pcm16_identity(
        "b".repeat(64),
        INPUT_SHA.into(),
        INPUT_SHA.into(),
        320_000,
        320_000,
        0,
    );
    let vad = VadEvidence::complete(
        VadComponentEvidence::for_test("test-vad", "test-v1"),
        320_000,
        vec![SourceVadInterval::for_test(0, 320_000)],
    );
    ledger
        .attach_client_preflight_artifact(
            job_id,
            &NewClientPreflightArtifact {
                manifest_path: std::env::temp_dir().join(format!("{job_id}-client-preflight.json")),
                manifest_sha256: OUTPUT_SHA.into(),
                source_pcm_sha256: INPUT_SHA.into(),
                source_sample_count: 320_000,
            },
            &PreprocessingEvidence::new(normalization, vad),
            20,
        )
        .unwrap();
    ledger
}
