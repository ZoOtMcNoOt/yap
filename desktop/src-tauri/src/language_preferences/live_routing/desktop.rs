use crate::language::live_catalog::LocalLanguageCatalog;

use super::{
    model::{
        project_status, LiveLanguageConfiguration, LiveLanguageRoutingPreferenceIssue,
        LiveLanguageRoutingStatus,
    },
    persistence::{self, EnabledAlternateLocales, LiveLanguageRoutingError},
};

#[tauri::command]
pub(crate) fn live_language_routing_status(
    window: tauri::WebviewWindow,
) -> Result<LiveLanguageRoutingStatus, String> {
    crate::authorization::ensure_main(&window)?;
    status_from_current_preferences()
}

#[tauri::command]
pub(crate) fn set_live_language_routing(
    window: tauri::WebviewWindow,
    live_runtime: tauri::State<'_, crate::live::runtime::LiveRuntime>,
    enabled_alternate_locales: Vec<String>,
    catalog_revision: String,
) -> Result<LiveLanguageRoutingStatus, String> {
    crate::authorization::ensure_main(&window)?;
    let _live_mutation = live_runtime.begin_language_support_mutation()?;
    let _preference_mutation = super::super::persistence::lock_mutation()
        .map_err(super::super::desktop::preference_error_message)?;
    if catalog_revision != crate::stt::nemotron::LIVE_LANGUAGE_CATALOG_REVISION {
        return Err(routing_error_message(
            LiveLanguageRoutingError::StaleCatalog,
        ));
    }
    let primary = super::super::persistence::load()
        .map_err(super::super::desktop::preference_error_message)?
        .ok_or_else(|| {
            "Confirm a primary language before configuring automatic switching.".to_string()
        })?;
    LocalLanguageCatalog::nemotron_with_explicit_alternates(&primary, &enabled_alternate_locales)
        .map_err(|_| routing_error_message(LiveLanguageRoutingError::InvalidSelection))?;
    let saved = persistence::save(enabled_alternate_locales).map_err(routing_error_message)?;
    project_status(Some(primary), &saved.locales, None)
}

pub(crate) fn live_language_configuration_for_warmup() -> Result<LiveLanguageConfiguration, String>
{
    let _preference_mutation = super::super::persistence::lock_mutation()
        .map_err(super::super::desktop::preference_error_message)?;
    let primary = super::super::persistence::load()
        .map_err(super::super::desktop::preference_error_message)?
        .ok_or_else(|| {
            "Confirm a primary language in Settings before starting live dictation.".to_string()
        })?;
    let (catalog, routing_issue_code) = match persistence::load() {
        Ok(selections) if selections.locales.is_empty() => (None, None),
        Ok(selections) => match LocalLanguageCatalog::nemotron_with_explicit_alternates(
            &primary,
            &selections.locales,
        ) {
            Ok(catalog) => (Some(catalog), None),
            Err(_) => (None, Some("stale_catalog")),
        },
        Err(error) => (None, Some(routing_error_code(error))),
    };
    Ok(LiveLanguageConfiguration {
        primary_language_bcp47: primary,
        catalog,
        routing_issue_code,
    })
}

fn status_from_current_preferences() -> Result<LiveLanguageRoutingStatus, String> {
    let _preference_mutation = super::super::persistence::lock_mutation()
        .map_err(super::super::desktop::preference_error_message)?;
    let primary = super::super::persistence::load()
        .map_err(super::super::desktop::preference_error_message)?;
    match persistence::load() {
        Ok(EnabledAlternateLocales { locales }) => project_status(primary, &locales, None),
        Err(LiveLanguageRoutingError::InvalidStoredPreference) => project_status(
            primary,
            &[],
            Some(LiveLanguageRoutingPreferenceIssue::InvalidStoredPreference),
        ),
        Err(LiveLanguageRoutingError::IncompatibleSchema(_)) => project_status(
            primary,
            &[],
            Some(LiveLanguageRoutingPreferenceIssue::IncompatibleSchema),
        ),
        Err(LiveLanguageRoutingError::StaleCatalog) => project_status(
            primary,
            &[],
            Some(LiveLanguageRoutingPreferenceIssue::StaleCatalog),
        ),
        Err(error) => Err(routing_error_message(error)),
    }
}

fn routing_error_code(error: LiveLanguageRoutingError) -> &'static str {
    match error {
        LiveLanguageRoutingError::InvalidSelection => "invalid_selection",
        LiveLanguageRoutingError::InvalidStoredPreference => "invalid_stored_preference",
        LiveLanguageRoutingError::IncompatibleSchema(_) => "incompatible_schema",
        LiveLanguageRoutingError::StaleCatalog => "stale_catalog",
        LiveLanguageRoutingError::Access => "access",
        LiveLanguageRoutingError::Save => "save",
    }
}

fn routing_error_message(error: LiveLanguageRoutingError) -> String {
    match error {
        LiveLanguageRoutingError::InvalidSelection => {
            "Choose only available automatic alternates, with at most one exact locale per language.".into()
        }
        LiveLanguageRoutingError::InvalidStoredPreference => {
            "Automatic-language settings need explicit recovery.".into()
        }
        LiveLanguageRoutingError::IncompatibleSchema(_) => {
            "Automatic-language settings were written by a newer Yap version.".into()
        }
        LiveLanguageRoutingError::StaleCatalog => {
            "Local language support changed. Review and save the automatic alternates again.".into()
        }
        LiveLanguageRoutingError::Access => "Could not access automatic-language settings.".into(),
        LiveLanguageRoutingError::Save => "Could not save automatic-language settings.".into(),
    }
}
