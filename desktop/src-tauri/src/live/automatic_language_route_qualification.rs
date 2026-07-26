use std::{
    collections::BTreeSet,
    fs,
    path::{Component, Path, PathBuf},
    sync::Arc,
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::{
    language_pipeline::{LanguagePipelineBatch, LanguageWindowConfig, LiveLanguagePipeline},
    language_router::LanguageAudioAction,
};
use crate::{
    audio::{
        frame::{AudioFrame, PreparedFrame},
        session::{SessionId, TrackId},
    },
    language::{
        live_catalog::LocalLanguageCatalog,
        live_diarization::{
            AcousticEvidenceThresholds, AcousticLanguageObservation,
            AutomaticLanguageRoutingPolicy, LanguageDecisionOutcome, LanguageSpan,
            PrimaryBiasedInitialLanguageSelectorConfig, SustainedLanguageSwitchConfig,
        },
    },
    stt::ambernet_language_detector::{
        AmberNetSileroLanguageDetector, MODEL_FILE, RESIDENT_LANGUAGE_HOP_SAMPLES,
        RESIDENT_LANGUAGE_WINDOW_SAMPLES,
    },
};

const SAMPLE_RATE: u64 = 16_000;
const MAX_MANIFEST_BYTES: u64 = 1024 * 1024;
const MAX_WAV_BYTES: u64 = 4 * 1024 * 1024;
const MAX_MONOLINGUAL_CASES: usize = 128;
const MAX_CONSTRUCTED_CASES: usize = 128;
const MAX_HOLDBACK_SAMPLES: usize = SAMPLE_RATE as usize * 12;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MonolingualCase {
    expected_language: String,
    target_locale: String,
    fleurs_config: String,
    split: String,
    row_id: u64,
    path: String,
    duration_ms: u64,
    frame_count: u64,
    sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ConstructedSwitchCase {
    id: String,
    variant: String,
    first_language: String,
    second_language: String,
    boundary_sample: u64,
    boundary_tolerance_samples: u64,
    path: String,
    frame_count: u64,
    sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NaturalSwitchManifest {
    audio_path: String,
    audio_sha256: String,
    frame_count: u64,
    boundary_tolerance_ms: u64,
    expected_segments: Vec<ExpectedNaturalSegment>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ExpectedNaturalSegment {
    start_ms: u64,
    end_ms: u64,
    language: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct QualificationDefinition {
    qualification_id: String,
    detector: FrozenDetector,
    policy: FrozenPolicy,
    corpora: FrozenCorpora,
    success_gates: FrozenSuccessGates,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct FrozenDetector {
    model_sha256: String,
    silero_vad_sha256: String,
    window_samples: u64,
    hop_samples: u64,
    minimum_speech_ratio: f32,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct FrozenPolicy {
    initial_alternate_observations: u8,
    initial_alternate_evidence_samples: u64,
    initial_selection_deadline_samples: u64,
    sustained_observations: u8,
    sustained_evidence_samples: u64,
    maximum_observation_gap_samples: u64,
    uncalibrated_margin_gate: Option<f32>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct FrozenCorpora {
    monolingual_fleurs_manifest_sha256: String,
    constructed_manifest_sha256: String,
    natural_manifest_sha256: String,
    natural_audio_sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct FrozenSuccessGates {
    monolingual_same_primary_false_routes: usize,
    opposite_primary_correct_initial_routes_minimum: usize,
    english_monolingual_false_spanish_initial_routes: usize,
    english_monolingual_correct_initial_routes_from_spanish_primary_minimum: usize,
    spanish_monolingual_correct_initial_routes_minimum: usize,
    spanish_monolingual_cases: usize,
    constructed_wrong_language_transitions: usize,
    constructed_correct_second_language_minimum: usize,
    constructed_boundary_out_of_tolerance_maximum: usize,
    constructed_cases: usize,
    constructed_boundary_p95_maximum_ms: u64,
    natural_expected_language_order_minimum_segments: usize,
    natural_expected_segments: usize,
    natural_matched_boundaries_minimum: usize,
    natural_unrelated_language_routes: usize,
    natural_boundary_p95_maximum_ms: u64,
    audio_sample_duplication_or_loss: usize,
    network_access_during_inference: bool,
}

#[derive(Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
struct MonolingualSummary {
    cases: usize,
    same_primary_retained: usize,
    same_primary_false_routes: usize,
    opposite_primary_initial_routes: usize,
    english_false_spanish_initial_routes: usize,
    english_correct_initial_routes_from_spanish_primary: usize,
    spanish_correct_initial_routes_from_english_primary: usize,
}

#[derive(Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
struct ConstructedSummary {
    cases: usize,
    correct_second_language: usize,
    missing_second_language: usize,
    wrong_language_transitions: usize,
    boundary_out_of_tolerance: usize,
    boundary_p95_ms: u64,
    audio_sample_duplication_or_loss: usize,
}

#[derive(Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
struct NaturalSummary {
    expected_segments: usize,
    observed_segments: usize,
    expected_language_order_segments: usize,
    matched_boundaries: usize,
    unrelated_language_routes: usize,
    matched_boundary_p95_ms: u64,
    audio_sample_duplication_or_loss: usize,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct QualificationSummary {
    schema_version: u8,
    qualification_id: String,
    definition_sha256: String,
    monolingual_manifest_sha256: String,
    constructed_manifest_sha256: String,
    natural_manifest_sha256: String,
    monolingual: MonolingualSummary,
    constructed: ConstructedSummary,
    natural: NaturalSummary,
    promotion_eligible: bool,
}

#[derive(Debug)]
struct RoutedAudio {
    spans: Vec<LanguageSpan>,
    exact_source_coverage: bool,
}

#[test]
#[ignore = "requires frozen private qualification audio plus pinned AmberNet and Silero"]
fn frozen_english_spanish_automatic_route_qualification() {
    let ambernet_root = required_path("YAP_TEST_AMBERNET_LID_ROOT");
    let silero_root = required_path("YAP_TEST_SILERO_ROOT");
    let definition_path = required_path("YAP_TEST_NARROW_ROUTE_DEFINITION");
    let monolingual_path = required_path("YAP_TEST_NARROW_ROUTE_MONOLINGUAL_MANIFEST");
    let constructed_path = required_path("YAP_TEST_NARROW_ROUTE_CONSTRUCTED_MANIFEST");
    let natural_path = required_path("YAP_TEST_NARROW_ROUTE_NATURAL_MANIFEST");

    let definition_bytes = read_bounded_regular_file(&definition_path, MAX_MANIFEST_BYTES).unwrap();
    let definition: QualificationDefinition = serde_json::from_slice(&definition_bytes).unwrap();
    validate_frozen_runtime(&definition, &ambernet_root, &silero_root);

    let monolingual_bytes =
        read_bounded_regular_file(&monolingual_path, MAX_MANIFEST_BYTES).unwrap();
    let constructed_bytes =
        read_bounded_regular_file(&constructed_path, MAX_MANIFEST_BYTES).unwrap();
    let natural_bytes = read_bounded_regular_file(&natural_path, MAX_MANIFEST_BYTES).unwrap();
    assert_eq!(
        sha256(&monolingual_bytes),
        definition.corpora.monolingual_fleurs_manifest_sha256
    );
    assert_eq!(
        sha256(&constructed_bytes),
        definition.corpora.constructed_manifest_sha256
    );
    assert_eq!(
        sha256(&natural_bytes),
        definition.corpora.natural_manifest_sha256
    );
    let monolingual_cases: Vec<MonolingualCase> =
        serde_json::from_slice(&monolingual_bytes).unwrap();
    let constructed_cases: Vec<ConstructedSwitchCase> =
        serde_json::from_slice(&constructed_bytes).unwrap();
    let natural_manifest: NaturalSwitchManifest = serde_json::from_slice(&natural_bytes).unwrap();

    let monolingual = evaluate_monolingual_cases(
        &ambernet_root,
        &silero_root,
        &monolingual_path,
        &monolingual_cases,
        &definition,
    );
    let constructed = evaluate_constructed_cases(
        &ambernet_root,
        &silero_root,
        &constructed_path,
        &constructed_cases,
        &definition,
    );
    let natural = evaluate_natural_case(
        &ambernet_root,
        &silero_root,
        &natural_path,
        &natural_manifest,
        &definition,
    );

    let gates = &definition.success_gates;
    let promotion_eligible = monolingual.same_primary_false_routes
        <= gates.monolingual_same_primary_false_routes
        && monolingual.opposite_primary_initial_routes
            >= gates.opposite_primary_correct_initial_routes_minimum
        && monolingual.english_false_spanish_initial_routes
            <= gates.english_monolingual_false_spanish_initial_routes
        && monolingual.english_correct_initial_routes_from_spanish_primary
            >= gates.english_monolingual_correct_initial_routes_from_spanish_primary_minimum
        && monolingual.spanish_correct_initial_routes_from_english_primary
            >= gates.spanish_monolingual_correct_initial_routes_minimum
        && monolingual_cases
            .iter()
            .filter(|case| case.expected_language == "es")
            .count()
            == gates.spanish_monolingual_cases
        && constructed.wrong_language_transitions <= gates.constructed_wrong_language_transitions
        && constructed.correct_second_language >= gates.constructed_correct_second_language_minimum
        && constructed.boundary_out_of_tolerance
            <= gates.constructed_boundary_out_of_tolerance_maximum
        && constructed.cases == gates.constructed_cases
        && constructed.boundary_p95_ms <= gates.constructed_boundary_p95_maximum_ms
        && natural.expected_language_order_segments
            >= gates.natural_expected_language_order_minimum_segments
        && natural.expected_segments == gates.natural_expected_segments
        && natural.matched_boundaries >= gates.natural_matched_boundaries_minimum
        && natural.unrelated_language_routes <= gates.natural_unrelated_language_routes
        && natural.matched_boundary_p95_ms <= gates.natural_boundary_p95_maximum_ms
        && constructed.audio_sample_duplication_or_loss + natural.audio_sample_duplication_or_loss
            <= gates.audio_sample_duplication_or_loss
        && !gates.network_access_during_inference;

    let summary = QualificationSummary {
        schema_version: 1,
        qualification_id: definition.qualification_id,
        definition_sha256: sha256(&definition_bytes),
        monolingual_manifest_sha256: sha256(&monolingual_bytes),
        constructed_manifest_sha256: sha256(&constructed_bytes),
        natural_manifest_sha256: sha256(&natural_bytes),
        monolingual,
        constructed,
        natural,
        promotion_eligible,
    };
    eprintln!(
        "narrow_automatic_route_qualification={}",
        serde_json::to_string(&summary).unwrap()
    );
    assert!(
        summary.promotion_eligible,
        "frozen narrow-route qualification failed"
    );
}

fn validate_frozen_runtime(
    definition: &QualificationDefinition,
    ambernet_root: &Path,
    silero_root: &Path,
) {
    assert_eq!(
        definition.detector.window_samples,
        RESIDENT_LANGUAGE_WINDOW_SAMPLES
    );
    assert_eq!(
        definition.detector.hop_samples,
        RESIDENT_LANGUAGE_HOP_SAMPLES
    );
    assert_eq!(definition.detector.minimum_speech_ratio, 0.25);
    assert_eq!(
        sha256_file(&ambernet_root.join(MODEL_FILE)),
        definition.detector.model_sha256
    );
    assert_eq!(
        sha256_file(&silero_root.join("silero_vad.onnx")),
        definition.detector.silero_vad_sha256
    );
}

fn evaluate_monolingual_cases(
    ambernet_root: &Path,
    silero_root: &Path,
    manifest_path: &Path,
    cases: &[MonolingualCase],
    definition: &QualificationDefinition,
) -> MonolingualSummary {
    assert!(!cases.is_empty() && cases.len() <= MAX_MONOLINGUAL_CASES);
    let root = manifest_path.parent().unwrap().canonicalize().unwrap();
    let catalog = LocalLanguageCatalog::try_new("en-US", ["en-US", "es-US"]).unwrap();
    let mut detector =
        AmberNetSileroLanguageDetector::load_at(ambernet_root, silero_root, catalog).unwrap();
    let mut identities = BTreeSet::new();
    let mut summary = MonolingualSummary::default();

    for case in cases {
        assert!(matches!(case.expected_language.as_str(), "en" | "es"));
        assert_eq!(case.split, "test");
        assert_eq!(
            case.target_locale.split('-').next(),
            Some(case.expected_language.as_str())
        );
        assert!(identities.insert((case.fleurs_config.clone(), case.split.clone(), case.row_id)));
        let path = safe_fixture_path(&root, &case.path);
        let wave = read_verified_wave(&path, &case.sha256, case.frame_count);
        let decoded_duration_ms = wave.samples().len() as u64 * 1_000 / SAMPLE_RATE;
        assert!(decoded_duration_ms.abs_diff(case.duration_ms) <= 1);
        let observations = detect_windows(&mut detector, wave.samples());

        let expected_locale = locale_for_language(&case.expected_language);
        let opposite_locale = opposite_locale(expected_locale);
        let same_primary = replay_policy(
            expected_locale,
            &observations,
            wave.samples().len() as u64,
            definition,
        );
        let opposite_primary = replay_policy(
            opposite_locale,
            &observations,
            wave.samples().len() as u64,
            definition,
        );
        summary.cases += 1;
        if same_primary
            .first()
            .is_some_and(|span| span.language_bcp47 == expected_locale)
            && same_primary
                .iter()
                .all(|span| span.language_bcp47 == expected_locale)
        {
            summary.same_primary_retained += 1;
        } else {
            summary.same_primary_false_routes += 1;
        }
        if opposite_primary.first().is_some_and(|span| {
            span.language_bcp47 == expected_locale
                && span.start_sample == 0
                && span.disposition
                    == crate::language::span_contract::LanguageSpanDisposition::AcousticInitialSelection
        }) {
            summary.opposite_primary_initial_routes += 1;
            if case.expected_language == "es" && opposite_locale == "en-US" {
                summary.spanish_correct_initial_routes_from_english_primary += 1;
            } else if case.expected_language == "en" && opposite_locale == "es-US" {
                summary.english_correct_initial_routes_from_spanish_primary += 1;
            }
        }
        if case.expected_language == "en"
            && expected_locale == "en-US"
            && same_primary
                .first()
                .is_some_and(|span| span.language_bcp47 == "es-US")
        {
            summary.english_false_spanish_initial_routes += 1;
        }
    }
    summary
}

fn evaluate_constructed_cases(
    ambernet_root: &Path,
    silero_root: &Path,
    manifest_path: &Path,
    cases: &[ConstructedSwitchCase],
    definition: &QualificationDefinition,
) -> ConstructedSummary {
    assert!(!cases.is_empty() && cases.len() <= MAX_CONSTRUCTED_CASES);
    let root = manifest_path.parent().unwrap().canonicalize().unwrap();
    let mut summary = ConstructedSummary::default();
    let mut boundary_errors = Vec::new();
    let mut ids = BTreeSet::new();

    for first_language in ["en", "es"] {
        let primary_locale = locale_for_language(first_language);
        let mut pipeline = load_pipeline(ambernet_root, silero_root, primary_locale, definition);
        for case in cases
            .iter()
            .filter(|case| case.first_language == first_language)
        {
            assert!(ids.insert(case.id.clone()));
            assert!(!case.variant.is_empty());
            assert_eq!(case.second_language, opposite_language(first_language));
            let path = safe_fixture_path(&root, &case.path);
            let wave = read_verified_wave(&path, &case.sha256, case.frame_count);
            let routed = route_wave(&mut pipeline, wave.samples(), &case.id);
            summary.cases += 1;
            if !routed.exact_source_coverage {
                summary.audio_sample_duplication_or_loss += 1;
            }
            let expected_first = locale_for_language(&case.first_language);
            let expected_second = locale_for_language(&case.second_language);
            let languages = routed
                .spans
                .iter()
                .map(|span| span.language_bcp47.as_str())
                .collect::<Vec<_>>();
            if languages == [expected_first, expected_second] {
                summary.correct_second_language += 1;
                let observed_boundary = routed.spans[0].end_sample;
                let error = observed_boundary.abs_diff(case.boundary_sample);
                if error > case.boundary_tolerance_samples {
                    summary.boundary_out_of_tolerance += 1;
                }
                boundary_errors.push(error * 1_000 / SAMPLE_RATE);
            } else if languages == [expected_first] {
                summary.missing_second_language += 1;
            } else {
                summary.wrong_language_transitions += 1;
            }
        }
    }
    assert_eq!(ids.len(), cases.len());
    summary.boundary_p95_ms = percentile(&mut boundary_errors, 95);
    summary
}

fn evaluate_natural_case(
    ambernet_root: &Path,
    silero_root: &Path,
    manifest_path: &Path,
    manifest: &NaturalSwitchManifest,
    definition: &QualificationDefinition,
) -> NaturalSummary {
    assert_eq!(
        manifest.audio_sha256,
        definition.corpora.natural_audio_sha256
    );
    assert!(!manifest.expected_segments.is_empty() && manifest.expected_segments.len() <= 64);
    let root = manifest_path.parent().unwrap().canonicalize().unwrap();
    let path = safe_fixture_path(&root, &manifest.audio_path);
    let wave = read_verified_wave(&path, &manifest.audio_sha256, manifest.frame_count);
    let mut pipeline = load_pipeline(ambernet_root, silero_root, "en-US", definition);
    let routed = route_wave(&mut pipeline, wave.samples(), "miami-natural-switch");
    let expected = manifest
        .expected_segments
        .iter()
        .map(|segment| locale_for_language(&segment.language))
        .collect::<Vec<_>>();
    assert_eq!(manifest.expected_segments[0].start_ms, 0);
    assert_eq!(
        manifest.expected_segments.last().unwrap().end_ms * SAMPLE_RATE / 1_000,
        wave.samples().len() as u64
    );
    for pair in manifest.expected_segments.windows(2) {
        assert_eq!(pair[0].end_ms, pair[1].start_ms);
    }
    let observed = routed
        .spans
        .iter()
        .map(|span| span.language_bcp47.as_str())
        .collect::<Vec<_>>();
    let matched_order = longest_common_subsequence_length(&expected, &observed);
    let mut boundary_errors = Vec::new();
    let tolerance_ms = manifest.boundary_tolerance_ms;
    let mut observed_index = 0;
    for expected_segment in manifest.expected_segments.iter().skip(1) {
        let expected_locale = locale_for_language(&expected_segment.language);
        if let Some((relative, span)) = routed.spans[observed_index..]
            .iter()
            .enumerate()
            .find(|(_, span)| span.language_bcp47 == expected_locale && span.start_sample > 0)
        {
            observed_index += relative + 1;
            let expected_sample = expected_segment.start_ms * SAMPLE_RATE / 1_000;
            let error_ms = span.start_sample.abs_diff(expected_sample) * 1_000 / SAMPLE_RATE;
            if error_ms <= tolerance_ms {
                boundary_errors.push(error_ms);
            }
        }
    }
    let matched_boundaries = boundary_errors.len();
    NaturalSummary {
        expected_segments: expected.len(),
        observed_segments: observed.len(),
        expected_language_order_segments: matched_order,
        matched_boundaries,
        unrelated_language_routes: observed
            .iter()
            .filter(|language| !matches!(**language, "en-US" | "es-US"))
            .count(),
        matched_boundary_p95_ms: percentile(&mut boundary_errors, 95),
        audio_sample_duplication_or_loss: usize::from(!routed.exact_source_coverage),
    }
}

fn load_pipeline(
    ambernet_root: &Path,
    silero_root: &Path,
    primary_locale: &str,
    definition: &QualificationDefinition,
) -> LiveLanguagePipeline<AmberNetSileroLanguageDetector> {
    let catalog = LocalLanguageCatalog::try_new(primary_locale, ["en-US", "es-US"]).unwrap();
    let detector =
        AmberNetSileroLanguageDetector::load_at(ambernet_root, silero_root, catalog.clone())
            .unwrap();
    LiveLanguagePipeline::new(
        detector,
        &catalog,
        initial_config(definition),
        sustained_config(definition),
        LanguageWindowConfig::try_new(
            definition.detector.window_samples,
            definition.detector.hop_samples,
        )
        .unwrap(),
        MAX_HOLDBACK_SAMPLES,
    )
    .unwrap()
}

fn route_wave(
    pipeline: &mut LiveLanguagePipeline<AmberNetSileroLanguageDetector>,
    samples: &[f32],
    fixture_id: &str,
) -> RoutedAudio {
    pipeline.reset_session().unwrap();
    let mut actions = Vec::new();
    let mut spans = Vec::new();
    for (sequence, chunk) in samples.chunks(SAMPLE_RATE as usize).enumerate() {
        let batch = pipeline
            .push(frame(fixture_id, sequence as u64, chunk))
            .unwrap();
        absorb_batch(batch, &mut actions, &mut spans);
    }
    let finish = pipeline.finish().unwrap();
    absorb_batch(finish.batch, &mut actions, &mut spans);
    if let Some(span) = finish.routing.final_span {
        spans.push(span);
    }
    actions.extend(finish.routing.actions);

    let mut cursor = 0_u64;
    let mut exact_source_coverage = true;
    for action in actions {
        match action {
            LanguageAudioAction::Feed { audio, .. } => {
                if audio.range.start_sample != cursor
                    || audio.range.end_sample > samples.len() as u64
                    || audio.samples.as_slice()
                        != &samples
                            [audio.range.start_sample as usize..audio.range.end_sample as usize]
                {
                    exact_source_coverage = false;
                }
                cursor = audio.range.end_sample;
            }
            LanguageAudioAction::Switch(transition) => {
                if transition.boundary_sample != cursor {
                    exact_source_coverage = false;
                }
            }
        }
    }
    exact_source_coverage &= cursor == samples.len() as u64;
    RoutedAudio {
        spans,
        exact_source_coverage,
    }
}

fn absorb_batch(
    batch: LanguagePipelineBatch,
    actions: &mut Vec<LanguageAudioAction>,
    spans: &mut Vec<LanguageSpan>,
) {
    for decision in batch.decisions {
        if let LanguageDecisionOutcome::Switched(transition) = decision {
            if let Some(span) = transition.completed_span {
                spans.push(span);
            }
        }
    }
    actions.extend(batch.actions);
}

fn detect_windows(
    detector: &mut AmberNetSileroLanguageDetector,
    samples: &[f32],
) -> Vec<AcousticLanguageObservation> {
    let window = RESIDENT_LANGUAGE_WINDOW_SAMPLES as usize;
    let hop = RESIDENT_LANGUAGE_HOP_SAMPLES as usize;
    assert!(samples.len() >= window);
    (0..=samples.len() - window)
        .step_by(hop)
        .map(|start| {
            detector
                .observe(
                    start as u64,
                    (start + window) as u64,
                    &samples[start..start + window],
                )
                .unwrap()
        })
        .collect()
}

fn replay_policy(
    primary_locale: &str,
    observations: &[AcousticLanguageObservation],
    source_end_sample: u64,
    definition: &QualificationDefinition,
) -> Vec<LanguageSpan> {
    let mut policy = AutomaticLanguageRoutingPolicy::new(
        primary_locale,
        ["en-US", "es-US"],
        initial_config(definition),
        sustained_config(definition),
    )
    .unwrap();
    let mut spans = Vec::new();
    for observation in observations.iter().cloned() {
        if let LanguageDecisionOutcome::Switched(transition) = policy.observe(observation).unwrap()
        {
            if let Some(span) = transition.completed_span {
                spans.push(span);
            }
        }
    }
    if let Some(span) = policy.finish(source_end_sample).unwrap() {
        spans.push(span);
    }
    spans
}

fn initial_config(
    definition: &QualificationDefinition,
) -> PrimaryBiasedInitialLanguageSelectorConfig {
    let evidence_thresholds = AcousticEvidenceThresholds::try_new(
        definition.detector.minimum_speech_ratio,
        None,
        definition.policy.uncalibrated_margin_gate,
    )
    .unwrap();
    PrimaryBiasedInitialLanguageSelectorConfig::try_new(
        definition.policy.initial_alternate_observations,
        definition.policy.initial_alternate_evidence_samples,
        definition.policy.maximum_observation_gap_samples,
        definition.policy.initial_selection_deadline_samples,
        evidence_thresholds,
    )
    .unwrap()
}

fn sustained_config(definition: &QualificationDefinition) -> SustainedLanguageSwitchConfig {
    let evidence_thresholds = AcousticEvidenceThresholds::try_new(
        definition.detector.minimum_speech_ratio,
        None,
        definition.policy.uncalibrated_margin_gate,
    )
    .unwrap();
    SustainedLanguageSwitchConfig::try_new(
        definition.policy.sustained_observations,
        definition.policy.sustained_evidence_samples,
        definition.policy.maximum_observation_gap_samples,
        evidence_thresholds,
    )
    .unwrap()
}

fn frame(fixture_id: &str, sequence: u64, samples: &[f32]) -> PreparedFrame {
    PreparedFrame {
        metadata: AudioFrame {
            session_id: SessionId::new(format!("qualification-{fixture_id}")).unwrap(),
            track_id: TrackId::new("microphone").unwrap(),
            sequence,
            sample_rate_hz: SAMPLE_RATE as u32,
            channels: 1,
            start_ms: sequence * 1_000,
            duration_ms: u32::try_from(samples.len() as u64 * 1_000 / SAMPLE_RATE).unwrap(),
            sample_count: samples.len(),
        },
        samples: Arc::from(samples.to_vec()),
    }
}

fn read_verified_wave(
    path: &Path,
    expected_sha256: &str,
    expected_frames: u64,
) -> sherpa_onnx::Wave {
    let before = read_bounded_regular_file(path, MAX_WAV_BYTES).unwrap();
    assert_eq!(sha256(&before), expected_sha256);
    let wave = sherpa_onnx::Wave::read(path.to_str().unwrap()).unwrap();
    let after = read_bounded_regular_file(path, MAX_WAV_BYTES).unwrap();
    assert_eq!(before, after);
    assert_eq!(wave.sample_rate(), SAMPLE_RATE as i32);
    assert_eq!(wave.samples().len() as u64, expected_frames);
    wave
}

fn safe_fixture_path(root: &Path, relative: &str) -> PathBuf {
    let mut components = Path::new(relative).components();
    assert!(matches!(components.next(), Some(Component::Normal(_))));
    assert!(components.next().is_none());
    let path = root.join(relative);
    assert_eq!(path.parent().unwrap().canonicalize().unwrap(), root);
    path
}

fn required_path(environment: &str) -> PathBuf {
    PathBuf::from(
        std::env::var(environment).unwrap_or_else(|_| panic!("{environment} is required")),
    )
}

fn read_bounded_regular_file(path: &Path, maximum_bytes: u64) -> std::io::Result<Vec<u8>> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file() || metadata.len() > maximum_bytes {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "qualification artifact is not a bounded regular file",
        ));
    }
    let bytes = fs::read(path)?;
    if bytes.len() as u64 != metadata.len() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "qualification artifact changed while it was read",
        ));
    }
    Ok(bytes)
}

fn sha256_file(path: &Path) -> String {
    sha256(&read_bounded_regular_file(path, 1024 * 1024 * 1024).unwrap())
}

fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn locale_for_language(language: &str) -> &'static str {
    match language {
        "en" => "en-US",
        "es" => "es-US",
        _ => panic!("qualification language is outside the frozen pair"),
    }
}

fn opposite_locale(locale: &str) -> &'static str {
    match locale {
        "en-US" => "es-US",
        "es-US" => "en-US",
        _ => panic!("qualification locale is outside the frozen pair"),
    }
}

fn opposite_language(language: &str) -> &'static str {
    match language {
        "en" => "es",
        "es" => "en",
        _ => panic!("qualification language is outside the frozen pair"),
    }
}

fn percentile(values: &mut [u64], percentile: usize) -> u64 {
    if values.is_empty() {
        return u64::MAX;
    }
    values.sort_unstable();
    values[(values.len() - 1) * percentile / 100]
}

fn longest_common_subsequence_length(left: &[&str], right: &[&str]) -> usize {
    let mut previous = vec![0_usize; right.len() + 1];
    for left_value in left {
        let mut current = vec![0_usize; right.len() + 1];
        for (right_index, right_value) in right.iter().enumerate() {
            current[right_index + 1] = if left_value == right_value {
                previous[right_index] + 1
            } else {
                current[right_index].max(previous[right_index + 1])
            };
        }
        previous = current;
    }
    previous[right.len()]
}
