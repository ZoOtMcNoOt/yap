//! Hash-bound source-time language evidence for one live capture.

#[cfg(test)]
use super::live_diarization::AcousticLanguageDecisionEvidence;
use super::live_diarization::{LanguageSpan, LanguageSpanDisposition};
use super::span_contract::{
    valid_component_revision, validate_sequence, LanguageSpanBoundaryAuthority,
    LanguageSpanSequenceError, LANGUAGE_SPAN_SAMPLE_RATE_HZ, LANGUAGE_SPAN_SCHEMA_VERSION,
};

pub const LIVE_LANGUAGE_EVIDENCE_SCHEMA_VERSION: u16 = LANGUAGE_SPAN_SCHEMA_VERSION;
pub const LIVE_LANGUAGE_SAMPLE_RATE_HZ: u32 = LANGUAGE_SPAN_SAMPLE_RATE_HZ;
const MAX_LANGUAGE_SPANS: usize = 2_048;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LiveLanguageMode {
    FixedPrimary,
    Automatic,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LiveLanguageStatus {
    Complete,
    Degraded,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LiveLanguageDegradation {
    ArtifactsUnavailable,
    DetectorFailed,
    RoutingFailed,
    SourceDiscontinuity,
    HoldbackCapacityExceeded,
}

#[derive(Debug, Clone, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LiveLanguageEvidence {
    pub schema_version: u16,
    pub sample_rate_hz: u32,
    pub source_end_sample: u64,
    pub boundary_authority: LanguageSpanBoundaryAuthority,
    pub primary_language_bcp47: String,
    pub mode: LiveLanguageMode,
    pub status: LiveLanguageStatus,
    pub degradation: Option<LiveLanguageDegradation>,
    pub detector_component_revision: Option<String>,
    pub spans: Vec<LanguageSpan>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LiveLanguageEvidenceError {
    InvalidEnvelope,
    InvalidComponent,
    InvalidSpan,
    InvalidCoverage,
}

impl std::fmt::Display for LiveLanguageEvidenceError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::InvalidEnvelope => "live language evidence envelope is invalid",
            Self::InvalidComponent => "live language evidence component is invalid",
            Self::InvalidSpan => "live language evidence span is invalid",
            Self::InvalidCoverage => "live language evidence does not cover source time",
        })
    }
}

impl std::error::Error for LiveLanguageEvidenceError {}

impl LiveLanguageEvidence {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        source_end_sample: u64,
        primary_language_bcp47: String,
        mode: LiveLanguageMode,
        status: LiveLanguageStatus,
        degradation: Option<LiveLanguageDegradation>,
        detector_component_revision: Option<String>,
        spans: Vec<LanguageSpan>,
    ) -> Result<Self, LiveLanguageEvidenceError> {
        let evidence = Self {
            schema_version: LIVE_LANGUAGE_EVIDENCE_SCHEMA_VERSION,
            sample_rate_hz: LIVE_LANGUAGE_SAMPLE_RATE_HZ,
            source_end_sample,
            boundary_authority: LanguageSpanBoundaryAuthority::ClientDecision,
            primary_language_bcp47,
            mode,
            status,
            degradation,
            detector_component_revision,
            spans,
        };
        evidence.validate()?;
        Ok(evidence)
    }

    pub fn validate(&self) -> Result<(), LiveLanguageEvidenceError> {
        if self.schema_version != LIVE_LANGUAGE_EVIDENCE_SCHEMA_VERSION
            || self.sample_rate_hz != LIVE_LANGUAGE_SAMPLE_RATE_HZ
            || self.source_end_sample == 0
            || self.boundary_authority != LanguageSpanBoundaryAuthority::ClientDecision
            || !crate::stt::nemotron::supports_live_language(&self.primary_language_bcp47)
            || self.spans.is_empty()
            || self.spans.len() > MAX_LANGUAGE_SPANS
            || (self.status == LiveLanguageStatus::Complete) != self.degradation.is_none()
        {
            return Err(LiveLanguageEvidenceError::InvalidEnvelope);
        }
        if self
            .detector_component_revision
            .as_deref()
            .is_some_and(|revision| !valid_component_revision(revision))
        {
            return Err(LiveLanguageEvidenceError::InvalidComponent);
        }
        match self.mode {
            LiveLanguageMode::FixedPrimary
                if self.detector_component_revision.is_some()
                    || self.spans.len() != 1
                    || self.status != LiveLanguageStatus::Complete =>
            {
                return Err(LiveLanguageEvidenceError::InvalidEnvelope)
            }
            LiveLanguageMode::Automatic
                if self.status == LiveLanguageStatus::Complete
                    && self.detector_component_revision.is_none() =>
            {
                return Err(LiveLanguageEvidenceError::InvalidEnvelope)
            }
            _ => {}
        }
        if let Err(error) =
            validate_sequence(self.boundary_authority, self.source_end_sample, &self.spans)
        {
            return Err(match error {
                LanguageSpanSequenceError::InvalidEnvelope => {
                    LiveLanguageEvidenceError::InvalidEnvelope
                }
                LanguageSpanSequenceError::InvalidSpan => LiveLanguageEvidenceError::InvalidSpan,
                LanguageSpanSequenceError::InvalidCoverage => {
                    LiveLanguageEvidenceError::InvalidCoverage
                }
            });
        }

        let mut expected_start = 0_u64;
        let mut previous_language = None;
        for (index, span) in self.spans.iter().enumerate() {
            if !crate::stt::nemotron::supports_live_language(&span.language_bcp47)
                || previous_language == Some(span.language_bcp47.as_str())
            {
                return Err(LiveLanguageEvidenceError::InvalidSpan);
            }
            match (
                index,
                span.disposition,
                span.component_revision.as_deref(),
                span.decision_evidence.as_ref(),
            ) {
                (0, LanguageSpanDisposition::ConfirmedPrimary, None, None)
                    if span.language_bcp47 == self.primary_language_bcp47 => {}
                (0, LanguageSpanDisposition::AcousticInitialSelection, Some(_), Some(_))
                    if span.language_bcp47 != self.primary_language_bcp47 => {}
                (0, _, _, _) => return Err(LiveLanguageEvidenceError::InvalidSpan),
                (_, LanguageSpanDisposition::AcousticSwitch, Some(_), Some(_)) => {}
                (_, LanguageSpanDisposition::FallbackPrimary, None, None)
                    if span.language_bcp47 == self.primary_language_bcp47
                        && self.status == LiveLanguageStatus::Degraded => {}
                _ => return Err(LiveLanguageEvidenceError::InvalidSpan),
            }
            previous_language = Some(span.language_bcp47.as_str());
            expected_start = span.end_sample;
        }
        if expected_start != self.source_end_sample {
            return Err(LiveLanguageEvidenceError::InvalidCoverage);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn span(
        start_sample: u64,
        end_sample: u64,
        language_bcp47: &str,
        decision_revision: u64,
        disposition: LanguageSpanDisposition,
        component_revision: Option<&str>,
    ) -> LanguageSpan {
        LanguageSpan {
            start_sample,
            end_sample,
            language_bcp47: language_bcp47.into(),
            decision_revision,
            disposition,
            component_revision: component_revision.map(str::to_owned),
            decision_evidence: matches!(
                disposition,
                LanguageSpanDisposition::AcousticInitialSelection
                    | LanguageSpanDisposition::AcousticSwitch
            )
            .then_some(AcousticLanguageDecisionEvidence {
                evidence_start_sample: start_sample,
                evidence_end_sample: end_sample,
                observation_count: 3,
                minimum_score: Some(0.8),
                minimum_margin: Some(0.4),
            }),
        }
    }

    #[test]
    fn automatic_evidence_requires_contiguous_revisioned_source_coverage() {
        let evidence = LiveLanguageEvidence::try_new(
            48_000,
            "en-US".into(),
            LiveLanguageMode::Automatic,
            LiveLanguageStatus::Complete,
            None,
            Some("lid@sha256:test".into()),
            vec![
                span(
                    0,
                    16_000,
                    "en-US",
                    1,
                    LanguageSpanDisposition::ConfirmedPrimary,
                    None,
                ),
                span(
                    16_000,
                    48_000,
                    "ja-JP",
                    2,
                    LanguageSpanDisposition::AcousticSwitch,
                    Some("lid@sha256:test"),
                ),
            ],
        )
        .unwrap();

        assert_eq!(evidence.spans.len(), 2);
        assert_eq!(evidence.spans.last().unwrap().end_sample, 48_000);
    }

    #[test]
    fn automatic_evidence_can_begin_with_a_bounded_initial_alternate_selection() {
        let evidence = LiveLanguageEvidence::try_new(
            48_000,
            "en-US".into(),
            LiveLanguageMode::Automatic,
            LiveLanguageStatus::Complete,
            None,
            Some("lid@sha256:test".into()),
            vec![span(
                0,
                48_000,
                "es-US",
                1,
                LanguageSpanDisposition::AcousticInitialSelection,
                Some("lid@sha256:test"),
            )],
        )
        .unwrap();

        assert_eq!(evidence.spans[0].language_bcp47, "es-US");
    }

    #[test]
    fn degraded_automatic_evidence_can_return_to_primary_explicitly() {
        LiveLanguageEvidence::try_new(
            64_000,
            "en-US".into(),
            LiveLanguageMode::Automatic,
            LiveLanguageStatus::Degraded,
            Some(LiveLanguageDegradation::DetectorFailed),
            Some("lid@sha256:test".into()),
            vec![
                span(
                    0,
                    16_000,
                    "en-US",
                    1,
                    LanguageSpanDisposition::ConfirmedPrimary,
                    None,
                ),
                span(
                    16_000,
                    48_000,
                    "ja-JP",
                    2,
                    LanguageSpanDisposition::AcousticSwitch,
                    Some("lid@sha256:test"),
                ),
                span(
                    48_000,
                    64_000,
                    "en-US",
                    3,
                    LanguageSpanDisposition::FallbackPrimary,
                    None,
                ),
            ],
        )
        .unwrap();
    }

    #[test]
    fn malformed_or_incomplete_span_sets_fail_closed() {
        let result = LiveLanguageEvidence::try_new(
            32_000,
            "en-US".into(),
            LiveLanguageMode::Automatic,
            LiveLanguageStatus::Complete,
            None,
            Some("lid@sha256:test".into()),
            vec![span(
                1,
                16_000,
                "en-US",
                1,
                LanguageSpanDisposition::ConfirmedPrimary,
                None,
            )],
        );

        assert!(result.is_err());
    }

    #[test]
    fn acoustic_switch_evidence_must_be_bounded_and_numerically_valid() {
        let mut evidence = LiveLanguageEvidence::try_new(
            48_000,
            "en-US".into(),
            LiveLanguageMode::Automatic,
            LiveLanguageStatus::Complete,
            None,
            Some("lid@sha256:test".into()),
            vec![
                span(
                    0,
                    16_000,
                    "en-US",
                    1,
                    LanguageSpanDisposition::ConfirmedPrimary,
                    None,
                ),
                span(
                    16_000,
                    48_000,
                    "ja-JP",
                    2,
                    LanguageSpanDisposition::AcousticSwitch,
                    Some("lid@sha256:test"),
                ),
            ],
        )
        .unwrap();

        evidence.spans[1]
            .decision_evidence
            .as_mut()
            .unwrap()
            .observation_count = 0;
        assert_eq!(
            evidence.validate(),
            Err(LiveLanguageEvidenceError::InvalidSpan)
        );

        let decision = evidence.spans[1].decision_evidence.as_mut().unwrap();
        decision.observation_count = 3;
        decision.minimum_score = Some(f32::NAN);
        assert_eq!(
            evidence.validate(),
            Err(LiveLanguageEvidenceError::InvalidSpan)
        );
    }
}
