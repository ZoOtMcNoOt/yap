//! Bounded local acoustic-LID pipeline with a replaceable detector seam.

use crate::{
    audio::frame::PreparedFrame,
    language::{
        live_catalog::LocalLanguageCatalog,
        live_diarization::{
            AcousticEvidenceThresholds, AcousticLanguageObservation, LanguageDecisionOutcome,
            PrimaryBiasedInitialLanguageSelectorConfig, SustainedLanguageSwitchConfig,
        },
    },
    stt::ambernet_language_detector::{
        AmberNetSileroLanguageDetector, RESIDENT_LANGUAGE_HOP_SAMPLES,
        RESIDENT_LANGUAGE_WINDOW_SAMPLES,
    },
};

use super::{
    language_router::{
        LanguageAudioAction, LanguageRoutingError, LanguageRoutingFinish, LiveLanguageRouter,
    },
    source_audio::{SourceAudioHoldback, SourceSampleRange},
};

const SAMPLE_RATE: u64 = 16_000;
const RESIDENT_MIN_CANDIDATE_SAMPLES: u64 = SAMPLE_RATE;
const RESIDENT_MAX_OBSERVATION_GAP_SAMPLES: u64 = SAMPLE_RATE;
const RESIDENT_INITIAL_SELECTION_DEADLINE_SAMPLES: u64 = SAMPLE_RATE * 4;
const RESIDENT_MAX_HOLDBACK_SAMPLES: usize = SAMPLE_RATE as usize * 12;
const RESIDENT_REQUIRED_OBSERVATIONS: u8 = 3;
const RESIDENT_MIN_SPEECH_RATIO: f32 = 0.25;
// Frozen by the released-candidate AmberNet evaluation. The resolver reports
// softmax probability margin, so ambiguous global winners must abstain here.
const RESIDENT_MIN_CLASSIFICATION_MARGIN: f32 = 0.4;
const MIN_WINDOW_SAMPLES: u64 = SAMPLE_RATE;
const MAX_WINDOW_SAMPLES: u64 = SAMPLE_RATE * 20;
const MIN_HOP_SAMPLES: u64 = SAMPLE_RATE / 4;
const MAX_WINDOWS_PER_FRAME: usize = 64;

pub(super) trait LanguageWindowDetector {
    fn component_revision(&self) -> &str;

    fn observe(
        &mut self,
        range: SourceSampleRange,
        samples: &[f32],
    ) -> Result<AcousticLanguageObservation, String>;
}

impl LanguageWindowDetector for AmberNetSileroLanguageDetector {
    fn component_revision(&self) -> &str {
        AmberNetSileroLanguageDetector::component_revision(self)
    }

    fn observe(
        &mut self,
        range: SourceSampleRange,
        samples: &[f32],
    ) -> Result<AcousticLanguageObservation, String> {
        self.observe(range.start_sample, range.end_sample, samples)
            .map_err(|error| error.to_string())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct LanguageWindowConfig {
    window_samples: u64,
    hop_samples: u64,
}

impl LanguageWindowConfig {
    pub(super) fn try_new(
        window_samples: u64,
        hop_samples: u64,
    ) -> Result<Self, LanguagePipelineError> {
        if !(MIN_WINDOW_SAMPLES..=MAX_WINDOW_SAMPLES).contains(&window_samples)
            || !(MIN_HOP_SAMPLES..=window_samples).contains(&hop_samples)
        {
            return Err(LanguagePipelineError::InvalidWindowConfiguration);
        }
        Ok(Self {
            window_samples,
            hop_samples,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct LanguagePipelineBatch {
    pub(super) decisions: Vec<LanguageDecisionOutcome>,
    pub(super) actions: Vec<LanguageAudioAction>,
}

impl LanguagePipelineBatch {
    fn empty() -> Self {
        Self {
            decisions: Vec::new(),
            actions: Vec::new(),
        }
    }

    fn append_decision(
        &mut self,
        outcome: LanguageDecisionOutcome,
        mut actions: Vec<LanguageAudioAction>,
    ) {
        self.decisions.push(outcome);
        self.actions.append(&mut actions);
    }

    fn append(&mut self, mut other: Self) {
        self.decisions.append(&mut other.decisions);
        self.actions.append(&mut other.actions);
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct LanguagePipelineFinish {
    pub(super) batch: LanguagePipelineBatch,
    pub(super) routing: LanguageRoutingFinish,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) enum LanguagePipelineError {
    InvalidWindowConfiguration,
    SourceRangeDiverged,
    Routing(LanguageRoutingError),
    Detector(String),
}

impl std::fmt::Display for LanguagePipelineError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidWindowConfiguration => {
                formatter.write_str("local language window configuration is invalid")
            }
            Self::SourceRangeDiverged => {
                formatter.write_str("local language source-retention ranges diverged")
            }
            Self::Routing(error) => error.fmt(formatter),
            Self::Detector(error) => write!(formatter, "local language detector failed: {error}"),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct LanguagePipelinePushError {
    pub(super) error: LanguagePipelineError,
    pub(super) frame_admitted: bool,
    pub(super) committed_batch: LanguagePipelineBatch,
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct LanguagePipelineFinishError {
    pub(super) error: LanguagePipelineError,
    pub(super) committed_batch: LanguagePipelineBatch,
}

struct LanguagePipelineProcessingError {
    error: LanguagePipelineError,
    committed_batch: LanguagePipelineBatch,
}

impl std::error::Error for LanguagePipelineError {}

impl From<LanguageRoutingError> for LanguagePipelineError {
    fn from(error: LanguageRoutingError) -> Self {
        Self::Routing(error)
    }
}

#[derive(Clone)]
struct LanguageWindowPlanner {
    config: LanguageWindowConfig,
    next_start_sample: Option<u64>,
}

impl LanguageWindowPlanner {
    fn new(config: LanguageWindowConfig) -> Self {
        Self {
            config,
            next_start_sample: None,
        }
    }

    fn observe_audio_start(&mut self, start_sample: u64) {
        self.next_start_sample.get_or_insert(start_sample);
    }

    fn next_ready(&self, source_end_sample: u64) -> Option<SourceSampleRange> {
        let start_sample = self.next_start_sample?;
        let end_sample = start_sample.checked_add(self.config.window_samples)?;
        (end_sample <= source_end_sample).then_some(SourceSampleRange {
            start_sample,
            end_sample,
        })
    }

    fn advance(&mut self) -> Result<(), LanguagePipelineError> {
        let start = self
            .next_start_sample
            .ok_or(LanguagePipelineError::InvalidWindowConfiguration)?;
        self.next_start_sample = Some(
            start
                .checked_add(self.config.hop_samples)
                .ok_or(LanguagePipelineError::InvalidWindowConfiguration)?,
        );
        Ok(())
    }

    fn next_start_sample(&self) -> Option<u64> {
        self.next_start_sample
    }
}

/// Owns detector scheduling, pending source audio, and hysteretic decisions.
pub(super) struct LiveLanguagePipeline<D> {
    detector: D,
    catalog: LocalLanguageCatalog,
    initial_selection_config: PrimaryBiasedInitialLanguageSelectorConfig,
    sustained_switch_config: SustainedLanguageSwitchConfig,
    window_config: LanguageWindowConfig,
    maximum_holdback_samples: usize,
    router: LiveLanguageRouter,
    detector_audio: SourceAudioHoldback,
    planner: LanguageWindowPlanner,
}

pub(super) type ResidentLanguagePipeline = LiveLanguagePipeline<AmberNetSileroLanguageDetector>;

pub(super) fn load_resident_language_pipeline(
    catalog: LocalLanguageCatalog,
) -> Result<ResidentLanguagePipeline, crate::stt::error::SttError> {
    let detector = AmberNetSileroLanguageDetector::load(catalog.clone())?;
    let evidence_thresholds = AcousticEvidenceThresholds::try_new(
        RESIDENT_MIN_SPEECH_RATIO,
        None,
        Some(RESIDENT_MIN_CLASSIFICATION_MARGIN),
    )
    .map_err(|_| crate::stt::error::SttError::SidecarCrash)?;
    let initial_selection = PrimaryBiasedInitialLanguageSelectorConfig::try_new(
        RESIDENT_REQUIRED_OBSERVATIONS,
        RESIDENT_MIN_CANDIDATE_SAMPLES,
        RESIDENT_MAX_OBSERVATION_GAP_SAMPLES,
        RESIDENT_INITIAL_SELECTION_DEADLINE_SAMPLES,
        evidence_thresholds,
    )
    .map_err(|_| crate::stt::error::SttError::SidecarCrash)?;
    let sustained_switch = SustainedLanguageSwitchConfig::try_new(
        RESIDENT_REQUIRED_OBSERVATIONS,
        RESIDENT_MIN_CANDIDATE_SAMPLES,
        RESIDENT_MAX_OBSERVATION_GAP_SAMPLES,
        evidence_thresholds,
    )
    .map_err(|_| crate::stt::error::SttError::SidecarCrash)?;
    let windows = LanguageWindowConfig::try_new(
        RESIDENT_LANGUAGE_WINDOW_SAMPLES,
        RESIDENT_LANGUAGE_HOP_SAMPLES,
    )
    .map_err(|_| crate::stt::error::SttError::SidecarCrash)?;
    LiveLanguagePipeline::new(
        detector,
        &catalog,
        initial_selection,
        sustained_switch,
        windows,
        RESIDENT_MAX_HOLDBACK_SAMPLES,
    )
    .map_err(|_| crate::stt::error::SttError::SidecarCrash)
}

impl<D> LiveLanguagePipeline<D>
where
    D: LanguageWindowDetector,
{
    pub(super) fn new(
        detector: D,
        catalog: &LocalLanguageCatalog,
        initial_selection_config: PrimaryBiasedInitialLanguageSelectorConfig,
        sustained_switch_config: SustainedLanguageSwitchConfig,
        window_config: LanguageWindowConfig,
        maximum_holdback_samples: usize,
    ) -> Result<Self, LanguagePipelineError> {
        let router = LiveLanguageRouter::new(
            catalog.primary_language_bcp47(),
            catalog.enabled_locales(),
            initial_selection_config,
            sustained_switch_config,
            maximum_holdback_samples,
        )?;
        let detector_capacity = maximum_holdback_samples
            .checked_add(
                usize::try_from(window_config.window_samples)
                    .map_err(|_| LanguagePipelineError::InvalidWindowConfiguration)?,
            )
            .ok_or(LanguagePipelineError::InvalidWindowConfiguration)?;
        let detector_audio =
            SourceAudioHoldback::new(detector_capacity).map_err(LanguageRoutingError::from)?;
        Ok(Self {
            detector,
            catalog: catalog.clone(),
            initial_selection_config,
            sustained_switch_config,
            window_config,
            maximum_holdback_samples,
            router,
            detector_audio,
            planner: LanguageWindowPlanner::new(window_config),
        })
    }

    pub(super) fn push(
        &mut self,
        frame: PreparedFrame,
    ) -> Result<LanguagePipelineBatch, LanguagePipelinePushError> {
        let mut router = self.router.clone();
        let mut detector_audio = self.detector_audio.clone();
        let range = router
            .push(frame.clone())
            .map_err(|error| LanguagePipelinePushError {
                error: error.into(),
                frame_admitted: false,
                committed_batch: LanguagePipelineBatch::empty(),
            })?;
        let detector_range =
            detector_audio
                .push(frame)
                .map_err(|error| LanguagePipelinePushError {
                    error: LanguageRoutingError::from(error).into(),
                    frame_admitted: false,
                    committed_batch: LanguagePipelineBatch::empty(),
                })?;
        if detector_range != range {
            return Err(LanguagePipelinePushError {
                error: LanguagePipelineError::SourceRangeDiverged,
                frame_admitted: false,
                committed_batch: LanguagePipelineBatch::empty(),
            });
        }
        self.router = router;
        self.detector_audio = detector_audio;
        self.planner.observe_audio_start(range.start_sample);
        self.process_ready(range.end_sample)
            .map_err(|failure| LanguagePipelinePushError {
                error: failure.error,
                frame_admitted: true,
                committed_batch: failure.committed_batch,
            })
    }

    pub(super) fn finish(&mut self) -> Result<LanguagePipelineFinish, LanguagePipelineFinishError> {
        let source_end =
            self.router
                .source_end_sample()
                .ok_or_else(|| LanguagePipelineFinishError {
                    error: LanguageRoutingError::SessionHasNoAudio.into(),
                    committed_batch: LanguagePipelineBatch::empty(),
                })?;
        let mut batch = LanguagePipelineBatch::empty();
        while self.planner.next_ready(source_end).is_some() {
            match self.process_ready(source_end) {
                Ok(next) => batch.append(next),
                Err(mut failure) => {
                    batch.append(failure.committed_batch);
                    failure.committed_batch = batch;
                    return Err(LanguagePipelineFinishError {
                        error: failure.error,
                        committed_batch: failure.committed_batch,
                    });
                }
            }
        }
        let routing = self
            .router
            .finish()
            .map_err(|error| LanguagePipelineFinishError {
                error: error.into(),
                committed_batch: batch.clone(),
            })?;
        self.detector_audio.reset();
        Ok(LanguagePipelineFinish { batch, routing })
    }

    pub(super) fn abandon_detection(
        &mut self,
    ) -> Result<LanguageRoutingFinish, LanguagePipelineError> {
        let finish = self.router.finish().map_err(LanguagePipelineError::from)?;
        self.detector_audio.reset();
        Ok(finish)
    }

    pub(super) fn reset_session(&mut self) -> Result<(), LanguagePipelineError> {
        self.router = LiveLanguageRouter::new(
            self.catalog.primary_language_bcp47(),
            self.catalog.enabled_locales(),
            self.initial_selection_config,
            self.sustained_switch_config,
            self.maximum_holdback_samples,
        )?;
        self.detector_audio.reset();
        self.planner = LanguageWindowPlanner::new(self.window_config);
        Ok(())
    }

    pub(super) fn source_end_sample(&self) -> Option<u64> {
        self.router.source_end_sample()
    }

    pub(super) fn component_revision(&self) -> &str {
        self.detector.component_revision()
    }

    fn process_ready(
        &mut self,
        source_end_sample: u64,
    ) -> Result<LanguagePipelineBatch, LanguagePipelineProcessingError> {
        let mut batch = LanguagePipelineBatch::empty();
        for _ in 0..MAX_WINDOWS_PER_FRAME {
            let Some(range) = self.planner.next_ready(source_end_sample) else {
                return Ok(batch);
            };
            let audio = self.detector_audio.copy_range(range).map_err(|error| {
                LanguagePipelineProcessingError {
                    error: LanguageRoutingError::from(error).into(),
                    committed_batch: batch.clone(),
                }
            })?;
            let observation = self
                .detector
                .observe(range, &audio.samples)
                .map_err(|error| LanguagePipelineProcessingError {
                    error: LanguagePipelineError::Detector(error),
                    committed_batch: batch.clone(),
                })?;
            let mut router = self.router.clone();
            let decision =
                router
                    .observe(observation)
                    .map_err(|error| LanguagePipelineProcessingError {
                        error: error.into(),
                        committed_batch: batch.clone(),
                    })?;
            let mut planner = self.planner.clone();
            planner
                .advance()
                .map_err(|error| LanguagePipelineProcessingError {
                    error,
                    committed_batch: batch.clone(),
                })?;
            let mut detector_audio = self.detector_audio.clone();
            detector_audio
                .discard_before(
                    planner
                        .next_start_sample()
                        .ok_or(LanguagePipelineError::InvalidWindowConfiguration)
                        .map_err(|error| LanguagePipelineProcessingError {
                            error,
                            committed_batch: batch.clone(),
                        })?,
                )
                .map_err(|error| LanguagePipelineProcessingError {
                    error: LanguageRoutingError::from(error).into(),
                    committed_batch: batch.clone(),
                })?;
            self.router = router;
            self.planner = planner;
            self.detector_audio = detector_audio;
            batch.append_decision(decision.outcome, decision.actions);
        }
        Ok(batch)
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::audio::{
        frame::AudioFrame,
        session::{SessionId, TrackId},
    };

    const COMPONENT: &str = "fake-local-lid@sha256:test";

    struct ScriptedDetector {
        fail_at: Option<u64>,
    }

    impl LanguageWindowDetector for ScriptedDetector {
        fn component_revision(&self) -> &str {
            COMPONENT
        }

        fn observe(
            &mut self,
            range: SourceSampleRange,
            _samples: &[f32],
        ) -> Result<AcousticLanguageObservation, String> {
            if self.fail_at == Some(range.start_sample) {
                return Err("synthetic detector failure".into());
            }
            let language = if range.start_sample == 0 {
                Some("en-US")
            } else {
                Some("fr-FR")
            };
            AcousticLanguageObservation::try_new(
                range.start_sample,
                range.end_sample,
                language,
                0.9,
                Some(0.8),
                Some(0.4),
                COMPONENT,
            )
            .map_err(|error| error.to_string())
        }
    }

    fn frame(second: u64) -> PreparedFrame {
        let start = second * SAMPLE_RATE;
        let samples = (start..start + SAMPLE_RATE)
            .map(|sample| sample as f32)
            .collect::<Vec<_>>();
        PreparedFrame {
            metadata: AudioFrame {
                session_id: SessionId::new("language-pipeline-test").unwrap(),
                track_id: TrackId::new("microphone").unwrap(),
                sequence: second,
                sample_rate_hz: SAMPLE_RATE as u32,
                channels: 1,
                start_ms: second * 1_000,
                duration_ms: 1_000,
                sample_count: samples.len(),
            },
            samples: Arc::from(samples),
        }
    }

    fn fixture_frame(sequence: u64, samples: &[f32]) -> PreparedFrame {
        PreparedFrame {
            metadata: AudioFrame {
                session_id: SessionId::new("language-pipeline-fixture").unwrap(),
                track_id: TrackId::new("microphone").unwrap(),
                sequence,
                sample_rate_hz: SAMPLE_RATE as u32,
                channels: 1,
                start_ms: sequence * 1_000,
                duration_ms: 1_000,
                sample_count: samples.len(),
            },
            samples: Arc::from(samples.to_vec()),
        }
    }

    fn initial_selection_config() -> PrimaryBiasedInitialLanguageSelectorConfig {
        PrimaryBiasedInitialLanguageSelectorConfig::try_new(
            3,
            SAMPLE_RATE,
            SAMPLE_RATE,
            SAMPLE_RATE * 4,
            AcousticEvidenceThresholds::try_new(0.5, None, Some(0.1)).unwrap(),
        )
        .unwrap()
    }

    fn sustained_switch_config() -> SustainedLanguageSwitchConfig {
        SustainedLanguageSwitchConfig::try_new(
            3,
            SAMPLE_RATE,
            SAMPLE_RATE,
            AcousticEvidenceThresholds::try_new(0.5, None, Some(0.1)).unwrap(),
        )
        .unwrap()
    }

    fn pipeline(fail_at: Option<u64>) -> LiveLanguagePipeline<ScriptedDetector> {
        let catalog = LocalLanguageCatalog::try_new("en-US", ["en-US", "fr-FR"]).unwrap();
        LiveLanguagePipeline::new(
            ScriptedDetector { fail_at },
            &catalog,
            initial_selection_config(),
            sustained_switch_config(),
            LanguageWindowConfig::try_new(SAMPLE_RATE, SAMPLE_RATE / 2).unwrap(),
            SAMPLE_RATE as usize * 8,
        )
        .unwrap()
    }

    #[test]
    fn sliding_windows_drive_one_ordered_lossless_switch_pipeline() {
        let mut pipeline = pipeline(None);
        let mut actions = Vec::new();
        let mut decisions = Vec::new();
        for second in 0..4 {
            let batch = pipeline.push(frame(second)).unwrap();
            actions.extend(batch.actions);
            decisions.extend(batch.decisions);
        }
        let finish = pipeline.finish().unwrap();
        actions.extend(finish.batch.actions);
        decisions.extend(finish.batch.decisions);
        actions.extend(finish.routing.actions);

        assert!(decisions
            .iter()
            .any(|decision| matches!(decision, LanguageDecisionOutcome::Switched(_))));
        let mut cursor = 0;
        let mut boundary = None;
        for action in actions {
            match action {
                LanguageAudioAction::Feed { audio, .. } => {
                    assert_eq!(audio.range.start_sample, cursor);
                    cursor = audio.range.end_sample;
                }
                LanguageAudioAction::Switch(transition) => {
                    assert_eq!(transition.boundary_sample, cursor);
                    boundary = Some(cursor);
                }
            }
        }
        assert_eq!(boundary, Some(12_000));
        assert_eq!(cursor, SAMPLE_RATE * 4);
    }

    #[test]
    fn overlapping_detector_history_survives_earlier_asr_commits() {
        let catalog = LocalLanguageCatalog::try_new("en-US", ["en-US", "fr-FR"]).unwrap();
        let mut pipeline = LiveLanguagePipeline::new(
            ScriptedDetector { fail_at: None },
            &catalog,
            PrimaryBiasedInitialLanguageSelectorConfig::try_new(
                RESIDENT_REQUIRED_OBSERVATIONS,
                RESIDENT_MIN_CANDIDATE_SAMPLES,
                RESIDENT_MAX_OBSERVATION_GAP_SAMPLES,
                RESIDENT_INITIAL_SELECTION_DEADLINE_SAMPLES,
                AcousticEvidenceThresholds::try_new(RESIDENT_MIN_SPEECH_RATIO, None, None).unwrap(),
            )
            .unwrap(),
            SustainedLanguageSwitchConfig::try_new(
                RESIDENT_REQUIRED_OBSERVATIONS,
                RESIDENT_MIN_CANDIDATE_SAMPLES,
                RESIDENT_MAX_OBSERVATION_GAP_SAMPLES,
                AcousticEvidenceThresholds::try_new(RESIDENT_MIN_SPEECH_RATIO, None, None).unwrap(),
            )
            .unwrap(),
            LanguageWindowConfig::try_new(
                RESIDENT_LANGUAGE_WINDOW_SAMPLES,
                RESIDENT_LANGUAGE_HOP_SAMPLES,
            )
            .unwrap(),
            RESIDENT_MAX_HOLDBACK_SAMPLES,
        )
        .unwrap();

        let mut actions = Vec::new();
        for second in 0..4 {
            actions.extend(pipeline.push(frame(second)).unwrap().actions);
        }
        let finish = pipeline.finish().unwrap();
        actions.extend(finish.batch.actions);
        actions.extend(finish.routing.actions);

        let mut cursor = 0;
        for action in actions {
            match action {
                LanguageAudioAction::Feed { audio, .. } => {
                    assert_eq!(audio.range.start_sample, cursor);
                    cursor = audio.range.end_sample;
                }
                LanguageAudioAction::Switch(transition) => {
                    assert_eq!(transition.boundary_sample, cursor);
                }
            }
        }
        assert_eq!(cursor, SAMPLE_RATE * 4);
    }

    #[test]
    fn detector_failure_does_not_advance_or_discard_its_window() {
        let mut pipeline = pipeline(Some(0));

        let failure = pipeline.push(frame(0)).unwrap_err();

        assert_eq!(
            failure.error,
            LanguagePipelineError::Detector("synthetic detector failure".into())
        );
        assert!(failure.frame_admitted);
        assert_eq!(failure.committed_batch, LanguagePipelineBatch::empty());
        assert_eq!(
            pipeline.router.retained_range(),
            Some(SourceSampleRange {
                start_sample: 0,
                end_sample: SAMPLE_RATE,
            })
        );
    }

    #[test]
    fn later_window_failure_returns_prior_commits_and_abandon_drains_exactly_once() {
        let mut pipeline = pipeline(Some(SAMPLE_RATE));
        let samples = (0..SAMPLE_RATE * 2)
            .map(|sample| sample as f32)
            .collect::<Vec<_>>();
        let long_frame = PreparedFrame {
            metadata: AudioFrame {
                session_id: SessionId::new("language-pipeline-test").unwrap(),
                track_id: TrackId::new("microphone").unwrap(),
                sequence: 0,
                sample_rate_hz: SAMPLE_RATE as u32,
                channels: 1,
                start_ms: 0,
                duration_ms: 2_000,
                sample_count: samples.len(),
            },
            samples: Arc::from(samples),
        };

        let failure = pipeline.push(long_frame).unwrap_err();

        assert_eq!(
            failure.error,
            LanguagePipelineError::Detector("synthetic detector failure".into())
        );
        assert!(failure.frame_admitted);
        assert_eq!(failure.committed_batch.decisions.len(), 2);
        assert!(!failure.committed_batch.actions.is_empty());

        let mut actions = failure.committed_batch.actions;
        actions.extend(pipeline.abandon_detection().unwrap().actions);
        let mut cursor = 0;
        for action in actions {
            match action {
                LanguageAudioAction::Feed { audio, .. } => {
                    assert_eq!(audio.range.start_sample, cursor);
                    cursor = audio.range.end_sample;
                }
                LanguageAudioAction::Switch(_) => {
                    panic!("a two-window candidate must not switch before hysteresis")
                }
            }
        }
        assert_eq!(cursor, SAMPLE_RATE * 2);
    }

    #[test]
    fn reset_discards_a_pending_switch_before_the_next_session() {
        let mut pipeline = pipeline(None);

        pipeline.push(frame(0)).unwrap();
        let pending = pipeline.push(frame(1)).unwrap();
        assert!(pending.decisions.iter().any(|decision| matches!(
            decision,
            LanguageDecisionOutcome::Pending {
                language_bcp47,
                observation_count: 2,
                ..
            } if language_bcp47 == "fr-FR"
        )));

        pipeline.reset_session().unwrap();
        let first = pipeline.push(frame(0)).unwrap();
        let finish = pipeline.finish().unwrap();
        let mut actions = first.actions;
        actions.extend(finish.batch.actions);
        actions.extend(finish.routing.actions);

        let mut cursor = 0;
        for action in actions {
            match action {
                LanguageAudioAction::Feed {
                    language_bcp47,
                    audio,
                } => {
                    assert_eq!(language_bcp47, "en-US");
                    assert_eq!(audio.range.start_sample, cursor);
                    cursor = audio.range.end_sample;
                }
                LanguageAudioAction::Switch(_) => {
                    panic!("a cancelled prior-session candidate must not leak")
                }
            }
        }
        assert_eq!(cursor, SAMPLE_RATE);
        assert_eq!(finish.routing.final_span.unwrap().start_sample, 0);
    }

    #[test]
    fn window_configuration_is_bounded_for_latency_and_memory() {
        assert!(LanguageWindowConfig::try_new(SAMPLE_RATE - 1, SAMPLE_RATE / 2).is_err());
        assert!(LanguageWindowConfig::try_new(SAMPLE_RATE, SAMPLE_RATE / 4 - 1).is_err());
        assert!(LanguageWindowConfig::try_new(SAMPLE_RATE, SAMPLE_RATE + 1).is_err());
        assert!(LanguageWindowConfig::try_new(SAMPLE_RATE * 21, SAMPLE_RATE).is_err());
    }

    #[test]
    #[ignore = "requires pinned AmberNet, Silero, and private-path public WAV fixtures"]
    fn pinned_resident_detector_routes_a_constructed_language_switch_without_audio_loss() {
        let ambernet_root = std::path::PathBuf::from(
            std::env::var("YAP_TEST_AMBERNET_LID_ROOT")
                .expect("YAP_TEST_AMBERNET_LID_ROOT is required"),
        );
        let silero_root = std::path::PathBuf::from(
            std::env::var("YAP_TEST_SILERO_ROOT").expect("YAP_TEST_SILERO_ROOT is required"),
        );
        let fixtures = std::path::PathBuf::from(
            std::env::var("YAP_TEST_AMBERNET_LID_FIXTURES")
                .expect("YAP_TEST_AMBERNET_LID_FIXTURES is required"),
        );
        let catalog = LocalLanguageCatalog::try_new("en-US", ["en-US", "ja-JP"]).unwrap();
        let detector =
            AmberNetSileroLanguageDetector::load_at(&ambernet_root, &silero_root, catalog.clone())
                .unwrap();
        let initial_selection = PrimaryBiasedInitialLanguageSelectorConfig::try_new(
            RESIDENT_REQUIRED_OBSERVATIONS,
            RESIDENT_MIN_CANDIDATE_SAMPLES,
            RESIDENT_MAX_OBSERVATION_GAP_SAMPLES,
            RESIDENT_INITIAL_SELECTION_DEADLINE_SAMPLES,
            AcousticEvidenceThresholds::try_new(
                RESIDENT_MIN_SPEECH_RATIO,
                None,
                Some(RESIDENT_MIN_CLASSIFICATION_MARGIN),
            )
            .unwrap(),
        )
        .unwrap();
        let sustained_switch = SustainedLanguageSwitchConfig::try_new(
            RESIDENT_REQUIRED_OBSERVATIONS,
            RESIDENT_MIN_CANDIDATE_SAMPLES,
            RESIDENT_MAX_OBSERVATION_GAP_SAMPLES,
            AcousticEvidenceThresholds::try_new(
                RESIDENT_MIN_SPEECH_RATIO,
                None,
                Some(RESIDENT_MIN_CLASSIFICATION_MARGIN),
            )
            .unwrap(),
        )
        .unwrap();
        let windows = LanguageWindowConfig::try_new(
            RESIDENT_LANGUAGE_WINDOW_SAMPLES,
            RESIDENT_LANGUAGE_HOP_SAMPLES,
        )
        .unwrap();
        let mut pipeline = LiveLanguagePipeline::new(
            detector,
            &catalog,
            initial_selection,
            sustained_switch,
            windows,
            RESIDENT_MAX_HOLDBACK_SAMPLES,
        )
        .unwrap();

        const FIXTURE_SECONDS: usize = 6;
        let samples_per_fixture = SAMPLE_RATE as usize * FIXTURE_SECONDS;
        let read_fixture = |file: &str| {
            let path = fixtures.join(file);
            let wave = sherpa_onnx::Wave::read(path.to_str().unwrap()).unwrap();
            assert_eq!(wave.sample_rate(), SAMPLE_RATE as i32);
            assert!(wave.samples().len() >= samples_per_fixture);
            wave.samples()[..samples_per_fixture].to_vec()
        };
        let english = read_fixture("en.wav");
        let japanese = read_fixture("ja.wav");
        let source = english.into_iter().chain(japanese).collect::<Vec<_>>();
        let expected_boundary = samples_per_fixture as u64;

        let mut actions = Vec::new();
        let mut transitions = Vec::new();
        for (sequence, samples) in source.chunks_exact(SAMPLE_RATE as usize).enumerate() {
            let batch = pipeline
                .push(fixture_frame(sequence as u64, samples))
                .unwrap();
            for decision in batch.decisions {
                if let LanguageDecisionOutcome::Switched(transition) = decision {
                    transitions.push(transition);
                }
            }
            actions.extend(batch.actions);
        }
        let finish = pipeline.finish().unwrap();
        for decision in finish.batch.decisions {
            if let LanguageDecisionOutcome::Switched(transition) = decision {
                transitions.push(transition);
            }
        }
        actions.extend(finish.batch.actions);
        actions.extend(finish.routing.actions);

        let switch = transitions
            .iter()
            .find(|transition| {
                transition.from_language_bcp47 == "en-US" && transition.to_language_bcp47 == "ja-JP"
            })
            .expect("the pinned resident detector should confirm the constructed switch");
        assert!(
            switch.boundary_sample.abs_diff(expected_boundary) <= SAMPLE_RATE * 2,
            "switch boundary {} was too far from expected boundary {expected_boundary}",
            switch.boundary_sample
        );
        eprintln!(
            "constructed_switch from=en-US to=ja-JP expected_sample={expected_boundary} observed_sample={} absolute_error_ms={}",
            switch.boundary_sample,
            switch.boundary_sample.abs_diff(expected_boundary) * 1_000 / SAMPLE_RATE
        );

        let mut cursor = 0;
        for action in actions {
            match action {
                LanguageAudioAction::Feed { audio, .. } => {
                    assert_eq!(audio.range.start_sample, cursor);
                    cursor = audio.range.end_sample;
                }
                LanguageAudioAction::Switch(transition) => {
                    assert_eq!(transition.boundary_sample, cursor);
                }
            }
        }
        assert_eq!(cursor, source.len() as u64);
    }
}
