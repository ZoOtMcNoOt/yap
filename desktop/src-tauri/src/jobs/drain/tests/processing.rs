use super::*;
use sha2::{Digest, Sha256};

#[test]
fn exact_processing_target_does_not_fall_through_to_a_neighbor_after_cancellation() {
    let root = temp_dir("exact-processing-target");
    let remote_jobs = root.join("remote-jobs");
    let source_a = root.join("source-a.wav");
    let source_b = root.join("source-b.wav");
    write_pcm_wav(&source_a, &[0_u8; 320]);
    write_pcm_wav(&source_b, &[0_u8; 320]);
    let ledger = JobLedger::open_in_memory().unwrap();
    let mut job_a = queued_job("job-exact-processing-a", source_a);
    job_a.status = RecordingJobStatus::ServerProcessing;
    let mut job_b = queued_job("job-exact-processing-b", source_b);
    job_b.status = RecordingJobStatus::ServerProcessing;
    ledger.insert_jobs(&[job_a, job_b]).unwrap();
    ledger
        .request_cancellation("job-exact-processing-a", 1_720_000_000_100)
        .unwrap();
    let client = BatchApiClient::new(
        reqwest::Client::builder().build().unwrap(),
        "http://127.0.0.1:9",
    )
    .unwrap();

    tauri::async_runtime::block_on(async {
        assert!(!advance_processing_job_once_guarded_for_test(
            &ledger,
            &remote_jobs,
            &client,
            "job-exact-processing-a",
            1_720_000_000_200,
            &BatchCommitGuard::Unchecked,
        )
        .await
        .unwrap());
    });

    let cancelled = ledger.get_job("job-exact-processing-a").unwrap().unwrap();
    assert_eq!(cancelled.status, RecordingJobStatus::Cancelled);
    let neighbor = ledger.get_job("job-exact-processing-b").unwrap().unwrap();
    assert_eq!(neighbor.status, RecordingJobStatus::ServerProcessing);
    assert_eq!(neighbor.attempt_count, 0);
    assert_eq!(neighbor.error_code, None);

    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn cancelling_a_recovered_saving_job_removes_its_uncommitted_result() {
    let root = temp_dir("cancel-recovered-saving-result");
    let remote_jobs = root.join("remote-jobs");
    let ledger = JobLedger::open_in_memory().unwrap();
    let request = commit_remote_job_for_result_tests(
        &ledger,
        &root,
        &remote_jobs,
        "job-cancel-recovered-saving",
    );
    let result = complete_result_for(&request);

    ledger
        .begin_remote_result_saving("job-cancel-recovered-saving", 1_720_000_000_500)
        .unwrap();
    let output = crate::jobs::remote::publish_remote_result(
        "job-cancel-recovered-saving",
        &remote_jobs,
        &result,
        None,
    )
    .unwrap();
    assert!(output.is_file());

    let cancelled = ledger
        .request_cancellation("job-cancel-recovered-saving", 1_720_000_000_600)
        .unwrap();
    assert_eq!(cancelled.status, RecordingJobStatus::Cancelled);
    crate::jobs::remote::reset_unattached_spool("job-cancel-recovered-saving", &remote_jobs)
        .unwrap();

    assert!(!remote_jobs.join("job-cancel-recovered-saving").exists());
    assert!(ledger
        .finalize_remote_result(
            "job-cancel-recovered-saving",
            &output,
            1_722_592_000_000,
            1_720_000_000_700,
            RecordingJobStatus::Complete,
        )
        .is_err());
    assert_eq!(
        ledger
            .get_job("job-cancel-recovered-saving")
            .unwrap()
            .unwrap()
            .status,
        RecordingJobStatus::Cancelled
    );

    drop(ledger);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn offline_restart_finalizes_a_published_saving_result_despite_other_pending_work() {
    let root = temp_dir("restart-published-saving-result");
    let database = root.join("jobs.sqlite3");
    let remote_jobs = root.join("remote-jobs");
    let ledger = JobLedger::open(&database).unwrap();
    commit_remote_job_for_result_tests(&ledger, &root, &remote_jobs, "job-a-unpublished-saving");
    ledger
        .begin_remote_result_saving("job-a-unpublished-saving", 1_720_000_000_450)
        .unwrap();
    let request = commit_remote_job_for_result_tests(
        &ledger,
        &root,
        &remote_jobs,
        "job-restart-published-saving",
    );
    let result = complete_result_for(&request);

    ledger
        .begin_remote_result_saving("job-restart-published-saving", 1_720_000_000_500)
        .unwrap();
    let first_output = crate::jobs::remote::publish_remote_result(
        "job-restart-published-saving",
        &remote_jobs,
        &result,
        None,
    )
    .unwrap();
    commit_remote_job_for_result_tests(
        &ledger,
        &root,
        &remote_jobs,
        "job-unreachable-persisted-cancellation",
    );
    let cancellation = ledger
        .request_cancellation("job-unreachable-persisted-cancellation", 1_720_000_000_550)
        .unwrap();
    assert_eq!(cancellation.status, RecordingJobStatus::Cancelled);
    drop(ledger);

    let reopened = JobLedger::open(&database).unwrap();
    let saving = reopened
        .get_job("job-restart-published-saving")
        .unwrap()
        .unwrap();
    assert_eq!(saving.status, RecordingJobStatus::Saving);
    assert_eq!(saving.output_path, None);

    let publication_gate = Mutex::new(());
    assert!(matches!(
        finalize_next_locally_published_saving_result(
            &reopened,
            &remote_jobs,
            &publication_gate,
            1_720_000_000_600,
        )
        .unwrap(),
        LocalSavingRecovery::Finalized
    ));
    let pending_cancellation = reopened
        .get_prepared_remote_job("job-unreachable-persisted-cancellation")
        .unwrap()
        .unwrap();
    assert_eq!(
        pending_cancellation.server_cancellation_acknowledged_at_ms,
        None
    );
    assert_eq!(
        reopened
            .get_job("job-a-unpublished-saving")
            .unwrap()
            .unwrap()
            .status,
        RecordingJobStatus::Saving
    );
    let result_directories = fs::read_dir(remote_jobs.join("job-restart-published-saving"))
        .unwrap()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_ok_and(|kind| kind.is_dir())
                && entry
                    .file_name()
                    .to_str()
                    .is_some_and(|name| name.starts_with("result-"))
        })
        .count();
    assert_eq!(result_directories, 1);

    let complete = reopened.get_job("job-restart-published-saving").unwrap();
    let complete = complete.unwrap();
    assert_eq!(complete.status, RecordingJobStatus::Complete);
    assert_eq!(
        complete.output_path.as_deref(),
        Some(first_output.as_path())
    );
    let published =
        crate::jobs::remote::read_published_remote_result_bundle(&first_output, &remote_jobs)
            .unwrap();
    assert_eq!(published.result, result);

    drop(reopened);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn published_result_and_cancellation_share_one_deterministic_mutation_boundary() {
    assert_published_result_wins_when_it_holds_the_mutation_boundary();
    assert_cancellation_wins_when_it_holds_the_mutation_boundary();
}

fn assert_published_result_wins_when_it_holds_the_mutation_boundary() {
    let root = temp_dir("published-result-wins-cancel-race");
    let job_id = "job-published-result-wins";
    let (resources, output) = published_saving_resources(&root, job_id);
    let jobs = Arc::new(RecordingJobs::from_resources_for_test(
        Arc::clone(&resources),
        &root,
    ));
    let (recovery_locked_tx, recovery_locked_rx) = mpsc::channel();
    let (release_recovery_tx, release_recovery_rx) = mpsc::channel();
    let recovery_resources = Arc::clone(&resources);
    let recovery = thread::spawn(move || {
        finalize_published_saving_result_with_mutation_observer_for_test(
            recovery_resources.ledger(),
            recovery_resources.remote_jobs_directory(),
            recovery_resources.mutation(),
            job_id,
            1_720_000_000_600,
            || {
                recovery_locked_tx.send(()).unwrap();
                release_recovery_rx.recv().unwrap();
            },
        )
    });
    recovery_locked_rx.recv().unwrap();

    let (cancel_started_tx, cancel_started_rx) = mpsc::channel();
    let (cancel_done_tx, cancel_done_rx) = mpsc::channel();
    let cancel_jobs = Arc::clone(&jobs);
    let cancel = thread::spawn(move || {
        cancel_started_tx.send(()).unwrap();
        let result = cancel_jobs.cancel_with_mutation_observer_for_test(
            &MediaOwner::new(),
            job_id,
            1_720_000_000_700,
            || {},
        );
        cancel_done_tx.send(()).unwrap();
        result
    });
    cancel_started_rx.recv().unwrap();
    assert!(matches!(
        cancel_done_rx.recv_timeout(Duration::from_millis(100)),
        Err(mpsc::RecvTimeoutError::Timeout)
    ));

    release_recovery_tx.send(()).unwrap();
    assert!(recovery.join().unwrap().unwrap());
    assert!(cancel.join().unwrap().is_err());
    let complete = resources.ledger().get_job(job_id).unwrap().unwrap();
    assert_eq!(complete.status, RecordingJobStatus::Complete);
    assert_eq!(complete.output_path.as_deref(), Some(output.as_path()));
    assert!(output.is_file());

    drop(jobs);
    drop(resources);
    fs::remove_dir_all(root).unwrap();
}

fn assert_cancellation_wins_when_it_holds_the_mutation_boundary() {
    let root = temp_dir("cancellation-wins-published-result-race");
    let job_id = "job-cancellation-wins";
    let (resources, _) = published_saving_resources(&root, job_id);
    let jobs = Arc::new(RecordingJobs::from_resources_for_test(
        Arc::clone(&resources),
        &root,
    ));
    let (cancel_locked_tx, cancel_locked_rx) = mpsc::channel();
    let (release_cancel_tx, release_cancel_rx) = mpsc::channel();
    let cancel_jobs = Arc::clone(&jobs);
    let cancel = thread::spawn(move || {
        cancel_jobs.cancel_with_mutation_observer_for_test(
            &MediaOwner::new(),
            job_id,
            1_720_000_000_600,
            || {
                cancel_locked_tx.send(()).unwrap();
                release_cancel_rx.recv().unwrap();
            },
        )
    });
    cancel_locked_rx.recv().unwrap();

    let (recovery_started_tx, recovery_started_rx) = mpsc::channel();
    let (recovery_done_tx, recovery_done_rx) = mpsc::channel();
    let recovery_resources = Arc::clone(&resources);
    let recovery = thread::spawn(move || {
        recovery_started_tx.send(()).unwrap();
        let result = finalize_published_saving_result_with_mutation_observer_for_test(
            recovery_resources.ledger(),
            recovery_resources.remote_jobs_directory(),
            recovery_resources.mutation(),
            job_id,
            1_720_000_000_700,
            || {},
        );
        recovery_done_tx.send(()).unwrap();
        result
    });
    recovery_started_rx.recv().unwrap();
    assert!(matches!(
        recovery_done_rx.recv_timeout(Duration::from_millis(100)),
        Err(mpsc::RecvTimeoutError::Timeout)
    ));

    release_cancel_tx.send(()).unwrap();
    assert_eq!(
        cancel.join().unwrap().unwrap().status,
        RecordingJobStatus::Cancelled
    );
    assert!(!recovery.join().unwrap().unwrap());
    let cancelled = resources.ledger().get_job(job_id).unwrap().unwrap();
    assert_eq!(cancelled.status, RecordingJobStatus::Cancelled);
    assert!(!resources.remote_jobs_directory().join(job_id).exists());

    drop(jobs);
    drop(resources);
    fs::remove_dir_all(root).unwrap();
}

fn published_saving_resources(
    root: &Path,
    job_id: &str,
) -> (Arc<RecordingJobResources>, std::path::PathBuf) {
    let remote_jobs = root.join("remote-jobs");
    let resources = Arc::new(RecordingJobResources::from_storage(
        JobLedger::open_in_memory().unwrap(),
        root.join("owned-live-recordings"),
        remote_jobs.clone(),
        root.join("recording-native-selection-registry.json"),
    ));
    let request =
        commit_remote_job_for_result_tests(resources.ledger(), root, &remote_jobs, job_id);
    resources
        .ledger()
        .begin_remote_result_saving(job_id, 1_720_000_000_500)
        .unwrap();
    let output = crate::jobs::remote::publish_remote_result(
        job_id,
        &remote_jobs,
        &complete_result_for(&request),
        None,
    )
    .unwrap();
    (resources, output)
}

fn commit_remote_job_for_result_tests(
    ledger: &JobLedger,
    root: &Path,
    remote_jobs: &Path,
    job_id: &str,
) -> CreateRecordingJobRequest {
    let source = root.join(format!("{job_id}.wav"));
    let owned_live = root.join("live-recordings");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &[0_u8; 320]);
    ledger.insert_job(&queued_job(job_id, source)).unwrap();
    let owner = OwnerNamespace::local("i-result-lifecycle-test").unwrap();
    prepare_next_queued_job(
        ledger,
        &owned_live,
        remote_jobs,
        &owner,
        1_720_000_000_100,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
    )
    .unwrap();
    let prepared = ledger.get_prepared_remote_job(job_id).unwrap().unwrap();
    let request =
        CreateRecordingJobRequest::decode_persisted(&prepared.create_request_json).unwrap();
    let base_url = "http://127.0.0.1:43117";
    ledger
        .begin_remote_create_attempt(job_id, base_url, 1_720_000_000_200)
        .unwrap();
    ledger
        .record_server_job_id(
            job_id,
            &format!(
                "job-{}",
                Sha256::digest(job_id.as_bytes())[..16]
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect::<String>()
            ),
            base_url,
            1_720_000_000_200,
        )
        .unwrap();
    for chunk in &request.chunks {
        ledger
            .acknowledge_remote_chunk(
                job_id,
                &chunk.replay_key.track_id,
                chunk.replay_key.sequence_start,
                chunk.replay_key.sequence_end,
                &chunk.content_identity.sha256,
                1_720_000_000_300,
            )
            .unwrap();
    }
    ledger
        .mark_remote_job_committed(job_id, 1_720_000_000_400)
        .unwrap();
    request
}

fn complete_result_for(request: &CreateRecordingJobRequest) -> TranscriptResultRevision {
    TranscriptResultRevision {
        session_id: request.metadata.session_id.as_str().to_owned(),
        revision: 1,
        authority: "server_authoritative".into(),
        created_at_utc: "2026-07-14T21:00:02Z".into(),
        capture_manifest_sha256: request.capture_manifest.sha256.clone(),
        previous_result_sha256: None,
        status: "complete".into(),
        language: Some(LanguageDecision {
            language_bcp47: "en-US".into(),
            confidence: Some(0.98),
        }),
        transcript: "Recovered private result.".into(),
        speaker_result_sha256: None,
        language_segments: None,
        language_span_evidence: None,
        alignment: AlignmentOutcome {
            status: AlignmentStatus::Unavailable,
            reason: Some(AlignmentUnavailableReason::ProviderUnsupported),
            component_revision: "joint-segment-timing-v1".into(),
        },
        aligned_words: Vec::new(),
        model_provenance: vec![ModelRevision {
            model_id: "CohereLabs/cohere-transcribe-03-2026".into(),
            revision: "b1eacc2686a3d08ceaae5f24a88b1d519620bc09".into(),
            calibration_revision: "asr-not-applicable".into(),
        }],
    }
}

#[test]
fn partial_server_result_is_published_before_the_ledger_becomes_partial() {
    let root = temp_dir("result");
    let database = root.join("jobs.sqlite3");
    let source = root.join("source.wav");
    let owned_live = root.join("live-recordings");
    let remote_jobs = root.join("remote-jobs");
    fs::create_dir_all(&owned_live).unwrap();
    write_pcm_wav(&source, &vec![0_u8; 320]);
    let ledger = JobLedger::open(&database).unwrap();
    ledger
        .insert_job(&queued_job("job-drain-result", source))
        .unwrap();
    let owner = OwnerNamespace::local("i-drain-test").unwrap();
    prepare_next_queued_job(
        &ledger,
        &owned_live,
        &remote_jobs,
        &owner,
        1_720_000_000_100,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
    )
    .unwrap();
    let prepared = ledger
        .get_prepared_remote_job("job-drain-result")
        .unwrap()
        .unwrap();
    let request =
        CreateRecordingJobRequest::decode_persisted(&prepared.create_request_json).unwrap();
    let server_job_id = "job-0123456789abcdef0123456789abcdef";
    let projection = serde_json::json!({
        "jobId": server_job_id,
        "sessionId": request.metadata.session_id.as_str(),
        "displayName": request.display_name,
        "sessionMode": "meeting",
        "sessionOrigin": "imported_file",
        "status": "partial",
        "route": "server_batch",
        "captureManifest": request.capture_manifest,
        "createdAtUtc": "2026-07-14T21:00:00Z",
        "updatedAtUtc": "2026-07-14T21:00:02Z"
    });
    let runtime_lock = "d".repeat(64);
    let speaker_texts = [
        "Phase five is connected.",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
    ];
    let transcript_text = speaker_texts.join(" ");
    let speaker_turns = speaker_texts
        .iter()
        .enumerate()
        .map(|(index, text)| {
            let speaker_number = index + 1;
            serde_json::json!({
                "turnId": format!("turn-{speaker_number:06}"),
                "startMs": 0,
                "endMs": 10,
                "text": text,
                "attribution": {
                    "kind": "session_speaker",
                    "sessionSpeakerId": format!("speaker-{speaker_number}")
                },
                "confidence": null,
                "supportingTrackIds": ["track-1"],
                "overlapGroupId": "overlap-000001"
            })
        })
        .collect::<Vec<_>>();
    let mut result = serde_json::json!({
        "sessionId": request.metadata.session_id.as_str(),
        "revision": 1,
        "authority": "server_authoritative",
        "createdAtUtc": "2026-07-14T21:00:02Z",
        "captureManifestSha256": request.capture_manifest.sha256,
        "previousResultSha256": null,
        "status": "partial",
        "language": {
            "languageBcp47": "en-US",
            "confidence": null
        },
        "transcript": transcript_text,
        "alignment": {
            "status": "unavailable",
            "reason": "ALIGNMENT_PROVIDER_UNSUPPORTED",
            "componentRevision": "joint-segment-timing-v1"
        },
        "alignedWords": [],
        "modelProvenance": [{
            "modelId": "Trelis/tiron",
            "revision": "90bc0a4d198cd5cf6679b0e478375ba3a0040575",
            "calibrationRevision": runtime_lock
        }]
    });
    let speaker_result = serde_json::json!({
        "sessionId": request.metadata.session_id.as_str(),
        "revision": 1,
        "authority": "server_authoritative",
        "createdAtUtc": "2026-07-14T21:00:02Z",
        "captureManifestSha256": request.capture_manifest.sha256,
        "previousResultSha256": null,
        "status": "partial",
        "language": {"languageBcp47": "en-US", "confidence": null},
        "runtimeLockSha256": runtime_lock,
        "speakerTurns": speaker_turns,
        "speakerCapacityDegradation": {
            "code": "SPEAKER_CAPACITY_REACHED",
            "fallbackDisposition": "not_run_recommended",
            "scope": "meeting",
            "startSample": 0,
            "endSample": 160,
            "observedSpeakerCount": 8,
            "speakerLimit": 8
        },
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
                "calibrationRevision": runtime_lock
            },
            {
                "modelId": "TrelisResearch/tiron",
                "revision": "d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c",
                "calibrationRevision": runtime_lock
            },
            {
                "modelId": "speechbrain/spkrec-ecapa-voxceleb",
                "revision": "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
                "calibrationRevision": runtime_lock
            }
        ]
    });
    let decoded_speaker_result: crate::server_connector::batch::SpeakerResultRevision =
        serde_json::from_value(speaker_result.clone()).unwrap();
    result["speakerResultSha256"] =
        serde_json::json!(decoded_speaker_result.content_sha256().unwrap());
    let (base_url, observed, server) = start_json_server(vec![
        (200, projection),
        (200, result),
        (200, speaker_result.clone()),
    ]);
    ledger
        .begin_remote_create_attempt("job-drain-result", &base_url, 1_720_000_000_200)
        .unwrap();
    ledger
        .record_server_job_id(
            "job-drain-result",
            server_job_id,
            &base_url,
            1_720_000_000_200,
        )
        .unwrap();
    for chunk in &request.chunks {
        ledger
            .acknowledge_remote_chunk(
                "job-drain-result",
                &chunk.replay_key.track_id,
                chunk.replay_key.sequence_start,
                chunk.replay_key.sequence_end,
                &chunk.content_identity.sha256,
                1_720_000_000_300,
            )
            .unwrap();
    }
    ledger
        .mark_remote_job_committed("job-drain-result", 1_720_000_000_400)
        .unwrap();
    let client = BatchApiClient::new(
        reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(2))
            .timeout(Duration::from_secs(5))
            .build()
            .unwrap(),
        &base_url,
    )
    .unwrap();

    tauri::async_runtime::block_on(async {
        assert!(
            super::advance_processing_once(&ledger, &remote_jobs, &client, 1_720_000_000_500,)
                .await
                .unwrap()
        );
    });
    server.join().unwrap();

    let partial = ledger.get_job("job-drain-result").unwrap().unwrap();
    assert_eq!(partial.status, RecordingJobStatus::Partial);
    assert_eq!(partial.expires_at_ms, Some(1_722_592_000_000));
    let output = partial.output_path.unwrap();
    assert_eq!(
        ledger
            .finalize_remote_result(
                "job-drain-result",
                &output,
                1_722_592_000_000,
                1_720_000_000_600,
                RecordingJobStatus::Partial,
            )
            .unwrap()
            .status,
        RecordingJobStatus::Partial,
    );
    assert!(ledger
        .finalize_remote_result(
            "job-drain-result",
            &output,
            1_722_592_000_000,
            1_720_000_000_600,
            RecordingJobStatus::Complete,
        )
        .is_err());
    assert_eq!(
        fs::read_to_string(&output).unwrap(),
        format!("{transcript_text}\n")
    );
    let result_path = output.parent().unwrap().join("result.json");
    let persisted: serde_json::Value =
        serde_json::from_slice(&fs::read(result_path).unwrap()).unwrap();
    assert_eq!(
        persisted["captureManifestSha256"],
        request.capture_manifest.sha256
    );
    let persisted_speaker: serde_json::Value = serde_json::from_slice(
        &fs::read(output.parent().unwrap().join("speaker-result.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(persisted_speaker, speaker_result);
    let requests = observed.lock().unwrap();
    assert_eq!(requests.len(), 3);
    assert!(requests[0].starts_with(&format!("GET /v1/jobs/{server_job_id} HTTP/1.1")));
    assert!(requests[1].starts_with(&format!("GET /v1/jobs/{server_job_id}/result HTTP/1.1")));
    assert!(requests[2].starts_with(&format!(
        "GET /v1/jobs/{server_job_id}/speaker-result HTTP/1.1"
    )));
    drop(requests);
    let jobs = crate::jobs::commands::RecordingJobs::from_ledger(ledger, &root);
    let catalog = jobs.published_remote_transcript_catalog().unwrap();
    assert_eq!(catalog.sessions.len(), 1);
    assert_eq!(
        catalog.sessions[0].warning.as_deref(),
        Some(
            "Speaker attribution may be incomplete because the server reached its eight-speaker limit; fallback reprocessing was recommended but not run."
        )
    );
    drop(jobs);
    fs::remove_dir_all(root).unwrap();
}
