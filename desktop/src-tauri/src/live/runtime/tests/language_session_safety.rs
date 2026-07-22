use std::{collections::VecDeque, sync::Arc};

use crate::{
    audio::{
        frame::{AudioFrame, PreparedFrame},
        session::{SessionId, TrackId},
    },
    language::{
        live_catalog::LocalLanguageCatalog,
        live_diarization::{
            AcousticEvidenceThresholds, AcousticLanguageObservation,
            PrimaryBiasedInitialLanguageSelectorConfig, SustainedLanguageSwitchConfig,
        },
        live_evidence::{
            LiveLanguageDegradation, LiveLanguageEvidence, LiveLanguageMode, LiveLanguageStatus,
        },
    },
    live::{
        language_pipeline::{LanguageWindowConfig, LanguageWindowDetector, LiveLanguagePipeline},
        language_router::LanguageAudioAction,
        runtime::language_session::LiveLanguageSession,
        source_audio::SourceSampleRange,
    },
};

const SAMPLE_RATE: u64 = 16_000;
const COMPONENT_REVISION: &str = "test-language-detector@sha256:fixture";

#[derive(Debug)]
enum ScriptedObservation {
    Language(&'static str),
    Failure,
}

struct ScriptedDetector {
    observations: VecDeque<ScriptedObservation>,
}

impl LanguageWindowDetector for ScriptedDetector {
    fn component_revision(&self) -> &str {
        COMPONENT_REVISION
    }

    fn observe(
        &mut self,
        range: SourceSampleRange,
        _samples: &[f32],
    ) -> Result<AcousticLanguageObservation, String> {
        match self
            .observations
            .pop_front()
            .expect("the test must provide one outcome per detector window")
        {
            ScriptedObservation::Language(language) => AcousticLanguageObservation::try_new(
                range.start_sample,
                range.end_sample,
                Some(language),
                0.9,
                Some(0.8),
                Some(0.5),
                COMPONENT_REVISION,
            )
            .map_err(|error| error.to_string()),
            ScriptedObservation::Failure => Err("synthetic detector failure".into()),
        }
    }
}

fn pipeline(
    observations: impl IntoIterator<Item = ScriptedObservation>,
    window_samples: u64,
    maximum_holdback_samples: usize,
) -> LiveLanguagePipeline<ScriptedDetector> {
    let catalog = LocalLanguageCatalog::try_new("en-US", ["en-US", "fr-FR"]).unwrap();
    let thresholds = AcousticEvidenceThresholds::try_new(0.5, None, Some(0.1)).unwrap();
    LiveLanguagePipeline::new(
        ScriptedDetector {
            observations: observations.into_iter().collect(),
        },
        &catalog,
        PrimaryBiasedInitialLanguageSelectorConfig::try_new(
            3,
            SAMPLE_RATE,
            SAMPLE_RATE,
            SAMPLE_RATE * 4,
            thresholds,
        )
        .unwrap(),
        SustainedLanguageSwitchConfig::try_new(3, SAMPLE_RATE, SAMPLE_RATE, thresholds).unwrap(),
        LanguageWindowConfig::try_new(window_samples, SAMPLE_RATE).unwrap(),
        maximum_holdback_samples,
    )
    .unwrap()
}

fn frame(sequence: u64, samples: usize) -> PreparedFrame {
    let start_sample = sequence * samples as u64;
    let values = (start_sample..start_sample + samples as u64)
        .map(|sample| sample as f32)
        .collect::<Vec<_>>();
    PreparedFrame {
        metadata: AudioFrame {
            session_id: SessionId::new("language-session-safety").unwrap(),
            track_id: TrackId::new("microphone").unwrap(),
            sequence,
            sample_rate_hz: SAMPLE_RATE as u32,
            channels: 1,
            start_ms: start_sample * 1_000 / SAMPLE_RATE,
            duration_ms: AudioFrame::duration_ms_from_samples(samples, SAMPLE_RATE as u32),
            sample_count: samples,
        },
        samples: Arc::from(values),
    }
}

fn automatic_session(
    pipeline: Option<LiveLanguagePipeline<ScriptedDetector>>,
    degradation: Option<LiveLanguageDegradation>,
) -> LiveLanguageSession<ScriptedDetector> {
    LiveLanguageSession::new(
        pipeline,
        "en-US".into(),
        degradation,
        LiveLanguageMode::Automatic,
    )
}

fn assert_contiguous_primary_coverage(actions: &[LanguageAudioAction], expected_end_sample: u64) {
    let mut cursor = 0;
    for action in actions {
        let LanguageAudioAction::Feed {
            language_bcp47,
            audio,
        } = action
        else {
            panic!("primary fallback must not produce a language switch");
        };
        assert_eq!(language_bcp47, "en-US");
        assert_eq!(audio.range.start_sample, cursor);
        assert_eq!(audio.samples.len() as u64, audio.range.len());
        for (offset, sample) in audio.samples.iter().enumerate() {
            assert_eq!(*sample, (cursor + offset as u64) as f32);
        }
        cursor = audio.range.end_sample;
    }
    assert_eq!(cursor, expected_end_sample);
}

fn assert_primary_evidence(
    evidence: LiveLanguageEvidence,
    status: LiveLanguageStatus,
    degradation: Option<LiveLanguageDegradation>,
    expected_end_sample: u64,
    expected_component_revision: Option<&str>,
) {
    assert_eq!(evidence.status, status);
    assert_eq!(evidence.degradation, degradation);
    assert_eq!(
        evidence.detector_component_revision.as_deref(),
        expected_component_revision
    );
    assert_eq!(evidence.spans.len(), 1);
    assert_eq!(evidence.spans[0].language_bcp47, "en-US");
    assert_eq!(evidence.spans[0].end_sample, expected_end_sample);
}

#[test]
fn short_automatic_utterance_flushes_once_as_the_confirmed_primary() {
    let pipeline = pipeline([], SAMPLE_RATE * 3, SAMPLE_RATE as usize * 8);
    let mut session = automatic_session(Some(pipeline), None);
    assert!(!session.begin_session());

    let pushed = session.push(frame(0, SAMPLE_RATE as usize / 2)).unwrap();
    assert!(pushed.actions.is_empty());
    assert!(pushed.direct_primary_frame.is_none());

    let finished = session.finish().unwrap();
    assert_eq!(finished.actions.len(), 1);
    assert_contiguous_primary_coverage(&finished.actions, SAMPLE_RATE / 2);
    assert_primary_evidence(
        finished.evidence.unwrap(),
        LiveLanguageStatus::Complete,
        None,
        SAMPLE_RATE / 2,
        Some(COMPONENT_REVISION),
    );
}

#[test]
fn detector_failure_drains_admitted_audio_and_records_primary_fallback() {
    let pipeline = pipeline(
        [ScriptedObservation::Failure],
        SAMPLE_RATE,
        SAMPLE_RATE as usize * 8,
    );
    let mut session = automatic_session(Some(pipeline), None);
    session.begin_session();

    let pushed = session.push(frame(0, SAMPLE_RATE as usize)).unwrap();
    assert!(pushed.degradation_started);
    assert!(pushed.direct_primary_frame.is_none());
    assert_eq!(pushed.actions.len(), 1);
    assert_contiguous_primary_coverage(&pushed.actions, SAMPLE_RATE);

    let finished = session.finish().unwrap();
    assert!(finished.actions.is_empty());
    assert_primary_evidence(
        finished.evidence.unwrap(),
        LiveLanguageStatus::Degraded,
        Some(LiveLanguageDegradation::DetectorFailed),
        SAMPLE_RATE,
        Some(COMPONENT_REVISION),
    );
}

#[test]
fn detector_failure_after_a_switch_drains_audio_before_returning_to_primary() {
    let pipeline = pipeline(
        [
            ScriptedObservation::Language("fr-FR"),
            ScriptedObservation::Language("fr-FR"),
            ScriptedObservation::Language("fr-FR"),
            ScriptedObservation::Failure,
        ],
        SAMPLE_RATE,
        SAMPLE_RATE as usize * 8,
    );
    let mut session = automatic_session(Some(pipeline), None);
    session.begin_session();
    let mut actions = Vec::new();
    for second in 0..3 {
        let pushed = session.push(frame(second, SAMPLE_RATE as usize)).unwrap();
        assert!(!pushed.return_to_primary);
        actions.extend(pushed.actions);
    }
    let failed = session.push(frame(3, SAMPLE_RATE as usize)).unwrap();
    assert!(failed.degradation_started);
    assert!(failed.return_to_primary);
    assert!(failed.direct_primary_frame.is_none());
    actions.extend(failed.actions);
    let mut cursor = 0;
    let mut active_language = "en-US";
    for action in actions {
        match action {
            LanguageAudioAction::Switch(transition) => {
                assert_eq!(transition.boundary_sample, cursor);
                assert_eq!(transition.from_language_bcp47, active_language);
                active_language = "fr-FR";
                assert_eq!(transition.to_language_bcp47, active_language);
            }
            LanguageAudioAction::Feed {
                language_bcp47,
                audio,
            } => {
                assert_eq!(language_bcp47, active_language);
                assert_eq!(audio.range.start_sample, cursor);
                cursor = audio.range.end_sample;
            }
        }
    }
    assert_eq!(cursor, SAMPLE_RATE * 4);
    assert_eq!(active_language, "fr-FR");
    let evidence = session.finish().unwrap().evidence.unwrap();
    assert_eq!(evidence.status, LiveLanguageStatus::Degraded);
    assert_eq!(
        evidence.degradation,
        Some(LiveLanguageDegradation::DetectorFailed)
    );
    assert_eq!(evidence.spans.len(), 1);
    assert_eq!(evidence.spans[0].language_bcp47, "fr-FR");
    assert_eq!(evidence.spans[0].end_sample, SAMPLE_RATE * 4);
}

#[test]
fn holdback_exhaustion_rejects_transactionally_and_returns_the_frame_to_primary() {
    let pipeline = pipeline([], SAMPLE_RATE * 2, SAMPLE_RATE as usize / 2);
    let mut session = automatic_session(Some(pipeline), None);
    session.begin_session();

    let pushed = session.push(frame(0, SAMPLE_RATE as usize)).unwrap();
    assert!(pushed.degradation_started);
    assert!(pushed.actions.is_empty());
    let returned = pushed
        .direct_primary_frame
        .expect("a frame rejected before admission must be returned to the ASR path");
    assert_eq!(returned.samples.len(), SAMPLE_RATE as usize);
    assert_primary_evidence(
        session.finish().unwrap().evidence.unwrap(),
        LiveLanguageStatus::Degraded,
        Some(LiveLanguageDegradation::HoldbackCapacityExceeded),
        SAMPLE_RATE,
        Some(COMPONENT_REVISION),
    );
}

#[test]
fn cancelled_pending_switch_cannot_leak_into_the_restarted_session() {
    let pipeline = pipeline(
        [
            ScriptedObservation::Language("fr-FR"),
            ScriptedObservation::Language("fr-FR"),
            ScriptedObservation::Language("en-US"),
        ],
        SAMPLE_RATE,
        SAMPLE_RATE as usize * 8,
    );
    let mut session = automatic_session(Some(pipeline), None);
    session.begin_session();
    let first = session.push(frame(0, SAMPLE_RATE as usize)).unwrap();
    let second = session.push(frame(1, SAMPLE_RATE as usize)).unwrap();
    assert!(first.actions.is_empty());
    assert!(second.actions.is_empty());

    assert!(!session.begin_session());
    let restarted = session.push(frame(0, SAMPLE_RATE as usize)).unwrap();
    let finished = session.finish().unwrap();
    let actions = restarted
        .actions
        .into_iter()
        .chain(finished.actions)
        .collect::<Vec<_>>();
    assert_contiguous_primary_coverage(&actions, SAMPLE_RATE);
    assert_primary_evidence(
        finished.evidence.unwrap(),
        LiveLanguageStatus::Complete,
        None,
        SAMPLE_RATE,
        Some(COMPONENT_REVISION),
    );
}

#[test]
fn unavailable_local_artifacts_remain_visible_while_primary_dictation_continues() {
    let mut session = automatic_session(None, Some(LiveLanguageDegradation::ArtifactsUnavailable));
    assert!(session.begin_session());

    let pushed = session.push(frame(0, SAMPLE_RATE as usize / 4)).unwrap();
    assert!(pushed.actions.is_empty());
    assert!(pushed.direct_primary_frame.is_some());
    assert!(!pushed.degradation_started);

    assert_primary_evidence(
        session.finish().unwrap().evidence.unwrap(),
        LiveLanguageStatus::Degraded,
        Some(LiveLanguageDegradation::ArtifactsUnavailable),
        SAMPLE_RATE / 4,
        None,
    );
}
