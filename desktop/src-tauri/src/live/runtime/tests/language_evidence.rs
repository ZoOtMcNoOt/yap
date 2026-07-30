use super::*;
use crate::{
    audio::{
        frame::TrackConfigurationRevision,
        timeline::{ClockMappingRevision, RecordingRevisionTransition},
    },
    language::{
        live_diarization::{LanguageSpan, LanguageSpanDisposition},
        live_evidence::{LiveLanguageEvidence, LiveLanguageMode, LiveLanguageStatus},
    },
};

#[test]
fn stop_persists_worker_language_evidence_before_recording_finalization() {
    let runtime = LiveRuntime::new();
    let directory = std::env::temp_dir().join(format!(
        "yap-runtime-language-evidence-{}",
        std::process::id()
    ));
    std::fs::remove_dir_all(&directory).ok();
    let session_id = SessionId::new("runtime-language-evidence").unwrap();
    let track_id = TrackId::new("live-microphone").unwrap();
    let (recording_sink, recording_receiver) = bounded_sink(SinkKind::Recording, 8);
    let recording = RecordingSinkHandle::spawn(
        directory.clone(),
        session_id.clone(),
        recording_sink.clone(),
        recording_receiver,
    );
    recording_sink
        .try_send(RecordingInput::RevisionTransition(
            RecordingRevisionTransition::new(
                TrackConfigurationRevision::new(track_id.clone(), 1, 0, 16_000).unwrap(),
                ClockMappingRevision::new(track_id.clone(), 1, 0, 0).unwrap(),
            )
            .unwrap(),
        ))
        .unwrap();
    recording_sink
        .try_send(RecordingInput::PreparedFrame(PreparedFrame {
            metadata: AudioFrame {
                session_id: session_id.clone(),
                track_id,
                sequence: 0,
                sample_rate_hz: 16_000,
                channels: 1,
                start_ms: 0,
                duration_ms: 1,
                sample_count: 1,
            },
            samples: Arc::from([0.25]),
        }))
        .unwrap();

    let evidence = LiveLanguageEvidence::try_new(
        1,
        "en-US".into(),
        LiveLanguageMode::Automatic,
        LiveLanguageStatus::Complete,
        None,
        Some("test-lid@sha256:fixture".into()),
        vec![LanguageSpan {
            start_sample: 0,
            end_sample: 1,
            language_bcp47: "en-US".into(),
            decision_revision: 1,
            disposition: LanguageSpanDisposition::ConfirmedPrimary,
            component_revision: None,
            decision_evidence: None,
        }],
    )
    .unwrap();
    let (samples_tx, samples_rx) = mpsc::sync_channel(1);
    let worker = std::thread::spawn(move || match samples_rx.recv().unwrap() {
        StreamMessage::Finish { session, done } => {
            assert_eq!(session, 42);
            done.send(StreamFinishReport {
                status: StreamFinishStatus::Completed,
                language_evidence: Some(evidence),
                processing: None,
            })
            .unwrap();
        }
        StreamMessage::PreparedFrames { .. } => panic!("expected a finish message"),
    });

    {
        let mut inner = runtime.inner.lock().unwrap();
        inner.set_recording_for_test(recording);
        inner.set_stream_for_test(SessionStream::from_channel_for_test(42, samples_tx, worker));
    }
    runtime.active_session.store(42, Ordering::SeqCst);

    assert_eq!(runtime.stop_stream(), StreamFinishStatus::Completed);
    let finalized = runtime.finalize_recording().unwrap().unwrap();
    assert_eq!(finalized.status, CaptureStatus::Complete);
    let sidecar: serde_json::Value = serde_json::from_slice(
        &std::fs::read(directory.join(format!("live-{session_id}.capture.json"))).unwrap(),
    )
    .unwrap();
    assert_eq!(sidecar["languageEvidence"]["sourceEndSample"], 1);
    assert_eq!(
        sidecar["languageEvidence"]["detectorComponentRevision"],
        "test-lid@sha256:fixture"
    );

    runtime.inner.lock().unwrap().retire_stream();
    std::fs::remove_dir_all(directory).ok();
}
