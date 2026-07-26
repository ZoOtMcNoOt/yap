//! Deterministic mapping from acoustic language codes to local ASR tags.
//!
//! Acoustic LID identifies a language, not a regional dialect. The catalog
//! therefore permits at most one enabled BCP 47 locale per base language and
//! never invents a region.

use std::collections::{BTreeMap, BTreeSet};

const MAX_LOCAL_LANGUAGES: usize = 128;
const SUPPORTED_LOCAL_ASR_LOCALES: &[&str] = &[
    // Transcription-ready.
    "en-US", "en-GB", "es-US", "es-ES", "fr-FR", "fr-CA", "it-IT", "pt-BR", "pt-PT", "nl-NL",
    "de-DE", "tr-TR", "ru-RU", "ar-AR", "hi-IN", "ja-JP", "ko-KR", "vi-VN", "uk-UA",
    // Broad coverage. Availability is not a quality-promotion claim.
    "pl-PL", "sv-SE", "cs-CZ", "nb-NO", "da-DK", "bg-BG", "fi-FI", "hr-HR", "sk-SK", "zh-CN",
    "hu-HU", "ro-RO", "et-EE",
];

/// Changes when the executable local ASR locale catalog, automatic-route
/// preview matrix, or language detector identity changes.
pub(crate) const LOCAL_LANGUAGE_ROUTING_REVISION: &str =
    "nemotron-3.5-asr-streaming-0.6b-1120ms-int8@d2f58fb3c1ae44829133de74c1b5aa6e3e6dda04/locales-v1/ambernet-1.12.0-int8-qdq-ef1006c-margin0.4-v1";

pub(crate) fn supports_local_asr_language(language_bcp47: &str) -> bool {
    SUPPORTED_LOCAL_ASR_LOCALES.contains(&language_bcp47)
}

pub(crate) fn supported_local_asr_locales() -> &'static [&'static str] {
    SUPPORTED_LOCAL_ASR_LOCALES
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LocalLanguageCatalogError {
    InvalidPrimary,
    InvalidLocale,
    UnsupportedLocale,
    PrimaryMissing,
    AmbiguousBaseLanguage,
    AutomaticAlternateUnavailable,
    TooManyLanguages,
}

impl std::fmt::Display for LocalLanguageCatalogError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::InvalidPrimary => "primary local language is invalid",
            Self::InvalidLocale => "local language catalog contains an invalid locale",
            Self::UnsupportedLocale => "local language catalog contains an unsupported locale",
            Self::PrimaryMissing => "local language catalog does not contain its primary locale",
            Self::AmbiguousBaseLanguage => {
                "local language catalog contains multiple locales for one acoustic language"
            }
            Self::AutomaticAlternateUnavailable => {
                "local language catalog contains an unavailable automatic route"
            }
            Self::TooManyLanguages => "local language catalog is too large",
        })
    }
}

impl std::error::Error for LocalLanguageCatalogError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalLanguageCatalog {
    primary_language_bcp47: String,
    by_language_code: BTreeMap<String, String>,
}

impl LocalLanguageCatalog {
    pub fn try_new<I, S>(
        primary_language_bcp47: &str,
        enabled_locales: I,
    ) -> Result<Self, LocalLanguageCatalogError>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        if !super::valid_bcp47(primary_language_bcp47) {
            return Err(LocalLanguageCatalogError::InvalidPrimary);
        }
        let mut by_language_code = BTreeMap::new();
        let mut exact = BTreeSet::new();
        for locale in enabled_locales {
            let locale = locale.as_ref();
            if !super::valid_bcp47(locale) {
                return Err(LocalLanguageCatalogError::InvalidLocale);
            }
            if !supports_local_asr_language(locale) {
                return Err(LocalLanguageCatalogError::UnsupportedLocale);
            }
            if !exact.insert(locale.to_owned()) {
                return Err(LocalLanguageCatalogError::AmbiguousBaseLanguage);
            }
            if exact.len() > MAX_LOCAL_LANGUAGES {
                return Err(LocalLanguageCatalogError::TooManyLanguages);
            }
            let code = base_language(locale);
            if by_language_code
                .insert(code.to_owned(), locale.to_owned())
                .is_some()
            {
                return Err(LocalLanguageCatalogError::AmbiguousBaseLanguage);
            }
        }
        if !exact.contains(primary_language_bcp47) {
            return Err(LocalLanguageCatalogError::PrimaryMissing);
        }
        Ok(Self {
            primary_language_bcp47: primary_language_bcp47.to_owned(),
            by_language_code,
        })
    }

    /// Builds the closed automatic-routing catalog from the confirmed primary
    /// and user-enabled alternates in the explicitly bounded preview matrix.
    /// Model support alone never enables an automatic route, and availability
    /// is not a locale-specific quality claim.
    pub fn with_explicit_automatic_alternates<I, S>(
        primary_language_bcp47: &str,
        enabled_alternate_locales: I,
    ) -> Result<Self, LocalLanguageCatalogError>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        if !supports_local_asr_language(primary_language_bcp47) {
            return Err(LocalLanguageCatalogError::InvalidPrimary);
        }
        let available = available_automatic_alternates(primary_language_bcp47);
        let mut enabled = vec![primary_language_bcp47.to_owned()];
        for locale in enabled_alternate_locales {
            let locale = locale.as_ref();
            if !super::valid_bcp47(locale) {
                return Err(LocalLanguageCatalogError::InvalidLocale);
            }
            if !supports_local_asr_language(locale) {
                return Err(LocalLanguageCatalogError::UnsupportedLocale);
            }
            if !available.contains(locale) {
                return Err(LocalLanguageCatalogError::AutomaticAlternateUnavailable);
            }
            enabled.push(locale.to_owned());
        }
        Self::try_new(primary_language_bcp47, enabled)
    }

    pub fn primary_language_bcp47(&self) -> &str {
        &self.primary_language_bcp47
    }

    pub fn resolve_language_code(&self, language_code: &str) -> Option<&str> {
        if !(2..=3).contains(&language_code.len())
            || !language_code.bytes().all(|byte| byte.is_ascii_lowercase())
        {
            return None;
        }
        self.by_language_code.get(language_code).map(String::as_str)
    }

    pub fn enabled_locales(&self) -> impl Iterator<Item = &str> {
        self.by_language_code.values().map(String::as_str)
    }
}

pub(crate) fn available_automatic_alternates(primary_locale: &str) -> BTreeSet<&'static str> {
    let primary_language = base_language(primary_locale);
    supported_local_asr_locales()
        .iter()
        .copied()
        // Acoustic LID cannot choose between regional variants. Every other
        // base language in this exact Nemotron catalog is represented in the
        // frozen AmberNet holdout. That aggregate evidence supports an
        // explicit, default-off preview; it does not certify natural switching
        // or a regional locale. Users still opt into each regional locale.
        .filter(|locale| base_language(locale) != primary_language)
        .collect()
}

pub(crate) fn automatic_language_options(
    primary_locale: &str,
) -> BTreeMap<&'static str, Vec<&'static str>> {
    let mut grouped = BTreeMap::new();
    for locale in available_automatic_alternates(primary_locale) {
        grouped
            .entry(base_language(locale))
            .or_insert_with(Vec::new)
            .push(locale);
    }
    grouped
}

pub(crate) fn base_language(locale: &str) -> &str {
    locale
        .split_once('-')
        .map_or(locale, |(language, _)| language)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_catalog_maps_one_acoustic_code_to_one_selected_locale() {
        let catalog =
            LocalLanguageCatalog::try_new("en-GB", ["en-GB", "es-ES", "fr-CA", "ja-JP"]).unwrap();

        assert_eq!(catalog.resolve_language_code("en"), Some("en-GB"));
        assert_eq!(catalog.resolve_language_code("es"), Some("es-ES"));
        assert_eq!(catalog.resolve_language_code("fr"), Some("fr-CA"));
        assert_eq!(catalog.resolve_language_code("ja"), Some("ja-JP"));
        assert_eq!(catalog.resolve_language_code("EN"), None);
    }

    #[test]
    fn duplicate_regional_variants_are_rejected_instead_of_guessed() {
        assert_eq!(
            LocalLanguageCatalog::try_new("en-US", ["en-US", "en-GB"]),
            Err(LocalLanguageCatalogError::AmbiguousBaseLanguage)
        );
    }

    #[test]
    fn automatic_catalog_requires_explicit_alternates_even_when_routes_are_available() {
        let catalog = LocalLanguageCatalog::with_explicit_automatic_alternates(
            "en-US",
            std::iter::empty::<&str>(),
        )
        .unwrap();

        assert_eq!(catalog.resolve_language_code("en"), Some("en-US"));
        assert_eq!(catalog.resolve_language_code("ja"), None);
        assert_eq!(catalog.enabled_locales().collect::<Vec<_>>(), ["en-US"]);
    }

    #[test]
    fn same_language_regional_alternates_fail_closed() {
        assert_eq!(
            LocalLanguageCatalog::with_explicit_automatic_alternates("en-US", ["en-GB"]),
            Err(LocalLanguageCatalogError::AutomaticAlternateUnavailable)
        );
    }

    #[test]
    fn automatic_options_cover_the_explicit_preview_intersection() {
        let options = automatic_language_options("en-US");

        assert!(!options.contains_key("en"));
        assert_eq!(options.get("es"), Some(&vec!["es-ES", "es-US"]));
        assert_eq!(options.get("fr"), Some(&vec!["fr-CA", "fr-FR"]));
        assert_eq!(options.get("nb"), Some(&vec!["nb-NO"]));
        assert_eq!(options.get("zh"), Some(&vec!["zh-CN"]));
        assert_eq!(options.values().map(Vec::len).sum::<usize>(), 30);
    }

    #[test]
    fn primary_must_be_supported_and_present() {
        assert_eq!(
            LocalLanguageCatalog::try_new("en-US", ["fr-FR"]),
            Err(LocalLanguageCatalogError::PrimaryMissing)
        );
        assert_eq!(
            LocalLanguageCatalog::try_new("el-GR", ["el-GR"]),
            Err(LocalLanguageCatalogError::UnsupportedLocale)
        );
    }

    #[test]
    fn local_asr_catalog_contains_exactly_the_executable_locales() {
        assert_eq!(SUPPORTED_LOCAL_ASR_LOCALES.len(), 32);
        assert_eq!(
            SUPPORTED_LOCAL_ASR_LOCALES
                .iter()
                .copied()
                .collect::<std::collections::HashSet<_>>()
                .len(),
            SUPPORTED_LOCAL_ASR_LOCALES.len()
        );
        assert!(SUPPORTED_LOCAL_ASR_LOCALES
            .iter()
            .all(|locale| super::super::valid_bcp47(locale)));
        assert!(supports_local_asr_language("en-US"));
        assert!(supports_local_asr_language("et-EE"));
        for locale in [
            "el-GR", "lt-LT", "lv-LV", "mt-MT", "sl-SI", "he-IL", "th-TH", "nn-NO", "es-MX",
        ] {
            assert!(
                !supports_local_asr_language(locale),
                "unexpected support: {locale}"
            );
        }
    }
}
