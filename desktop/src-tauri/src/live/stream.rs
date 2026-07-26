use std::path::Path;
use std::sync::mpsc;
use std::time::{Duration, Instant};

use sherpa_onnx::{OnlineRecognizer, OnlineRecognizerConfig, OnlineStream};

use crate::audio::frame::PreparedFrame;
use crate::stt::error::SttError;

const SAMPLE_RATE: i32 = 16_000;
const TAIL_SILENCE: Duration = Duration::from_millis(1500);

pub(crate) enum StreamMessage {
    Samples {
        session: u64,
        frame: PreparedFrame,
    },
    Finish {
        session: u64,
        done: mpsc::Sender<super::runtime::StreamFinishReport>,
    },
}

impl StreamMessage {
    pub(crate) fn from_prepared(session: u64, frame: PreparedFrame) -> Self {
        Self::Samples { session, frame }
    }

    #[cfg(test)]
    fn session(&self) -> u64 {
        match self {
            Self::Samples { session, .. } | Self::Finish { session, .. } => *session,
        }
    }

    #[cfg(test)]
    fn samples(&self) -> &[f32] {
        match self {
            Self::Samples { frame, .. } => &frame.samples,
            Self::Finish { .. } => &[],
        }
    }

    #[cfg(test)]
    fn start_ms(&self) -> Option<u64> {
        match self {
            Self::Samples { frame, .. } => Some(frame.metadata.start_ms),
            Self::Finish { .. } => None,
        }
    }
}

pub struct LiveStreamEngine {
    recognizer: OnlineRecognizer,
    stream: OnlineStream,
    language_bcp47: String,
    _model_guard: crate::stt::nemotron::ModelLoadGuard,
    last_text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum StreamLanguageTransition {
    Unchanged,
    Switched { finalized_text: Option<String> },
}

impl LiveStreamEngine {
    pub fn new() -> Result<Self, SttError> {
        Self::new_for_language("en-US")
    }

    pub(crate) fn new_for_language(language_bcp47: &str) -> Result<Self, SttError> {
        Self::new_for_language_with_threads(language_bcp47, crate::stt::nemotron::INFERENCE_THREADS)
    }

    fn new_for_language_with_threads(
        language_bcp47: &str,
        inference_threads: i32,
    ) -> Result<Self, SttError> {
        if !crate::language::live_catalog::supports_local_asr_language(language_bcp47) {
            return Err(SttError::BadLang);
        }
        assert!(
            (1..=crate::stt::nemotron::INFERENCE_THREADS).contains(&inference_threads),
            "local ASR thread budget must stay within the supported range"
        );
        let language_bcp47 = language_bcp47.to_owned();
        let mut native_load_elapsed = None;
        let loaded = crate::stt::nemotron::load_local_fallback(|paths| {
            let started = Instant::now();
            let recognizer = OnlineRecognizer::create(&recognizer_config(paths, inference_threads))
                .ok_or(SttError::SidecarUnreachable)?;
            native_load_elapsed = Some(started.elapsed());
            Ok(recognizer)
        })?;
        let (recognizer, model_guard) = loaded.into_parts();
        crate::stt::log_stt_timed(
            "nemotron.load",
            native_load_elapsed.unwrap_or_default(),
            crate::stt::nemotron::MODEL_LABEL,
        );
        let stream = create_stream(&recognizer, &language_bcp47);
        Ok(Self {
            recognizer,
            stream,
            language_bcp47,
            _model_guard: model_guard,
            last_text: String::new(),
        })
    }

    #[cfg(test)]
    pub(crate) fn new_for_language_with_test_thread_budget(
        language_bcp47: &str,
        inference_threads: i32,
    ) -> Result<Self, SttError> {
        Self::new_for_language_with_threads(language_bcp47, inference_threads)
    }

    pub fn reset(&mut self) {
        self.stream = create_stream(&self.recognizer, &self.language_bcp47);
        self.last_text.clear();
    }

    pub(crate) fn language_bcp47(&self) -> &str {
        &self.language_bcp47
    }

    pub(crate) fn reset_for_language(&mut self, language_bcp47: &str) -> Result<(), SttError> {
        if !crate::language::live_catalog::supports_local_asr_language(language_bcp47) {
            return Err(SttError::BadLang);
        }
        self.language_bcp47.clear();
        self.language_bcp47.push_str(language_bcp47);
        self.stream = create_stream(&self.recognizer, &self.language_bcp47);
        self.last_text.clear();
        Ok(())
    }

    /// Closes the current language segment before opening a fresh stream.
    ///
    /// The caller owns source-time buffering and must only feed audio on the
    /// appropriate side of its accepted language boundary to each stream.
    pub(crate) fn transition_language(
        &mut self,
        language_bcp47: &str,
    ) -> Result<StreamLanguageTransition, SttError> {
        if !crate::language::live_catalog::supports_local_asr_language(language_bcp47) {
            return Err(SttError::BadLang);
        }
        if language_bcp47 == self.language_bcp47 {
            return Ok(StreamLanguageTransition::Unchanged);
        }

        let finalized_text = self.finish();
        self.language_bcp47.clear();
        self.language_bcp47.push_str(language_bcp47);
        self.stream = create_stream(&self.recognizer, &self.language_bcp47);
        self.last_text.clear();
        Ok(StreamLanguageTransition::Switched { finalized_text })
    }

    pub fn accept_samples(&mut self, samples: &[f32]) -> Option<String> {
        if samples.is_empty() {
            return None;
        }
        self.stream.accept_waveform(SAMPLE_RATE, samples);
        self.decode_ready();
        self.changed_text()
    }

    pub fn finish(&mut self) -> Option<String> {
        let tail = vec![0.0; silence_samples(TAIL_SILENCE)];
        self.stream.accept_waveform(SAMPLE_RATE, &tail);
        self.stream.input_finished();
        self.decode_ready();
        self.changed_text()
            .or_else(|| (!self.last_text.is_empty()).then(|| self.last_text.clone()))
    }

    fn decode_ready(&self) {
        while self.recognizer.is_ready(&self.stream) {
            self.recognizer.decode(&self.stream);
        }
    }

    fn changed_text(&mut self) -> Option<String> {
        let text = self
            .recognizer
            .get_result(&self.stream)?
            .text
            .trim()
            .to_string();
        if text.is_empty() || text == self.last_text {
            return None;
        }
        self.last_text = text.clone();
        Some(text)
    }
}

fn create_stream(recognizer: &OnlineRecognizer, language_bcp47: &str) -> OnlineStream {
    let stream = recognizer.create_stream();
    stream.set_option("language", language_bcp47);
    stream
}

pub fn chunk_samples() -> usize {
    (SAMPLE_RATE as u64 * crate::stt::nemotron::CHUNK_MS / 1000) as usize
}

pub fn silence_samples(duration: Duration) -> usize {
    (SAMPLE_RATE as u128 * duration.as_millis() / 1000) as usize
}

fn recognizer_config(
    paths: &crate::stt::nemotron::NemotronPaths,
    inference_threads: i32,
) -> OnlineRecognizerConfig {
    let mut config = OnlineRecognizerConfig::default();
    config.model_config.transducer.encoder = Some(path_string(&paths.encoder));
    config.model_config.transducer.decoder = Some(path_string(&paths.decoder));
    config.model_config.transducer.joiner = Some(path_string(&paths.joiner));
    config.model_config.tokens = Some(path_string(&paths.tokens));
    config.model_config.num_threads = inference_threads;
    config.model_config.provider = Some("cpu".into());
    config.model_config.model_type = Some("nemo_transducer".into());
    config.decoding_method = Some("greedy_search".into());
    config
}

fn path_string(path: &Path) -> String {
    path.to_string_lossy().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::audio::frame::{AudioFrame, PreparedFrame};
    use crate::audio::session::{SessionId, TrackId};
    use std::sync::Arc;

    #[test]
    fn stream_chunk_matches_pinned_nemotron_export() {
        assert_eq!(chunk_samples(), 17_920);
    }

    #[test]
    fn tail_silence_is_bounded() {
        assert_eq!(silence_samples(Duration::from_millis(1500)), 24_000);
    }

    #[test]
    fn config_uses_nemotron_transducer_on_cpu() {
        let paths = crate::stt::nemotron::NemotronPaths {
            encoder: "C:/models/encoder.int8.onnx".into(),
            decoder: "C:/models/decoder.int8.onnx".into(),
            joiner: "C:/models/joiner.int8.onnx".into(),
            tokens: "C:/models/tokens.txt".into(),
        };
        let config = recognizer_config(&paths, crate::stt::nemotron::INFERENCE_THREADS);
        assert_eq!(
            config.model_config.model_type.as_deref(),
            Some("nemo_transducer")
        );
        assert_eq!(config.model_config.provider.as_deref(), Some("cpu"));
        assert_eq!(
            config.model_config.num_threads,
            crate::stt::nemotron::INFERENCE_THREADS
        );
        assert_eq!(config.decoding_method.as_deref(), Some("greedy_search"));
    }

    #[test]
    fn config_accepts_a_bounded_resource_profile_thread_budget() {
        let paths = crate::stt::nemotron::NemotronPaths {
            encoder: "C:/models/encoder.int8.onnx".into(),
            decoder: "C:/models/decoder.int8.onnx".into(),
            joiner: "C:/models/joiner.int8.onnx".into(),
            tokens: "C:/models/tokens.txt".into(),
        };
        let config = recognizer_config(&paths, 1);
        assert_eq!(config.model_config.num_threads, 1);
    }

    #[test]
    fn unsupported_language_fails_before_model_loading() {
        assert!(matches!(
            LiveStreamEngine::new_for_language("el-GR"),
            Err(SttError::BadLang)
        ));
    }

    #[test]
    fn installed_model_validates_transitions_and_reapplies_language_after_reset() {
        if !crate::stt::nemotron::is_installed() {
            return;
        }
        let mut engine = LiveStreamEngine::new_for_language("en-US").unwrap();

        assert_eq!(engine.transition_language("el-GR"), Err(SttError::BadLang));
        assert_eq!(engine.stream.get_option("language"), "en-US");
        assert_eq!(
            engine.transition_language("en-US").unwrap(),
            StreamLanguageTransition::Unchanged
        );
        assert_eq!(
            engine.transition_language("fr-FR").unwrap(),
            StreamLanguageTransition::Switched {
                finalized_text: None
            }
        );
        assert_eq!(engine.stream.get_option("language"), "fr-FR");

        engine.reset();

        assert_eq!(engine.stream.get_option("language"), "fr-FR");
    }

    #[test]
    fn prepared_frames_become_stream_messages_without_changing_samples() {
        let frame = PreparedFrame {
            metadata: AudioFrame {
                session_id: SessionId::new("stream-test").unwrap(),
                track_id: TrackId::new("microphone").unwrap(),
                sequence: 4,
                sample_rate_hz: 16_000,
                channels: 1,
                start_ms: 10,
                duration_ms: 2,
                sample_count: 2,
            },
            samples: Arc::from([0.25_f32, -0.25]),
        };

        let message = StreamMessage::from_prepared(7, frame);

        assert_eq!(message.session(), 7);
        assert_eq!(message.samples(), &[0.25, -0.25]);
        assert_eq!(message.start_ms(), Some(10));
    }
}
