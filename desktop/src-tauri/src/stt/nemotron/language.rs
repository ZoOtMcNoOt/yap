// This catalog is part of the exact pinned Nemotron export contract in the
// parent module. It deliberately excludes the model card's adaptation-ready
// locales because their tokenizer entries are not executable support evidence.
pub(super) const SUPPORTED_LIVE_LOCALES: &[&str] = &[
    // Transcription-ready.
    "en-US", "en-GB", "es-US", "es-ES", "fr-FR", "fr-CA", "it-IT", "pt-BR", "pt-PT", "nl-NL",
    "de-DE", "tr-TR", "ru-RU", "ar-AR", "hi-IN", "ja-JP", "ko-KR", "vi-VN", "uk-UA",
    // Broad coverage. Availability is not a quality-promotion claim.
    "pl-PL", "sv-SE", "cs-CZ", "nb-NO", "da-DK", "bg-BG", "fi-FI", "hr-HR", "sk-SK", "zh-CN",
    "hu-HU", "ro-RO", "et-EE",
];

/// Changes when either the pinned model export or its executable locale
/// allowlist or available automatic-route preview matrix changes. Persisted explicit
/// alternates are bound to this value so an upgrade cannot silently reinterpret
/// an old choice.
pub(crate) const LIVE_LANGUAGE_CATALOG_REVISION: &str =
    "nemotron-3.5-asr-streaming-0.6b-1120ms-int8@d2f58fb3c1ae44829133de74c1b5aa6e3e6dda04/locales-v1/ambernet-1.12.0-int8-qdq-ef1006c-margin0.4-v1";

pub(crate) fn supports_live_language(language_bcp47: &str) -> bool {
    SUPPORTED_LIVE_LOCALES.contains(&language_bcp47)
}

pub(crate) fn supported_live_locales() -> &'static [&'static str] {
    SUPPORTED_LIVE_LOCALES
}
