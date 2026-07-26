//! Converts a complete acoustic classifier output into one fail-closed locale.
//!
//! The strongest label is selected before consulting the user's enabled
//! locales. This deliberately prevents a closed-set classifier from forcing
//! the best enabled language when a disabled or unsupported language actually
//! won the window.

use std::collections::BTreeSet;

use super::live_catalog::LocalLanguageCatalog;

const MAX_LANGUAGE_LABELS: usize = 256;

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct AcousticLanguageClassification {
    pub(crate) language_code: Option<String>,
    pub(crate) language_bcp47: Option<String>,
    pub(crate) score: f32,
    pub(crate) margin: f32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum AcousticLanguageClassificationError {
    InvalidLabelCount,
    InvalidLanguageCode,
    DuplicateLanguageCode,
    InvalidLogit,
}

impl std::fmt::Display for AcousticLanguageClassificationError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::InvalidLabelCount => {
                "acoustic language labels do not match the locked classifier output"
            }
            Self::InvalidLanguageCode => {
                "acoustic language classifier contains an invalid language code"
            }
            Self::DuplicateLanguageCode => {
                "acoustic language classifier contains a duplicate language code"
            }
            Self::InvalidLogit => "acoustic language classifier returned an invalid logit",
        })
    }
}

impl std::error::Error for AcousticLanguageClassificationError {}

/// Immutable mapping from one locked acoustic classifier to the user's enabled
/// regional locales. Label validation and locale resolution happen once when
/// the component is loaded, not on every overlapping observation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct AcousticLanguageLogitResolver {
    language_codes: Vec<String>,
    language_bcp47: Vec<Option<String>>,
}

impl AcousticLanguageLogitResolver {
    pub(crate) fn try_new(
        catalog: &LocalLanguageCatalog,
        expected_label_count: usize,
        language_codes: Vec<String>,
    ) -> Result<Self, AcousticLanguageClassificationError> {
        if !(2..=MAX_LANGUAGE_LABELS).contains(&expected_label_count)
            || language_codes.len() != expected_label_count
        {
            return Err(AcousticLanguageClassificationError::InvalidLabelCount);
        }

        let mut unique_codes = BTreeSet::new();
        for language_code in &language_codes {
            if !valid_language_code(language_code) {
                return Err(AcousticLanguageClassificationError::InvalidLanguageCode);
            }
            if !unique_codes.insert(language_code.as_str()) {
                return Err(AcousticLanguageClassificationError::DuplicateLanguageCode);
            }
        }

        let language_bcp47 = language_codes
            .iter()
            .map(|code| catalog.resolve_language_code(code).map(str::to_owned))
            .collect();
        Ok(Self {
            language_codes,
            language_bcp47,
        })
    }

    /// Resolves logits from every locked classifier label without enabled-set
    /// filtering or renormalization.
    pub(crate) fn classify(
        &self,
        logits: &[f32],
    ) -> Result<AcousticLanguageClassification, AcousticLanguageClassificationError> {
        if logits.len() != self.language_codes.len() {
            return Err(AcousticLanguageClassificationError::InvalidLabelCount);
        }
        if logits.iter().any(|logit| !logit.is_finite()) {
            return Err(AcousticLanguageClassificationError::InvalidLogit);
        }

        let (mut best_index, mut runner_up_index) = if logits[0] >= logits[1] {
            (0, 1)
        } else {
            (1, 0)
        };
        for index in 2..logits.len() {
            if logits[index] > logits[best_index] {
                runner_up_index = best_index;
                best_index = index;
            } else if logits[index] > logits[runner_up_index] {
                runner_up_index = index;
            }
        }
        let best_logit = f64::from(logits[best_index]);
        let normalization = logits
            .iter()
            .map(|logit| (f64::from(*logit) - best_logit).exp())
            .sum::<f64>();
        if !normalization.is_finite() || normalization <= 0.0 {
            return Err(AcousticLanguageClassificationError::InvalidLogit);
        }

        let score = (1.0 / normalization) as f32;
        let runner_up_score =
            ((f64::from(logits[runner_up_index]) - best_logit).exp() / normalization) as f32;
        let margin = (score - runner_up_score).max(0.0);
        let unique_winner = logits[best_index] > logits[runner_up_index];

        Ok(AcousticLanguageClassification {
            language_code: unique_winner.then(|| self.language_codes[best_index].clone()),
            language_bcp47: unique_winner
                .then(|| self.language_bcp47[best_index].clone())
                .flatten(),
            score,
            margin,
        })
    }
}

fn valid_language_code(language_code: &str) -> bool {
    (2..=3).contains(&language_code.len())
        && language_code.bytes().all(|byte| byte.is_ascii_lowercase())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn codes(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| (*value).to_owned()).collect()
    }

    fn resolver(catalog: &LocalLanguageCatalog, values: &[&str]) -> AcousticLanguageLogitResolver {
        AcousticLanguageLogitResolver::try_new(catalog, values.len(), codes(values)).unwrap()
    }

    #[test]
    fn strongest_disabled_language_causes_abstention_instead_of_enabled_fallback() {
        let catalog = LocalLanguageCatalog::try_new("en-US", ["en-US", "fr-FR"]).unwrap();
        let classification = resolver(&catalog, &["en", "fr", "ja"])
            .classify(&[9.0, 8.0, 10.0])
            .unwrap();

        assert_eq!(classification.language_code.as_deref(), Some("ja"));
        assert_eq!(classification.language_bcp47, None);
        assert!(classification.score > 0.6);
        assert!(classification.margin > 0.3);
    }

    #[test]
    fn winning_base_language_preserves_the_users_selected_region() {
        let catalog = LocalLanguageCatalog::try_new("en-GB", ["en-GB", "fr-CA"]).unwrap();
        let classification = resolver(&catalog, &["en", "fr", "ja"])
            .classify(&[4.0, 1.0, 0.0])
            .unwrap();

        assert_eq!(classification.language_code.as_deref(), Some("en"));
        assert_eq!(classification.language_bcp47.as_deref(), Some("en-GB"));
    }

    #[test]
    fn equal_global_winners_abstain_independent_of_label_order() {
        let catalog = LocalLanguageCatalog::try_new("en-US", ["en-US", "fr-FR"]).unwrap();
        for language_codes in [codes(&["en", "fr"]), codes(&["fr", "en"])] {
            let classification =
                AcousticLanguageLogitResolver::try_new(&catalog, 2, language_codes)
                    .unwrap()
                    .classify(&[1.0, 1.0])
                    .unwrap();
            assert_eq!(classification.language_code, None);
            assert_eq!(classification.language_bcp47, None);
            assert_eq!(classification.margin, 0.0);
        }
    }

    #[test]
    fn locked_shape_codes_and_finite_logits_are_mandatory() {
        let catalog = LocalLanguageCatalog::try_new("en-US", ["en-US"]).unwrap();
        assert_eq!(
            AcousticLanguageLogitResolver::try_new(&catalog, 3, codes(&["en", "fr"])),
            Err(AcousticLanguageClassificationError::InvalidLabelCount)
        );
        assert_eq!(
            AcousticLanguageLogitResolver::try_new(&catalog, 2, codes(&["en", "en"])),
            Err(AcousticLanguageClassificationError::DuplicateLanguageCode)
        );
        assert_eq!(
            AcousticLanguageLogitResolver::try_new(&catalog, 2, codes(&["EN", "fr"])),
            Err(AcousticLanguageClassificationError::InvalidLanguageCode)
        );
        let resolver = resolver(&catalog, &["en", "fr"]);
        assert_eq!(
            resolver.classify(&[f32::NAN, 0.0]),
            Err(AcousticLanguageClassificationError::InvalidLogit)
        );
        assert_eq!(
            resolver.classify(&[1.0]),
            Err(AcousticLanguageClassificationError::InvalidLabelCount)
        );
    }
}
