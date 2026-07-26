use std::{
    fs::{self, File},
    io::{Seek, SeekFrom, Write},
    time::{Duration, UNIX_EPOCH},
};

use crate::{
    audio::session::OwnerNamespace,
    language::{
        span_contract::{LanguageSpan, LanguageSpanBoundaryAuthority, LanguageSpanDisposition},
        RecordingLanguageDecision,
    },
    server_connector::batch::{
        LanguageDecision, LanguageSegment, LanguageSegmentReason, LanguageSegmentStatus,
        ModelRevision, ServerLanguageSpanEvidence, TranscriptResultRevision, MAX_VAD_INTERVALS,
    },
};

use super::preparation::prepare_imported_pcm_wav_with_advisory_vad_for_test;
use super::preprocessing::{
    AdvisoryVadEngine, AdvisoryVadRuntimeError, AdvisoryVadSession, SourceVadInterval,
    VadComponentEvidence,
};
use super::{
    prepare_imported_pcm_wav, prepare_imported_pcm_wav_with_cancellation, publish_remote_result,
    read_prepared_chunk, read_published_remote_transcript, reset_unattached_spool,
    validate_pcm_data_bytes, validate_published_result_contract, ImportedPcmWavPreparation,
};

const TEST_ASR_CATALOG_REVISION: &str =
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

struct FixedIntervalVad {
    accepted_pcm_bytes: usize,
}

impl AdvisoryVadEngine for FixedIntervalVad {
    fn component(&self) -> VadComponentEvidence {
        VadComponentEvidence::for_test("test-vad", "test-revision")
    }

    fn accept_pcm16(
        &mut self,
        pcm: &[u8],
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), AdvisoryVadRuntimeError> {
        ensure_active().map_err(AdvisoryVadRuntimeError::Cancelled)?;
        self.accepted_pcm_bytes += pcm.len();
        Ok(())
    }

    fn finish(
        &mut self,
        emit: &mut dyn FnMut(SourceVadInterval) -> Result<(), &'static str>,
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), AdvisoryVadRuntimeError> {
        ensure_active().map_err(AdvisoryVadRuntimeError::Cancelled)?;
        emit(SourceVadInterval::for_test(160, 320)).map_err(AdvisoryVadRuntimeError::Engine)
    }
}

struct UnboundedVad;

impl AdvisoryVadEngine for UnboundedVad {
    fn component(&self) -> VadComponentEvidence {
        VadComponentEvidence::for_test("unbounded-test-vad", "test-revision")
    }

    fn accept_pcm16(
        &mut self,
        _pcm: &[u8],
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), AdvisoryVadRuntimeError> {
        ensure_active().map_err(AdvisoryVadRuntimeError::Cancelled)?;
        Ok(())
    }

    fn finish(
        &mut self,
        emit: &mut dyn FnMut(SourceVadInterval) -> Result<(), &'static str>,
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), AdvisoryVadRuntimeError> {
        for _ in 0..=MAX_VAD_INTERVALS {
            ensure_active().map_err(AdvisoryVadRuntimeError::Cancelled)?;
            // Exercise a misbehaving backend that ignores the collector's
            // stop signal instead of trusting every implementation to stop.
            let _ = emit(SourceVadInterval::for_test(0, 1));
        }
        Ok(())
    }
}

struct FinishCancellationVad;

impl AdvisoryVadEngine for FinishCancellationVad {
    fn component(&self) -> VadComponentEvidence {
        VadComponentEvidence::for_test("cancellation-test-vad", "test-revision")
    }

    fn accept_pcm16(
        &mut self,
        _pcm: &[u8],
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), AdvisoryVadRuntimeError> {
        ensure_active().map_err(AdvisoryVadRuntimeError::Cancelled)?;
        Ok(())
    }

    fn finish(
        &mut self,
        _emit: &mut dyn FnMut(SourceVadInterval) -> Result<(), &'static str>,
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), AdvisoryVadRuntimeError> {
        ensure_active().map_err(AdvisoryVadRuntimeError::Cancelled)?;
        ensure_active().map_err(AdvisoryVadRuntimeError::Cancelled)
    }
}

#[test]
fn advisory_vad_finish_propagates_cancellation_instead_of_encoding_a_model_error() {
    let mut engine = FinishCancellationVad;
    let session = AdvisoryVadSession::running(&mut engine);
    let mut checks = 0_u8;
    let error = session
        .finish(0, &mut || {
            checks += 1;
            if checks >= 3 {
                Err("recording job preprocessing was cancelled".into())
            } else {
                Ok(())
            }
        })
        .expect_err("cancellation during native finish must abort preprocessing");

    assert_eq!(error, "recording job preprocessing was cancelled");
}

#[test]
fn client_intake_matches_the_server_four_hour_pcm_ceiling() {
    let four_hours = 16_000_u64 * 2 * 4 * 60 * 60;
    assert!(validate_pcm_data_bytes(four_hours).is_ok());
    assert!(validate_pcm_data_bytes(four_hours + 2).is_err());
}

#[test]
fn advisory_vad_evidence_never_removes_non_speech_source_audio() {
    let root = std::env::temp_dir().join(format!(
        "yap-source-authoritative-vad-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let source_path = root.join("source.wav");
    let mut pcm = vec![0_u8; 320];
    pcm.extend(std::iter::repeat_n(0x40_u8, 320));
    pcm.extend(std::iter::repeat_n(0_u8, 320));
    write_pcm_wav(&source_path, &pcm);
    let original = fs::read(&source_path).unwrap();
    let mut source = File::open(&source_path).unwrap();
    let owner = OwnerNamespace::local("i-source-authoritative-vad").unwrap();
    let mut vad = FixedIntervalVad {
        accepted_pcm_bytes: 0,
    };
    let language_decision = RecordingLanguageDecision::primary("en-US".into()).unwrap();

    let prepared = prepare_imported_pcm_wav_with_advisory_vad_for_test(
        ImportedPcmWavPreparation {
            job_id: "job-source-authoritative-vad",
            display_name: "source.wav",
            source: &mut source,
            spool_root: &root.join("spool"),
            owner_namespace: &owner,
            started_at: UNIX_EPOCH + Duration::from_secs(1_720_000_000),
            language_decision: &language_decision,
            asr_catalog_revision: TEST_ASR_CATALOG_REVISION,
        },
        &mut vad,
    )
    .unwrap();

    assert_eq!(
        prepared.request.asr_catalog_revision.as_deref(),
        Some(TEST_ASR_CATALOG_REVISION)
    );
    assert_eq!(vad.accepted_pcm_bytes, pcm.len());
    assert_eq!(fs::read(&prepared.chunks[0].artifact_path).unwrap(), pcm);
    assert_eq!(fs::read(&source_path).unwrap(), original);
    assert_eq!(prepared.request.capture_manifest.schema_version, 2);

    let manifest: serde_json::Value =
        serde_json::from_slice(&fs::read(&prepared.capture_manifest_path).unwrap()).unwrap();
    assert_eq!(manifest["schemaVersion"], 2);
    assert_eq!(
        manifest["preprocessing"]["normalization"]["method"],
        "canonical_pcm16_identity"
    );
    assert_eq!(
        manifest["preprocessing"]["normalization"]["sourceSampleCount"],
        480
    );
    assert_eq!(
        manifest["preprocessing"]["normalization"]["outputSampleCount"],
        480
    );
    assert_eq!(
        manifest["preprocessing"]["normalization"]["paddingSamples"],
        0
    );
    assert_eq!(
        manifest["preprocessing"]["normalization"]["sourceTimePreserved"],
        true
    );
    assert_eq!(manifest["preprocessing"]["vad"]["status"], "complete");
    assert_eq!(
        manifest["preprocessing"]["vad"]["component"]["id"],
        "test-vad"
    );
    assert_eq!(
        manifest["preprocessing"]["vad"]["intervals"],
        serde_json::json!([{
            "startSample": 160,
            "endSampleExclusive": 320,
            "startMs": 10,
            "endMs": 20
        }])
    );

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn advisory_vad_discards_unbounded_backend_output() {
    let root =
        std::env::temp_dir().join(format!("yap-bounded-vad-evidence-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let source_path = root.join("source.wav");
    write_pcm_wav(&source_path, &[0_u8; 320]);
    let mut source = File::open(&source_path).unwrap();
    let owner = OwnerNamespace::local("i-bounded-vad-evidence").unwrap();
    let mut vad = UnboundedVad;
    let language_decision = RecordingLanguageDecision::primary("en-US".into()).unwrap();

    let prepared = prepare_imported_pcm_wav_with_advisory_vad_for_test(
        ImportedPcmWavPreparation {
            job_id: "job-bounded-vad-evidence",
            display_name: "source.wav",
            source: &mut source,
            spool_root: &root.join("spool"),
            owner_namespace: &owner,
            started_at: UNIX_EPOCH + Duration::from_secs(1_720_000_000),
            language_decision: &language_decision,
            asr_catalog_revision: TEST_ASR_CATALOG_REVISION,
        },
        &mut vad,
    )
    .unwrap();

    let manifest: serde_json::Value =
        serde_json::from_slice(&fs::read(&prepared.capture_manifest_path).unwrap()).unwrap();
    assert_eq!(manifest["preprocessing"]["vad"]["status"], "error");
    assert_eq!(
        manifest["preprocessing"]["vad"]["errorCode"],
        "segment_limit_exceeded"
    );
    assert_eq!(
        manifest["preprocessing"]["vad"]["intervals"],
        serde_json::json!([])
    );

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn source_mutation_during_admission_is_rejected_without_publishing_a_spool() {
    let root =
        std::env::temp_dir().join(format!("yap-source-admission-race-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let source_path = root.join("source.wav");
    let original_pcm = vec![0x11_u8; 128 * 1024];
    let replacement_pcm = vec![0x22_u8; original_pcm.len()];
    write_pcm_wav(&source_path, &original_pcm);
    let original_container = fs::read(&source_path).unwrap();
    let replacement_path = root.join("replacement.wav");
    write_pcm_wav(&replacement_path, &replacement_pcm);
    let replacement_container = fs::read(&replacement_path).unwrap();
    let mut source = File::open(&source_path).unwrap();
    let spool = root.join("spool");
    let owner = OwnerNamespace::local("i-source-admission-race").unwrap();
    let mut mutated_at = None;

    let error = prepare_imported_pcm_wav_with_cancellation(
        ImportedPcmWavPreparation {
            job_id: "job-source-admission-race",
            display_name: "source.wav",
            source: &mut source,
            spool_root: &spool,
            owner_namespace: &owner,
            started_at: UNIX_EPOCH + Duration::from_secs(1_720_000_000),
            language_decision: &RecordingLanguageDecision::primary("en-US".into()).unwrap(),
            asr_catalog_revision: TEST_ASR_CATALOG_REVISION,
        },
        || {
            if mutated_at.is_none() {
                let snapshot = fs::read_dir(&spool)
                    .ok()
                    .into_iter()
                    .flatten()
                    .filter_map(Result::ok)
                    .map(|entry| entry.path().join("admitted-source.wav"))
                    .find(|path| path.exists());
                if let Some(snapshot) = snapshot {
                    let frozen_bytes = fs::metadata(snapshot).unwrap().len() as usize;
                    if frozen_bytes >= 64 * 1024 && frozen_bytes < original_container.len() {
                        let mut writer = fs::OpenOptions::new()
                            .write(true)
                            .open(&source_path)
                            .unwrap();
                        writer.seek(SeekFrom::Start(frozen_bytes as u64)).unwrap();
                        writer
                            .write_all(&replacement_container[frozen_bytes..])
                            .unwrap();
                        writer.sync_all().unwrap();
                        mutated_at = Some(frozen_bytes);
                    }
                }
            }
            Ok(())
        },
    )
    .err()
    .expect("a concurrent source mutation must fail admission");

    assert!(mutated_at.is_some());
    assert!(error.contains("selected recording changed while it was being admitted"));
    assert!(!spool.join("job-source-admission-race").exists());
    assert_eq!(fs::read_dir(&spool).unwrap().count(), 0);

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn cancellation_interrupts_chunking_and_removes_unpublished_spool() {
    let root = std::env::temp_dir().join(format!(
        "yap-preparation-cancellation-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let source_path = root.join("source.wav");
    let pcm = vec![0_u8; super::preparation::CHUNK_PCM_BYTES + 320];
    write_pcm_wav(&source_path, &pcm);
    let original = fs::read(&source_path).unwrap();
    let mut source = File::open(&source_path).unwrap();
    let spool = root.join("spool");
    let owner = OwnerNamespace::local("i-cancel-preparation").unwrap();

    let error = prepare_imported_pcm_wav_with_cancellation(
        ImportedPcmWavPreparation {
            job_id: "job-cancel-preparation",
            display_name: "source.wav",
            source: &mut source,
            spool_root: &spool,
            owner_namespace: &owner,
            started_at: UNIX_EPOCH + Duration::from_secs(1_720_000_000),
            language_decision: &RecordingLanguageDecision::primary("en-US".into()).unwrap(),
            asr_catalog_revision: TEST_ASR_CATALOG_REVISION,
        },
        || {
            let first_chunk_exists = fs::read_dir(&spool)
                .ok()
                .into_iter()
                .flatten()
                .filter_map(Result::ok)
                .filter_map(|entry| fs::read_dir(entry.path()).ok())
                .flatten()
                .filter_map(Result::ok)
                .any(|entry| entry.path().extension().is_some_and(|value| value == "pcm"));
            if first_chunk_exists {
                Err("recording job preprocessing was cancelled".into())
            } else {
                Ok(())
            }
        },
    )
    .err()
    .expect("preprocessing cancellation must interrupt the second chunk");

    assert_eq!(error, "recording job preprocessing was cancelled");
    assert_eq!(fs::read(&source_path).unwrap(), original);
    assert!(!spool.join("job-cancel-preparation").exists());
    assert!(fs::read_dir(&spool).unwrap().next().is_none());

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn cancellation_interrupts_riff_chunk_inspection_before_spooling() {
    let root = std::env::temp_dir().join(format!(
        "yap-riff-inspection-cancellation-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let source_path = root.join("source.wav");
    write_pcm_wav_with_empty_chunks(&source_path, &[0_u8; 320], 32);
    let mut source = File::open(&source_path).unwrap();
    let spool = root.join("spool");
    let owner = OwnerNamespace::local("i-cancel-riff-inspection").unwrap();
    let mut checks = 0_usize;
    let mut spool_existed_at_cancellation = false;

    let error = prepare_imported_pcm_wav_with_cancellation(
        ImportedPcmWavPreparation {
            job_id: "job-cancel-riff-inspection",
            display_name: "source.wav",
            source: &mut source,
            spool_root: &spool,
            owner_namespace: &owner,
            started_at: UNIX_EPOCH + Duration::from_secs(1_720_000_000),
            language_decision: &RecordingLanguageDecision::primary("en-US".into()).unwrap(),
            asr_catalog_revision: TEST_ASR_CATALOG_REVISION,
        },
        || {
            checks += 1;
            if checks >= 5 {
                spool_existed_at_cancellation = spool.exists();
                Err("recording job preprocessing was cancelled".into())
            } else {
                Ok(())
            }
        },
    )
    .err()
    .expect("cancellation must interrupt RIFF inspection");

    assert_eq!(error, "recording job preprocessing was cancelled");
    assert!(!spool_existed_at_cancellation);
    assert!(!spool.exists());

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn excessive_riff_chunk_count_is_rejected_before_spooling() {
    let root = std::env::temp_dir().join(format!("yap-riff-chunk-count-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let source_path = root.join("source.wav");
    write_pcm_wav_with_empty_chunks(&source_path, &[0_u8; 320], super::wav::MAX_WAV_CHUNKS + 1);
    let mut source = File::open(&source_path).unwrap();
    let spool = root.join("spool");
    let owner = OwnerNamespace::local("i-riff-chunk-count").unwrap();

    let error = prepare_imported_pcm_wav(
        "job-riff-chunk-count",
        "source.wav",
        &mut source,
        &spool,
        &owner,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
        &RecordingLanguageDecision::primary("en-US".into()).unwrap(),
    )
    .err()
    .expect("excessive RIFF chunk count must be rejected");

    assert_eq!(error, "imported WAV contains too many RIFF chunks");
    assert!(!spool.exists());

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn wav_bytes_outside_declared_riff_are_rejected_before_spooling() {
    let root = std::env::temp_dir().join(format!("yap-riff-boundary-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let source_path = root.join("source.wav");
    write_pcm_wav(&source_path, &[0_u8; 320]);
    let mut append = fs::OpenOptions::new()
        .append(true)
        .open(&source_path)
        .unwrap();
    append.write_all(b"private trailing bytes").unwrap();
    append.sync_all().unwrap();
    drop(append);
    let mut source = File::open(&source_path).unwrap();
    let owner = OwnerNamespace::local("i-riff-boundary").unwrap();

    let error = prepare_imported_pcm_wav(
        "job-riff-boundary",
        "source.wav",
        &mut source,
        &root.join("spool"),
        &owner,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
        &RecordingLanguageDecision::primary("en-US".into()).unwrap(),
    )
    .err()
    .expect("trailing bytes must reject the imported WAV");

    assert_eq!(
        error,
        "imported WAV file length does not match its RIFF boundary"
    );
    assert!(!root.join("spool").exists());
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn oversized_wav_container_metadata_is_rejected_before_spooling() {
    let root = std::env::temp_dir().join(format!("yap-riff-overhead-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let source_path = root.join("source.wav");
    write_pcm_wav_with_junk(
        &source_path,
        &[0_u8; 320],
        super::MAX_WAV_CONTAINER_OVERHEAD_BYTES as usize,
    );
    let mut source = File::open(&source_path).unwrap();
    let owner = OwnerNamespace::local("i-riff-overhead").unwrap();

    let error = prepare_imported_pcm_wav(
        "job-riff-overhead",
        "source.wav",
        &mut source,
        &root.join("spool"),
        &owner,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
        &RecordingLanguageDecision::primary("en-US".into()).unwrap(),
    )
    .err()
    .expect("oversized WAV metadata must be rejected");

    assert_eq!(error, "imported WAV container metadata is too large");
    assert!(!root.join("spool").exists());
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn canonical_pcm_wav_becomes_an_immutable_owned_upload_manifest() {
    let root = std::env::temp_dir().join(format!("yap-prepare-import-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let source_path = root.join("source.wav");
    let pcm = vec![0_u8; 320];
    write_pcm_wav(&source_path, &pcm);
    let original = fs::read(&source_path).unwrap();
    let mut source = File::open(&source_path).unwrap();
    let owner = OwnerNamespace::local("i-prepare-import-test").unwrap();
    let language = RecordingLanguageDecision::manual_override("fr-FR".into()).unwrap();

    let prepared = prepare_imported_pcm_wav(
        "job-prepare-import-test",
        "source.wav",
        &mut source,
        &root.join("spool"),
        &owner,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
        &language,
    )
    .unwrap();

    assert_eq!(prepared.request.route, "server_batch");
    assert_eq!(
        prepared.request.metadata.origin,
        crate::audio::session::SessionOrigin::ImportedFile
    );
    assert_eq!(
        prepared.request.metadata.preferred_languages_bcp47,
        ["fr-FR"]
    );
    assert_eq!(prepared.request.language_decision, language);
    assert_eq!(prepared.request.tracks.len(), 1);
    assert_eq!(prepared.request.chunks.len(), 1);
    assert_eq!(prepared.chunks.len(), 1);
    assert_eq!(fs::read(&prepared.chunks[0].artifact_path).unwrap(), pcm);
    assert!(prepared.capture_manifest_path.is_file());
    assert_eq!(
        fs::metadata(&prepared.capture_manifest_path).unwrap().len(),
        prepared.request.capture_manifest.byte_length
    );
    assert_eq!(fs::read(source_path).unwrap(), original);
    assert_eq!(prepared.owner_namespace, owner.as_str());
    assert_eq!(
        read_prepared_chunk(
            &prepared.chunks[0].artifact_path,
            &root.join("spool"),
            &prepared.chunks[0].reference,
        )
        .unwrap(),
        pcm
    );

    let capture_manifest: serde_json::Value =
        serde_json::from_slice(&fs::read(&prepared.capture_manifest_path).unwrap()).unwrap();
    let durable = prepared.into_ledger_state().unwrap();
    let durable_request: serde_json::Value =
        serde_json::from_str(&durable.create_request_json).unwrap();
    assert_eq!(durable_request["route"], "server_batch");
    assert_eq!(durable_request["languageDecision"]["mode"], "fixed");
    assert_eq!(
        durable_request["languageDecision"]["languageBcp47"],
        "fr-FR"
    );
    assert_eq!(
        capture_manifest["languageDecision"]["disposition"],
        "manualOverride"
    );
    assert_eq!(durable.chunks.len(), 1);
    assert_eq!(durable.chunks[0].content_byte_length, 320);
    assert_eq!(durable.chunks[0].sequence_start, 0);
    assert_eq!(durable.chunks[0].sequence_end, 159);

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn explicit_dynamic_recording_uses_und_catalog_language_without_a_fixed_fallback() {
    let root = std::env::temp_dir().join(format!("yap-dynamic-language-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let source_path = root.join("source.wav");
    write_pcm_wav(&source_path, &vec![0_u8; 320]);
    let mut source = File::open(&source_path).unwrap();
    let owner = OwnerNamespace::local("i-dynamic-language").unwrap();
    let decision = RecordingLanguageDecision::explicit_dynamic();

    let prepared = prepare_imported_pcm_wav(
        "job-dynamic-language",
        "source.wav",
        &mut source,
        &root.join("spool"),
        &owner,
        UNIX_EPOCH + Duration::from_secs(1_720_000_000),
        &decision,
    )
    .unwrap();

    assert_eq!(prepared.request.language_decision, decision);
    assert_eq!(
        prepared.request.metadata.locale_hint_bcp47.as_deref(),
        Some("und")
    );
    assert_eq!(prepared.request.metadata.preferred_languages_bcp47, ["und"]);
    let encoded = serde_json::to_value(&prepared.request).unwrap();
    assert_eq!(encoded["languageDecision"]["mode"], "dynamic");
    assert!(encoded["languageDecision"]["languageBcp47"].is_null());
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn cleanup_removes_only_exact_owned_job_staging_shapes_after_a_crash() {
    let root = std::env::temp_dir().join(format!("yap-staging-cleanup-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    let spool = root.join("remote-jobs");
    fs::create_dir_all(&spool).unwrap();
    let abandoned_prepare = spool.join(".job-stale-4242-7.part");
    let abandoned_quarantine = spool.join(".job-stale-orphan-4242-8");
    let unrelated = spool.join(".job-stale-user-data");
    for directory in [&abandoned_prepare, &abandoned_quarantine, &unrelated] {
        fs::create_dir(directory).unwrap();
        fs::write(directory.join("private.pcm"), b"private bytes").unwrap();
    }

    reset_unattached_spool("job-stale", &spool).unwrap();

    assert!(!abandoned_prepare.exists());
    assert!(!abandoned_quarantine.exists());
    assert!(unrelated.is_dir());
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn published_remote_transcript_is_reopened_only_through_its_result_revision() {
    let root = std::env::temp_dir().join(format!("yap-result-open-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    let spool = root.join("remote-jobs");
    let job_id = "job-result-open";
    fs::create_dir_all(spool.join(job_id)).unwrap();
    let result = TranscriptResultRevision {
        session_id: "s-result-open".into(),
        revision: 1,
        authority: "server_authoritative".into(),
        created_at_utc: "2026-07-14T21:00:02Z".into(),
        capture_manifest_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
            .into(),
        previous_result_sha256: None,
        status: "complete".into(),
        language: Some(LanguageDecision {
            language_bcp47: "en-US".into(),
            confidence: Some(0.98),
        }),
        transcript: "Private result.".into(),
        language_segments: None,
        language_span_evidence: None,
        alignment: None,
        aligned_words: Vec::new(),
        model_provenance: vec![ModelRevision {
            model_id: "CohereLabs/cohere-transcribe-03-2026".into(),
            revision: "b1eacc2686a3d08ceaae5f24a88b1d519620bc09".into(),
            calibration_revision: "asr-not-applicable".into(),
        }],
    };

    let output = publish_remote_result(job_id, &spool, &result).unwrap();
    let reopened = read_published_remote_transcript(&output, &spool).unwrap();
    assert_eq!(reopened.text, "Private result.\n");
    assert_eq!(reopened.result, result);

    let mut future_shape = serde_json::to_value(&result).unwrap();
    future_shape
        .as_object_mut()
        .unwrap()
        .insert("futureAuthority".into(), serde_json::json!({}));
    assert!(serde_json::from_value::<TranscriptResultRevision>(future_shape).is_err());

    let mut empty = result.clone();
    empty.transcript = " \n\t".into();
    assert!(validate_published_result_contract(&empty, 1).is_err());
    assert!(publish_remote_result(job_id, &spool, &empty).is_err());
    let mut offset_timestamp = result.clone();
    offset_timestamp.created_at_utc = "2026-07-14T16:00:02-05:00".into();
    assert!(validate_published_result_contract(&offset_timestamp, 1).is_err());

    fs::write(&output, "tampered\n").unwrap();
    assert!(read_published_remote_transcript(&output, &spool).is_err());
    assert!(read_published_remote_transcript(
        &spool
            .join(job_id)
            .join("result-00000000000000000001/../transcript.txt"),
        &spool,
    )
    .is_err());

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn dynamic_result_requires_ordered_lossless_detected_or_unknown_segments() {
    let result = TranscriptResultRevision {
        session_id: "s-dynamic-language-result".into(),
        revision: 1,
        authority: "server_authoritative".into(),
        created_at_utc: "2026-07-17T21:00:02Z".into(),
        capture_manifest_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
            .into(),
        previous_result_sha256: None,
        status: "complete".into(),
        language: Some(LanguageDecision {
            language_bcp47: "und".into(),
            confidence: None,
        }),
        transcript: "hello bonjour".into(),
        language_segments: Some(vec![
            LanguageSegment {
                index: 0,
                source_span_index: 0,
                text: "hello".into(),
                status: LanguageSegmentStatus::Detected,
                language_bcp47: Some("en-US".into()),
                raw_language_tag: Some("en-US".into()),
                reason: None,
            },
            LanguageSegment {
                index: 1,
                source_span_index: 0,
                text: "bonjour".into(),
                status: LanguageSegmentStatus::Unknown,
                language_bcp47: None,
                raw_language_tag: Some("el-GR".into()),
                reason: Some(LanguageSegmentReason::DisabledLanguageTag),
            },
        ]),
        language_span_evidence: Some(ServerLanguageSpanEvidence {
            schema_version: 1,
            sample_rate_hz: 16_000,
            source_end_sample: 16_000,
            boundary_authority: LanguageSpanBoundaryAuthority::ServerUtterance,
            provider_id: "nemotron".into(),
            pool_id: "nemotron-batch".into(),
            model_id: "nvidia/nemotron-3.5-asr-streaming-0.6b".into(),
            model_revision: "f3d333391852ba876df169dcc9ba902d25b6ab0b".into(),
            utterance_plan_sha256:
                "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee".into(),
            spans: vec![LanguageSpan {
                start_sample: 0,
                end_sample: 16_000,
                language_bcp47: "und".into(),
                decision_revision: 1,
                disposition: LanguageSpanDisposition::ServerUnknown,
                component_revision: Some("f3d333391852ba876df169dcc9ba902d25b6ab0b".into()),
                decision_evidence: None,
            }],
        }),
        alignment: None,
        aligned_words: Vec::new(),
        model_provenance: vec![ModelRevision {
            model_id: "nvidia/nemotron-3.5-asr-streaming-0.6b".into(),
            revision: "f3d333391852ba876df169dcc9ba902d25b6ab0b".into(),
            calibration_revision: "asr-not-applicable".into(),
        }],
    };

    assert!(validate_published_result_contract(&result, 1).is_ok());
    let mut text_loss = result.clone();
    text_loss.transcript = "hello".into();
    assert!(validate_published_result_contract(&text_loss, 1).is_err());
    let mut primary_fallback = result;
    primary_fallback.language_segments.as_mut().unwrap()[1].language_bcp47 = Some("en-US".into());
    assert!(validate_published_result_contract(&primary_fallback, 1).is_err());
}

#[test]
fn aligned_result_requires_exact_raw_words_and_source_bounded_intervals() {
    let value = serde_json::json!({
        "sessionId": "s-alignment-result",
        "revision": 1,
        "authority": "server_authoritative",
        "createdAtUtc": "2026-07-18T12:00:00Z",
        "captureManifestSha256":
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "previousResultSha256": null,
        "status": "complete",
        "language": {"languageBcp47": "en-US", "confidence": null},
        "transcript": "hello world.",
        "alignment": {
            "status": "available",
            "reason": null,
            "componentRevision": "cohere-attention-en-v1"
        },
        "alignedWords": [
            {
                "wordIndex": 0,
                "text": "hello",
                "startMs": 80,
                "endMs": 240,
                "turnId": null,
                "attribution": {"kind": "unknown"},
                "confidence": null
            },
            {
                "wordIndex": 1,
                "text": "world.",
                "startMs": 240,
                "endMs": 480,
                "turnId": null,
                "attribution": {"kind": "unknown"},
                "confidence": null
            }
        ],
        "modelProvenance": [{
            "modelId": "CohereLabs/cohere-transcribe-03-2026",
            "revision": "b1eacc2686a3d08ceaae5f24a88b1d519620bc09",
            "calibrationRevision": "asr-not-applicable"
        }]
    });
    let result: TranscriptResultRevision = serde_json::from_value(value).unwrap();
    assert!(validate_published_result_contract(&result, 1).is_ok());

    let mut text_drift = result.clone();
    text_drift.aligned_words[1].text = "world".into();
    assert!(validate_published_result_contract(&text_drift, 1).is_err());
    let mut overlap = result.clone();
    overlap.aligned_words[1].start_ms = 239;
    assert!(validate_published_result_contract(&overlap, 1).is_err());
    let mut invented_confidence = result.clone();
    invented_confidence.aligned_words[0].confidence = Some(0.9);
    assert!(validate_published_result_contract(&invented_confidence, 1).is_err());
    let mut unavailable_with_words = result;
    unavailable_with_words.alignment.as_mut().unwrap().status =
        crate::server_connector::batch::AlignmentStatus::Unavailable;
    unavailable_with_words.alignment.as_mut().unwrap().reason =
        Some(crate::server_connector::batch::AlignmentUnavailableReason::RuntimeFailed);
    assert!(validate_published_result_contract(&unavailable_with_words, 1).is_err());
}

fn write_pcm_wav(path: &std::path::Path, pcm: &[u8]) {
    let mut file = File::create(path).unwrap();
    file.write_all(b"RIFF").unwrap();
    file.write_all(&(36_u32 + pcm.len() as u32).to_le_bytes())
        .unwrap();
    file.write_all(b"WAVEfmt ").unwrap();
    file.write_all(&16_u32.to_le_bytes()).unwrap();
    file.write_all(&1_u16.to_le_bytes()).unwrap();
    file.write_all(&1_u16.to_le_bytes()).unwrap();
    file.write_all(&16_000_u32.to_le_bytes()).unwrap();
    file.write_all(&32_000_u32.to_le_bytes()).unwrap();
    file.write_all(&2_u16.to_le_bytes()).unwrap();
    file.write_all(&16_u16.to_le_bytes()).unwrap();
    file.write_all(b"data").unwrap();
    file.write_all(&(pcm.len() as u32).to_le_bytes()).unwrap();
    file.write_all(pcm).unwrap();
    file.sync_all().unwrap();
}

fn write_pcm_wav_with_junk(path: &std::path::Path, pcm: &[u8], junk_bytes: usize) {
    let file_bytes = 52_u64 + junk_bytes as u64 + pcm.len() as u64;
    let mut file = File::create(path).unwrap();
    file.write_all(b"RIFF").unwrap();
    file.write_all(&u32::try_from(file_bytes - 8).unwrap().to_le_bytes())
        .unwrap();
    file.write_all(b"WAVEfmt ").unwrap();
    file.write_all(&16_u32.to_le_bytes()).unwrap();
    file.write_all(&1_u16.to_le_bytes()).unwrap();
    file.write_all(&1_u16.to_le_bytes()).unwrap();
    file.write_all(&16_000_u32.to_le_bytes()).unwrap();
    file.write_all(&32_000_u32.to_le_bytes()).unwrap();
    file.write_all(&2_u16.to_le_bytes()).unwrap();
    file.write_all(&16_u16.to_le_bytes()).unwrap();
    file.write_all(b"JUNK").unwrap();
    file.write_all(&u32::try_from(junk_bytes).unwrap().to_le_bytes())
        .unwrap();
    file.write_all(&vec![0_u8; junk_bytes]).unwrap();
    file.write_all(b"data").unwrap();
    file.write_all(&u32::try_from(pcm.len()).unwrap().to_le_bytes())
        .unwrap();
    file.write_all(pcm).unwrap();
    file.sync_all().unwrap();
}

fn write_pcm_wav_with_empty_chunks(path: &std::path::Path, pcm: &[u8], chunk_count: usize) {
    let file_bytes = 44_u64 + (chunk_count as u64 * 8) + pcm.len() as u64;
    let mut file = File::create(path).unwrap();
    file.write_all(b"RIFF").unwrap();
    file.write_all(&u32::try_from(file_bytes - 8).unwrap().to_le_bytes())
        .unwrap();
    file.write_all(b"WAVEfmt ").unwrap();
    file.write_all(&16_u32.to_le_bytes()).unwrap();
    file.write_all(&1_u16.to_le_bytes()).unwrap();
    file.write_all(&1_u16.to_le_bytes()).unwrap();
    file.write_all(&16_000_u32.to_le_bytes()).unwrap();
    file.write_all(&32_000_u32.to_le_bytes()).unwrap();
    file.write_all(&2_u16.to_le_bytes()).unwrap();
    file.write_all(&16_u16.to_le_bytes()).unwrap();
    for _ in 0..chunk_count {
        file.write_all(b"JUNK").unwrap();
        file.write_all(&0_u32.to_le_bytes()).unwrap();
    }
    file.write_all(b"data").unwrap();
    file.write_all(&u32::try_from(pcm.len()).unwrap().to_le_bytes())
        .unwrap();
    file.write_all(pcm).unwrap();
    file.sync_all().unwrap();
}
