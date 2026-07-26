use crate::language::live_catalog::{
    automatic_language_options, base_language, LocalLanguageCatalog,
};

pub(super) const CURRENT_SCHEMA_VERSION: u16 = 2;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub enum LiveLanguageRoutingPreferenceIssue {
    InvalidStoredPreference,
    IncompatibleSchema,
    StaleCatalog,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AutomaticLanguageOption {
    pub language_code: String,
    pub locales: Vec<String>,
    pub selected_locale_bcp47: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveLanguageRoutingStatus {
    pub schema_version: u16,
    pub catalog_revision: String,
    pub primary_language_bcp47: Option<String>,
    pub enabled_locales: Vec<String>,
    pub automatic_languages: Vec<AutomaticLanguageOption>,
    pub preference_issue: Option<LiveLanguageRoutingPreferenceIssue>,
}

pub(crate) struct LiveLanguageConfiguration {
    pub(crate) primary_language_bcp47: String,
    pub(crate) catalog: Option<LocalLanguageCatalog>,
    pub(crate) routing_issue_code: Option<&'static str>,
}

pub(super) fn project_status(
    primary_language_bcp47: Option<String>,
    enabled_alternate_locales: &[String],
    mut preference_issue: Option<LiveLanguageRoutingPreferenceIssue>,
) -> Result<LiveLanguageRoutingStatus, String> {
    let options = primary_language_bcp47
        .as_deref()
        .map(automatic_language_options)
        .unwrap_or_default();
    let selection_is_current = enabled_alternate_locales.iter().all(|selected| {
        options
            .get(base_language(selected))
            .is_some_and(|locales| locales.contains(&selected.as_str()))
    });
    if preference_issue.is_none() && !selection_is_current {
        preference_issue = Some(LiveLanguageRoutingPreferenceIssue::StaleCatalog);
    }

    let automatic_languages = options
        .into_iter()
        .map(|(language_code, locales)| AutomaticLanguageOption {
            language_code: language_code.to_owned(),
            selected_locale_bcp47: enabled_alternate_locales
                .iter()
                .find(|locale| base_language(locale) == language_code)
                .cloned(),
            locales: locales.into_iter().map(str::to_owned).collect(),
        })
        .collect();

    let enabled_locales = match (primary_language_bcp47.as_deref(), preference_issue) {
        (Some(primary), None) => LocalLanguageCatalog::nemotron_with_explicit_alternates(
            primary,
            enabled_alternate_locales,
        )
        .map_err(|error| error.to_string())?
        .enabled_locales()
        .map(str::to_owned)
        .collect(),
        _ => Vec::new(),
    };

    Ok(LiveLanguageRoutingStatus {
        schema_version: CURRENT_SCHEMA_VERSION,
        catalog_revision: crate::stt::nemotron::LIVE_LANGUAGE_CATALOG_REVISION.to_owned(),
        primary_language_bcp47,
        enabled_locales,
        automatic_languages,
        preference_issue,
    })
}
