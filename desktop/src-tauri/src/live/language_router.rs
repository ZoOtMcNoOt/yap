//! Transactional audio routing around accepted acoustic-language boundaries.

use crate::{
    audio::frame::PreparedFrame,
    language::live_diarization::{
        AcousticLanguageObservation, AutomaticLanguageRoutingPolicy, LanguageDecisionOutcome,
        LanguageDiarizationError, LanguageSpan, LanguageTransition,
        PrimaryBiasedInitialLanguageSelectorConfig, SustainedLanguageSwitchConfig,
    },
};

#[cfg(test)]
use crate::language::live_diarization::AcousticEvidenceThresholds;

use super::source_audio::{
    SourceAudioChunk, SourceAudioError, SourceAudioHoldback, SourceSampleRange,
};

#[derive(Debug, Clone, PartialEq)]
pub(super) enum LanguageAudioAction {
    Feed {
        language_bcp47: String,
        audio: SourceAudioChunk,
    },
    Switch(LanguageTransition),
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct LanguageRoutingDecision {
    pub(super) outcome: LanguageDecisionOutcome,
    pub(super) actions: Vec<LanguageAudioAction>,
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct LanguageRoutingFinish {
    pub(super) final_span: Option<LanguageSpan>,
    pub(super) actions: Vec<LanguageAudioAction>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum LanguageRoutingError {
    Diarization(LanguageDiarizationError),
    SourceAudio(SourceAudioError),
    BoundaryAlreadyCommitted,
    SessionHasNoAudio,
}

impl std::fmt::Display for LanguageRoutingError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Diarization(error) => error.fmt(formatter),
            Self::SourceAudio(error) => error.fmt(formatter),
            Self::BoundaryAlreadyCommitted => {
                formatter.write_str("language boundary arrived after its audio was committed")
            }
            Self::SessionHasNoAudio => formatter.write_str("language session has no audio"),
        }
    }
}

impl std::error::Error for LanguageRoutingError {}

impl From<LanguageDiarizationError> for LanguageRoutingError {
    fn from(error: LanguageDiarizationError) -> Self {
        Self::Diarization(error)
    }
}

impl From<SourceAudioError> for LanguageRoutingError {
    fn from(error: SourceAudioError) -> Self {
        Self::SourceAudio(error)
    }
}

/// One owner for pending audio and the language policy that releases it.
#[derive(Clone)]
pub(super) struct LiveLanguageRouter {
    policy: AutomaticLanguageRoutingPolicy,
    holdback: SourceAudioHoldback,
}

impl LiveLanguageRouter {
    pub(super) fn new<I, S>(
        primary_language_bcp47: &str,
        supported_languages: I,
        initial_selection_config: PrimaryBiasedInitialLanguageSelectorConfig,
        sustained_switch_config: SustainedLanguageSwitchConfig,
        maximum_holdback_samples: usize,
    ) -> Result<Self, LanguageRoutingError>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        Ok(Self {
            policy: AutomaticLanguageRoutingPolicy::new(
                primary_language_bcp47,
                supported_languages,
                initial_selection_config,
                sustained_switch_config,
            )?,
            holdback: SourceAudioHoldback::new(maximum_holdback_samples)?,
        })
    }

    pub(super) fn push(
        &mut self,
        frame: PreparedFrame,
    ) -> Result<SourceSampleRange, LanguageRoutingError> {
        self.holdback.push(frame).map_err(Into::into)
    }

    pub(super) fn source_end_sample(&self) -> Option<u64> {
        self.holdback.source_end_sample()
    }

    /// Applies an observation transactionally: neither policy nor retained
    /// audio advances if the resulting routing batch cannot be represented.
    pub(super) fn observe(
        &mut self,
        observation: AcousticLanguageObservation,
    ) -> Result<LanguageRoutingDecision, LanguageRoutingError> {
        let mut policy = self.policy.clone();
        let mut holdback = self.holdback.clone();
        let outcome = policy.observe(observation)?;
        let actions = route_decision(&policy, &outcome, &mut holdback)?;
        self.policy = policy;
        self.holdback = holdback;
        Ok(LanguageRoutingDecision { outcome, actions })
    }

    pub(super) fn finish(&mut self) -> Result<LanguageRoutingFinish, LanguageRoutingError> {
        let end_sample = self
            .holdback
            .source_end_sample()
            .ok_or(LanguageRoutingError::SessionHasNoAudio)?;
        let mut policy = self.policy.clone();
        let mut holdback = self.holdback.clone();
        let final_span = policy.finish(end_sample)?;
        let mut actions = Vec::new();
        drain_as_current(&policy, end_sample, &mut holdback, &mut actions)?;
        self.policy = policy;
        self.holdback = holdback;
        Ok(LanguageRoutingFinish {
            final_span,
            actions,
        })
    }

    #[cfg(test)]
    pub(super) fn retained_range(&self) -> Option<SourceSampleRange> {
        self.holdback.retained_range()
    }
}

fn route_decision(
    policy: &AutomaticLanguageRoutingPolicy,
    outcome: &LanguageDecisionOutcome,
    holdback: &mut SourceAudioHoldback,
) -> Result<Vec<LanguageAudioAction>, LanguageRoutingError> {
    let mut actions = Vec::new();
    if let LanguageDecisionOutcome::Switched(transition) = outcome {
        let retained = holdback
            .retained_range()
            .ok_or(LanguageRoutingError::SessionHasNoAudio)?;
        if transition.boundary_sample < retained.start_sample {
            return Err(LanguageRoutingError::BoundaryAlreadyCommitted);
        }
        drain_as(
            &transition.from_language_bcp47,
            transition.boundary_sample,
            holdback,
            &mut actions,
        )?;
        actions.push(LanguageAudioAction::Switch((**transition).clone()));
    }
    drain_as_current(policy, policy.safe_commit_sample(), holdback, &mut actions)?;
    Ok(actions)
}

fn drain_as_current(
    policy: &AutomaticLanguageRoutingPolicy,
    end_sample: u64,
    holdback: &mut SourceAudioHoldback,
    actions: &mut Vec<LanguageAudioAction>,
) -> Result<(), LanguageRoutingError> {
    drain_as(
        policy.current_language_bcp47(),
        end_sample,
        holdback,
        actions,
    )
}

fn drain_as(
    language_bcp47: &str,
    end_sample: u64,
    holdback: &mut SourceAudioHoldback,
    actions: &mut Vec<LanguageAudioAction>,
) -> Result<(), LanguageRoutingError> {
    let Some(retained) = holdback.retained_range() else {
        return Ok(());
    };
    if end_sample < retained.start_sample {
        return Err(LanguageRoutingError::BoundaryAlreadyCommitted);
    }
    if end_sample == retained.start_sample {
        return Ok(());
    }
    let audio = holdback.drain_before(end_sample)?;
    actions.push(LanguageAudioAction::Feed {
        language_bcp47: language_bcp47.to_owned(),
        audio,
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::audio::{
        frame::AudioFrame,
        session::{SessionId, TrackId},
    };

    const SAMPLE_RATE: u32 = 16_000;
    const COMPONENT: &str = "local-lid@sha256:test";

    fn frame(second: u64) -> PreparedFrame {
        let start = second * u64::from(SAMPLE_RATE);
        let samples = (start..start + u64::from(SAMPLE_RATE))
            .map(|sample| sample as f32)
            .collect::<Vec<_>>();
        PreparedFrame {
            metadata: AudioFrame {
                session_id: SessionId::new("language-router-test").unwrap(),
                track_id: TrackId::new("microphone").unwrap(),
                sequence: second,
                sample_rate_hz: SAMPLE_RATE,
                channels: 1,
                start_ms: second * 1_000,
                duration_ms: 1_000,
                sample_count: samples.len(),
            },
            samples: Arc::from(samples),
        }
    }

    fn observation(start_sample: u64, language: Option<&str>) -> AcousticLanguageObservation {
        AcousticLanguageObservation::try_new(
            start_sample,
            start_sample + u64::from(SAMPLE_RATE),
            language,
            0.9,
            Some(0.8),
            Some(0.4),
            COMPONENT,
        )
        .unwrap()
    }

    fn router() -> LiveLanguageRouter {
        LiveLanguageRouter::new(
            "en-US",
            ["en-US", "fr-FR"],
            PrimaryBiasedInitialLanguageSelectorConfig::try_new(
                3,
                u64::from(SAMPLE_RATE),
                u64::from(SAMPLE_RATE),
                u64::from(SAMPLE_RATE) * 4,
                AcousticEvidenceThresholds::try_new(0.5, None, Some(0.1)).unwrap(),
            )
            .unwrap(),
            SustainedLanguageSwitchConfig::try_new(
                3,
                u64::from(SAMPLE_RATE),
                u64::from(SAMPLE_RATE),
                AcousticEvidenceThresholds::try_new(0.5, None, Some(0.1)).unwrap(),
            )
            .unwrap(),
            SAMPLE_RATE as usize * 8,
        )
        .unwrap()
    }

    #[test]
    fn accepted_switch_partitions_audio_without_duplicates_or_drops() {
        let mut router = router();
        for second in 0..4 {
            router.push(frame(second)).unwrap();
        }

        let mut actions = Vec::new();
        actions.extend(
            router
                .observe(observation(0, Some("en-US")))
                .unwrap()
                .actions,
        );
        actions.extend(
            router
                .observe(observation(8_000, Some("fr-FR")))
                .unwrap()
                .actions,
        );
        actions.extend(
            router
                .observe(observation(16_000, Some("fr-FR")))
                .unwrap()
                .actions,
        );
        let switch = router.observe(observation(24_000, Some("fr-FR"))).unwrap();
        assert!(matches!(
            switch.outcome,
            LanguageDecisionOutcome::Switched(_)
        ));
        actions.extend(switch.actions);
        actions.extend(router.finish().unwrap().actions);

        let mut cursor = 0;
        let mut languages = Vec::new();
        let mut switch_boundary = None;
        for action in actions {
            match action {
                LanguageAudioAction::Feed {
                    language_bcp47,
                    audio,
                } => {
                    assert_eq!(audio.range.start_sample, cursor);
                    assert_eq!(audio.samples.len() as u64, audio.range.len());
                    for (offset, sample) in audio.samples.iter().enumerate() {
                        assert_eq!(*sample, (cursor + offset as u64) as f32);
                    }
                    cursor = audio.range.end_sample;
                    languages.push((language_bcp47, audio.range));
                }
                LanguageAudioAction::Switch(transition) => {
                    assert_eq!(cursor, transition.boundary_sample);
                    switch_boundary = Some(transition.boundary_sample);
                }
            }
        }

        assert_eq!(switch_boundary, Some(12_000));
        assert_eq!(cursor, 64_000);
        assert!(languages
            .iter()
            .filter(|(language, _)| language == "en-US")
            .all(|(_, range)| range.end_sample <= 12_000));
        assert!(languages
            .iter()
            .filter(|(language, _)| language == "fr-FR")
            .all(|(_, range)| range.start_sample >= 12_000));
        assert_eq!(router.retained_range(), None);
    }

    #[test]
    fn ambiguous_window_advances_holdback_but_a_candidate_freezes_it() {
        let mut router = router();
        for second in 0..3 {
            router.push(frame(second)).unwrap();
        }
        router.observe(observation(0, Some("en-US"))).unwrap();
        assert_eq!(router.retained_range().unwrap().start_sample, 8_000);

        router.observe(observation(8_000, None)).unwrap();
        assert_eq!(router.retained_range().unwrap().start_sample, 16_000);

        router.observe(observation(16_000, Some("fr-FR"))).unwrap();
        assert_eq!(router.retained_range().unwrap().start_sample, 16_000);
    }

    #[test]
    fn discontinuous_frame_is_rejected_without_losing_pending_audio() {
        let mut router = router();
        router.push(frame(0)).unwrap();
        let retained = router.retained_range();

        assert!(matches!(
            router.push(frame(2)),
            Err(LanguageRoutingError::SourceAudio(
                SourceAudioError::Discontinuity { .. }
            ))
        ));
        assert_eq!(router.retained_range(), retained);
    }
}
