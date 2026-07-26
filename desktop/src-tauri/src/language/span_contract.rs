//! Versioned source-time language spans shared by local and server workflows.

pub const LANGUAGE_SPAN_SCHEMA_VERSION: u16 = 1;
pub const LANGUAGE_SPAN_SAMPLE_RATE_HZ: u32 = 16_000;
pub const MAX_LANGUAGE_SPANS: usize = 4_096;
const MAX_COMPONENT_REVISION_BYTES: usize = 256;
const MAX_DECISION_OBSERVATIONS: u32 = 4_096;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub enum LanguageSpanBoundaryAuthority {
    ClientDecision,
    ServerUtterance,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub enum LanguageSpanDisposition {
    ConfirmedPrimary,
    AcousticInitialSelection,
    AcousticSwitch,
    FallbackPrimary,
    ServerDetected,
    ServerUnknown,
}

#[derive(Debug, Clone, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AcousticLanguageDecisionEvidence {
    pub evidence_start_sample: u64,
    pub evidence_end_sample: u64,
    pub observation_count: u32,
    pub minimum_score: Option<f32>,
    pub minimum_margin: Option<f32>,
}

#[derive(Debug, Clone, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LanguageSpan {
    pub start_sample: u64,
    pub end_sample: u64,
    pub language_bcp47: String,
    pub decision_revision: u64,
    pub disposition: LanguageSpanDisposition,
    pub component_revision: Option<String>,
    pub decision_evidence: Option<AcousticLanguageDecisionEvidence>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LanguageSpanSequenceError {
    InvalidEnvelope,
    InvalidSpan,
    InvalidCoverage,
}

pub fn sequence_is_valid(
    boundary_authority: LanguageSpanBoundaryAuthority,
    source_end_sample: u64,
    spans: &[LanguageSpan],
) -> bool {
    validate_sequence(boundary_authority, source_end_sample, spans).is_ok()
}

pub fn validate_sequence(
    boundary_authority: LanguageSpanBoundaryAuthority,
    source_end_sample: u64,
    spans: &[LanguageSpan],
) -> Result<(), LanguageSpanSequenceError> {
    if source_end_sample == 0 || spans.is_empty() || spans.len() > MAX_LANGUAGE_SPANS {
        return Err(LanguageSpanSequenceError::InvalidEnvelope);
    }
    let mut expected_start = 0_u64;
    for (index, span) in spans.iter().enumerate() {
        if span.start_sample != expected_start
            || span.end_sample <= span.start_sample
            || span.end_sample > source_end_sample
            || span.decision_revision != index as u64 + 1
        {
            return Err(LanguageSpanSequenceError::InvalidCoverage);
        }
        if !super::valid_bcp47(&span.language_bcp47)
            || span
                .component_revision
                .as_deref()
                .is_some_and(|revision| !valid_component_revision(revision))
            || span
                .decision_evidence
                .as_ref()
                .is_some_and(|evidence| !valid_decision_evidence(evidence, span, source_end_sample))
            || !authority_fields_are_valid(boundary_authority, span)
        {
            return Err(LanguageSpanSequenceError::InvalidSpan);
        }
        expected_start = span.end_sample;
    }
    if expected_start != source_end_sample {
        return Err(LanguageSpanSequenceError::InvalidCoverage);
    }
    Ok(())
}

fn authority_fields_are_valid(
    boundary_authority: LanguageSpanBoundaryAuthority,
    span: &LanguageSpan,
) -> bool {
    match (
        boundary_authority,
        span.disposition,
        span.language_bcp47.as_str(),
        span.component_revision.as_deref(),
        span.decision_evidence.as_ref(),
    ) {
        (
            LanguageSpanBoundaryAuthority::ClientDecision,
            LanguageSpanDisposition::ConfirmedPrimary | LanguageSpanDisposition::FallbackPrimary,
            language,
            None,
            None,
        ) => language != "und",
        (
            LanguageSpanBoundaryAuthority::ClientDecision,
            LanguageSpanDisposition::AcousticInitialSelection
            | LanguageSpanDisposition::AcousticSwitch,
            language,
            Some(_),
            Some(_),
        ) => language != "und",
        (
            LanguageSpanBoundaryAuthority::ServerUtterance,
            LanguageSpanDisposition::ServerDetected,
            language,
            Some(_),
            None,
        ) => language != "und",
        (
            LanguageSpanBoundaryAuthority::ServerUtterance,
            LanguageSpanDisposition::ServerUnknown,
            "und",
            Some(_),
            None,
        ) => true,
        _ => false,
    }
}

fn valid_decision_evidence(
    evidence: &AcousticLanguageDecisionEvidence,
    span: &LanguageSpan,
    source_end_sample: u64,
) -> bool {
    evidence.evidence_start_sample < evidence.evidence_end_sample
        && evidence.evidence_end_sample <= source_end_sample
        && evidence.evidence_start_sample < span.end_sample
        && evidence.evidence_end_sample > span.start_sample
        && (1..=MAX_DECISION_OBSERVATIONS).contains(&evidence.observation_count)
        && valid_optional_ratio(evidence.minimum_score)
        && valid_optional_ratio(evidence.minimum_margin)
}

fn valid_optional_ratio(value: Option<f32>) -> bool {
    value.is_none_or(|value| value.is_finite() && (0.0..=1.0).contains(&value))
}

pub(crate) fn valid_component_revision(revision: &str) -> bool {
    !revision.is_empty()
        && revision.len() <= MAX_COMPONENT_REVISION_BYTES
        && revision.is_ascii()
        && !revision.bytes().any(|byte| byte.is_ascii_control())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn server_utterance_spans_are_contiguous_and_never_claim_client_boundaries() {
        let spans = vec![
            LanguageSpan {
                start_sample: 0,
                end_sample: 16_000,
                language_bcp47: "en-US".into(),
                decision_revision: 1,
                disposition: LanguageSpanDisposition::ServerDetected,
                component_revision: Some("model@revision".into()),
                decision_evidence: None,
            },
            LanguageSpan {
                start_sample: 16_000,
                end_sample: 32_000,
                language_bcp47: "und".into(),
                decision_revision: 2,
                disposition: LanguageSpanDisposition::ServerUnknown,
                component_revision: Some("model@revision".into()),
                decision_evidence: None,
            },
        ];

        assert!(sequence_is_valid(
            LanguageSpanBoundaryAuthority::ServerUtterance,
            32_000,
            &spans,
        ));
        assert!(!sequence_is_valid(
            LanguageSpanBoundaryAuthority::ClientDecision,
            32_000,
            &spans,
        ));
    }
}
