use super::*;

#[test]
fn projection_failure_after_a_durable_import_commit_still_notifies() {
    let notified = Cell::new(false);

    let result = notify_after_durable_import_commit(
        Ok::<_, JobCommandError>(()),
        |_| Err::<(), _>(command_error("INJECTED_FAILURE", "injected")),
        || notified.set(true),
    );

    assert_eq!(result.unwrap_err().code, "INJECTED_FAILURE");
    assert!(notified.get());
}

#[test]
fn failure_before_a_durable_import_commit_does_not_notify() {
    let notified = Cell::new(false);

    let result = notify_after_durable_import_commit(
        Err::<(), _>(command_error("INJECTED_FAILURE", "injected")),
        |_| Ok(()),
        || notified.set(true),
    );

    assert_eq!(result.unwrap_err().code, "INJECTED_FAILURE");
    assert!(!notified.get());
}

#[test]
fn mutation_adapter_notifies_even_when_the_operation_returns_an_error() {
    let notified = Cell::new(false);

    let result = mutate_then_notify(
        || Err::<(), _>(command_error("INJECTED_FAILURE", "injected")),
        || notified.set(true),
    );

    assert_eq!(result.unwrap_err().code, "INJECTED_FAILURE");
    assert!(notified.get());
}

#[test]
fn durable_import_retains_picker_proof_but_stays_non_runnable_until_projection() {
    let dir = temp_dir("accepted-before-source-authority");
    let source = dir.join("meeting.wav");
    fs::write(&source, b"RIFF-command-fixture").unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open_in_memory().unwrap(), &dir);
    let media = MediaOwner::new();
    let decision = crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap();
    let binding = crate::jobs::AsrCatalogBinding::for_test();

    let prepared = jobs.prepare_imports(vec![source.clone()]).unwrap();
    let committed = jobs
        .commit_prepared_imports(prepared, 1_000, decision, &binding)
        .unwrap();
    let staged = jobs.ledger().list_recoverable_jobs().unwrap();
    assert_eq!(staged.len(), 1);
    assert_eq!(staged[0].status, RecordingJobStatus::Accepted);
    assert!(
        jobs.selection_registry_path.is_file(),
        "durable staging must retain native picker proof before the Accepted row exists"
    );
    assert!(
        !jobs.registry_path.exists(),
        "active playback authority must wait for projection"
    );
    assert_eq!(media.active_admission_count_for_test(), 0);

    let projected = jobs
        .project_committed_imports(&media, committed, 1_001)
        .unwrap();
    assert_eq!(projected[0].status, RecordingJobStatus::Preflighting);
    assert!(projected[0].playback_path.is_some());
    assert!(jobs.selection_registry_path.is_file());

    drop(media);
    drop(jobs);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn snapshot_recovers_an_interrupted_import_only_from_retained_picker_proof() {
    let dir = temp_dir("recover-accepted-source-authority");
    let source = dir.join("meeting.wav");
    fs::write(&source, b"RIFF-command-fixture").unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open_in_memory().unwrap(), &dir);
    let media = MediaOwner::new();
    let decision = crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap();
    let binding = crate::jobs::AsrCatalogBinding::for_test();

    let prepared = jobs.prepare_imports(vec![source]).unwrap();
    let _interrupted = jobs
        .commit_prepared_imports(prepared, 1_000, decision, &binding)
        .unwrap();
    assert_eq!(
        jobs.ledger().list_recoverable_jobs().unwrap()[0].status,
        RecordingJobStatus::Accepted
    );
    assert!(jobs.selection_registry_path.is_file());

    let recovered = jobs.snapshot(&media, 1_001).unwrap();
    assert_eq!(recovered[0].status, RecordingJobStatus::Preflighting);
    assert!(recovered[0].playback_path.is_some());
    assert_eq!(
        jobs.ledger().list_recoverable_jobs().unwrap()[0].status,
        RecordingJobStatus::Preflighting
    );

    drop(media);
    drop(jobs);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn snapshot_never_reconstructs_picker_authority_from_an_accepted_ledger_path() {
    let dir = temp_dir("accepted-without-picker-proof");
    let source = dir.join("meeting.wav");
    fs::write(&source, b"RIFF-command-fixture").unwrap();
    let canonical_source = source.canonicalize().unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open_in_memory().unwrap(), &dir);
    let media = MediaOwner::new();
    jobs.ledger()
        .insert_job(&NewRecordingJob {
            job_id: "job-no-picker-proof".into(),
            session_mode: SessionMode::Meeting,
            session_origin: SessionOrigin::ImportedFile,
            source_path: Some(canonical_source.clone()),
            source_ownership: SourceOwnership::External,
            output_path: None,
            display_name: "meeting.wav".into(),
            status: RecordingJobStatus::Accepted,
            route: Some(RecordingRoute::ServerBatch),
            attempt_count: 0,
            next_attempt_at_ms: None,
            cancellation_requested: false,
            capture_commit_path: None,
            capture_manifest_sha256: None,
            error_code: None,
            error_message: None,
            created_at_ms: 1_000,
            updated_at_ms: 1_000,
            expires_at_ms: Some(1_000 + PENDING_JOB_LIFETIME_MS),
            language_decision: crate::jobs::RecordingLanguageDecision::primary("en-US".into())
                .unwrap(),
            language_decision_locked: true,
            client_stage_history_complete: true,
            asr_catalog_binding: Some(crate::jobs::AsrCatalogBinding::for_test()),
        })
        .unwrap();

    let snapshot = jobs.snapshot(&media, 1_001).unwrap();

    assert_eq!(snapshot[0].status, RecordingJobStatus::Failed);
    assert_eq!(snapshot[0].error.as_deref(), Some("SOURCE_UNSAFE"));
    assert_eq!(snapshot[0].source_path, None);
    assert_eq!(snapshot[0].playback_path, None);
    assert_eq!(media.active_admission_count_for_test(), 0);
    assert!(
        crate::recording_access::read_registered_playback_paths(&jobs.selection_registry_path)
            .unwrap()
            .is_empty()
    );
    assert!(open_and_reveal_are_denied(
        &jobs,
        &canonical_source,
        &dir.join("recording-playback-registry.json"),
    ));

    drop(media);
    drop(jobs);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn cancellation_between_import_commit_and_projection_cannot_restore_authority() {
    let dir = temp_dir("cancel-before-source-projection");
    let source = dir.join("meeting.wav");
    fs::write(&source, b"RIFF-command-fixture").unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open_in_memory().unwrap(), &dir);
    let media = MediaOwner::new();
    let decision = crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap();
    let binding = crate::jobs::AsrCatalogBinding::for_test();

    let prepared = jobs.prepare_imports(vec![source.clone()]).unwrap();
    let committed = jobs
        .commit_prepared_imports(prepared, 1_000, decision, &binding)
        .unwrap();
    let job_id = jobs.ledger().list_recoverable_jobs().unwrap()[0]
        .job_id
        .clone();
    jobs.cancel(&media, &job_id, 1_001, || {}).unwrap();

    let projected = jobs
        .project_committed_imports(&media, committed, 1_002)
        .unwrap();
    assert_eq!(projected[0].status, RecordingJobStatus::Cancelled);
    assert_eq!(projected[0].playback_path, None);
    assert!(open_and_reveal_are_denied(
        &jobs,
        &source,
        &dir.join("general-playback-registry.json")
    ));

    drop(media);
    drop(jobs);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn completed_remote_catalog_revalidates_the_immutable_result_before_history_projection() {
    let dir = temp_dir("completed-remote-catalog");
    let database = dir.join("jobs.sqlite3");
    let source_path = dir.join("meeting.wav");
    let remote_jobs = dir.join("remote-jobs");
    write_pcm_wav(&source_path, &vec![0_u8; 320]);
    let mut source = fs::File::open(&source_path).unwrap();
    let owner = crate::audio::session::OwnerNamespace::local("i-catalog-test").unwrap();
    let prepared = remote::prepare_imported_pcm_wav(
        "job-completed-catalog",
        "meeting.wav",
        &mut source,
        &remote_jobs,
        &owner,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
        &crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap(),
    )
    .unwrap();
    let request = prepared.request.clone();
    let durable = prepared.into_ledger_state().unwrap();
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&NewRecordingJob {
            job_id: "job-completed-catalog".into(),
            session_mode: SessionMode::Meeting,
            session_origin: SessionOrigin::ImportedFile,
            source_path: Some(source_path.clone()),
            source_ownership: SourceOwnership::External,
            output_path: None,
            display_name: "meeting.wav".into(),
            status: RecordingJobStatus::Preprocessing,
            route: Some(RecordingRoute::ServerBatch),
            attempt_count: 0,
            next_attempt_at_ms: None,
            cancellation_requested: false,
            capture_commit_path: None,
            capture_manifest_sha256: None,
            error_code: None,
            error_message: None,
            created_at_ms: 1_720_000_000_000,
            updated_at_ms: 1_720_000_000_000,
            expires_at_ms: Some(1_720_604_800_000),
            language_decision: crate::jobs::RecordingLanguageDecision::primary("en-US".into())
                .unwrap(),
            language_decision_locked: true,
            client_stage_history_complete: true,
            asr_catalog_binding: Some(crate::jobs::AsrCatalogBinding::for_test()),
        })
        .unwrap();
    ledger
        .attach_prepared_remote_job("job-completed-catalog", &durable, 1_720_000_000_100)
        .unwrap();
    let server_job_id = "job-0123456789abcdef0123456789abcdef";
    ledger
        .begin_remote_create_attempt(
            "job-completed-catalog",
            "http://127.0.0.1:18765",
            1_720_000_000_200,
        )
        .unwrap();
    ledger
        .record_server_job_id(
            "job-completed-catalog",
            server_job_id,
            "http://127.0.0.1:18765",
            1_720_000_000_200,
        )
        .unwrap();
    for chunk in &request.chunks {
        ledger
            .acknowledge_remote_chunk(
                "job-completed-catalog",
                &chunk.replay_key.track_id,
                chunk.replay_key.sequence_start,
                chunk.replay_key.sequence_end,
                &chunk.content_identity.sha256,
                1_720_000_000_300,
            )
            .unwrap();
    }
    ledger
        .mark_remote_job_committed("job-completed-catalog", 1_720_000_000_400)
        .unwrap();
    ledger
        .begin_remote_result_saving("job-completed-catalog", 1_720_000_000_500)
        .unwrap();
    let runtime_lock_sha256 = "d".repeat(64);
    let mut result = crate::server_connector::batch::TranscriptResultRevision {
        session_id: request.metadata.session_id.to_string(),
        revision: 1,
        authority: "server_authoritative".into(),
        created_at_utc: "2026-07-14T21:00:02Z".into(),
        capture_manifest_sha256: request.capture_manifest.sha256.clone(),
        previous_result_sha256: None,
        status: "complete".into(),
        language: Some(crate::server_connector::batch::LanguageDecision {
            language_bcp47: "en-US".into(),
            confidence: Some(0.98),
        }),
        transcript: "Catalog result.".into(),
        speaker_result_sha256: None,
        language_segments: None,
        language_span_evidence: None,
        alignment: Some(
            serde_json::from_value(serde_json::json!({
                "status": "unavailable",
                "reason": "ALIGNMENT_PROVIDER_UNSUPPORTED",
                "componentRevision": "joint-segment-timing-v1"
            }))
            .unwrap(),
        ),
        aligned_words: Vec::new(),
        model_provenance: vec![crate::server_connector::batch::ModelRevision {
            model_id: "Trelis/tiron".into(),
            revision: "90bc0a4d198cd5cf6679b0e478375ba3a0040575".into(),
            calibration_revision: runtime_lock_sha256.clone(),
        }],
    };
    let speaker_result: crate::server_connector::batch::SpeakerResultRevision =
        serde_json::from_value(serde_json::json!({
            "sessionId": request.metadata.session_id.as_str(),
            "revision": 1,
            "authority": "server_authoritative",
            "createdAtUtc": "2026-07-14T21:00:02Z",
            "captureManifestSha256": request.capture_manifest.sha256,
            "previousResultSha256": null,
            "status": "complete",
            "language": {"languageBcp47": "en-US", "confidence": 0.98},
            "runtimeLockSha256": runtime_lock_sha256,
            "speakerTurns": [{
                "turnId": "turn-000001",
                "startMs": 0,
                "endMs": 10,
                "text": "Catalog result.",
                "attribution": {
                    "kind": "session_speaker",
                    "sessionSpeakerId": "speaker-1"
                },
                "confidence": null,
                "supportingTrackIds": [request.tracks[0].track_id],
                "overlapGroupId": null
            }],
            "speakerCapacityDegradation": null,
            "alignment": {
                "status": "unavailable",
                "reason": "ALIGNMENT_PROVIDER_UNSUPPORTED",
                "componentRevision": "joint-segment-timing-v1"
            },
            "alignedWords": [],
            "modelProvenance": [
                {
                    "modelId": "Trelis/tiron",
                    "revision": "90bc0a4d198cd5cf6679b0e478375ba3a0040575",
                    "calibrationRevision": runtime_lock_sha256
                },
                {
                    "modelId": "TrelisResearch/tiron",
                    "revision": "d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c",
                    "calibrationRevision": runtime_lock_sha256
                },
                {
                    "modelId": "speechbrain/spkrec-ecapa-voxceleb",
                    "revision": "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
                    "calibrationRevision": runtime_lock_sha256
                }
            ]
        }))
        .unwrap();
    result.speaker_result_sha256 = speaker_result.content_sha256();
    let output = remote::publish_remote_result(
        "job-completed-catalog",
        &remote_jobs,
        &result,
        Some(&speaker_result),
    )
    .unwrap();
    ledger
        .finalize_remote_result(
            "job-completed-catalog",
            &output,
            1_722_592_000_000,
            1_720_000_000_600,
            RecordingJobStatus::Complete,
        )
        .unwrap();
    let jobs = RecordingJobs::from_ledger(ledger, &dir);

    let catalog = jobs.completed_remote_transcripts().unwrap();
    assert_eq!(catalog.sessions.len(), 1);
    assert_eq!(
        catalog.sessions[0].output_path,
        output.display().to_string()
    );
    assert_eq!(
        catalog.sessions[0].result_summary,
        super::super::TranscriptResultSummary {
            language_bcp47: "en-US".into(),
            language_status: super::super::TranscriptLanguageStatus::Fixed,
            timing_status: super::super::TranscriptTimingStatus::Unavailable,
            active_language_correction_count: None,
            language_review_required_count: None,
        }
    );
    assert!(catalog.maintenance_warnings.is_empty());
    let speaker_turns = catalog.sessions[0].speaker_turns.as_ref().unwrap();
    assert_eq!(speaker_turns.len(), 1);
    assert_eq!(speaker_turns[0].speaker_id, "speaker-1");
    assert_eq!(speaker_turns[0].text, "Catalog result.");

    let status_corruption = rusqlite::Connection::open(&database).unwrap();
    status_corruption
        .execute(
            "UPDATE recording_jobs SET status = 'partial' WHERE job_id = 'job-completed-catalog'",
            [],
        )
        .unwrap();
    drop(status_corruption);
    let mismatched_status = jobs.completed_remote_transcripts().unwrap();
    assert!(mismatched_status.sessions.is_empty());
    assert_eq!(mismatched_status.maintenance_warnings.len(), 1);
    let restored_status = rusqlite::Connection::open(&database).unwrap();
    restored_status
        .execute(
            "UPDATE recording_jobs SET status = 'complete' WHERE job_id = 'job-completed-catalog'",
            [],
        )
        .unwrap();
    drop(restored_status);

    let result_directory = output.parent().unwrap();
    let canonical_speaker_bytes = serde_json::to_vec(&speaker_result).unwrap();
    let mut changed_speaker_bytes = canonical_speaker_bytes.clone();
    changed_speaker_bytes.push(b'\n');
    fs::write(
        result_directory.join("speaker-result.json"),
        &changed_speaker_bytes,
    )
    .unwrap();
    assert!(remote::read_published_remote_transcript(&output, &remote_jobs).is_err());
    fs::write(
        result_directory.join("speaker-result.json"),
        &canonical_speaker_bytes,
    )
    .unwrap();

    let mut forged_speaker_value = serde_json::to_value(&speaker_result).unwrap();
    forged_speaker_value["speakerTurns"][0]["supportingTrackIds"] =
        serde_json::json!(["other-track"]);
    let forged_speaker: crate::server_connector::batch::SpeakerResultRevision =
        serde_json::from_value(forged_speaker_value).unwrap();
    let mut forged_result = result.clone();
    forged_result.speaker_result_sha256 = forged_speaker.content_sha256();
    fs::write(
        result_directory.join("result.json"),
        serde_json::to_vec(&forged_result).unwrap(),
    )
    .unwrap();
    fs::write(
        result_directory.join("speaker-result.json"),
        serde_json::to_vec(&forged_speaker).unwrap(),
    )
    .unwrap();
    let request_mismatch = jobs.completed_remote_transcripts().unwrap();
    assert!(request_mismatch.sessions.is_empty());
    assert_eq!(request_mismatch.maintenance_warnings.len(), 1);

    fs::write(
        result_directory.join("result.json"),
        serde_json::to_vec(&result).unwrap(),
    )
    .unwrap();
    fs::write(
        result_directory.join("speaker-result.json"),
        serde_json::to_vec(&speaker_result).unwrap(),
    )
    .unwrap();

    fs::write(&output, "tampered\n").unwrap();
    let rejected = jobs.completed_remote_transcripts().unwrap();
    assert!(rejected.sessions.is_empty());
    assert_eq!(rejected.maintenance_warnings.len(), 1);

    assert!(jobs
        .snapshot(&MediaOwner::new(), 1_722_592_000_000)
        .unwrap()
        .is_empty());
    assert!(!remote_jobs.join("job-completed-catalog").exists());
    assert!(
        source_path.is_file(),
        "external source must never be deleted"
    );

    drop(jobs);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn create_imports_validates_and_native_allowlists_a_canonical_recording() {
    let dir = temp_dir("create-import");
    let source = dir.join("meeting.wav");
    fs::write(&source, b"RIFF-command-fixture").unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open_in_memory().unwrap(), &dir);
    let media = MediaOwner::new();

    let created = jobs
        .create_imports(&media, vec![source.display().to_string()], 1_000)
        .unwrap();

    assert_eq!(created.len(), 1);
    assert_eq!(
        created[0].source_path.as_deref(),
        source.canonicalize().unwrap().to_str()
    );
    assert!(created[0]
        .playback_path
        .as_deref()
        .is_some_and(|path| path.starts_with("http://127.0.0.1:")));
    assert_eq!(created[0].id, jobs.snapshot(&media, 1_001).unwrap()[0].id);
    assert!(fs::read_to_string(&jobs.registry_path)
        .unwrap()
        .contains("meeting.wav"));
    assert!(!dir.join("recording-playback-registry.json").exists());

    drop(media);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn per_job_language_override_is_frozen_when_a_source_is_admitted() {
    let dir = temp_dir("create-import-language");
    let source = dir.join("meeting.wav");
    fs::write(&source, b"RIFF-command-fixture").unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open_in_memory().unwrap(), &dir);
    let media = MediaOwner::new();
    let manual = crate::jobs::RecordingLanguageDecision::manual_override("fr-FR".into()).unwrap();

    let created = jobs
        .create_imports_with_language(
            &media,
            vec![source.display().to_string()],
            1_000,
            manual.clone(),
        )
        .unwrap();
    assert_eq!(created[0].language_decision, manual);

    let replayed = jobs
        .create_imports_with_language(
            &media,
            vec![source.display().to_string()],
            1_001,
            manual.clone(),
        )
        .unwrap();
    assert_eq!(replayed[0].id, created[0].id);
    assert_eq!(replayed[0].language_decision, manual);
    assert_eq!(
        jobs.snapshot(&media, 1_002).unwrap()[0].language_decision,
        manual
    );

    let conflict = jobs
        .create_imports_with_language(
            &media,
            vec![source.display().to_string()],
            1_003,
            crate::jobs::RecordingLanguageDecision::primary("en-US".into()).unwrap(),
        )
        .unwrap_err();
    assert_eq!(conflict.code, "LANGUAGE_DECISION_CONFLICT");
    assert_eq!(jobs.snapshot(&media, 1_004).unwrap().len(), 1);

    drop(media);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn create_imports_rejects_media_outside_the_admitted_container_set() {
    let dir = temp_dir("create-unsupported-remote-media");
    // MP3 is admitted now and decoded during preparation, so the rejection case
    // has to be a container this build cannot decode at all. A malformed file
    // with an admitted extension is refused later, by the decoder.
    let source = dir.join("meeting.m4a");
    fs::write(&source, b"not admitted before remote preparation").unwrap();
    let jobs = RecordingJobs::from_ledger(JobLedger::open_in_memory().unwrap(), &dir);
    let media = MediaOwner::new();

    let error = jobs
        .create_imports(&media, vec![source.display().to_string()], 1_000)
        .unwrap_err();

    assert_eq!(error.code, "REMOTE_MEDIA_UNSUPPORTED");
    assert!(error.message.contains("WAV and MP3"));
    assert!(jobs.snapshot(&media, 1_001).unwrap().is_empty());

    drop(media);
    fs::remove_dir_all(dir).unwrap();
}
