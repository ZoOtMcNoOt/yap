use sherpa_onnx::{SileroVadModelConfig, VadModelConfig, VoiceActivityDetector};

use crate::stt::{
    error::SttError,
    nemotron::ModelLoadGuard,
    silero_vad::{root_dir, ARTIFACTS},
};

const SAMPLE_RATE_HZ: i32 = 16_000;
const WINDOW_SAMPLES: usize = 512;
const MAX_SPEECH_RATIO_SAMPLES: usize = SAMPLE_RATE_HZ as usize * 20;
const MAX_INTERVALS: usize = 4_096;
// Sherpa's max_speech_duration raises its decision threshold after the limit;
// it does not hard-cut a high-confidence continuous segment. Keep enough
// result-buffer headroom for natural uninterrupted speech so the native ring
// does not repeatedly grow and copy during imported-file preprocessing.
const RESULT_BUFFER_SECONDS: f32 = 120.0;

pub(crate) struct SileroVadDetector {
    detector: VoiceActivityDetector,
    _guard: ModelLoadGuard,
    pending: Vec<f32>,
    accepted_samples: u64,
    intervals: Vec<(u64, u64)>,
}

#[derive(Debug)]
pub(crate) enum SileroVadRuntimeError {
    Cancelled(String),
    Engine(&'static str),
}

impl std::fmt::Display for SileroVadRuntimeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Cancelled(message) => write!(formatter, "cancelled: {message}"),
            Self::Engine(code) => write!(formatter, "engine error: {code}"),
        }
    }
}

impl std::error::Error for SileroVadRuntimeError {}

impl SileroVadDetector {
    pub(crate) fn load() -> Result<Self, SttError> {
        Self::load_at(&root_dir())
    }

    pub(crate) fn load_at(root: &std::path::Path) -> Result<Self, SttError> {
        super::resolve_model_at(&root.join(ARTIFACTS[0].file))?;
        let guard = ModelLoadGuard::open(root, ARTIFACTS)?;
        let model = guard
            .path(0)
            .to_str()
            .ok_or(SttError::ModelCorrupt)?
            .to_owned();
        let config = VadModelConfig {
            silero_vad: SileroVadModelConfig {
                model: Some(model),
                threshold: 0.5,
                min_silence_duration: 0.25,
                min_speech_duration: 0.25,
                window_size: WINDOW_SAMPLES as i32,
                max_speech_duration: 5.0,
            },
            sample_rate: SAMPLE_RATE_HZ,
            num_threads: 1,
            provider: Some("cpu".into()),
            debug: false,
            ..Default::default()
        };
        let detector = VoiceActivityDetector::create(&config, RESULT_BUFFER_SECONDS)
            .ok_or(SttError::ModelCorrupt)?;
        guard.revalidate_after_native_load()?;
        Ok(Self {
            detector,
            _guard: guard,
            pending: Vec::with_capacity(WINDOW_SAMPLES),
            accepted_samples: 0,
            intervals: Vec::new(),
        })
    }

    pub(crate) fn accept_pcm16_with_cancellation(
        &mut self,
        pcm: &[u8],
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), SileroVadRuntimeError> {
        if !pcm.len().is_multiple_of(2) {
            return Err(SileroVadRuntimeError::Engine("invalid_pcm16"));
        }
        self.accepted_samples = self
            .accepted_samples
            .checked_add((pcm.len() / 2) as u64)
            .ok_or(SileroVadRuntimeError::Engine("sample_count_overflow"))?;
        for sample in pcm.chunks_exact(2) {
            self.pending
                .push(f32::from(i16::from_le_bytes([sample[0], sample[1]])) / f32::from(i16::MAX));
            if self.pending.len() == WINDOW_SAMPLES {
                ensure_active().map_err(SileroVadRuntimeError::Cancelled)?;
                self.detector.accept_waveform(&self.pending);
                ensure_active().map_err(SileroVadRuntimeError::Cancelled)?;
                self.pending.clear();
                self.drain(ensure_active)?;
            }
        }
        Ok(())
    }

    /// Measures speech coverage for one bounded local-LID window and resets
    /// all detector state before returning.
    pub(crate) fn speech_ratio(&mut self, samples: &[f32]) -> Result<f32, SileroVadRuntimeError> {
        validate_speech_window(samples)?;
        self.reset_window_state();
        let result = (|| {
            self.accepted_samples = samples.len() as u64;
            for chunk in samples.chunks(WINDOW_SAMPLES) {
                self.pending.extend_from_slice(chunk);
                if self.pending.len() == WINDOW_SAMPLES {
                    self.detector.accept_waveform(&self.pending);
                    self.pending.clear();
                    self.drain(&mut || Ok(()))?;
                }
            }
            let intervals = self.finish_with_cancellation(&mut || Ok(()))?;
            let speech_samples = intervals.iter().try_fold(0_u64, |total, (start, end)| {
                total
                    .checked_add(end - start)
                    .ok_or(SileroVadRuntimeError::Engine("sample_count_overflow"))
            })?;
            Ok(speech_samples as f32 / samples.len() as f32)
        })();
        self.reset_window_state();
        result
    }

    pub(crate) fn finish_with_cancellation(
        &mut self,
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<Vec<(u64, u64)>, SileroVadRuntimeError> {
        ensure_active().map_err(SileroVadRuntimeError::Cancelled)?;
        if !self.pending.is_empty() {
            self.pending.resize(WINDOW_SAMPLES, 0.0);
            ensure_active().map_err(SileroVadRuntimeError::Cancelled)?;
            self.detector.accept_waveform(&self.pending);
            ensure_active().map_err(SileroVadRuntimeError::Cancelled)?;
            self.pending.clear();
            self.drain(ensure_active)?;
        }
        ensure_active().map_err(SileroVadRuntimeError::Cancelled)?;
        self.detector.flush();
        ensure_active().map_err(SileroVadRuntimeError::Cancelled)?;
        self.drain(ensure_active)?;
        for (_, end) in &mut self.intervals {
            *end = (*end).min(self.accepted_samples);
        }
        if self
            .intervals
            .iter()
            .any(|(start, end)| start >= end || *end > self.accepted_samples)
        {
            return Err(SileroVadRuntimeError::Engine("invalid_interval"));
        }
        ensure_active().map_err(SileroVadRuntimeError::Cancelled)?;
        Ok(std::mem::take(&mut self.intervals))
    }

    fn drain(
        &mut self,
        ensure_active: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<(), SileroVadRuntimeError> {
        loop {
            ensure_active().map_err(SileroVadRuntimeError::Cancelled)?;
            let Some(segment) = self.detector.front() else {
                break;
            };
            let start = u64::try_from(segment.start())
                .map_err(|_| SileroVadRuntimeError::Engine("invalid_interval"))?;
            let length = u64::try_from(segment.n())
                .map_err(|_| SileroVadRuntimeError::Engine("invalid_interval"))?;
            let end = start
                .checked_add(length)
                .ok_or(SileroVadRuntimeError::Engine("invalid_interval"))?;
            drop(segment);
            self.detector.pop();
            ensure_active().map_err(SileroVadRuntimeError::Cancelled)?;
            if self.intervals.len() >= MAX_INTERVALS {
                return Err(SileroVadRuntimeError::Engine("segment_limit_exceeded"));
            }
            self.intervals.push((start, end));
        }
        Ok(())
    }

    fn reset_window_state(&mut self) {
        self.detector.reset();
        self.pending.clear();
        self.accepted_samples = 0;
        self.intervals.clear();
    }
}

fn validate_speech_window(samples: &[f32]) -> Result<(), SileroVadRuntimeError> {
    if !(WINDOW_SAMPLES..=MAX_SPEECH_RATIO_SAMPLES).contains(&samples.len())
        || samples
            .iter()
            .any(|sample| !sample.is_finite() || sample.abs() > 2.0)
    {
        Err(SileroVadRuntimeError::Engine("invalid_window"))
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_missing_model_never_creates_or_downloads_an_artifact() {
        let root = std::env::temp_dir().join(format!(
            "yap-silero-missing-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        assert!(matches!(
            SileroVadDetector::load_at(&root),
            Err(SttError::ModelMissing)
        ));
        assert!(!root.exists());
    }

    #[test]
    fn speech_ratio_rejects_unbounded_or_non_finite_windows_before_inference() {
        assert!(validate_speech_window(&[]).is_err());
        assert!(validate_speech_window(&vec![0.0; WINDOW_SAMPLES - 1]).is_err());
        let mut invalid = vec![0.0; WINDOW_SAMPLES];
        invalid[0] = f32::NAN;
        assert!(validate_speech_window(&invalid).is_err());
        assert!(validate_speech_window(&vec![0.0; WINDOW_SAMPLES]).is_ok());
    }

    #[test]
    #[ignore = "requires YAP_TEST_SILERO_MODEL pointing to the pinned public fixture"]
    fn pinned_real_detector_processes_silence_with_bounded_feeds() {
        let source = std::path::PathBuf::from(
            std::env::var("YAP_TEST_SILERO_MODEL")
                .expect("YAP_TEST_SILERO_MODEL is required for this ignored fixture test"),
        );
        let root = std::env::temp_dir().join(format!(
            "yap-silero-detector-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        std::fs::copy(&source, root.join(ARTIFACTS[0].file)).unwrap();

        let mut detector = SileroVadDetector::load_at(&root).unwrap();
        let window = vec![0_u8; WINDOW_SAMPLES * 2];
        for _ in 0..63 {
            detector
                .accept_pcm16_with_cancellation(&window, &mut || Ok(()))
                .unwrap();
        }
        assert!(detector
            .finish_with_cancellation(&mut || Ok(()))
            .unwrap()
            .is_empty());
        assert_eq!(detector.speech_ratio(&vec![0.0; 16_000]).unwrap(), 0.0);

        drop(detector);
        std::fs::remove_dir_all(root).unwrap();
    }
}
