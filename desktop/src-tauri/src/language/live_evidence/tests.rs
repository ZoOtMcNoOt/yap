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

#[test]
fn historical_evidence_does_not_depend_on_the_current_model_catalog() {
    assert!(
        !super::super::live_catalog::supports_local_asr_language("el-GR"),
        "test locale must remain outside the current local ASR catalog"
    );
    let evidence = LiveLanguageEvidence::try_new(
        16_000,
        "el-GR".into(),
        LiveLanguageMode::FixedPrimary,
        LiveLanguageStatus::Complete,
        None,
        None,
        vec![span(
            0,
            16_000,
            "el-GR",
            1,
            LanguageSpanDisposition::ConfirmedPrimary,
            None,
        )],
    )
    .unwrap();

    evidence.validate().unwrap();
}
