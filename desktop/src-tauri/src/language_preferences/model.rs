use crate::server_connector::AsrCapabilityCatalog;

pub(super) const CURRENT_SCHEMA_VERSION: u16 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub enum PrimaryLanguagePreferenceIssue {
    InvalidStoredPreference,
    IncompatibleSchema,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PrimaryLanguageStatus {
    pub schema_version: u16,
    pub confirmed_language_bcp47: Option<String>,
    pub suggested_language_bcp47: Option<String>,
    pub confirmed_language_available: Option<bool>,
    pub requires_confirmation: bool,
    pub preference_issue: Option<PrimaryLanguagePreferenceIssue>,
    pub capability_catalog: Option<AsrCapabilityCatalog>,
}

pub(super) fn project_status(
    confirmed_language_bcp47: Option<String>,
    os_locale: Option<&str>,
    capability_catalog: Option<AsrCapabilityCatalog>,
    preference_issue: Option<PrimaryLanguagePreferenceIssue>,
) -> PrimaryLanguageStatus {
    let suggested_language_bcp47 = (confirmed_language_bcp47.is_none()
        && preference_issue != Some(PrimaryLanguagePreferenceIssue::IncompatibleSchema))
    .then(|| {
        let locale = os_locale?;
        capability_catalog
            .as_ref()?
            .supports_fixed_batch(locale)
            .then(|| locale.to_owned())
    })
    .flatten();
    let confirmed_language_available = confirmed_language_bcp47.as_deref().and_then(|locale| {
        capability_catalog
            .as_ref()
            .map(|catalog| catalog.supports_fixed_batch(locale))
    });

    PrimaryLanguageStatus {
        schema_version: CURRENT_SCHEMA_VERSION,
        requires_confirmation: confirmed_language_bcp47.is_none(),
        confirmed_language_bcp47,
        suggested_language_bcp47,
        confirmed_language_available,
        preference_issue,
        capability_catalog,
    }
}

pub(super) fn canonical_os_locale(raw: Option<&str>) -> Option<String> {
    let raw = raw?.trim();
    let raw = raw.split(['.', '@']).next()?.replace('_', "-");
    let mut parts = raw.split('-');
    let language = parts.next()?.to_ascii_lowercase();
    let mut canonical = vec![language];
    for part in parts {
        let normalized = if part.len() == 4 && part.bytes().all(|byte| byte.is_ascii_alphabetic()) {
            let mut chars = part.chars();
            let first = chars.next()?.to_ascii_uppercase();
            format!("{first}{}", chars.as_str().to_ascii_lowercase())
        } else if part.len() == 2 && part.bytes().all(|byte| byte.is_ascii_alphabetic()) {
            part.to_ascii_uppercase()
        } else {
            part.to_owned()
        };
        canonical.push(normalized);
    }
    let canonical = canonical.join("-");
    crate::language::valid_bcp47(&canonical).then_some(canonical)
}

pub(super) fn validate_confirmation(
    language_bcp47: &str,
    catalog_revision: &str,
    catalog: &AsrCapabilityCatalog,
) -> Result<(), super::persistence::PrimaryLanguageError> {
    if catalog.catalog_revision != catalog_revision {
        return Err(super::persistence::PrimaryLanguageError::StaleCatalog);
    }
    if !crate::language::valid_bcp47(language_bcp47)
        || !catalog.supports_fixed_batch(language_bcp47)
    {
        return Err(super::persistence::PrimaryLanguageError::UnsupportedLocale);
    }
    Ok(())
}
