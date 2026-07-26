use std::{
    fs,
    path::{Component, Path, PathBuf},
    sync::Arc,
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::{
    language_pipeline::{load_resident_language_pipeline, LanguagePipelineBatch},
    language_router::LanguageAudioAction,
};
use crate::{
    audio::{
        frame::{AudioFrame, PreparedFrame},
        session::{SessionId, TrackId},
    },
    language::{
        live_catalog::LocalLanguageCatalog,
        live_diarization::{LanguageDecisionOutcome, LanguageSpan},
    },
    private_evidence::publish_private_json,
    stt::ambernet_language_detector::{
        AmberNetSileroLanguageDetector, RESIDENT_LANGUAGE_HOP_SAMPLES,
        RESIDENT_LANGUAGE_WINDOW_SAMPLES,
    },
};

const SAMPLE_RATE_HZ: u64 = 16_000;
const MAXIMUM_MANIFEST_BYTES: u64 = 1024 * 1024;
const MAXIMUM_WAV_BYTES: u64 = 4 * 1024 * 1024;
const MAXIMUM_CASES: usize = 32;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RepresentativeManifest {
    schema_version: u8,
    holdout: bool,
    inference_run_count: u64,
    cases: Vec<RepresentativeCase>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RepresentativeCase {
    acceptance_role: AcceptanceRole,
    primary_family: String,
    alternate_family: String,
    acceptable_entry_boundary_ms: Option<[u64; 2]>,
    acceptable_exit_boundary_ms: Option<[u64; 2]>,
    aligned_region_ms: AlignedRegion,
    clip: RepresentativeClip,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct AlignedRegion {
    alternate_speech_start: u64,
    alternate_speech_end: u64,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
enum AcceptanceRole {
    MustDetect,
    PrimaryLanguageFallback,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RepresentativeClip {
    duration_ms: u64,
    frame_count: u64,
    path: String,
    sha256: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
#[serde(rename_all = "camelCase")]
struct RepresentativeRouteEvidence {
    schema_version: u8,
    manifest_sha256: String,
    component_revision: String,
    cases: usize,
    must_detect_cases: usize,
    must_detect_passed: usize,
    primary_fallback_cases: usize,
    primary_fallback_passed: usize,
    exact_source_coverage_cases: usize,
    unrelated_route_cases: usize,
    entry_boundary_passed: usize,
    exit_boundary_passed: usize,
    behavior_contract_passed: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ExactDetectorDiagnosticEvidence {
    schema_version: u8,
    evidence_role: &'static str,
    manifest_sha256: String,
    component_revision: String,
    cases: Vec<ExactDetectorCaseDiagnostic>,
    alternate_region_windows: usize,
    speech_qualified_windows: usize,
    primary_label_windows: usize,
    alternate_label_windows: usize,
    abstention_windows: usize,
    alternate_margin_gate_windows: usize,
    maximum_consecutive_alternate_margin_gate_windows: usize,
    outside_region_alternate_margin_gate_windows: usize,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ExactDetectorCaseDiagnostic {
    case_index: usize,
    acceptance_role: AcceptanceRole,
    alternate_region_windows: usize,
    speech_qualified_windows: usize,
    primary_label_windows: usize,
    alternate_label_windows: usize,
    abstention_windows: usize,
    alternate_margin_gate_windows: usize,
    maximum_consecutive_alternate_margin_gate_windows: usize,
    outside_region_alternate_margin_gate_windows: usize,
}

struct RoutedCase {
    spans: Vec<LanguageSpan>,
    exact_source_coverage: bool,
}

/// One-time evidence collector retained for auditability. The frozen manifest
/// has already been consumed and must not be rerun or retuned. It publishes
/// aggregate behavior only; case IDs, source paths, transcript text, and audio
/// never enter output or repository evidence.
#[test]
#[ignore = "one-time representative route acquisition already consumed; do not rerun"]
fn collect_representative_natural_language_route_evidence_once() {
    let manifest_path = required_path("YAP_TEST_REPRESENTATIVE_ROUTE_MANIFEST");
    assert_private_external_path(&manifest_path);
    let manifest_bytes = read_bounded_regular_file(&manifest_path, MAXIMUM_MANIFEST_BYTES);
    let manifest_sha256 = sha256(&manifest_bytes);
    assert_eq!(
        manifest_sha256,
        required_string("YAP_TEST_REPRESENTATIVE_ROUTE_MANIFEST_SHA256")
    );
    let manifest: RepresentativeManifest = serde_json::from_slice(&manifest_bytes).unwrap();
    assert_eq!(manifest.schema_version, 1);
    assert!(manifest.holdout);
    assert_eq!(manifest.inference_run_count, 0);
    assert!(!manifest.cases.is_empty() && manifest.cases.len() <= MAXIMUM_CASES);

    let primary_locale = locale_for_family(&manifest.cases[0].primary_family);
    let alternate_locale = locale_for_family(&manifest.cases[0].alternate_family);
    assert_ne!(primary_locale, alternate_locale);
    let catalog = LocalLanguageCatalog::with_explicit_automatic_alternates(
        primary_locale,
        [alternate_locale],
    )
    .unwrap();
    let mut pipeline = load_resident_language_pipeline(catalog).unwrap();
    let component_revision = pipeline.component_revision().to_owned();
    let manifest_root = manifest_path.parent().unwrap().canonicalize().unwrap();

    let mut must_detect_cases = 0;
    let mut must_detect_passed = 0;
    let mut primary_fallback_cases = 0;
    let mut primary_fallback_passed = 0;
    let mut exact_source_coverage_cases = 0;
    let mut unrelated_route_cases = 0;
    let mut entry_boundary_passed = 0;
    let mut exit_boundary_passed = 0;

    for (case_index, case) in manifest.cases.iter().enumerate() {
        assert_eq!(locale_for_family(&case.primary_family), primary_locale);
        assert_eq!(locale_for_family(&case.alternate_family), alternate_locale);
        let clip_path = safe_descendant(&manifest_root, &case.clip.path);
        let wave = read_verified_wave(
            &clip_path,
            &case.clip.sha256,
            case.clip.frame_count,
            case.clip.duration_ms,
        );
        let routed = route_wave(&mut pipeline, wave.samples(), case_index);
        if routed.exact_source_coverage {
            exact_source_coverage_cases += 1;
        }
        let unrelated = routed.spans.iter().any(|span| {
            span.language_bcp47 != primary_locale && span.language_bcp47 != alternate_locale
        });
        if unrelated {
            unrelated_route_cases += 1;
        }
        let alternate_span = routed
            .spans
            .iter()
            .find(|span| span.language_bcp47 == alternate_locale);

        match case.acceptance_role {
            AcceptanceRole::MustDetect => {
                must_detect_cases += 1;
                let entry_passed = alternate_span.is_some_and(|span| {
                    sample_in_millisecond_range(
                        span.start_sample,
                        case.acceptable_entry_boundary_ms
                            .expect("must-detect case requires an entry range"),
                    )
                });
                let exit_passed = alternate_span.is_some_and(|span| {
                    sample_in_millisecond_range(
                        span.end_sample,
                        case.acceptable_exit_boundary_ms
                            .expect("must-detect case requires an exit range"),
                    )
                });
                entry_boundary_passed += usize::from(entry_passed);
                exit_boundary_passed += usize::from(exit_passed);
                must_detect_passed += usize::from(
                    entry_passed && exit_passed && routed.exact_source_coverage && !unrelated,
                );
            }
            AcceptanceRole::PrimaryLanguageFallback => {
                primary_fallback_cases += 1;
                let retained_primary = !routed.spans.is_empty()
                    && routed
                        .spans
                        .iter()
                        .all(|span| span.language_bcp47 == primary_locale);
                primary_fallback_passed +=
                    usize::from(retained_primary && routed.exact_source_coverage && !unrelated);
            }
        }
    }

    let cases = manifest.cases.len();
    let behavior_contract_passed = must_detect_passed == must_detect_cases
        && primary_fallback_passed == primary_fallback_cases
        && exact_source_coverage_cases == cases
        && unrelated_route_cases == 0;
    let evidence = RepresentativeRouteEvidence {
        schema_version: 1,
        manifest_sha256,
        component_revision,
        cases,
        must_detect_cases,
        must_detect_passed,
        primary_fallback_cases,
        primary_fallback_passed,
        exact_source_coverage_cases,
        unrelated_route_cases,
        entry_boundary_passed,
        exit_boundary_passed,
        behavior_contract_passed,
    };
    assert_eq!(
        evidence.primary_fallback_passed,
        evidence.primary_fallback_cases
    );
    assert_eq!(evidence.exact_source_coverage_cases, evidence.cases);
    assert_eq!(evidence.unrelated_route_cases, 0);
    persist_private_json("YAP_TEST_REPRESENTATIVE_ROUTE_EVIDENCE", &evidence);
    eprintln!(
        "representative_language_route_evidence={}",
        serde_json::to_string(&evidence).unwrap()
    );
}

/// Validates the already-consumed aggregate without reading audio or invoking
/// either model. Phase closure uses this audit check plus deterministic routing
/// safety tests; it does not relabel the failed natural-switch quality target.
#[test]
#[ignore = "requires the private aggregate from the consumed representative route"]
fn accepted_preview_evidence_preserves_failed_quality_and_passed_safety() {
    let evidence_path = required_path("YAP_TEST_REPRESENTATIVE_ROUTE_EVIDENCE");
    assert_private_external_path(&evidence_path);
    let evidence_bytes = read_bounded_regular_file(&evidence_path, MAXIMUM_MANIFEST_BYTES);
    assert_eq!(
        sha256(&evidence_bytes),
        required_string("YAP_TEST_REPRESENTATIVE_ROUTE_EVIDENCE_SHA256")
    );
    let evidence: RepresentativeRouteEvidence = serde_json::from_slice(&evidence_bytes).unwrap();

    assert_eq!(evidence.schema_version, 1);
    assert_eq!(
        evidence.manifest_sha256,
        required_string("YAP_TEST_REPRESENTATIVE_ROUTE_MANIFEST_SHA256")
    );
    assert!(!evidence.component_revision.is_empty());
    assert_eq!(evidence.cases, 5);
    assert_eq!(evidence.must_detect_cases, 4);
    assert_eq!(evidence.must_detect_passed, 0);
    assert_eq!(evidence.entry_boundary_passed, 0);
    assert_eq!(evidence.exit_boundary_passed, 0);
    assert_eq!(evidence.primary_fallback_cases, 1);
    assert_eq!(evidence.primary_fallback_passed, 1);
    assert_eq!(evidence.exact_source_coverage_cases, evidence.cases);
    assert_eq!(evidence.unrelated_route_cases, 0);
    assert!(!evidence.behavior_contract_passed);
}

/// Reuses an already-consumed representative set only to explain a failed
/// frozen route result. This is diagnostic evidence and cannot promote or
/// retune the detector/policy.
#[test]
#[ignore = "requires consumed private representative audio and imported AmberNet/Silero artifacts"]
fn diagnose_consumed_representative_route_with_exact_detector() {
    let manifest_path = required_path("YAP_TEST_REPRESENTATIVE_ROUTE_MANIFEST");
    assert_private_external_path(&manifest_path);
    let manifest_bytes = read_bounded_regular_file(&manifest_path, MAXIMUM_MANIFEST_BYTES);
    let manifest_sha256 = sha256(&manifest_bytes);
    assert_eq!(
        manifest_sha256,
        required_string("YAP_TEST_REPRESENTATIVE_ROUTE_MANIFEST_SHA256")
    );
    let manifest: RepresentativeManifest = serde_json::from_slice(&manifest_bytes).unwrap();
    assert_eq!(manifest.schema_version, 1);
    assert!(manifest.holdout);
    assert!(!manifest.cases.is_empty() && manifest.cases.len() <= MAXIMUM_CASES);

    let primary_locale = locale_for_family(&manifest.cases[0].primary_family);
    let alternate_locale = locale_for_family(&manifest.cases[0].alternate_family);
    let catalog = LocalLanguageCatalog::with_explicit_automatic_alternates(
        primary_locale,
        [alternate_locale],
    )
    .unwrap();
    let mut detector = AmberNetSileroLanguageDetector::load(catalog).unwrap();
    let component_revision = detector.component_revision().to_owned();
    let manifest_root = manifest_path.parent().unwrap().canonicalize().unwrap();
    let mut case_diagnostics = Vec::new();

    for (case_index, case) in manifest.cases.iter().enumerate() {
        assert_eq!(locale_for_family(&case.primary_family), primary_locale);
        assert_eq!(locale_for_family(&case.alternate_family), alternate_locale);
        let clip_path = safe_descendant(&manifest_root, &case.clip.path);
        let wave = read_verified_wave(
            &clip_path,
            &case.clip.sha256,
            case.clip.frame_count,
            case.clip.duration_ms,
        );
        case_diagnostics.push(diagnose_case(
            &mut detector,
            case,
            wave.samples(),
            case_index,
            primary_locale,
            alternate_locale,
        ));
    }

    let evidence = ExactDetectorDiagnosticEvidence {
        schema_version: 1,
        evidence_role: "post-failure-diagnostic",
        manifest_sha256,
        component_revision,
        alternate_region_windows: sum_case_diagnostics(&case_diagnostics, |case| {
            case.alternate_region_windows
        }),
        speech_qualified_windows: sum_case_diagnostics(&case_diagnostics, |case| {
            case.speech_qualified_windows
        }),
        primary_label_windows: sum_case_diagnostics(&case_diagnostics, |case| {
            case.primary_label_windows
        }),
        alternate_label_windows: sum_case_diagnostics(&case_diagnostics, |case| {
            case.alternate_label_windows
        }),
        abstention_windows: sum_case_diagnostics(&case_diagnostics, |case| case.abstention_windows),
        alternate_margin_gate_windows: sum_case_diagnostics(&case_diagnostics, |case| {
            case.alternate_margin_gate_windows
        }),
        maximum_consecutive_alternate_margin_gate_windows: case_diagnostics
            .iter()
            .map(|case| case.maximum_consecutive_alternate_margin_gate_windows)
            .max()
            .unwrap_or(0),
        outside_region_alternate_margin_gate_windows: sum_case_diagnostics(
            &case_diagnostics,
            |case| case.outside_region_alternate_margin_gate_windows,
        ),
        cases: case_diagnostics,
    };
    persist_private_json(
        "YAP_TEST_REPRESENTATIVE_ROUTE_DIAGNOSTIC_EVIDENCE",
        &evidence,
    );
    eprintln!(
        "exact_detector_diagnostic cases={} alternate_region_windows={} speech_qualified_windows={} primary_label_windows={} alternate_label_windows={} abstention_windows={} alternate_margin_gate_windows={} maximum_consecutive_alternate_margin_gate_windows={} outside_region_alternate_margin_gate_windows={}",
        evidence.cases.len(),
        evidence.alternate_region_windows,
        evidence.speech_qualified_windows,
        evidence.primary_label_windows,
        evidence.alternate_label_windows,
        evidence.abstention_windows,
        evidence.alternate_margin_gate_windows,
        evidence.maximum_consecutive_alternate_margin_gate_windows,
        evidence.outside_region_alternate_margin_gate_windows,
    );
}

fn diagnose_case(
    detector: &mut AmberNetSileroLanguageDetector,
    case: &RepresentativeCase,
    samples: &[f32],
    case_index: usize,
    primary_locale: &str,
    alternate_locale: &str,
) -> ExactDetectorCaseDiagnostic {
    let window = RESIDENT_LANGUAGE_WINDOW_SAMPLES as usize;
    let hop = RESIDENT_LANGUAGE_HOP_SAMPLES as usize;
    assert!(samples.len() >= window);
    let mut diagnostic = ExactDetectorCaseDiagnostic {
        case_index,
        acceptance_role: case.acceptance_role,
        alternate_region_windows: 0,
        speech_qualified_windows: 0,
        primary_label_windows: 0,
        alternate_label_windows: 0,
        abstention_windows: 0,
        alternate_margin_gate_windows: 0,
        maximum_consecutive_alternate_margin_gate_windows: 0,
        outside_region_alternate_margin_gate_windows: 0,
    };
    let mut consecutive_alternate = 0;
    for start in (0..=samples.len() - window).step_by(hop) {
        let end = start + window;
        let center_ms = (start as u64 + end as u64) * 500 / SAMPLE_RATE_HZ;
        let inside_alternate = case.aligned_region_ms.alternate_speech_start <= center_ms
            && center_ms <= case.aligned_region_ms.alternate_speech_end;
        let observation = detector
            .observe(start as u64, end as u64, &samples[start..end])
            .unwrap();
        let passes_alternate_margin = observation.language_bcp47.as_deref()
            == Some(alternate_locale)
            && observation.margin.is_some_and(|margin| margin >= 0.40);
        if inside_alternate {
            diagnostic.alternate_region_windows += 1;
            diagnostic.speech_qualified_windows += usize::from(observation.score.is_some());
            match observation.language_bcp47.as_deref() {
                Some(language) if language == primary_locale => {
                    diagnostic.primary_label_windows += 1;
                }
                Some(language) if language == alternate_locale => {
                    diagnostic.alternate_label_windows += 1;
                }
                None => diagnostic.abstention_windows += 1,
                Some(_) => unreachable!("closed catalog emitted an unrelated locale"),
            }
            if passes_alternate_margin {
                diagnostic.alternate_margin_gate_windows += 1;
                consecutive_alternate += 1;
                diagnostic.maximum_consecutive_alternate_margin_gate_windows = diagnostic
                    .maximum_consecutive_alternate_margin_gate_windows
                    .max(consecutive_alternate);
            } else {
                consecutive_alternate = 0;
            }
        } else {
            consecutive_alternate = 0;
            diagnostic.outside_region_alternate_margin_gate_windows +=
                usize::from(passes_alternate_margin);
        }
    }
    diagnostic
}

fn sum_case_diagnostics(
    cases: &[ExactDetectorCaseDiagnostic],
    select: impl Fn(&ExactDetectorCaseDiagnostic) -> usize,
) -> usize {
    cases.iter().map(select).sum()
}

fn route_wave(
    pipeline: &mut super::language_pipeline::ResidentLanguagePipeline,
    samples: &[f32],
    case_index: usize,
) -> RoutedCase {
    pipeline.reset_session().unwrap();
    let mut actions = Vec::new();
    let mut spans = Vec::new();
    for (sequence, chunk) in samples.chunks(SAMPLE_RATE_HZ as usize).enumerate() {
        let batch = pipeline
            .push(frame(case_index, sequence as u64, chunk))
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
                let start = audio.range.start_sample as usize;
                let end = audio.range.end_sample as usize;
                if audio.range.start_sample != cursor
                    || end > samples.len()
                    || start > end
                    || audio.samples.as_slice() != &samples[start..end]
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
    RoutedCase {
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

fn frame(case_index: usize, sequence: u64, samples: &[f32]) -> PreparedFrame {
    let start_sample = sequence * SAMPLE_RATE_HZ;
    PreparedFrame {
        metadata: AudioFrame {
            session_id: SessionId::new(format!("representative-route-{case_index}")).unwrap(),
            track_id: TrackId::new("microphone").unwrap(),
            sequence,
            sample_rate_hz: SAMPLE_RATE_HZ as u32,
            channels: 1,
            start_ms: start_sample * 1_000 / SAMPLE_RATE_HZ,
            duration_ms: u32::try_from(samples.len() as u64 * 1_000 / SAMPLE_RATE_HZ).unwrap(),
            sample_count: samples.len(),
        },
        samples: Arc::from(samples.to_vec()),
    }
}

fn read_verified_wave(
    path: &Path,
    expected_sha256: &str,
    expected_frames: u64,
    expected_duration_ms: u64,
) -> sherpa_onnx::Wave {
    let before = read_bounded_regular_file(path, MAXIMUM_WAV_BYTES);
    assert_eq!(sha256(&before), expected_sha256);
    let wave = sherpa_onnx::Wave::read(path.to_str().unwrap()).unwrap();
    let after = read_bounded_regular_file(path, MAXIMUM_WAV_BYTES);
    assert_eq!(before, after);
    assert_eq!(wave.sample_rate(), SAMPLE_RATE_HZ as i32);
    assert_eq!(wave.samples().len() as u64, expected_frames);
    assert!(
        (wave.samples().len() as u64 * 1_000 / SAMPLE_RATE_HZ).abs_diff(expected_duration_ms) <= 1
    );
    wave
}

fn sample_in_millisecond_range(sample: u64, range_ms: [u64; 2]) -> bool {
    let sample_ms = sample * 1_000 / SAMPLE_RATE_HZ;
    range_ms[0] <= sample_ms && sample_ms <= range_ms[1]
}

fn locale_for_family(family: &str) -> &'static str {
    match family {
        "de" => "de-DE",
        "en" => "en-US",
        _ => panic!("representative language family is outside the frozen pair"),
    }
}

fn safe_descendant(root: &Path, relative: &str) -> PathBuf {
    let relative = Path::new(relative);
    assert!(!relative.is_absolute());
    assert!(relative
        .components()
        .all(|component| { matches!(component, Component::Normal(_)) }));
    let path = root.join(relative).canonicalize().unwrap();
    assert!(path.starts_with(root));
    assert!(fs::symlink_metadata(&path).unwrap().file_type().is_file());
    path
}

fn read_bounded_regular_file(path: &Path, maximum_bytes: u64) -> Vec<u8> {
    let metadata = fs::symlink_metadata(path).unwrap();
    assert!(metadata.file_type().is_file());
    assert!(metadata.len() <= maximum_bytes);
    let bytes = fs::read(path).unwrap();
    assert_eq!(bytes.len() as u64, metadata.len());
    bytes
}

fn assert_private_external_path(path: &Path) {
    assert!(path.is_absolute());
    let canonical = path.canonicalize().unwrap();
    let repository_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap();
    assert!(!canonical.starts_with(repository_root));
}

fn required_path(environment: &str) -> PathBuf {
    PathBuf::from(required_string(environment))
}

fn required_string(environment: &str) -> String {
    std::env::var(environment).unwrap_or_else(|_| panic!("{environment} is required"))
}

fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn persist_private_json(environment: &str, evidence: &impl Serialize) {
    let destination = required_path(environment);
    publish_private_json(&destination, evidence)
        .unwrap_or_else(|error| panic!("failed to publish private route evidence: {error}"));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boundary_range_is_inclusive_at_both_edges() {
        assert!(sample_in_millisecond_range(16_000, [1_000, 2_000]));
        assert!(sample_in_millisecond_range(32_000, [1_000, 2_000]));
        assert!(!sample_in_millisecond_range(32_016, [1_000, 2_000]));
    }

    #[test]
    fn nested_fixture_paths_cannot_escape_the_manifest_root() {
        let escaped = Path::new("clips/../outside.wav");
        assert!(escaped
            .components()
            .any(|component| { !matches!(component, Component::Normal(_)) }));
    }
}
