use super::*;
use crate::language::{
    live_diarization::{LanguageSpan, LanguageSpanDisposition},
    live_evidence::{LiveLanguageEvidence, LiveLanguageMode, LiveLanguageStatus},
};

#[test]
fn reserved_recording_session_is_canonical_for_worker_frames_gaps_and_commit() {
    let directory = std::env::temp_dir().join(format!(
        "yap-runtime-reserved-session-{}",
        std::process::id()
    ));
    std::fs::remove_dir_all(&directory).ok();
    std::fs::create_dir_all(&directory).unwrap();
    let reservation = allocate_recording_session(&directory).unwrap();
    let recording_session_id = reservation.session_id().clone();
    let (recording_sink, recording_rx) =
        bounded_sink(SinkKind::Recording, RECORDING_QUEUE_CAPACITY);
    let recording =
        RecordingSinkHandle::spawn_reserved(reservation, recording_sink.clone(), recording_rx);
    let (local_asr, local_asr_rx) = bounded_sink(SinkKind::LocalAsr, 8);
    let coordinator = Arc::new(Mutex::new(capture_worker_coordinator(
        recording_session_id.clone(),
        recording_sink,
        local_asr,
    )));

    coordinator
        .lock()
        .unwrap()
        .consume(
            &CapturePacket {
                source_position_frames: 0,
                channels: 1,
                sample_rate_hz: 16_000,
                samples: vec![0.0; 4_000],
            },
            &LossAccumulator::new(),
        )
        .unwrap();
    let prepared = local_asr_rx.recv_timeout(Duration::from_secs(1)).unwrap();
    assert_eq!(prepared.metadata.session_id, recording_session_id);

    let mut crash_messages = Vec::new();
    assert!(!process_capture_loss(
        &coordinator,
        Ok(LossSnapshot {
            first_source_position_frames: 4_000,
            dropped_frames: 1_600,
            cause: GapCause::DeviceDiscontinuity,
            generation: 7,
        }),
        |message| crash_messages.push(message),
    ));
    assert!(crash_messages.is_empty());
    coordinator
        .lock()
        .unwrap()
        .consume(
            &CapturePacket {
                source_position_frames: 5_600,
                channels: 1,
                sample_rate_hz: 16_000,
                samples: vec![0.0; 400],
            },
            &LossAccumulator::new(),
        )
        .unwrap();
    coordinator.lock().unwrap().handoff_recording_completion();
    recording
        .append_language_evidence(
            LiveLanguageEvidence::try_new(
                6_000,
                "en-US".into(),
                LiveLanguageMode::FixedPrimary,
                LiveLanguageStatus::Complete,
                None,
                None,
                vec![LanguageSpan {
                    start_sample: 0,
                    end_sample: 6_000,
                    language_bcp47: "en-US".into(),
                    decision_revision: 1,
                    disposition: LanguageSpanDisposition::ConfirmedPrimary,
                    component_revision: None,
                    decision_evidence: None,
                }],
            )
            .unwrap(),
        )
        .unwrap();

    let result = recording.finalize().unwrap();
    assert_eq!(result.status, CaptureStatus::Complete, "{:?}", result.error);
    assert_eq!(result.session_id, recording_session_id);
    let commit: serde_json::Value = serde_json::from_slice(
        &std::fs::read(directory.join(format!("live-{recording_session_id}.commit.json"))).unwrap(),
    )
    .unwrap();
    let sidecar: serde_json::Value = serde_json::from_slice(
        &std::fs::read(directory.join(format!("live-{recording_session_id}.capture.json")))
            .unwrap(),
    )
    .unwrap();
    assert_eq!(commit["sessionId"], recording_session_id.as_str());
    assert_eq!(sidecar["sessionId"], recording_session_id.as_str());
    assert_eq!(sidecar["sequenceCoverage"][0]["firstSequence"], 0);
    assert_eq!(sidecar["sequenceCoverage"][0]["lastSequence"], 1);
    assert_eq!(sidecar["languageEvidence"]["sourceEndSample"], 6_000);
    assert_eq!(sidecar["languageEvidence"]["primaryLanguageBcp47"], "en-US");
    assert_eq!(sidecar["timelineGaps"].as_array().unwrap().len(), 1);
    let gap = &sidecar["timelineGaps"][0];
    assert_eq!(gap["sessionId"], recording_session_id.as_str());
    assert_eq!(gap["trackId"], "live-microphone");
    assert_eq!(gap["startMs"], 250);
    assert_eq!(gap["durationMs"], 100);
    assert_eq!(gap["sourcePositionFrames"], 4_000);
    assert_eq!(gap["droppedFrames"], 1_600);
    assert_eq!(gap["cause"], "device_discontinuity");
    assert_eq!(gap["generation"], 7);
    let scan = scan_recordings(&directory).unwrap();
    assert_eq!(scan.complete.len(), 1);
    assert_eq!(scan.complete[0].manifest.session_id, recording_session_id);

    std::fs::remove_dir_all(directory).unwrap();
}
