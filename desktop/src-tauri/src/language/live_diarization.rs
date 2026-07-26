use std::collections::BTreeSet;

pub use super::span_contract::{
    AcousticLanguageDecisionEvidence, LanguageSpan, LanguageSpanDisposition,
};

const MAX_SUPPORTED_LANGUAGES: usize = 128;
const MAX_COMPONENT_REVISION_BYTES: usize = 256;
const MAX_OBSERVATION_SAMPLES: u64 = 16_000 * 30;
const MAX_POLICY_SAMPLES: u64 = 16_000 * 60;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AcousticEvidenceThresholds {
    min_speech_ratio: f32,
    min_score: Option<f32>,
    min_margin: Option<f32>,
}

impl AcousticEvidenceThresholds {
    pub fn try_new(
        min_speech_ratio: f32,
        min_score: Option<f32>,
        min_margin: Option<f32>,
    ) -> Result<Self, LanguageDiarizationError> {
        if !valid_ratio(min_speech_ratio)
            || min_score.is_some_and(|score| !valid_ratio(score))
            || min_margin.is_some_and(|margin| !valid_ratio(margin))
        {
            return Err(LanguageDiarizationError::InvalidConfiguration);
        }
        Ok(Self {
            min_speech_ratio,
            min_score,
            min_margin,
        })
    }

    fn hold_reason(
        self,
        observation: &AcousticLanguageObservation,
        supported_languages: &BTreeSet<String>,
    ) -> Option<LanguageHoldReason> {
        if observation.speech_ratio < self.min_speech_ratio {
            Some(LanguageHoldReason::InsufficientSpeech)
        } else if observation.language_bcp47.is_none() {
            Some(LanguageHoldReason::Unknown)
        } else if !observation
            .language_bcp47
            .as_deref()
            .is_some_and(|language| supported_languages.contains(language))
        {
            Some(LanguageHoldReason::Unsupported)
        } else if self
            .min_score
            .is_some_and(|minimum| observation.score.is_none_or(|score| score < minimum))
        {
            Some(LanguageHoldReason::InsufficientScore)
        } else if self
            .min_margin
            .is_some_and(|minimum| observation.margin.is_none_or(|margin| margin < minimum))
        {
            Some(LanguageHoldReason::InsufficientMargin)
        } else {
            None
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SustainedLanguageSwitchConfig {
    required_observations: u8,
    min_candidate_samples: u64,
    max_observation_gap_samples: u64,
    evidence_thresholds: AcousticEvidenceThresholds,
}

impl SustainedLanguageSwitchConfig {
    pub fn try_new(
        required_observations: u8,
        min_candidate_samples: u64,
        max_observation_gap_samples: u64,
        evidence_thresholds: AcousticEvidenceThresholds,
    ) -> Result<Self, LanguageDiarizationError> {
        if !(2..=32).contains(&required_observations)
            || !(1..=MAX_POLICY_SAMPLES).contains(&min_candidate_samples)
            || !(1..=MAX_POLICY_SAMPLES).contains(&max_observation_gap_samples)
        {
            return Err(LanguageDiarizationError::InvalidConfiguration);
        }
        Ok(Self {
            required_observations,
            min_candidate_samples,
            max_observation_gap_samples,
            evidence_thresholds,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct AcousticLanguageObservation {
    pub start_sample: u64,
    pub end_sample: u64,
    pub language_bcp47: Option<String>,
    pub speech_ratio: f32,
    pub score: Option<f32>,
    pub margin: Option<f32>,
    pub component_revision: String,
}

impl AcousticLanguageObservation {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        start_sample: u64,
        end_sample: u64,
        language_bcp47: Option<&str>,
        speech_ratio: f32,
        score: Option<f32>,
        margin: Option<f32>,
        component_revision: &str,
    ) -> Result<Self, LanguageDiarizationError> {
        end_sample
            .checked_sub(start_sample)
            .filter(|length| (1..=MAX_OBSERVATION_SAMPLES).contains(length))
            .ok_or(LanguageDiarizationError::InvalidObservation)?;
        if !speech_ratio.is_finite()
            || !(0.0..=1.0).contains(&speech_ratio)
            || score.is_some_and(|value| !valid_ratio(value))
            || margin.is_some_and(|value| !valid_ratio(value))
            || component_revision.is_empty()
            || component_revision.len() > MAX_COMPONENT_REVISION_BYTES
            || !component_revision.is_ascii()
            || component_revision
                .bytes()
                .any(|byte| byte.is_ascii_control())
        {
            return Err(LanguageDiarizationError::InvalidObservation);
        }
        let language_bcp47 = language_bcp47
            .map(|language| {
                if super::valid_bcp47(language) {
                    Ok(language.to_owned())
                } else {
                    Err(LanguageDiarizationError::InvalidLanguage)
                }
            })
            .transpose()?;
        Ok(Self {
            start_sample,
            end_sample,
            language_bcp47,
            speech_ratio,
            score,
            margin,
            component_revision: component_revision.to_owned(),
        })
    }

    fn center_sample(&self) -> u64 {
        self.start_sample + (self.end_sample - self.start_sample) / 2
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct LanguageTransition {
    pub completed_span: Option<LanguageSpan>,
    pub from_language_bcp47: String,
    pub to_language_bcp47: String,
    pub boundary_sample: u64,
    pub decision_revision: u64,
    pub decision_evidence: AcousticLanguageDecisionEvidence,
    pub component_revision: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LanguageHoldReason {
    Unknown,
    Unsupported,
    InsufficientSpeech,
    InsufficientScore,
    InsufficientMargin,
}

#[derive(Debug, Clone, PartialEq)]
pub enum LanguageDecisionOutcome {
    Held(LanguageHoldReason),
    Stable,
    Pending {
        language_bcp47: String,
        observation_count: u32,
        evidence_samples: u64,
    },
    Switched(Box<LanguageTransition>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LanguageDiarizationError {
    InvalidConfiguration,
    InvalidObservation,
    InvalidLanguage,
    InvalidSupportedCatalog,
    OutOfOrderObservation,
    ComponentRevisionChanged,
    DecisionRevisionOverflow,
    EndBeforeCurrentSpan,
    SessionFinished,
}

impl std::fmt::Display for LanguageDiarizationError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::InvalidConfiguration => "language diarization configuration is invalid",
            Self::InvalidObservation => "acoustic language observation is invalid",
            Self::InvalidLanguage => "language observation is not canonical BCP 47",
            Self::InvalidSupportedCatalog => "supported local language catalog is invalid",
            Self::OutOfOrderObservation => "language observations are not source-time monotonic",
            Self::ComponentRevisionChanged => {
                "language detector revision changed during an active session"
            }
            Self::DecisionRevisionOverflow => "language decision revision overflowed",
            Self::EndBeforeCurrentSpan => "language span end precedes its current boundary",
            Self::SessionFinished => "language diarization session is already finished",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for LanguageDiarizationError {}

#[derive(Clone)]
struct CandidateEvidence {
    language_bcp47: String,
    first_center_sample: u64,
    last_center_sample: u64,
    decision_evidence: AcousticLanguageDecisionEvidence,
    component_revision: String,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PrimaryBiasedInitialLanguageSelectorConfig {
    required_alternate_observations: u8,
    min_alternate_candidate_samples: u64,
    max_observation_gap_samples: u64,
    selection_deadline_sample: u64,
    evidence_thresholds: AcousticEvidenceThresholds,
}

impl PrimaryBiasedInitialLanguageSelectorConfig {
    pub fn try_new(
        required_alternate_observations: u8,
        min_alternate_candidate_samples: u64,
        max_observation_gap_samples: u64,
        selection_deadline_sample: u64,
        evidence_thresholds: AcousticEvidenceThresholds,
    ) -> Result<Self, LanguageDiarizationError> {
        if !(2..=32).contains(&required_alternate_observations)
            || !(1..=MAX_POLICY_SAMPLES).contains(&min_alternate_candidate_samples)
            || !(1..=MAX_POLICY_SAMPLES).contains(&max_observation_gap_samples)
            || !(min_alternate_candidate_samples..=MAX_POLICY_SAMPLES)
                .contains(&selection_deadline_sample)
        {
            return Err(LanguageDiarizationError::InvalidConfiguration);
        }
        Ok(Self {
            required_alternate_observations,
            min_alternate_candidate_samples,
            max_observation_gap_samples,
            selection_deadline_sample,
            evidence_thresholds,
        })
    }
}

#[derive(Clone)]
pub struct PrimaryBiasedInitialLanguageSelector {
    config: PrimaryBiasedInitialLanguageSelectorConfig,
    primary_language_bcp47: String,
    supported_languages: BTreeSet<String>,
    last_observation_start_sample: Option<u64>,
    last_observation_center_sample: Option<u64>,
    active_component_revision: Option<String>,
    candidate: Option<CandidateEvidence>,
    selected: bool,
}

#[derive(Debug, Clone, PartialEq)]
struct InitialLanguageSelection {
    language_bcp47: String,
    outcome: LanguageDecisionOutcome,
    decision_evidence: Option<AcousticLanguageDecisionEvidence>,
    component_revision: Option<String>,
    last_observation_start_sample: Option<u64>,
    last_observation_center_sample: Option<u64>,
    safe_commit_sample: u64,
}

#[derive(Debug, Clone, PartialEq)]
enum InitialLanguageSelectionOutcome {
    Waiting(LanguageDecisionOutcome),
    Selected(InitialLanguageSelection),
}

impl PrimaryBiasedInitialLanguageSelector {
    pub fn new<I, S>(
        primary_language_bcp47: &str,
        supported_languages: I,
        config: PrimaryBiasedInitialLanguageSelectorConfig,
    ) -> Result<Self, LanguageDiarizationError>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let supported_languages =
            validate_supported_languages(primary_language_bcp47, supported_languages)?;
        Ok(Self {
            config,
            primary_language_bcp47: primary_language_bcp47.to_owned(),
            supported_languages,
            last_observation_start_sample: None,
            last_observation_center_sample: None,
            active_component_revision: None,
            candidate: None,
            selected: false,
        })
    }

    fn observe(
        &mut self,
        observation: AcousticLanguageObservation,
    ) -> Result<InitialLanguageSelectionOutcome, LanguageDiarizationError> {
        if self.selected {
            return Err(LanguageDiarizationError::SessionFinished);
        }
        let center = observation.center_sample();
        if self
            .last_observation_start_sample
            .is_some_and(|last| observation.start_sample <= last)
            || self
                .last_observation_center_sample
                .is_some_and(|last| center <= last)
        {
            return Err(LanguageDiarizationError::OutOfOrderObservation);
        }
        match &self.active_component_revision {
            Some(revision) if revision != &observation.component_revision => {
                return Err(LanguageDiarizationError::ComponentRevisionChanged)
            }
            Some(_) => {}
            None => self.active_component_revision = Some(observation.component_revision.clone()),
        }
        self.last_observation_start_sample = Some(observation.start_sample);
        self.last_observation_center_sample = Some(center);

        let hold_reason = self
            .config
            .evidence_thresholds
            .hold_reason(&observation, &self.supported_languages);

        if let Some(reason) = hold_reason {
            self.candidate = None;
            if center >= self.config.selection_deadline_sample {
                return Ok(InitialLanguageSelectionOutcome::Selected(
                    self.select_primary(LanguageDecisionOutcome::Held(reason), center),
                ));
            }
            return Ok(InitialLanguageSelectionOutcome::Waiting(
                LanguageDecisionOutcome::Held(reason),
            ));
        }

        let language = observation
            .language_bcp47
            .as_deref()
            .expect("qualified initial observation has a language");
        if language == self.primary_language_bcp47 {
            self.candidate = None;
            return Ok(InitialLanguageSelectionOutcome::Selected(
                self.select_primary(LanguageDecisionOutcome::Stable, center),
            ));
        }

        let can_extend = self.candidate.as_ref().is_some_and(|candidate| {
            candidate.language_bcp47 == language
                && observation.start_sample
                    <= candidate
                        .decision_evidence
                        .evidence_end_sample
                        .saturating_add(self.config.max_observation_gap_samples)
        });
        if can_extend {
            let candidate = self
                .candidate
                .as_mut()
                .expect("initial candidate extension was checked");
            candidate.last_center_sample = center;
            candidate.decision_evidence.evidence_end_sample = observation.end_sample;
            candidate.decision_evidence.observation_count = candidate
                .decision_evidence
                .observation_count
                .checked_add(1)
                .ok_or(LanguageDiarizationError::InvalidObservation)?;
            candidate.decision_evidence.minimum_score =
                minimum_optional(candidate.decision_evidence.minimum_score, observation.score);
            candidate.decision_evidence.minimum_margin = minimum_optional(
                candidate.decision_evidence.minimum_margin,
                observation.margin,
            );
        } else {
            self.candidate = Some(CandidateEvidence {
                language_bcp47: language.to_owned(),
                first_center_sample: center,
                last_center_sample: center,
                decision_evidence: AcousticLanguageDecisionEvidence {
                    evidence_start_sample: observation.start_sample,
                    evidence_end_sample: observation.end_sample,
                    observation_count: 1,
                    minimum_score: observation.score,
                    minimum_margin: observation.margin,
                },
                component_revision: observation.component_revision,
            });
        }

        let candidate = self.candidate.as_ref().expect("initial candidate was set");
        let evidence_samples = candidate
            .last_center_sample
            .saturating_sub(candidate.first_center_sample);
        if candidate.decision_evidence.observation_count
            >= u32::from(self.config.required_alternate_observations)
            && evidence_samples >= self.config.min_alternate_candidate_samples
        {
            let candidate = self
                .candidate
                .take()
                .expect("qualified initial candidate exists");
            self.selected = true;
            return Ok(InitialLanguageSelectionOutcome::Selected(
                InitialLanguageSelection {
                    language_bcp47: candidate.language_bcp47,
                    outcome: LanguageDecisionOutcome::Stable,
                    decision_evidence: Some(candidate.decision_evidence),
                    component_revision: Some(candidate.component_revision),
                    last_observation_start_sample: self.last_observation_start_sample,
                    last_observation_center_sample: self.last_observation_center_sample,
                    safe_commit_sample: candidate.last_center_sample,
                },
            ));
        }
        if center >= self.config.selection_deadline_sample {
            return Ok(InitialLanguageSelectionOutcome::Selected(
                self.select_primary(LanguageDecisionOutcome::Stable, center),
            ));
        }
        Ok(InitialLanguageSelectionOutcome::Waiting(
            LanguageDecisionOutcome::Pending {
                language_bcp47: candidate.language_bcp47.clone(),
                observation_count: candidate.decision_evidence.observation_count,
                evidence_samples,
            },
        ))
    }

    fn select_primary(
        &mut self,
        outcome: LanguageDecisionOutcome,
        safe_commit_sample: u64,
    ) -> InitialLanguageSelection {
        self.selected = true;
        InitialLanguageSelection {
            language_bcp47: self.primary_language_bcp47.clone(),
            outcome,
            decision_evidence: None,
            component_revision: self.active_component_revision.clone(),
            last_observation_start_sample: self.last_observation_start_sample,
            last_observation_center_sample: self.last_observation_center_sample,
            safe_commit_sample,
        }
    }
}

#[derive(Clone)]
pub struct SustainedLanguageSwitchDetector {
    config: SustainedLanguageSwitchConfig,
    supported_languages: BTreeSet<String>,
    current_language_bcp47: String,
    current_span_start_sample: u64,
    current_disposition: LanguageSpanDisposition,
    current_component_revision: Option<String>,
    current_decision_evidence: Option<AcousticLanguageDecisionEvidence>,
    decision_revision: u64,
    last_observation_start_sample: Option<u64>,
    last_observation_center_sample: Option<u64>,
    last_current_center_sample: Option<u64>,
    safe_commit_sample: u64,
    active_component_revision: Option<String>,
    candidate: Option<CandidateEvidence>,
    finished: bool,
}

impl SustainedLanguageSwitchDetector {
    pub fn new<I, S>(
        primary_language_bcp47: &str,
        supported_languages: I,
        config: SustainedLanguageSwitchConfig,
    ) -> Result<Self, LanguageDiarizationError>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let supported = validate_supported_languages(primary_language_bcp47, supported_languages)?;
        Ok(Self {
            config,
            supported_languages: supported,
            current_language_bcp47: primary_language_bcp47.to_owned(),
            current_span_start_sample: 0,
            current_disposition: LanguageSpanDisposition::ConfirmedPrimary,
            current_component_revision: None,
            current_decision_evidence: None,
            decision_revision: 1,
            last_observation_start_sample: None,
            last_observation_center_sample: None,
            last_current_center_sample: None,
            safe_commit_sample: 0,
            active_component_revision: None,
            candidate: None,
            finished: false,
        })
    }

    fn from_initial_selection(
        primary_language_bcp47: &str,
        supported_languages: BTreeSet<String>,
        config: SustainedLanguageSwitchConfig,
        selection: InitialLanguageSelection,
    ) -> Self {
        let selected_alternate = selection.language_bcp47 != primary_language_bcp47;
        Self {
            config,
            supported_languages,
            current_language_bcp47: selection.language_bcp47,
            current_span_start_sample: 0,
            current_disposition: if selected_alternate {
                LanguageSpanDisposition::AcousticInitialSelection
            } else {
                LanguageSpanDisposition::ConfirmedPrimary
            },
            current_component_revision: selected_alternate
                .then(|| selection.component_revision.clone())
                .flatten(),
            current_decision_evidence: selected_alternate
                .then(|| selection.decision_evidence.clone())
                .flatten(),
            decision_revision: 1,
            last_observation_start_sample: selection.last_observation_start_sample,
            last_observation_center_sample: selection.last_observation_center_sample,
            last_current_center_sample: selection.last_observation_center_sample,
            safe_commit_sample: selection.safe_commit_sample,
            active_component_revision: selection.component_revision,
            candidate: None,
            finished: false,
        }
    }

    pub fn current_language_bcp47(&self) -> &str {
        &self.current_language_bcp47
    }

    pub fn decision_revision(&self) -> u64 {
        self.decision_revision
    }

    /// Audio before this source position can no longer precede a future
    /// language boundary under the accepted policy state.
    pub fn safe_commit_sample(&self) -> u64 {
        self.safe_commit_sample
    }

    pub fn observe(
        &mut self,
        observation: AcousticLanguageObservation,
    ) -> Result<LanguageDecisionOutcome, LanguageDiarizationError> {
        if self.finished {
            return Err(LanguageDiarizationError::SessionFinished);
        }
        let center = observation.center_sample();
        if self
            .last_observation_start_sample
            .is_some_and(|last| observation.start_sample <= last)
            || self
                .last_observation_center_sample
                .is_some_and(|last| center <= last)
        {
            return Err(LanguageDiarizationError::OutOfOrderObservation);
        }
        match &self.active_component_revision {
            Some(revision) if revision != &observation.component_revision => {
                return Err(LanguageDiarizationError::ComponentRevisionChanged)
            }
            Some(_) => {}
            None => self.active_component_revision = Some(observation.component_revision.clone()),
        }
        self.last_observation_start_sample = Some(observation.start_sample);
        self.last_observation_center_sample = Some(center);

        if let Some(reason) = self
            .config
            .evidence_thresholds
            .hold_reason(&observation, &self.supported_languages)
        {
            return Ok(self.hold_current(center, reason));
        }
        let language = observation
            .language_bcp47
            .as_deref()
            .expect("qualified language observation has a language");

        if language == self.current_language_bcp47 {
            self.candidate = None;
            self.last_current_center_sample = Some(center);
            self.safe_commit_sample = center;
            return Ok(LanguageDecisionOutcome::Stable);
        }

        let can_extend = self.candidate.as_ref().is_some_and(|candidate| {
            candidate.language_bcp47 == language
                && observation.start_sample
                    <= candidate
                        .decision_evidence
                        .evidence_end_sample
                        .saturating_add(self.config.max_observation_gap_samples)
        });
        if can_extend {
            let candidate = self
                .candidate
                .as_mut()
                .expect("candidate extension was checked");
            candidate.last_center_sample = center;
            candidate.decision_evidence.evidence_end_sample = observation.end_sample;
            candidate.decision_evidence.observation_count = candidate
                .decision_evidence
                .observation_count
                .checked_add(1)
                .ok_or(LanguageDiarizationError::InvalidObservation)?;
            candidate.decision_evidence.minimum_score =
                minimum_optional(candidate.decision_evidence.minimum_score, observation.score);
            candidate.decision_evidence.minimum_margin = minimum_optional(
                candidate.decision_evidence.minimum_margin,
                observation.margin,
            );
        } else {
            self.candidate = Some(CandidateEvidence {
                language_bcp47: language.to_owned(),
                first_center_sample: center,
                last_center_sample: center,
                decision_evidence: AcousticLanguageDecisionEvidence {
                    evidence_start_sample: observation.start_sample,
                    evidence_end_sample: observation.end_sample,
                    observation_count: 1,
                    minimum_score: observation.score,
                    minimum_margin: observation.margin,
                },
                component_revision: observation.component_revision,
            });
        }

        let candidate = self.candidate.as_ref().expect("candidate was set");
        let evidence_samples = candidate
            .last_center_sample
            .saturating_sub(candidate.first_center_sample);
        if candidate.decision_evidence.observation_count
            < u32::from(self.config.required_observations)
            || evidence_samples < self.config.min_candidate_samples
        {
            return Ok(LanguageDecisionOutcome::Pending {
                language_bcp47: candidate.language_bcp47.clone(),
                observation_count: candidate.decision_evidence.observation_count,
                evidence_samples,
            });
        }

        let candidate = self.candidate.take().expect("qualified candidate exists");
        let boundary_sample = self
            .last_current_center_sample
            .filter(|last| *last < candidate.first_center_sample)
            .map(|last| last + (candidate.first_center_sample - last) / 2)
            .unwrap_or(candidate.first_center_sample)
            .max(self.current_span_start_sample);
        let completed_span = self.span_until(boundary_sample)?;
        let from_language_bcp47 = std::mem::replace(
            &mut self.current_language_bcp47,
            candidate.language_bcp47.clone(),
        );
        self.current_span_start_sample = boundary_sample;
        self.current_disposition = LanguageSpanDisposition::AcousticSwitch;
        self.current_component_revision = Some(candidate.component_revision.clone());
        self.current_decision_evidence = Some(candidate.decision_evidence.clone());
        self.decision_revision = self
            .decision_revision
            .checked_add(1)
            .ok_or(LanguageDiarizationError::DecisionRevisionOverflow)?;
        self.last_current_center_sample = Some(candidate.last_center_sample);
        self.safe_commit_sample = candidate.last_center_sample;

        Ok(LanguageDecisionOutcome::Switched(Box::new(
            LanguageTransition {
                completed_span,
                from_language_bcp47,
                to_language_bcp47: candidate.language_bcp47,
                boundary_sample,
                decision_revision: self.decision_revision,
                decision_evidence: candidate.decision_evidence,
                component_revision: candidate.component_revision,
            },
        )))
    }

    pub fn finish(
        &mut self,
        end_sample: u64,
    ) -> Result<Option<LanguageSpan>, LanguageDiarizationError> {
        if self.finished {
            return Err(LanguageDiarizationError::SessionFinished);
        }
        let span = self.span_until(end_sample)?;
        self.finished = true;
        self.candidate = None;
        Ok(span)
    }

    fn span_until(
        &self,
        end_sample: u64,
    ) -> Result<Option<LanguageSpan>, LanguageDiarizationError> {
        if end_sample < self.current_span_start_sample {
            return Err(LanguageDiarizationError::EndBeforeCurrentSpan);
        }
        if end_sample == self.current_span_start_sample {
            return Ok(None);
        }
        Ok(Some(LanguageSpan {
            start_sample: self.current_span_start_sample,
            end_sample,
            language_bcp47: self.current_language_bcp47.clone(),
            decision_revision: self.decision_revision,
            disposition: self.current_disposition,
            component_revision: self.current_component_revision.clone(),
            decision_evidence: self.current_decision_evidence.clone(),
        }))
    }

    fn hold_current(
        &mut self,
        center_sample: u64,
        reason: LanguageHoldReason,
    ) -> LanguageDecisionOutcome {
        self.candidate = None;
        self.last_current_center_sample = Some(center_sample);
        self.safe_commit_sample = center_sample;
        LanguageDecisionOutcome::Held(reason)
    }
}

/// Composes bounded startup selection with the later switch detector. Audio is
/// held at source sample zero until startup selects the primary locale, selects
/// a qualified alternate, or reaches its primary-fallback deadline.
#[derive(Clone)]
pub struct AutomaticLanguageRoutingPolicy {
    primary_language_bcp47: String,
    supported_languages: BTreeSet<String>,
    sustained_config: SustainedLanguageSwitchConfig,
    initial_selector: Option<PrimaryBiasedInitialLanguageSelector>,
    sustained_switch_detector: Option<SustainedLanguageSwitchDetector>,
}

impl AutomaticLanguageRoutingPolicy {
    pub fn new<I, S>(
        primary_language_bcp47: &str,
        supported_languages: I,
        initial_config: PrimaryBiasedInitialLanguageSelectorConfig,
        sustained_config: SustainedLanguageSwitchConfig,
    ) -> Result<Self, LanguageDiarizationError>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let supported_languages =
            validate_supported_languages(primary_language_bcp47, supported_languages)?;
        let initial_selector = PrimaryBiasedInitialLanguageSelector::new(
            primary_language_bcp47,
            supported_languages.iter().map(String::as_str),
            initial_config,
        )?;
        Ok(Self {
            primary_language_bcp47: primary_language_bcp47.to_owned(),
            supported_languages,
            sustained_config,
            initial_selector: Some(initial_selector),
            sustained_switch_detector: None,
        })
    }

    pub fn current_language_bcp47(&self) -> &str {
        self.sustained_switch_detector
            .as_ref()
            .map_or(&self.primary_language_bcp47, |detector| {
                detector.current_language_bcp47()
            })
    }

    pub fn decision_revision(&self) -> u64 {
        self.sustained_switch_detector
            .as_ref()
            .map_or(1, SustainedLanguageSwitchDetector::decision_revision)
    }

    pub fn safe_commit_sample(&self) -> u64 {
        self.sustained_switch_detector
            .as_ref()
            .map_or(0, SustainedLanguageSwitchDetector::safe_commit_sample)
    }

    pub fn observe(
        &mut self,
        observation: AcousticLanguageObservation,
    ) -> Result<LanguageDecisionOutcome, LanguageDiarizationError> {
        if let Some(detector) = self.sustained_switch_detector.as_mut() {
            return detector.observe(observation);
        }
        let initial_outcome = self
            .initial_selector
            .as_mut()
            .ok_or(LanguageDiarizationError::SessionFinished)?
            .observe(observation)?;
        let selection = match initial_outcome {
            InitialLanguageSelectionOutcome::Waiting(outcome) => return Ok(outcome),
            InitialLanguageSelectionOutcome::Selected(selection) => selection,
        };

        let selected_alternate = selection.language_bcp47 != self.primary_language_bcp47;
        let outcome = if selected_alternate {
            LanguageDecisionOutcome::Switched(Box::new(LanguageTransition {
                completed_span: None,
                from_language_bcp47: self.primary_language_bcp47.clone(),
                to_language_bcp47: selection.language_bcp47.clone(),
                boundary_sample: 0,
                decision_revision: 1,
                decision_evidence: selection
                    .decision_evidence
                    .clone()
                    .expect("alternate startup selection has bounded evidence"),
                component_revision: selection
                    .component_revision
                    .clone()
                    .expect("alternate startup selection has a component revision"),
            }))
        } else {
            selection.outcome.clone()
        };
        self.sustained_switch_detector =
            Some(SustainedLanguageSwitchDetector::from_initial_selection(
                &self.primary_language_bcp47,
                self.supported_languages.clone(),
                self.sustained_config,
                selection,
            ));
        self.initial_selector = None;
        Ok(outcome)
    }

    pub fn finish(
        &mut self,
        end_sample: u64,
    ) -> Result<Option<LanguageSpan>, LanguageDiarizationError> {
        if self.sustained_switch_detector.is_none() {
            self.sustained_switch_detector = Some(SustainedLanguageSwitchDetector::new(
                &self.primary_language_bcp47,
                self.supported_languages.iter().map(String::as_str),
                self.sustained_config,
            )?);
            self.initial_selector = None;
        }
        self.sustained_switch_detector
            .as_mut()
            .expect("finish initializes the sustained switch detector")
            .finish(end_sample)
    }
}

fn validate_supported_languages<I, S>(
    primary_language_bcp47: &str,
    supported_languages: I,
) -> Result<BTreeSet<String>, LanguageDiarizationError>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    if !super::valid_bcp47(primary_language_bcp47) {
        return Err(LanguageDiarizationError::InvalidSupportedCatalog);
    }
    let mut supported = BTreeSet::new();
    for language in supported_languages {
        let language = language.as_ref();
        if !super::valid_bcp47(language)
            || !supported.insert(language.to_owned())
            || supported.len() > MAX_SUPPORTED_LANGUAGES
        {
            return Err(LanguageDiarizationError::InvalidSupportedCatalog);
        }
    }
    if supported.is_empty() || !supported.contains(primary_language_bcp47) {
        return Err(LanguageDiarizationError::InvalidSupportedCatalog);
    }
    Ok(supported)
}

fn valid_ratio(value: f32) -> bool {
    value.is_finite() && (0.0..=1.0).contains(&value)
}

fn minimum_optional(left: Option<f32>, right: Option<f32>) -> Option<f32> {
    match (left, right) {
        (Some(left), Some(right)) => Some(left.min(right)),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const COMPONENT_REVISION: &str = "lid-candidate@sha256:abc123";

    fn thresholds() -> AcousticEvidenceThresholds {
        AcousticEvidenceThresholds::try_new(0.5, Some(0.6), Some(0.1)).unwrap()
    }

    fn config() -> SustainedLanguageSwitchConfig {
        SustainedLanguageSwitchConfig::try_new(3, 16_000, 16_000, thresholds()).unwrap()
    }

    fn policy() -> SustainedLanguageSwitchDetector {
        SustainedLanguageSwitchDetector::new("en-US", ["en-US", "fr-FR", "de-DE"], config())
            .unwrap()
    }

    fn automatic_policy() -> AutomaticLanguageRoutingPolicy {
        AutomaticLanguageRoutingPolicy::new(
            "en-US",
            ["en-US", "fr-FR"],
            PrimaryBiasedInitialLanguageSelectorConfig::try_new(
                3,
                16_000,
                16_000,
                64_000,
                thresholds(),
            )
            .unwrap(),
            config(),
        )
        .unwrap()
    }

    fn observation(start_sample: u64, language_bcp47: Option<&str>) -> AcousticLanguageObservation {
        AcousticLanguageObservation::try_new(
            start_sample,
            start_sample + 16_000,
            language_bcp47,
            0.9,
            Some(0.8),
            Some(0.4),
            COMPONENT_REVISION,
        )
        .unwrap()
    }

    #[test]
    fn configuration_rejects_unbounded_or_nonsensical_thresholds() {
        assert!(AcousticEvidenceThresholds::try_new(1.1, None, None).is_err());
        assert!(AcousticEvidenceThresholds::try_new(0.5, Some(-0.1), None).is_err());
        assert!(AcousticEvidenceThresholds::try_new(0.5, Some(1.1), None).is_err());
        assert!(AcousticEvidenceThresholds::try_new(0.5, None, Some(f32::NAN)).is_err());
        assert!(SustainedLanguageSwitchConfig::try_new(1, 16_000, 16_000, thresholds()).is_err());
        assert!(SustainedLanguageSwitchConfig::try_new(3, 0, 16_000, thresholds()).is_err());
        assert!(SustainedLanguageSwitchConfig::try_new(3, 16_000, 0, thresholds()).is_err());
        assert!(PrimaryBiasedInitialLanguageSelectorConfig::try_new(
            1,
            16_000,
            16_000,
            64_000,
            thresholds(),
        )
        .is_err());
        assert!(PrimaryBiasedInitialLanguageSelectorConfig::try_new(
            3,
            32_000,
            16_000,
            16_000,
            thresholds(),
        )
        .is_err());
    }

    #[test]
    fn policy_requires_a_valid_primary_inside_a_bounded_unique_catalog() {
        assert!(SustainedLanguageSwitchDetector::new("en-US", ["fr-FR"], config()).is_err());
        assert!(
            SustainedLanguageSwitchDetector::new("en-US", ["en-US", "en-US"], config()).is_err()
        );
        assert!(SustainedLanguageSwitchDetector::new("english", ["english"], config()).is_err());
    }

    #[test]
    fn initial_selector_latches_primary_on_the_first_qualified_primary_window() {
        let mut policy = automatic_policy();

        assert_eq!(
            policy.observe(observation(0, Some("en-US"))).unwrap(),
            LanguageDecisionOutcome::Stable
        );
        assert_eq!(policy.current_language_bcp47(), "en-US");
        assert_eq!(policy.safe_commit_sample(), 8_000);
    }

    #[test]
    fn initial_alternate_requires_repeated_evidence_and_owns_source_sample_zero() {
        let mut policy = automatic_policy();
        for start in [0, 8_000] {
            assert!(matches!(
                policy.observe(observation(start, Some("fr-FR"))).unwrap(),
                LanguageDecisionOutcome::Pending { .. }
            ));
            assert_eq!(policy.safe_commit_sample(), 0);
        }
        let LanguageDecisionOutcome::Switched(transition) =
            policy.observe(observation(16_000, Some("fr-FR"))).unwrap()
        else {
            panic!("three stable alternate observations must select the initial language");
        };

        assert_eq!(transition.boundary_sample, 0);
        assert_eq!(transition.completed_span, None);
        assert_eq!(transition.from_language_bcp47, "en-US");
        assert_eq!(transition.to_language_bcp47, "fr-FR");
        assert_eq!(transition.decision_revision, 1);
        assert_eq!(policy.current_language_bcp47(), "fr-FR");
        assert_eq!(
            policy.finish(48_000).unwrap(),
            Some(LanguageSpan {
                start_sample: 0,
                end_sample: 48_000,
                language_bcp47: "fr-FR".into(),
                decision_revision: 1,
                disposition: LanguageSpanDisposition::AcousticInitialSelection,
                component_revision: Some(COMPONENT_REVISION.into()),
                decision_evidence: Some(AcousticLanguageDecisionEvidence {
                    evidence_start_sample: 0,
                    evidence_end_sample: 32_000,
                    observation_count: 3,
                    minimum_score: Some(0.8),
                    minimum_margin: Some(0.4),
                }),
            })
        );
    }

    #[test]
    fn startup_ambiguity_holds_audio_then_falls_back_to_primary_at_the_deadline() {
        let mut policy = AutomaticLanguageRoutingPolicy::new(
            "en-US",
            ["en-US", "fr-FR"],
            PrimaryBiasedInitialLanguageSelectorConfig::try_new(
                3,
                16_000,
                16_000,
                24_000,
                thresholds(),
            )
            .unwrap(),
            config(),
        )
        .unwrap();

        assert_eq!(
            policy.observe(observation(0, None)).unwrap(),
            LanguageDecisionOutcome::Held(LanguageHoldReason::Unknown)
        );
        assert_eq!(policy.safe_commit_sample(), 0);
        assert_eq!(
            policy.observe(observation(16_000, None)).unwrap(),
            LanguageDecisionOutcome::Held(LanguageHoldReason::Unknown)
        );
        assert_eq!(policy.current_language_bcp47(), "en-US");
        assert_eq!(policy.safe_commit_sample(), 24_000);
    }

    #[test]
    fn sustained_detector_starts_only_after_the_initial_language_is_latched() {
        let mut policy = automatic_policy();
        for start in [0, 8_000, 16_000] {
            policy.observe(observation(start, Some("fr-FR"))).unwrap();
        }
        for start in [24_000, 32_000] {
            assert!(matches!(
                policy.observe(observation(start, Some("en-US"))).unwrap(),
                LanguageDecisionOutcome::Pending { .. }
            ));
        }
        let LanguageDecisionOutcome::Switched(transition) =
            policy.observe(observation(40_000, Some("en-US"))).unwrap()
        else {
            panic!("the sustained detector must own the later switch");
        };

        assert_eq!(transition.from_language_bcp47, "fr-FR");
        assert_eq!(transition.to_language_bcp47, "en-US");
        assert_eq!(transition.decision_revision, 2);
        assert_eq!(
            transition.completed_span.unwrap().disposition,
            LanguageSpanDisposition::AcousticInitialSelection
        );
    }

    #[test]
    fn stable_repeated_evidence_closes_one_span_at_a_deterministic_boundary() {
        let mut policy = policy();
        assert_eq!(
            policy.observe(observation(0, Some("en-US"))).unwrap(),
            LanguageDecisionOutcome::Stable
        );

        for start in [8_000, 16_000] {
            assert!(matches!(
                policy.observe(observation(start, Some("fr-FR"))).unwrap(),
                LanguageDecisionOutcome::Pending { .. }
            ));
        }
        let LanguageDecisionOutcome::Switched(transition) =
            policy.observe(observation(24_000, Some("fr-FR"))).unwrap()
        else {
            panic!("third stable observation must switch");
        };

        assert_eq!(transition.from_language_bcp47, "en-US");
        assert_eq!(transition.to_language_bcp47, "fr-FR");
        assert_eq!(transition.boundary_sample, 12_000);
        assert_eq!(transition.decision_revision, 2);
        assert_eq!(transition.decision_evidence.observation_count, 3);
        assert_eq!(transition.decision_evidence.evidence_start_sample, 8_000);
        assert_eq!(transition.decision_evidence.evidence_end_sample, 40_000);
        assert_eq!(transition.decision_evidence.minimum_score, Some(0.8));
        assert_eq!(transition.decision_evidence.minimum_margin, Some(0.4));
        assert_eq!(transition.component_revision, COMPONENT_REVISION);
        assert_eq!(
            transition.completed_span,
            Some(LanguageSpan {
                start_sample: 0,
                end_sample: 12_000,
                language_bcp47: "en-US".into(),
                decision_revision: 1,
                disposition: LanguageSpanDisposition::ConfirmedPrimary,
                component_revision: None,
                decision_evidence: None,
            })
        );

        assert_eq!(
            policy.finish(48_000).unwrap(),
            Some(LanguageSpan {
                start_sample: 12_000,
                end_sample: 48_000,
                language_bcp47: "fr-FR".into(),
                decision_revision: 2,
                disposition: LanguageSpanDisposition::AcousticSwitch,
                component_revision: Some(COMPONENT_REVISION.into()),
                decision_evidence: Some(AcousticLanguageDecisionEvidence {
                    evidence_start_sample: 8_000,
                    evidence_end_sample: 40_000,
                    observation_count: 3,
                    minimum_score: Some(0.8),
                    minimum_margin: Some(0.4),
                }),
            })
        );
    }

    #[test]
    fn one_window_or_rapidly_alternating_labels_never_switch() {
        let mut policy = policy();
        for (start, language) in [
            (0, "fr-FR"),
            (8_000, "de-DE"),
            (16_000, "fr-FR"),
            (24_000, "de-DE"),
        ] {
            assert!(matches!(
                policy.observe(observation(start, Some(language))).unwrap(),
                LanguageDecisionOutcome::Pending { .. }
            ));
        }
        assert_eq!(policy.current_language_bcp47(), "en-US");
        assert_eq!(policy.decision_revision(), 1);
    }

    #[test]
    fn ambiguity_and_long_gaps_reset_candidate_evidence() {
        let mut policy = policy();
        assert!(matches!(
            policy.observe(observation(0, Some("fr-FR"))).unwrap(),
            LanguageDecisionOutcome::Pending { .. }
        ));
        assert_eq!(
            policy.observe(observation(8_000, None)).unwrap(),
            LanguageDecisionOutcome::Held(LanguageHoldReason::Unknown)
        );
        assert!(matches!(
            policy.observe(observation(64_000, Some("fr-FR"))).unwrap(),
            LanguageDecisionOutcome::Pending {
                observation_count: 1,
                ..
            }
        ));
    }

    #[test]
    fn safe_commit_advances_on_held_or_stable_audio_and_freezes_during_a_candidate() {
        let mut policy = policy();
        assert_eq!(policy.safe_commit_sample(), 0);

        policy.observe(observation(0, Some("en-US"))).unwrap();
        assert_eq!(policy.safe_commit_sample(), 8_000);

        policy.observe(observation(8_000, None)).unwrap();
        assert_eq!(policy.safe_commit_sample(), 16_000);

        policy.observe(observation(16_000, Some("fr-FR"))).unwrap();
        assert_eq!(policy.safe_commit_sample(), 16_000);
        policy.observe(observation(24_000, Some("fr-FR"))).unwrap();
        assert_eq!(policy.safe_commit_sample(), 16_000);

        assert!(matches!(
            policy.observe(observation(32_000, Some("fr-FR"))).unwrap(),
            LanguageDecisionOutcome::Switched(_)
        ));
        assert_eq!(policy.safe_commit_sample(), 40_000);
    }

    #[test]
    fn weak_speech_score_margin_and_unsupported_labels_hold_the_current_language() {
        let mut policy = policy();
        let weak_speech = AcousticLanguageObservation::try_new(
            0,
            16_000,
            Some("fr-FR"),
            0.2,
            Some(0.9),
            Some(0.5),
            COMPONENT_REVISION,
        )
        .unwrap();
        assert_eq!(
            policy.observe(weak_speech).unwrap(),
            LanguageDecisionOutcome::Held(LanguageHoldReason::InsufficientSpeech)
        );

        let weak_score = AcousticLanguageObservation::try_new(
            8_000,
            24_000,
            Some("fr-FR"),
            0.9,
            Some(0.5),
            Some(0.4),
            COMPONENT_REVISION,
        )
        .unwrap();
        assert_eq!(
            policy.observe(weak_score).unwrap(),
            LanguageDecisionOutcome::Held(LanguageHoldReason::InsufficientScore)
        );

        let weak_margin = AcousticLanguageObservation::try_new(
            16_000,
            32_000,
            Some("fr-FR"),
            0.9,
            Some(0.7),
            None,
            COMPONENT_REVISION,
        )
        .unwrap();
        assert_eq!(
            policy.observe(weak_margin).unwrap(),
            LanguageDecisionOutcome::Held(LanguageHoldReason::InsufficientMargin)
        );
        assert_eq!(
            policy.observe(observation(24_000, Some("es-ES"))).unwrap(),
            LanguageDecisionOutcome::Held(LanguageHoldReason::Unsupported)
        );
        assert_eq!(policy.current_language_bcp47(), "en-US");
    }

    #[test]
    fn observations_are_monotonic_and_one_session_cannot_mix_model_revisions() {
        let mut policy = policy();
        policy.observe(observation(8_000, Some("en-US"))).unwrap();
        assert_eq!(
            policy.observe(observation(4_000, Some("en-US"))),
            Err(LanguageDiarizationError::OutOfOrderObservation)
        );

        let changed_revision = AcousticLanguageObservation::try_new(
            16_000,
            32_000,
            Some("en-US"),
            0.9,
            Some(0.8),
            Some(0.4),
            "different-model@sha256:def456",
        )
        .unwrap();
        assert_eq!(
            policy.observe(changed_revision),
            Err(LanguageDiarizationError::ComponentRevisionChanged)
        );
    }

    #[test]
    fn malformed_observations_and_impossible_finish_offsets_fail_closed() {
        assert!(AcousticLanguageObservation::try_new(
            10,
            10,
            Some("en-US"),
            0.9,
            None,
            None,
            COMPONENT_REVISION,
        )
        .is_err());
        assert!(AcousticLanguageObservation::try_new(
            0,
            10,
            Some("english"),
            0.9,
            None,
            None,
            COMPONENT_REVISION,
        )
        .is_err());
        assert!(AcousticLanguageObservation::try_new(
            0,
            10,
            Some("en-US"),
            0.9,
            Some(1.1),
            Some(0.1),
            COMPONENT_REVISION,
        )
        .is_err());
        assert!(AcousticLanguageObservation::try_new(
            0,
            10,
            Some("en-US"),
            0.9,
            Some(0.8),
            Some(1.1),
            COMPONENT_REVISION,
        )
        .is_err());
        assert!(AcousticLanguageObservation::try_new(
            0,
            10,
            Some("en-US"),
            f32::NAN,
            None,
            None,
            COMPONENT_REVISION,
        )
        .is_err());

        let mut policy = policy();
        let transition = [0, 8_000, 16_000]
            .into_iter()
            .find_map(
                |start| match policy.observe(observation(start, Some("fr-FR"))).unwrap() {
                    LanguageDecisionOutcome::Switched(transition) => Some(transition),
                    _ => None,
                },
            )
            .unwrap();
        assert_eq!(
            policy.finish(transition.boundary_sample - 1),
            Err(LanguageDiarizationError::EndBeforeCurrentSpan)
        );
    }
}
