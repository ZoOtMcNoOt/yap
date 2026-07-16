use crate::language::RecordingLanguageDecision;
use crate::server_connector::{AsrCapabilityCatalog, ServerConnector};

use super::model::{
    canonical_os_locale, project_status, validate_confirmation, PrimaryLanguagePreferenceIssue,
    PrimaryLanguageStatus,
};
use super::persistence::{self, PrimaryLanguageError};

#[tauri::command]
pub(crate) async fn primary_language_status(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<PrimaryLanguageStatus, String> {
    crate::authorization::ensure_main(&window)?;
    let catalog =
        crate::server_connector::current_asr_capabilities(&app, connector.inner()).await?;
    let last_known = crate::server_connector::last_known_asr_capabilities()?;
    status_from(
        persistence::load(),
        sys_locale::get_locale().as_deref(),
        catalog,
        last_known,
    )
}

#[tauri::command]
pub(crate) async fn confirm_primary_language(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
    language_bcp47: String,
    catalog_revision: String,
) -> Result<PrimaryLanguageStatus, String> {
    crate::authorization::ensure_main(&window)?;
    let catalog = crate::server_connector::current_asr_capabilities(&app, connector.inner())
        .await?
        .ok_or_else(|| "Current ASR language capabilities are unavailable.".to_string())?;
    validate_confirmation(&language_bcp47, &catalog_revision, &catalog)
        .map_err(preference_error_message)?;
    let confirmed = persistence::save(&language_bcp47).map_err(preference_error_message)?;
    let last_known = crate::server_connector::last_known_asr_capabilities()?;
    Ok(project_status(
        Some(confirmed),
        None,
        Some(catalog),
        last_known,
        None,
    ))
}

fn status_from(
    loaded: Result<Option<String>, PrimaryLanguageError>,
    raw_os_locale: Option<&str>,
    catalog: Option<AsrCapabilityCatalog>,
    last_known: Option<crate::server_connector::LastKnownAsrCapabilities>,
) -> Result<PrimaryLanguageStatus, String> {
    let os_locale = canonical_os_locale(raw_os_locale);
    match loaded {
        Ok(confirmed) => Ok(project_status(
            confirmed,
            os_locale.as_deref(),
            catalog,
            last_known,
            None,
        )),
        Err(PrimaryLanguageError::InvalidStoredPreference) => Ok(project_status(
            None,
            os_locale.as_deref(),
            catalog,
            last_known,
            Some(PrimaryLanguagePreferenceIssue::InvalidStoredPreference),
        )),
        Err(PrimaryLanguageError::IncompatibleSchema(_)) => Ok(project_status(
            None,
            None,
            catalog,
            last_known,
            Some(PrimaryLanguagePreferenceIssue::IncompatibleSchema),
        )),
        Err(error) => Err(preference_error_message(error)),
    }
}

fn preference_error_message(error: PrimaryLanguageError) -> String {
    match error {
        PrimaryLanguageError::InvalidLocale | PrimaryLanguageError::UnsupportedLocale => {
            "Choose a language from the current fixed-batch capability list.".into()
        }
        PrimaryLanguageError::StaleCatalog => {
            "Language capabilities changed. Refresh the list and confirm again.".into()
        }
        PrimaryLanguageError::IncompatibleSchema(_) => {
            "Primary-language settings were written by a newer Yap version.".into()
        }
        PrimaryLanguageError::InvalidStoredPreference => {
            "Primary-language settings need explicit recovery.".into()
        }
        PrimaryLanguageError::Access => "Could not access primary-language settings.".into(),
        PrimaryLanguageError::Save => "Could not save the primary language.".into(),
    }
}

pub(crate) fn confirmed_primary_language() -> Result<Option<String>, String> {
    persistence::load().map_err(preference_error_message)
}

pub(crate) async fn resolve_recording_language_decision(
    app: &tauri::AppHandle,
    connector: &ServerConnector,
    language_bcp47: &str,
    catalog_revision: &str,
) -> Result<RecordingLanguageDecision, String> {
    let primary = confirmed_primary_language()?.ok_or_else(|| {
        "Confirm a primary language in Settings before adding recordings.".to_string()
    })?;
    let catalog = crate::server_connector::current_asr_capabilities(app, connector)
        .await?
        .ok_or_else(|| "Current ASR language capabilities are unavailable.".to_string())?;
    validate_confirmation(language_bcp47, catalog_revision, &catalog)
        .map_err(preference_error_message)?;
    if language_bcp47 == primary {
        RecordingLanguageDecision::primary(language_bcp47.into())
    } else {
        RecordingLanguageDecision::manual_override(language_bcp47.into())
    }
    .map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn malformed_preference_projects_explicit_recovery_without_losing_catalog() {
        let catalog = AsrCapabilityCatalog::parse_bounded(include_bytes!(
            "../../../../server/openapi/examples/asr-capabilities.ok.json"
        ))
        .unwrap();

        let status = status_from(
            Err(PrimaryLanguageError::InvalidStoredPreference),
            Some("en-US"),
            Some(catalog),
            None,
        )
        .unwrap();

        assert_eq!(
            status.preference_issue,
            Some(PrimaryLanguagePreferenceIssue::InvalidStoredPreference)
        );
        assert_eq!(status.suggested_language_bcp47.as_deref(), Some("en-US"));
        assert!(status.requires_confirmation);
    }
}
