//! Bounded resident AmberNet acoustic language identification.
//!
//! The model is an explicitly imported, hash-locked NVIDIA AmberNet 1.12.0
//! derivative. It supplies acoustic evidence only; the Rust live-language
//! policy remains the sole owner of locale selection, switching, and spans.

#[cfg(test)]
mod evaluation;
mod frontend;
mod lifecycle;

use std::{
    path::{Path, PathBuf},
    sync::OnceLock,
};

use ort::{session::Session, value::TensorRef};

use crate::{
    language::{
        acoustic_language_classification::{
            AcousticLanguageClassificationError, AcousticLanguageLogitResolver,
        },
        live_catalog::LocalLanguageCatalog,
        live_diarization::{AcousticLanguageObservation, LanguageDiarizationError},
    },
    stt::{
        error::SttError,
        nemotron::{Artifact, ModelLoadGuard},
        silero_vad::{SileroVadDetector, SileroVadRuntimeError},
    },
};

use frontend::{
    AmberNetFeatureExtractor, FeatureExtractionError, MEL_BINS, PADDED_FRAMES, SAMPLE_RATE_HZ,
    WINDOW_SAMPLES,
};

pub use lifecycle::{
    import_from_file, remove, status, verify, AcousticLanguageDetectorInstallState,
    AcousticLanguageDetectorStatus, AcousticLanguageDetectorView,
};

pub const MODEL_ID: &str = "nvidia/nemo/langid_ambernet";
pub const MODEL_REVISION: &str = "1.12.0";
pub const MODEL_SOURCE_URL: &str =
    "https://api.ngc.nvidia.com/v2/models/nvidia/nemo/langid_ambernet/versions/1.12.0/files/ambernet.nemo";
pub const COMPONENT_REVISION: &str =
    "ambernet-1.12.0-int8-qdq@sha256:ef1006c7637803540e12ab01021e442382857689cbe0b1909d3128acf66a0a3e+frontend:nemo-fixed-3s-v1";
pub const WINDOW_COMPONENT_REVISION: &str =
    "ambernet-1.12.0-int8-qdq@sha256:ef1006c7637803540e12ab01021e442382857689cbe0b1909d3128acf66a0a3e+frontend:nemo-fixed-3s-v1+silero-vad@sha256:9e2449e1087496d8";

pub(super) const MODEL_DIRECTORY: &str = "ambernet-lid/sha256-ef1006c763780354";
pub(crate) const MODEL_FILE: &str = "ambernet-1.12.0-classifier-int8-qdq.onnx";
pub(crate) const MODEL_SHA256: &str =
    "ef1006c7637803540e12ab01021e442382857689cbe0b1909d3128acf66a0a3e";
pub(crate) const RESIDENT_LANGUAGE_WINDOW_SAMPLES: u64 = WINDOW_SAMPLES as u64;
pub(crate) const RESIDENT_LANGUAGE_HOP_SAMPLES: u64 = (SAMPLE_RATE_HZ / 2) as u64;
const MIN_SPEECH_RATIO_FOR_CLASSIFICATION: f32 = 0.25;
const OUTPUT_LABEL_COUNT: usize = 107;

pub(super) const ARTIFACTS: &[Artifact] = &[Artifact {
    file: MODEL_FILE,
    sha256: MODEL_SHA256,
    bytes: 29_613_392,
}];

// The raw order is part of the locked 1.12.0 checkpoint contract. Deprecated
// identifiers are preserved here so the source label-order hash remains
// auditable, then normalized only at the model boundary.
const RAW_AMBERNET_LANGUAGE_CODES: [&str; OUTPUT_LABEL_COUNT] = [
    "ab", "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs", "ca", "ceb",
    "cs", "cy", "da", "de", "el", "en", "eo", "es", "et", "eu", "fa", "fi", "fo", "fr", "gl", "gn",
    "gu", "gv", "ha", "haw", "hi", "hr", "ht", "hu", "hy", "ia", "id", "is", "it", "iw", "ja",
    "jw", "ka", "kk", "km", "kn", "ko", "la", "lb", "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml",
    "mn", "mr", "ms", "mt", "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru",
    "sa", "sco", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw", "ta", "te",
    "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi", "war", "yi", "yo", "zh",
];

static ONNX_RUNTIME_INITIALIZATION: OnceLock<Result<(), ()>> = OnceLock::new();

pub struct AmberNetLanguageIdentifier {
    // Field order is deliberate: the native session must drop before the model
    // snapshot guard releases the exact bytes that backed it.
    session: Session,
    frontend: AmberNetFeatureExtractor,
    resolver: AcousticLanguageLogitResolver,
    _model_guard: ModelLoadGuard,
}

pub(crate) struct AmberNetSileroLanguageDetector {
    language: AmberNetLanguageIdentifier,
    speech: SileroVadDetector,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AmberNetLanguageError {
    InvalidWindow,
    InferenceFailed,
    InvalidResult,
}

impl std::fmt::Display for AmberNetLanguageError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::InvalidWindow => "AmberNet language-identification window is invalid",
            Self::InferenceFailed => "AmberNet language-identification inference failed",
            Self::InvalidResult => "AmberNet language-identification result is invalid",
        })
    }
}

impl std::error::Error for AmberNetLanguageError {}

#[derive(Debug)]
pub(crate) enum AmberNetSileroLanguageError {
    Speech(SileroVadRuntimeError),
    Language(AmberNetLanguageError),
    Observation(LanguageDiarizationError),
}

impl std::fmt::Display for AmberNetSileroLanguageError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Speech(error) => write!(formatter, "local speech mask failed: {error}"),
            Self::Language(error) => write!(formatter, "local language classifier failed: {error}"),
            Self::Observation(error) => {
                write!(formatter, "local language observation is invalid: {error}")
            }
        }
    }
}

impl std::error::Error for AmberNetSileroLanguageError {}

impl AmberNetLanguageIdentifier {
    pub fn load(catalog: &LocalLanguageCatalog) -> Result<Self, SttError> {
        Self::load_at(&root_dir(), catalog)
    }

    fn load_at(root: &Path, catalog: &LocalLanguageCatalog) -> Result<Self, SttError> {
        initialize_static_onnx_runtime()?;
        let guard = ModelLoadGuard::open(root, ARTIFACTS)?;
        let builder = Session::builder().map_err(|_| SttError::ModelCorrupt)?;
        let builder = builder
            .with_intra_threads(1)
            .map_err(|_| SttError::ModelCorrupt)?;
        let mut builder = builder
            .with_inter_threads(1)
            .map_err(|_| SttError::ModelCorrupt)?;
        let session = builder
            .commit_from_file(guard.path(0))
            .map_err(|_| SttError::ModelCorrupt)?;
        if session.inputs().len() != 1
            || session.inputs()[0].name() != "processed_signal"
            || session.outputs().len() != 1
            || session.outputs()[0].name() != "logits"
        {
            return Err(SttError::ModelCorrupt);
        }
        // Build once so malformed or duplicate label maps cannot fail later in
        // an active capture session.
        let resolver = AcousticLanguageLogitResolver::try_new(
            catalog,
            OUTPUT_LABEL_COUNT,
            normalized_language_codes(),
        )
        .map_err(|_| SttError::ModelCorrupt)?;
        guard.revalidate_after_native_load()?;
        Ok(Self {
            session,
            frontend: AmberNetFeatureExtractor::new(),
            resolver,
            _model_guard: guard,
        })
    }

    fn classify(
        &mut self,
        samples: &[f32],
    ) -> Result<
        crate::language::acoustic_language_classification::AcousticLanguageClassification,
        AmberNetLanguageError,
    > {
        let features = self
            .frontend
            .process(samples)
            .map_err(|error| match error {
                FeatureExtractionError::InvalidWindow => AmberNetLanguageError::InvalidWindow,
                FeatureExtractionError::FftFailed => AmberNetLanguageError::InferenceFailed,
            })?;
        let input =
            TensorRef::<f32>::from_array_view(([1_usize, MEL_BINS, PADDED_FRAMES], features))
                .map_err(|_| AmberNetLanguageError::InferenceFailed)?;
        let outputs = self
            .session
            .run(ort::inputs!["processed_signal" => input])
            .map_err(|_| AmberNetLanguageError::InferenceFailed)?;
        let logits = outputs
            .get("logits")
            .ok_or(AmberNetLanguageError::InvalidResult)?
            .try_extract_array::<f32>()
            .map_err(|_| AmberNetLanguageError::InvalidResult)?;
        if logits.shape() != [1, OUTPUT_LABEL_COUNT] {
            return Err(AmberNetLanguageError::InvalidResult);
        }
        let logits = logits
            .as_slice()
            .ok_or(AmberNetLanguageError::InvalidResult)?;
        self.resolver.classify(logits).map_err(classification_error)
    }
}

impl AmberNetSileroLanguageDetector {
    pub(crate) fn load(catalog: LocalLanguageCatalog) -> Result<Self, SttError> {
        Ok(Self {
            language: AmberNetLanguageIdentifier::load(&catalog)?,
            speech: SileroVadDetector::load()?,
        })
    }

    #[cfg(test)]
    pub(crate) fn load_at(
        ambernet_root: &Path,
        silero_root: &Path,
        catalog: LocalLanguageCatalog,
    ) -> Result<Self, SttError> {
        Ok(Self {
            language: AmberNetLanguageIdentifier::load_at(ambernet_root, &catalog)?,
            speech: SileroVadDetector::load_at(silero_root)?,
        })
    }

    pub(crate) fn component_revision(&self) -> &'static str {
        WINDOW_COMPONENT_REVISION
    }

    pub(crate) fn observe(
        &mut self,
        start_sample: u64,
        end_sample: u64,
        samples: &[f32],
    ) -> Result<AcousticLanguageObservation, AmberNetSileroLanguageError> {
        if end_sample.checked_sub(start_sample) != Some(samples.len() as u64) {
            return Err(AmberNetSileroLanguageError::Observation(
                LanguageDiarizationError::InvalidObservation,
            ));
        }
        let speech_ratio = self
            .speech
            .speech_ratio(samples)
            .map_err(AmberNetSileroLanguageError::Speech)?;
        let classification = if speech_ratio >= MIN_SPEECH_RATIO_FOR_CLASSIFICATION {
            Some(
                self.language
                    .classify(samples)
                    .map_err(AmberNetSileroLanguageError::Language)?,
            )
        } else {
            None
        };
        AcousticLanguageObservation::try_new(
            start_sample,
            end_sample,
            classification
                .as_ref()
                .and_then(|result| result.language_bcp47.as_deref()),
            speech_ratio,
            classification.as_ref().map(|result| result.score),
            classification.as_ref().map(|result| result.margin),
            WINDOW_COMPONENT_REVISION,
        )
        .map_err(AmberNetSileroLanguageError::Observation)
    }
}

pub fn root_dir() -> PathBuf {
    crate::stt::model::models_dir().join(MODEL_DIRECTORY)
}

fn initialize_static_onnx_runtime() -> Result<(), SttError> {
    match ONNX_RUNTIME_INITIALIZATION.get_or_init(|| {
        // Keep sherpa-onnx's statically linked ONNX Runtime in the final binary.
        let link_anchor = sherpa_onnx::SpeakerEmbeddingExtractorConfig::default();
        if link_anchor.provider.as_deref() != Some("cpu") {
            return Err(());
        }
        // SAFETY: OrtGetApiBase is supplied by the one sherpa-onnx static
        // archive. We check both pointers before copying the immutable API table,
        // and OnceLock guarantees one process-wide registration attempt.
        let api = unsafe {
            let base = ort::sys::OrtGetApiBase();
            if base.is_null() {
                return Err(());
            }
            let api = ((*base).GetApi)(ort::sys::ORT_API_VERSION);
            if api.is_null() {
                return Err(());
            }
            (*api).clone()
        };
        ort::set_api(api).then_some(()).ok_or(())
    }) {
        Ok(()) => Ok(()),
        Err(()) => Err(SttError::SidecarCrash),
    }
}

fn normalized_language_codes() -> Vec<String> {
    RAW_AMBERNET_LANGUAGE_CODES
        .iter()
        .map(|code| {
            match *code {
                "iw" => "he",
                "jw" => "jv",
                // Nemotron and the product catalog use Norwegian Bokmal's
                // modern ISO 639-1 identifier; Nynorsk (`nn`) stays distinct.
                "no" => "nb",
                current => current,
            }
            .to_owned()
        })
        .collect()
}

fn classification_error(_: AcousticLanguageClassificationError) -> AmberNetLanguageError {
    AmberNetLanguageError::InvalidResult
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn locked_label_map_has_expected_aliases_and_revision() {
        use sha2::{Digest, Sha256};

        assert_eq!(RAW_AMBERNET_LANGUAGE_CODES.len(), OUTPUT_LABEL_COUNT);
        assert_eq!(RAW_AMBERNET_LANGUAGE_CODES[44], "iw");
        assert_eq!(RAW_AMBERNET_LANGUAGE_CODES[46], "jw");
        assert_eq!(RAW_AMBERNET_LANGUAGE_CODES[70], "no");
        let label_order_hash = Sha256::digest(RAW_AMBERNET_LANGUAGE_CODES.join("\n").as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        assert_eq!(
            label_order_hash,
            "9c64d2027a37ed72852eea368a7c81eff62efb3c39e72a1567dad35fb83d2e50"
        );
        let normalized = normalized_language_codes();
        assert_eq!(normalized[44], "he");
        assert_eq!(normalized[46], "jv");
        assert_eq!(normalized[69], "nn");
        assert_eq!(normalized[70], "nb");
        assert!(COMPONENT_REVISION.contains(ARTIFACTS[0].sha256));
        assert!(WINDOW_COMPONENT_REVISION.contains(ARTIFACTS[0].sha256));
    }

    #[test]
    fn every_live_nemotron_language_resolves_without_collapsing_nynorsk() {
        let mut seen = std::collections::BTreeSet::new();
        let locales = crate::stt::nemotron::supported_live_locales()
            .iter()
            .copied()
            .filter(|locale| seen.insert(crate::language::live_catalog::base_language(locale)))
            .collect::<Vec<_>>();
        let catalog = LocalLanguageCatalog::try_new("en-US", locales.iter().copied()).unwrap();
        let codes = normalized_language_codes();
        let resolver =
            AcousticLanguageLogitResolver::try_new(&catalog, OUTPUT_LABEL_COUNT, codes.clone())
                .unwrap();

        for locale in locales {
            let code = crate::language::live_catalog::base_language(locale);
            let index = codes
                .iter()
                .position(|candidate| candidate == code)
                .unwrap();
            let mut logits = vec![-10.0_f32; OUTPUT_LABEL_COUNT];
            logits[index] = 10.0;
            let classification = resolver.classify(&logits).unwrap();
            assert_eq!(classification.language_bcp47.as_deref(), Some(locale));
        }

        let nynorsk = codes.iter().position(|code| code == "nn").unwrap();
        let mut logits = vec![-10.0_f32; OUTPUT_LABEL_COUNT];
        logits[nynorsk] = 10.0;
        let classification = resolver.classify(&logits).unwrap();
        assert_eq!(classification.language_code.as_deref(), Some("nn"));
        assert_eq!(classification.language_bcp47, None);
    }

    #[test]
    fn missing_detector_never_creates_or_downloads_files() {
        let root = std::env::temp_dir().join(format!(
            "yap-ambernet-lid-missing-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        let catalog = LocalLanguageCatalog::try_new("en-US", ["en-US"]).unwrap();
        assert!(AmberNetLanguageIdentifier::load_at(&root, &catalog).is_err());
        assert!(!root.exists());
    }

    #[test]
    #[ignore = "requires a verified AmberNet import and public 16 kHz WAV fixtures"]
    fn pinned_detector_loads_twice_and_classifies_public_fixtures() {
        let root = PathBuf::from(
            std::env::var("YAP_TEST_AMBERNET_LID_ROOT")
                .expect("YAP_TEST_AMBERNET_LID_ROOT is required"),
        );
        let fixtures = PathBuf::from(
            std::env::var("YAP_TEST_AMBERNET_LID_FIXTURES")
                .expect("YAP_TEST_AMBERNET_LID_FIXTURES is required"),
        );
        let mut fixture_paths = std::fs::read_dir(&fixtures)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .filter(|path| path.extension().is_some_and(|extension| extension == "wav"))
            .collect::<Vec<_>>();
        fixture_paths.sort();
        let catalog = LocalLanguageCatalog::try_new("en-US", ["en-US", "ja-JP"]).unwrap();
        for _ in 0..2 {
            let mut identifier = AmberNetLanguageIdentifier::load_at(&root, &catalog).unwrap();
            for (prefix, expected) in [("en-", "en-US"), ("ja-", "ja-JP")] {
                let mut attempted = 0_usize;
                let matched = fixture_paths
                    .iter()
                    .filter(|path| {
                        path.file_name()
                            .and_then(|name| name.to_str())
                            .is_some_and(|name| name.starts_with(prefix))
                    })
                    .take(10)
                    .any(|path| {
                        attempted += 1;
                        let wave = sherpa_onnx::Wave::read(path.to_str().unwrap()).unwrap();
                        assert_eq!(wave.sample_rate(), SAMPLE_RATE_HZ as i32);
                        if wave.samples().len() < WINDOW_SAMPLES {
                            return false;
                        }
                        identifier
                            .classify(&wave.samples()[..WINDOW_SAMPLES])
                            .unwrap()
                            .language_bcp47
                            .as_deref()
                            == Some(expected)
                    });
                assert!(
                    matched,
                    "none of {attempted} bounded {prefix} fixtures mapped to {expected}"
                );
            }
        }
    }
}
