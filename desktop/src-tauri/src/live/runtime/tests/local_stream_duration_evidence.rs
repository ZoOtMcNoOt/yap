use super::*;
use crate::{
    audio::{
        frame::{AudioFrame, PreparedFrame},
        session::{SessionId, TrackId},
    },
    language::live_evidence::LiveLanguageMode,
    live::{runtime::stream_events::LiveStreamEventSink, stream::LiveStreamEngine},
};
use std::{
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

mod evidence;
mod manifest;
mod pcm_wave;

use evidence::{
    persist_private_evidence, required_checked_head, LocalStreamDurationCaseEvidence,
    LocalStreamDurationEvidence,
};
use manifest::{
    direct_case_file, load_local_duration_suite, load_track_manifest, repository_root,
    LocalDurationSuiteCase,
};
use pcm_wave::Pcm16WaveReader;

const SAMPLE_RATE_HZ: u32 = 16_000;
const PACED_FRAME_SAMPLES: usize = 160;
const MAXIMUM_ADAPTER_DRAIN: Duration = Duration::from_millis(6_000);

#[derive(Default)]
struct DurationEventCollector {
    state: Mutex<DurationEventState>,
}

#[derive(Default)]
struct DurationEventState {
    session: u64,
    started: Option<Instant>,
    first_text_ms: Option<u128>,
    partial_updates: u64,
    final_updates: u64,
    language_degraded: bool,
    transcription_unavailable: bool,
}

#[derive(Debug, Clone, Copy)]
struct DurationEventSnapshot {
    first_text_ms: Option<u128>,
    partial_updates: u64,
    final_updates: u64,
    language_degraded: bool,
    transcription_unavailable: bool,
}

/// Runs both exact local-live duration ladders through the production-sized
/// capture-to-ASR queue, the single live stream worker, and finalization. Raw
/// audio and transcript text remain outside Git and never enter the evidence.
#[test]
#[ignore = "requires a private hash-bound local-duration suite, pinned Nemotron artifacts, and an external evidence destination"]
fn local_stream_duration_ladders_preserve_audio_and_finalize() {
    let repository = repository_root();
    let checked_head = required_checked_head(&repository);
    let suite = load_local_duration_suite();
    let model_lock = repository.join("desktop/model-artifacts.lock.json");
    let model_artifact_lock_sha256 =
        crate::stt::model::sha256_file(&model_lock).expect("model artifact lock must be readable");
    let logical_processor_budget = std::thread::available_parallelism()
        .expect("logical processor budget must be available")
        .get();

    let engine = LiveStreamEngine::new_for_language_with_test_thread_budget(
        "en-US",
        crate::stt::nemotron::INFERENCE_THREADS,
    )
    .expect("the pinned local Nemotron model must load");
    let inference = LiveInferenceBundle {
        engine,
        language_pipeline: None,
        initial_language_degradation: None,
        language_mode: LiveLanguageMode::FixedPrimary,
        primary_language_bcp47: "en-US".into(),
    };
    let active_session = Arc::new(AtomicU64::new(1));
    let events = Arc::new(DurationEventCollector::default());
    let mut stream = SessionStream::start_with_event_sink_for_test(
        inference,
        1,
        Arc::clone(&active_session),
        Box::new(Arc::clone(&events)),
    );

    let mut cases = Vec::with_capacity(suite.definition.cases.len());
    for (index, definition) in suite.definition.cases.iter().enumerate() {
        let session = u64::try_from(index + 1).expect("duration case count must fit in u64");
        active_session.store(session, Ordering::SeqCst);
        stream.retarget(session);
        let manifest = load_track_manifest(&suite.root, definition);
        let audio_path = direct_case_file(&suite.root, &definition.case_id, "audio.wav");
        let wave = Pcm16WaveReader::open(&audio_path, &manifest.audio);
        cases.push(run_duration_case(
            &mut stream,
            &events,
            session,
            definition,
            wave,
        ));
    }
    stream
        .shutdown(true)
        .expect("local duration worker must stop cleanly");

    let all_cases_passed = cases.iter().all(|case| case.passed);
    let qualification_profile = suite.definition.qualification_profile.clone();
    let evidence = LocalStreamDurationEvidence {
        schema_version: 2,
        checked_head,
        plan_sha256: suite.plan_sha256,
        suite_sha256: suite.suite_sha256,
        qualification_profile,
        model_artifact_lock_sha256,
        model_id: crate::stt::nemotron::MODEL_ID,
        primary_language_bcp47: "en-US",
        inference_threads: crate::stt::nemotron::INFERENCE_THREADS,
        logical_processor_budget,
        sample_rate_hz: SAMPLE_RATE_HZ,
        paced_frame_samples: PACED_FRAME_SAMPLES,
        measurement_boundary: "desktop-prepared-audio-frame-to-final",
        cases,
        all_cases_passed,
    };
    persist_private_evidence(&evidence);
    eprintln!(
        "local_stream_duration_summary={{\"qualificationProfile\":\"{}\",\"caseCount\":{},\"allCasesPassed\":{}}}",
        evidence.qualification_profile,
        evidence.cases.len(),
        evidence.all_cases_passed
    );
    assert!(all_cases_passed, "one or more local duration cases failed");
}

fn run_duration_case(
    stream: &mut SessionStream,
    events: &Arc<DurationEventCollector>,
    session: u64,
    definition: &LocalDurationSuiteCase,
    mut wave: Pcm16WaveReader,
) -> LocalStreamDurationCaseEvidence {
    let mut adapter = PendingAsrAdapter::new().start(stream.sender(), session);
    let frames = adapter.sink();
    let source_started = Instant::now();
    events.begin(session, source_started);
    let mut source_samples = 0_u64;
    let mut sequence = 0_u64;
    while let Some(samples) = wave
        .read_samples(PACED_FRAME_SAMPLES)
        .expect("duration track PCM must remain readable")
    {
        source_samples += samples.len() as u64;
        sleep_until(source_started + source_duration(source_samples));
        let start_sample = source_samples - samples.len() as u64;
        let _ = frames.try_send(duration_frame(session, sequence, start_sample, samples));
        sequence += 1;
    }
    wave.finish();
    let source_wall_ms = source_started.elapsed().as_millis();
    let audio_ms = definition.duration_samples * 1_000 / u64::from(SAMPLE_RATE_HZ);

    let drain_started = Instant::now();
    let drain = adapter
        .drain_after_capture(MAXIMUM_ADAPTER_DRAIN)
        .expect("local duration adapter must report its drain outcome");
    let adapter_drain_ms = drain_started.elapsed().as_millis();
    assert_eq!(drain, AdapterDrainStatus::Drained);

    let finalization_started = Instant::now();
    let report = stream.finisher().finish_session_report();
    let finalization_ms = finalization_started.elapsed().as_millis();
    let processing = report
        .processing
        .expect("completed local duration stream must report processing totals");
    let observed = events.snapshot(session);
    let outcome = frames.outcome();
    let expected_frames = definition
        .duration_samples
        .div_ceil(PACED_FRAME_SAMPLES as u64);
    let text_seen = observed.partial_updates > 0 || observed.final_updates > 0;
    let passed = source_samples == definition.duration_samples
        && outcome.accepted_frames == expected_frames
        && outcome.dropped_frames == 0
        && processing.audio_samples as u64 == definition.duration_samples
        && report.status == StreamFinishStatus::Completed
        && !observed.language_degraded
        && !observed.transcription_unavailable
        && (!definition.expect_text || text_seen);

    LocalStreamDurationCaseEvidence {
        ladder_id: definition.ladder_id.clone(),
        case_id: definition.case_id.clone(),
        duration_samples: definition.duration_samples,
        duration_ms: audio_ms,
        expected_frames,
        accepted_frames: outcome.accepted_frames,
        dropped_frames: outcome.dropped_frames,
        queue_high_water_mark: frames.high_water_mark(),
        source_wall_ms,
        source_overrun_ms: source_wall_ms.saturating_sub(u128::from(audio_ms)),
        adapter_drain_ms,
        finalization_ms,
        processed_audio_samples: processing.audio_samples,
        decode_chunks: processing.chunks,
        decode_ms: processing.decode_ms,
        worker_first_text_ms: processing.first_text_ms,
        capture_to_first_text_ms: observed.first_text_ms,
        partial_updates: observed.partial_updates,
        final_updates: observed.final_updates,
        expected_text: definition.expect_text,
        text_seen,
        language_degraded: observed.language_degraded,
        transcription_unavailable: observed.transcription_unavailable,
        stream_status: stream_status_name(report.status),
        passed,
    }
}

impl DurationEventCollector {
    fn begin(&self, session: u64, started: Instant) {
        *self.state.lock().expect("duration event state poisoned") = DurationEventState {
            session,
            started: Some(started),
            ..Default::default()
        };
    }

    fn observe_text(&self, final_update: bool, text: &str) {
        if text.trim().is_empty() {
            return;
        }
        let mut state = self.state.lock().expect("duration event state poisoned");
        if state.first_text_ms.is_none() {
            state.first_text_ms = state.started.map(|started| started.elapsed().as_millis());
        }
        if final_update {
            state.final_updates += 1;
        } else {
            state.partial_updates += 1;
        }
    }

    fn snapshot(&self, session: u64) -> DurationEventSnapshot {
        let state = self.state.lock().expect("duration event state poisoned");
        assert_eq!(state.session, session);
        DurationEventSnapshot {
            first_text_ms: state.first_text_ms,
            partial_updates: state.partial_updates,
            final_updates: state.final_updates,
            language_degraded: state.language_degraded,
            transcription_unavailable: state.transcription_unavailable,
        }
    }
}

impl LiveStreamEventSink for Arc<DurationEventCollector> {
    fn publish_partial(&self, text: &str) {
        self.observe_text(false, text);
    }

    fn publish_final(&self, text: &str) {
        self.observe_text(true, text);
    }

    fn return_to_listening(&self) {}

    fn mark_language_routing_degraded(&self) {
        self.state
            .lock()
            .expect("duration event state poisoned")
            .language_degraded = true;
    }

    fn mark_transcription_unavailable(&self) {
        self.state
            .lock()
            .expect("duration event state poisoned")
            .transcription_unavailable = true;
    }
}

fn duration_frame(
    session: u64,
    sequence: u64,
    start_sample: u64,
    samples: Vec<f32>,
) -> PreparedFrame {
    PreparedFrame {
        metadata: AudioFrame {
            session_id: SessionId::new(format!("local-duration-{session}")).unwrap(),
            track_id: TrackId::new("microphone").unwrap(),
            sequence,
            sample_rate_hz: SAMPLE_RATE_HZ,
            channels: 1,
            start_ms: start_sample * 1_000 / u64::from(SAMPLE_RATE_HZ),
            duration_ms: u32::try_from(samples.len() as u64 * 1_000 / u64::from(SAMPLE_RATE_HZ))
                .unwrap(),
            sample_count: samples.len(),
        },
        samples: Arc::from(samples),
    }
}

fn source_duration(samples: u64) -> Duration {
    Duration::from_nanos(samples.saturating_mul(1_000_000_000) / u64::from(SAMPLE_RATE_HZ))
}

fn sleep_until(deadline: Instant) {
    if let Some(remaining) = deadline.checked_duration_since(Instant::now()) {
        thread::sleep(remaining);
    }
}

fn stream_status_name(status: StreamFinishStatus) -> &'static str {
    match status {
        StreamFinishStatus::Completed => "completed",
        StreamFinishStatus::BackedUp => "backedUp",
        StreamFinishStatus::Disconnected => "disconnected",
        StreamFinishStatus::NoStream => "noStream",
        StreamFinishStatus::TimedOut => "timedOut",
    }
}
