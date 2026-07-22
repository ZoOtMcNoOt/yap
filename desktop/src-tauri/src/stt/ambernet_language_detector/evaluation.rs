use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Component, Path, PathBuf},
    time::Instant,
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::*;

const MAX_MANIFEST_BYTES: u64 = 512 * 1024;
const MAX_CASES: usize = 512;
const MAX_WAV_BYTES: u64 = 2 * 1024 * 1024;
const MAX_FIXTURE_DURATION_MS: u64 = 30_000;
const MAX_EVALUATION_WINDOWS: usize = 32_768;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LanguageComparatorCase {
    expected_language: String,
    target_locale: String,
    fleurs_config: String,
    row_id: u64,
    path: String,
    duration_ms: u64,
    sha256: String,
    fixture_access: String,
    #[serde(default)]
    transcript: Option<String>,
}

#[derive(Default, Serialize)]
#[serde(rename_all = "camelCase")]
struct LanguageScore {
    correct_cases: usize,
    total_cases: usize,
    correct_windows: usize,
    total_windows: usize,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LanguageComparatorSummary {
    schema_version: u8,
    component_revision: &'static str,
    manifest_sha256: String,
    fixture_cases: usize,
    correct_cases: usize,
    case_accuracy: f64,
    evaluated_windows: usize,
    correct_windows: usize,
    window_accuracy: f64,
    cases_with_speech: usize,
    speech_qualified_windows: usize,
    source_audio_ms: u64,
    evaluated_window_audio_ms: u64,
    resident_window_samples: u64,
    resident_hop_samples: u64,
    load_ms: f64,
    mean_inference_ms: f64,
    p50_inference_ms: f64,
    p95_inference_ms: f64,
    p99_inference_ms: f64,
    inference_real_time_factor: f64,
    per_language: BTreeMap<String, LanguageScore>,
    language_confusions: BTreeMap<String, BTreeMap<String, usize>>,
}

#[test]
fn comparator_metadata_rejects_unsafe_or_inconsistent_cases() {
    let mut case = valid_case();
    validate_case_metadata(&case).unwrap();

    case.path = "../outside.wav".into();
    assert!(validate_case_metadata(&case).is_err());
    case = valid_case();
    case.target_locale = "fr-FR".into();
    assert!(validate_case_metadata(&case).is_err());
    case = valid_case();
    case.sha256 = "A".repeat(64);
    assert!(validate_case_metadata(&case).is_err());
    case = valid_case();
    case.duration_ms = MAX_FIXTURE_DURATION_MS + 1;
    assert!(validate_case_metadata(&case).is_err());

    let mut votes = BTreeMap::from([("en".to_string(), 3), ("fr".to_string(), 2)]);
    assert_eq!(unique_plurality(&votes), Some("en"));
    votes.insert("fr".into(), 3);
    assert_eq!(unique_plurality(&votes), None);
}

#[test]
#[ignore = "requires hash-verified private-cache FLEURS fixtures plus pinned AmberNet and Silero"]
fn pinned_resident_detector_scores_hash_verified_fleurs_comparator() {
    let ambernet_root = required_path("YAP_TEST_AMBERNET_LID_ROOT");
    let silero_root = required_path("YAP_TEST_SILERO_ROOT");
    let manifest_path = required_path("YAP_TEST_AMBERNET_LID_MANIFEST");
    let manifest_bytes = read_bounded_regular_file(&manifest_path, MAX_MANIFEST_BYTES).unwrap();
    let manifest_sha256 = sha256(&manifest_bytes);
    let cases: Vec<LanguageComparatorCase> = serde_json::from_slice(&manifest_bytes).unwrap();
    assert!(!cases.is_empty() && cases.len() <= MAX_CASES);

    let fixture_root = manifest_path.parent().unwrap().canonicalize().unwrap();
    let mut paths = BTreeSet::new();
    let mut source_rows = BTreeSet::new();
    for case in &cases {
        validate_case_metadata(case).unwrap();
        assert!(paths.insert(case.path.clone()), "duplicate fixture path");
        assert!(
            source_rows.insert((case.fleurs_config.clone(), case.row_id)),
            "duplicate FLEURS source row"
        );
    }

    let catalog =
        LocalLanguageCatalog::try_new("en-US", ["en-US", "es-ES", "fr-FR", "pt-BR"]).unwrap();
    let load_started = Instant::now();
    let mut detector =
        AmberNetSileroLanguageDetector::load_at(&ambernet_root, &silero_root, catalog).unwrap();
    let load_ms = load_started.elapsed().as_secs_f64() * 1_000.0;

    let window_samples = usize::try_from(RESIDENT_LANGUAGE_WINDOW_SAMPLES).unwrap();
    let hop_samples = usize::try_from(RESIDENT_LANGUAGE_HOP_SAMPLES).unwrap();
    let mut correct_cases = 0;
    let mut correct_windows = 0;
    let mut evaluated_windows = 0;
    let mut cases_with_speech = 0;
    let mut speech_qualified_windows = 0;
    let mut source_audio_ms = 0;
    let mut inference_micros = Vec::with_capacity(cases.len());
    let mut per_language = BTreeMap::<String, LanguageScore>::new();
    let mut language_confusions = BTreeMap::<String, BTreeMap<String, usize>>::new();
    for case in &cases {
        let path = fixture_root.join(&case.path);
        assert_eq!(path.parent().unwrap().canonicalize().unwrap(), fixture_root);
        let before = read_bounded_regular_file(&path, MAX_WAV_BYTES).unwrap();
        assert_eq!(sha256(&before), case.sha256);
        let wave = sherpa_onnx::Wave::read(path.to_str().unwrap()).unwrap();
        let after = read_bounded_regular_file(&path, MAX_WAV_BYTES).unwrap();
        assert_eq!(sha256(&after), case.sha256);
        assert_eq!(before, after, "fixture changed while it was decoded");
        assert_eq!(wave.sample_rate(), SAMPLE_RATE_HZ as i32);
        let decoded_duration_ms = ((wave.samples().len() as u64 * 1_000)
            + (SAMPLE_RATE_HZ as u64 / 2))
            / SAMPLE_RATE_HZ as u64;
        assert!(decoded_duration_ms.abs_diff(case.duration_ms) <= 1);

        assert!(wave.samples().len() >= window_samples);
        source_audio_ms += decoded_duration_ms;
        let score = per_language
            .entry(case.expected_language.clone())
            .or_default();
        score.total_cases += 1;
        let mut votes = BTreeMap::<String, usize>::new();
        let mut case_has_speech = false;
        for start in (0..=wave.samples().len() - window_samples).step_by(hop_samples) {
            let end = start + window_samples;
            let inference_started = Instant::now();
            let observation = detector
                .observe(start as u64, end as u64, &wave.samples()[start..end])
                .unwrap();
            inference_micros.push(inference_started.elapsed().as_micros() as u64);
            evaluated_windows += 1;
            score.total_windows += 1;
            let detected_language = observation
                .language_bcp47
                .as_deref()
                .and_then(|locale| locale.split('-').next());
            let detected_label = detected_language.unwrap_or("unknown");
            *language_confusions
                .entry(case.expected_language.clone())
                .or_default()
                .entry(detected_label.to_owned())
                .or_default() += 1;
            if detected_language == Some(case.expected_language.as_str()) {
                correct_windows += 1;
                score.correct_windows += 1;
            }
            if observation.speech_ratio >= MIN_SPEECH_RATIO_FOR_CLASSIFICATION {
                case_has_speech = true;
                speech_qualified_windows += 1;
                if let Some(language) = detected_language {
                    *votes.entry(language.to_owned()).or_default() += 1;
                }
            }
        }
        assert!(evaluated_windows <= MAX_EVALUATION_WINDOWS);
        if case_has_speech {
            cases_with_speech += 1;
        }
        if unique_plurality(&votes) == Some(case.expected_language.as_str()) {
            correct_cases += 1;
            score.correct_cases += 1;
        }
    }

    inference_micros.sort_unstable();
    assert!(!inference_micros.is_empty());
    let mean_inference_ms =
        inference_micros.iter().sum::<u64>() as f64 / inference_micros.len() as f64 / 1_000.0;
    let evaluated_window_audio_ms =
        evaluated_windows as u64 * RESIDENT_LANGUAGE_WINDOW_SAMPLES * 1_000 / SAMPLE_RATE_HZ as u64;
    let summary = LanguageComparatorSummary {
        schema_version: 1,
        component_revision: WINDOW_COMPONENT_REVISION,
        manifest_sha256,
        fixture_cases: cases.len(),
        correct_cases,
        case_accuracy: correct_cases as f64 / cases.len() as f64,
        evaluated_windows,
        correct_windows,
        window_accuracy: correct_windows as f64 / evaluated_windows as f64,
        cases_with_speech,
        speech_qualified_windows,
        source_audio_ms,
        evaluated_window_audio_ms,
        resident_window_samples: RESIDENT_LANGUAGE_WINDOW_SAMPLES,
        resident_hop_samples: RESIDENT_LANGUAGE_HOP_SAMPLES,
        load_ms,
        mean_inference_ms,
        p50_inference_ms: percentile_millis(&inference_micros, 50),
        p95_inference_ms: percentile_millis(&inference_micros, 95),
        p99_inference_ms: percentile_millis(&inference_micros, 99),
        inference_real_time_factor: inference_micros.iter().sum::<u64>() as f64
            / 1_000.0
            / evaluated_window_audio_ms as f64,
        per_language,
        language_confusions,
    };
    eprintln!(
        "lid_comparator={}",
        serde_json::to_string(&summary).unwrap()
    );
}

fn required_path(environment: &str) -> PathBuf {
    PathBuf::from(
        std::env::var(environment).unwrap_or_else(|_| panic!("{environment} is required")),
    )
}

fn validate_case_metadata(case: &LanguageComparatorCase) -> Result<(), &'static str> {
    if !(2..=3).contains(&case.expected_language.len())
        || !case
            .expected_language
            .bytes()
            .all(|byte| byte.is_ascii_lowercase())
    {
        return Err("expected language is invalid");
    }
    if !crate::language::valid_bcp47(&case.target_locale)
        || case.target_locale.split('-').next() != Some(case.expected_language.as_str())
    {
        return Err("target locale does not match the expected language");
    }
    let mut components = Path::new(&case.path).components();
    if !matches!(components.next(), Some(Component::Normal(_))) || components.next().is_some() {
        return Err("fixture path is not one safe file name");
    }
    if !(250..=MAX_FIXTURE_DURATION_MS).contains(&case.duration_ms) {
        return Err("fixture duration is outside the comparator bound");
    }
    if case.sha256.len() != 64
        || !case
            .sha256
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("fixture SHA-256 is invalid");
    }
    if case.fleurs_config.is_empty()
        || case.fleurs_config.len() > 32
        || !case
            .fleurs_config
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
    {
        return Err("FLEURS config is invalid");
    }
    if !matches!(
        case.fixture_access.as_str(),
        "datasets-server" | "streaming-parquet"
    ) {
        return Err("fixture access method is unsupported");
    }
    if case
        .transcript
        .as_deref()
        .is_some_and(|transcript| transcript.is_empty() || transcript.len() > 8_192)
    {
        return Err("reference transcript is unbounded");
    }
    Ok(())
}

fn read_bounded_regular_file(path: &Path, maximum_bytes: u64) -> std::io::Result<Vec<u8>> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file() || metadata.len() > maximum_bytes {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "evaluation artifact is not a bounded regular file",
        ));
    }
    let bytes = fs::read(path)?;
    if bytes.len() as u64 != metadata.len() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "evaluation artifact changed while it was read",
        ));
    }
    Ok(bytes)
}

fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn percentile_millis(sorted_micros: &[u64], percentile: usize) -> f64 {
    let index = (sorted_micros.len() - 1) * percentile / 100;
    sorted_micros[index] as f64 / 1_000.0
}

fn unique_plurality(votes: &BTreeMap<String, usize>) -> Option<&str> {
    let mut winner = None;
    let mut maximum = 0;
    let mut tied = false;
    for (language, count) in votes {
        match count.cmp(&maximum) {
            std::cmp::Ordering::Greater => {
                winner = Some(language.as_str());
                maximum = *count;
                tied = false;
            }
            std::cmp::Ordering::Equal => tied = true,
            std::cmp::Ordering::Less => {}
        }
    }
    (!tied).then_some(winner).flatten()
}

fn valid_case() -> LanguageComparatorCase {
    LanguageComparatorCase {
        expected_language: "en".into(),
        target_locale: "en-US".into(),
        fleurs_config: "en_us".into(),
        row_id: 1,
        path: "en-1.wav".into(),
        duration_ms: 1_000,
        sha256: "a".repeat(64),
        fixture_access: "datasets-server".into(),
        transcript: Some("bounded reference".into()),
    }
}
