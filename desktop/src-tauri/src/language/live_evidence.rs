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
            || !super::valid_bcp47(&self.primary_language_bcp47)
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
            if !super::valid_bcp47(&span.language_bcp47)
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
mod tests;
