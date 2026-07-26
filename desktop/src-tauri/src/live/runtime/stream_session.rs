use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    mpsc, Arc,
};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use crate::language::live_evidence::LiveLanguageEvidence;

use super::super::{
    language_router::LanguageAudioAction,
    stream::{self, LiveStreamEngine, StreamLanguageTransition, StreamMessage},
};
use super::inference::LiveInferenceBundle;
use super::language_session::{LanguageFramePlan, ResidentLanguageSession};
use super::session_identity::active_session_matches;
use super::stream_events::{LiveStreamEventSink, TauriLiveStreamEventSink};
use super::warmup::SharedWarmup;
use super::worker::join_worker;

const TARGET_SAMPLE_RATE: u32 = 16_000;
const FINISH_ENQUEUE_TIMEOUT: Duration = Duration::from_millis(250);
const DRAIN_ON_STOP: Duration = Duration::from_millis(6000);

pub(super) struct SessionStream {
    session: Arc<AtomicU64>,
    samples_tx: mpsc::SyncSender<StreamMessage>,
    cancelled: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
    model_warmup: Option<Arc<SharedWarmup<LiveInferenceBundle>>>,
}

pub(super) struct StreamFinisher {
    samples_tx: mpsc::SyncSender<StreamMessage>,
    session: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StreamFinishStatus {
    Completed,
    BackedUp,
    Disconnected,
    NoStream,
    TimedOut,
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct StreamFinishReport {
    pub(super) status: StreamFinishStatus,
    pub(super) language_evidence: Option<LiveLanguageEvidence>,
    pub(super) processing: Option<StreamProcessingSummary>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct StreamProcessingSummary {
    pub(super) audio_samples: usize,
    pub(super) chunks: usize,
    pub(super) language_switches: usize,
    pub(super) decode_ms: u128,
    pub(super) first_text_ms: Option<u128>,
}

impl From<StreamFinishStatus> for StreamFinishReport {
    fn from(status: StreamFinishStatus) -> Self {
        Self {
            status,
            language_evidence: None,
            processing: None,
        }
    }
}

struct StreamWorker {
    engine: LiveStreamEngine,
    language: ResidentLanguageSession,
    buffer: Vec<f32>,
    buffer_start: usize,
    profile: StreamProfile,
    events: Box<dyn LiveStreamEventSink>,
    active_session: Arc<AtomicU64>,
    stream_session: Arc<AtomicU64>,
    active_stream_session: u64,
    engine_session_ready: bool,
    session_failed: bool,
}

#[derive(Default)]
struct StreamProfile {
    session: u64,
    started: Option<Instant>,
    first_text: Option<Duration>,
    decode_elapsed: Duration,
    audio_samples: usize,
    chunks: usize,
    language_switches: usize,
}

impl SessionStream {
    pub(super) fn start(
        inference: LiveInferenceBundle,
        session: u64,
        active_session: Arc<AtomicU64>,
        app: tauri::AppHandle,
        model_warmup: Arc<SharedWarmup<LiveInferenceBundle>>,
    ) -> Self {
        Self::start_with_event_sink(
            inference,
            session,
            active_session,
            Box::new(TauriLiveStreamEventSink::new(app)),
            Some(model_warmup),
        )
    }

    fn start_with_event_sink(
        inference: LiveInferenceBundle,
        session: u64,
        active_session: Arc<AtomicU64>,
        events: Box<dyn LiveStreamEventSink>,
        model_warmup: Option<Arc<SharedWarmup<LiveInferenceBundle>>>,
    ) -> Self {
        let (samples_tx, samples_rx) = mpsc::sync_channel::<StreamMessage>(1);
        let cancelled = Arc::new(AtomicBool::new(false));
        let stream_session = Arc::new(AtomicU64::new(session));
        let worker_cancelled = Arc::clone(&cancelled);
        let worker_session = Arc::clone(&stream_session);
        let worker = std::thread::spawn(move || {
            StreamWorker::new(inference, events, active_session, worker_session)
                .run(samples_rx, worker_cancelled);
        });

        Self {
            session: stream_session,
            samples_tx,
            cancelled,
            worker: Some(worker),
            model_warmup,
        }
    }

    #[cfg(test)]
    pub(super) fn start_with_event_sink_for_test(
        inference: LiveInferenceBundle,
        session: u64,
        active_session: Arc<AtomicU64>,
        events: Box<dyn LiveStreamEventSink>,
    ) -> Self {
        Self::start_with_event_sink(inference, session, active_session, events, None)
    }

    pub(super) fn retarget(&self, session: u64) {
        self.session.store(session, Ordering::SeqCst);
    }

    pub(super) fn sender(&self) -> mpsc::SyncSender<StreamMessage> {
        self.samples_tx.clone()
    }

    pub(super) fn is_running(&self) -> bool {
        self.worker
            .as_ref()
            .is_some_and(|worker| !worker.is_finished())
    }

    pub(super) fn is_finished(&self) -> bool {
        self.worker.as_ref().is_none_or(JoinHandle::is_finished)
    }

    pub(super) fn cancel_reader(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    pub(super) fn finisher(&self) -> StreamFinisher {
        StreamFinisher::new(self.samples_tx.clone(), self.session.load(Ordering::SeqCst))
    }

    pub(super) fn shutdown(mut self, join_reader: bool) -> Result<(), String> {
        self.cancelled.store(true, Ordering::SeqCst);
        drop(self.samples_tx);
        let result = if join_reader {
            if let Some(handle) = self.worker.take() {
                join_worker(handle)
            } else {
                Ok(())
            }
        } else {
            Ok(())
        };
        if let Some(warmup) = self.model_warmup.take() {
            warmup.release_in_use();
        }
        result
    }

    #[cfg(test)]
    pub(super) fn from_worker_for_test(
        session: u64,
        worker: JoinHandle<()>,
        cancelled: bool,
    ) -> Self {
        let (samples_tx, _samples_rx) = mpsc::sync_channel(1);
        Self {
            session: Arc::new(AtomicU64::new(session)),
            samples_tx,
            cancelled: Arc::new(AtomicBool::new(cancelled)),
            worker: Some(worker),
            model_warmup: None,
        }
    }

    #[cfg(test)]
    pub(super) fn from_channel_for_test(
        session: u64,
        samples_tx: mpsc::SyncSender<StreamMessage>,
        worker: JoinHandle<()>,
    ) -> Self {
        Self {
            session: Arc::new(AtomicU64::new(session)),
            samples_tx,
            cancelled: Arc::new(AtomicBool::new(false)),
            worker: Some(worker),
            model_warmup: None,
        }
    }
}

impl StreamFinisher {
    pub(super) fn new(samples_tx: mpsc::SyncSender<StreamMessage>, session: u64) -> Self {
        Self {
            samples_tx,
            session,
        }
    }

    #[cfg(test)]
    pub(super) fn finish_session(&self) -> StreamFinishStatus {
        self.finish_session_report().status
    }

    pub(super) fn finish_session_report(&self) -> StreamFinishReport {
        let (done_tx, done_rx) = mpsc::channel();
        let mut message = StreamMessage::Finish {
            session: self.session,
            done: done_tx,
        };
        let started = Instant::now();

        loop {
            match self.samples_tx.try_send(message) {
                Ok(()) => {
                    return match done_rx.recv_timeout(DRAIN_ON_STOP) {
                        Ok(report) => report,
                        Err(mpsc::RecvTimeoutError::Timeout) => StreamFinishStatus::TimedOut.into(),
                        Err(mpsc::RecvTimeoutError::Disconnected) => {
                            StreamFinishStatus::Disconnected.into()
                        }
                    };
                }
                Err(mpsc::TrySendError::Full(returned)) => {
                    if started.elapsed() >= FINISH_ENQUEUE_TIMEOUT {
                        return StreamFinishStatus::BackedUp.into();
                    }
                    message = returned;
                    std::thread::sleep(Duration::from_millis(10));
                }
                Err(mpsc::TrySendError::Disconnected(_)) => {
                    return StreamFinishStatus::Disconnected.into();
                }
            }
        }
    }
}

impl StreamFinishStatus {
    pub(super) fn should_retire_stream(self) -> bool {
        !matches!(
            self,
            StreamFinishStatus::Completed | StreamFinishStatus::NoStream
        )
    }

    pub(crate) fn should_report(self) -> bool {
        !matches!(
            self,
            StreamFinishStatus::Completed | StreamFinishStatus::NoStream
        )
    }
}

impl StreamWorker {
    fn new(
        inference: LiveInferenceBundle,
        events: Box<dyn LiveStreamEventSink>,
        active_session: Arc<AtomicU64>,
        stream_session: Arc<AtomicU64>,
    ) -> Self {
        let LiveInferenceBundle {
            engine,
            language_pipeline,
            initial_language_degradation,
            language_mode,
            primary_language_bcp47,
        } = inference;
        Self {
            engine,
            language: ResidentLanguageSession::new(
                language_pipeline,
                primary_language_bcp47,
                initial_language_degradation,
                language_mode,
            ),
            buffer: Vec::with_capacity(stream::chunk_samples() * 2),
            buffer_start: 0,
            profile: StreamProfile::default(),
            events,
            active_session,
            stream_session,
            active_stream_session: 0,
            engine_session_ready: false,
            session_failed: false,
        }
    }

    fn run(mut self, samples_rx: mpsc::Receiver<StreamMessage>, cancelled: Arc<AtomicBool>) {
        while !cancelled.load(Ordering::Relaxed) {
            match samples_rx.recv_timeout(Duration::from_millis(100)) {
                Ok(message) => self.process(message),
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => break,
            }
        }
    }

    fn process(&mut self, message: StreamMessage) {
        match message {
            StreamMessage::Samples { session, frame } => {
                if !should_accept_stream_samples(
                    session,
                    self.active_session.load(Ordering::SeqCst),
                    self.stream_session.load(Ordering::SeqCst),
                ) {
                    return;
                }
                if self.active_stream_session != session {
                    if let Err(error) = self.begin_session(session) {
                        crate::diagnostics::log(&format!(
                            "live language session initialization failed code={}",
                            error.code()
                        ));
                        self.fail_active_session();
                        return;
                    }
                }
                if self.session_failed {
                    return;
                }
                if let Err(error) = self.process_frame(session, frame) {
                    crate::diagnostics::log(&format!(
                        "live language routing failed code=runtime_contract message={error}"
                    ));
                    self.fail_active_session();
                }
            }
            StreamMessage::Finish { session, done } => {
                if self.active_stream_session == session {
                    let report = self.finish_active_session(session);
                    let _ = done.send(report);
                } else {
                    let _ = done.send(StreamFinishStatus::NoStream.into());
                }
            }
        }
    }

    fn begin_session(&mut self, session: u64) -> Result<(), crate::stt::error::SttError> {
        self.buffer.clear();
        self.buffer_start = 0;
        self.profile = StreamProfile::new(session);
        self.active_stream_session = session;
        self.engine_session_ready = false;
        self.session_failed = false;
        self.engine
            .reset_for_language(self.language.primary_language_bcp47())?;
        self.engine_session_ready = true;
        if self.language.begin_session() {
            self.mark_language_degraded();
        }
        Ok(())
    }

    fn process_frame(
        &mut self,
        session: u64,
        frame: crate::audio::frame::PreparedFrame,
    ) -> Result<(), String> {
        let LanguageFramePlan {
            actions,
            direct_primary_frame,
            return_to_primary,
            degradation_started,
        } = self.language.push(frame)?;
        self.apply_language_actions(session, actions)?;
        if return_to_primary {
            self.return_to_primary(session)?;
        }
        if let Some(frame) = direct_primary_frame {
            if self.engine.language_bcp47() != self.language.primary_language_bcp47() {
                self.return_to_primary(session)?;
            }
            self.buffer.extend(frame.samples.iter().copied());
            self.drain_buffer(false);
        }
        if degradation_started {
            self.mark_language_degraded();
        }
        Ok(())
    }

    fn finish_active_session(&mut self, session: u64) -> StreamFinishReport {
        if self.session_failed {
            if self.engine_session_ready {
                self.finish_engine(session);
            }
            self.reset_after_session();
            return StreamFinishStatus::Disconnected.into();
        }
        let language = match self.language.finish() {
            Ok(language) => language,
            Err(error) => {
                crate::diagnostics::log(&format!(
                    "live language evidence finalization failed code=invalid_evidence message={error}"
                ));
                self.mark_language_degraded();
                self.finish_engine(session);
                self.reset_after_session();
                return StreamFinishStatus::Disconnected.into();
            }
        };
        if let Err(error) = self.apply_language_actions(session, language.actions) {
            crate::diagnostics::log(&format!(
                "live language tail routing failed code=runtime_contract message={error}"
            ));
            self.mark_language_degraded();
            self.finish_engine(session);
            self.reset_after_session();
            return StreamFinishStatus::Disconnected.into();
        }
        self.finish_engine(session);
        crate::stt::log_stt(&self.profile.summary());
        let processing = Some(self.profile.processing_summary());
        self.reset_after_session();
        StreamFinishReport {
            status: StreamFinishStatus::Completed,
            language_evidence: language.evidence,
            processing,
        }
    }

    fn finish_engine(&mut self, session: u64) {
        self.drain_buffer(true);
        let started = Instant::now();
        let final_text = self.engine.finish();
        self.profile.decode_elapsed += started.elapsed();
        if let Some(text) = final_text {
            self.emit_final(session, &text);
        }
    }

    fn reset_after_session(&mut self) {
        if let Err(error) = self
            .engine
            .reset_for_language(self.language.primary_language_bcp47())
        {
            crate::diagnostics::log(&format!(
                "live stream primary-language reset failed code={}",
                error.code()
            ));
        }
        self.buffer.clear();
        self.buffer_start = 0;
        self.active_stream_session = 0;
        self.engine_session_ready = false;
        self.session_failed = false;
    }

    fn apply_language_actions(
        &mut self,
        session: u64,
        actions: Vec<LanguageAudioAction>,
    ) -> Result<(), String> {
        for action in actions {
            match action {
                LanguageAudioAction::Feed {
                    language_bcp47,
                    audio,
                } => {
                    if self.engine.language_bcp47() != language_bcp47 {
                        return Err("language audio did not match the active ASR stream".into());
                    }
                    self.buffer.extend_from_slice(&audio.samples);
                    self.drain_buffer(false);
                }
                LanguageAudioAction::Switch(transition) => {
                    if self.engine.language_bcp47() != transition.from_language_bcp47 {
                        return Err(
                            "language transition did not match the active ASR stream".into()
                        );
                    }
                    self.drain_buffer(true);
                    let started = Instant::now();
                    let switched = self
                        .engine
                        .transition_language(&transition.to_language_bcp47)
                        .map_err(|error| error.to_string())?;
                    self.profile.decode_elapsed += started.elapsed();
                    if let StreamLanguageTransition::Switched { finalized_text } = switched {
                        self.profile.language_switches += 1;
                        if let Some(text) = finalized_text {
                            self.emit_segment_final(session, &text);
                        }
                    }
                }
            }
        }
        Ok(())
    }

    fn return_to_primary(&mut self, session: u64) -> Result<(), String> {
        let primary = self.language.primary_language_bcp47().to_owned();
        if self.engine.language_bcp47() == primary {
            return Ok(());
        }
        self.drain_buffer(true);
        let started = Instant::now();
        let transition = self
            .engine
            .transition_language(&primary)
            .map_err(|error| error.to_string())?;
        self.profile.decode_elapsed += started.elapsed();
        if let StreamLanguageTransition::Switched { finalized_text } = transition {
            self.profile.language_switches += 1;
            if let Some(text) = finalized_text {
                self.emit_segment_final(session, &text);
            }
        }
        Ok(())
    }

    fn drain_buffer(&mut self, flush_all: bool) {
        while let Some(take) = next_decode_chunk_samples(
            self.buffer.len().saturating_sub(self.buffer_start),
            flush_all,
        ) {
            let available = self.buffer.len() - self.buffer_start;
            debug_assert!(take <= available);
            let end = self.buffer_start + take;
            self.profile.audio_samples += take;
            self.profile.chunks += 1;
            let started = Instant::now();
            let text = self
                .engine
                .accept_samples(&self.buffer[self.buffer_start..end]);
            self.buffer_start = end;
            self.profile.decode_elapsed += started.elapsed();
            if let Some(text) = text {
                self.profile.mark_first_text();
                self.emit_partial(self.profile.session, &text);
            }
        }
        if self.buffer_start == self.buffer.len() {
            self.buffer.clear();
            self.buffer_start = 0;
        } else if self.buffer_start >= stream::chunk_samples() * 4
            && self.buffer_start * 2 >= self.buffer.len()
        {
            self.buffer.drain(..self.buffer_start);
            self.buffer_start = 0;
        }
    }

    fn emit_partial(&self, session: u64, text: &str) {
        if !active_session_matches(self.active_session.load(Ordering::SeqCst), session) {
            return;
        }
        self.events.publish_partial(text);
    }

    fn emit_final(&self, session: u64, text: &str) {
        if !active_session_matches(self.active_session.load(Ordering::SeqCst), session) {
            return;
        }
        self.events.publish_final(text);
        std::thread::sleep(Duration::from_millis(180));
        self.events.return_to_listening();
    }

    fn emit_segment_final(&self, session: u64, text: &str) {
        if !active_session_matches(self.active_session.load(Ordering::SeqCst), session) {
            return;
        }
        self.events.publish_final(text);
        self.events.return_to_listening();
    }

    fn mark_language_degraded(&self) {
        self.events.mark_language_routing_degraded();
    }

    fn fail_active_session(&mut self) {
        if self.session_failed {
            return;
        }
        self.session_failed = true;
        self.events.mark_transcription_unavailable();
    }
}

fn next_decode_chunk_samples(available: usize, flush_all: bool) -> Option<usize> {
    let chunk = stream::chunk_samples();
    if available >= chunk {
        Some(chunk)
    } else if flush_all && available > 0 {
        Some(available)
    } else {
        None
    }
}

impl StreamProfile {
    fn new(session: u64) -> Self {
        Self {
            session,
            started: Some(Instant::now()),
            ..Default::default()
        }
    }

    fn mark_first_text(&mut self) {
        if self.first_text.is_none() {
            self.first_text = self.started.map(|started| started.elapsed());
        }
    }

    fn summary(&self) -> String {
        let audio_ms = self.audio_samples as u64 * 1000 / TARGET_SAMPLE_RATE as u64;
        let first_text_ms = self
            .first_text
            .map(|duration| duration.as_millis().to_string())
            .unwrap_or_else(|| "none".into());
        format!(
            "live nemotron profile session={} chunks={} language_switches={} audio_ms={} decode_ms={} first_text_ms={}",
            self.session,
            self.chunks,
            self.language_switches,
            audio_ms,
            self.decode_elapsed.as_millis(),
            first_text_ms
        )
    }

    fn processing_summary(&self) -> StreamProcessingSummary {
        StreamProcessingSummary {
            audio_samples: self.audio_samples,
            chunks: self.chunks,
            language_switches: self.language_switches,
            decode_ms: self.decode_elapsed.as_millis(),
            first_text_ms: self.first_text.map(|duration| duration.as_millis()),
        }
    }
}

pub(super) fn should_accept_stream_samples(
    message_session: u64,
    active_session: u64,
    stream_session: u64,
) -> bool {
    active_session_matches(active_session, message_session) && message_session == stream_session
}

#[cfg(test)]
mod buffer_planning_tests {
    use super::*;

    #[test]
    fn sub_chunk_correction_waits_during_capture_and_flushes_exactly_on_stop() {
        let short_correction = stream::chunk_samples() - 1;
        assert_eq!(next_decode_chunk_samples(short_correction, false), None);
        assert_eq!(
            next_decode_chunk_samples(short_correction, true),
            Some(short_correction)
        );
        assert_eq!(next_decode_chunk_samples(0, true), None);
    }

    #[test]
    fn full_chunk_decodes_without_waiting_for_stop() {
        let chunk = stream::chunk_samples();
        assert_eq!(next_decode_chunk_samples(chunk, false), Some(chunk));
        assert_eq!(next_decode_chunk_samples(chunk + 1, false), Some(chunk));
    }
}
