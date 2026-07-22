use crate::language::RecordingLanguageDecision;
use crate::server_connector::{AsrCapabilityCatalog, ServerConnector};

use super::model::{
    canonical_os_locale, project_status, validate_confirmation, PrimaryLanguagePreferenceIssue,
    PrimaryLanguageStatus,
};
use super::persistence::{self, PrimaryLanguageError};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum RecordingLanguageDecisionError {
    PrimaryRequired,
    PreferenceUnavailable(String),
    SelectionInvalid(String),
    IncompleteSelection,
}

impl RecordingLanguageDecisionError {
    pub(crate) fn code(&self) -> &'static str {
        match self {
            Self::PrimaryRequired => "PRIMARY_LANGUAGE_REQUIRED",
            Self::PreferenceUnavailable(_) => "PRIMARY_LANGUAGE_UNAVAILABLE",
            Self::SelectionInvalid(_) | Self::IncompleteSelection => "LANGUAGE_SELECTION_INVALID",
        }
    }
}

impl std::fmt::Display for RecordingLanguageDecisionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::PrimaryRequired => formatter
                .write_str("Confirm a primary language in Settings before adding recordings."),
            Self::PreferenceUnavailable(message) | Self::SelectionInvalid(message) => {
                formatter.write_str(message)
            }
            Self::IncompleteSelection => formatter.write_str(
                "Recording language mode, locale, and capability revision are inconsistent.",
            ),
        }
    }
}

#[tauri::command]
pub(crate) async fn primary_language_status(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<PrimaryLanguageStatus, String> {
    crate::authorization::ensure_main(&window)?;
    let catalog =
        crate::server_connector::current_asr_capabilities(&app, connector.inner()).await?;
    let last_known = last_known_only_when_offline(catalog.is_none(), || {
        crate::server_connector::last_known_asr_capabilities()
    })?;
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
    live_runtime: tauri::State<'_, crate::live::runtime::LiveRuntime>,
    language_bcp47: String,
    catalog_revision: String,
) -> Result<PrimaryLanguageStatus, String> {
    crate::authorization::ensure_main(&window)?;
    let _live_mutation = live_runtime.begin_primary_language_mutation()?;
    let committed = crate::server_connector::with_current_asr_capabilities(
        &app,
        connector.inner(),
        |current| {
            let catalog = current.catalog();
            let _mutation = persistence::lock_mutation().map_err(preference_error_message)?;
            validate_confirmation(&language_bcp47, &catalog_revision, catalog)
                .map_err(preference_error_message)?;
            let confirmed = persistence::save(&language_bcp47).map_err(preference_error_message)?;
            Ok::<_, String>((confirmed, catalog.clone()))
        },
    )
    .await?
    .ok_or_else(|| "Current ASR language capabilities are unavailable.".to_string())?;
    let (confirmed, catalog) = committed?;
    Ok(project_status(
        Some(confirmed),
        None,
        Some(catalog),
        None,
        None,
    ))
}

fn last_known_only_when_offline(
    offline: bool,
    load: impl FnOnce() -> Result<Option<crate::server_connector::LastKnownAsrCapabilities>, String>,
) -> Result<Option<crate::server_connector::LastKnownAsrCapabilities>, String> {
    if offline {
        load()
    } else {
        Ok(None)
    }
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

pub(super) fn preference_error_message(error: PrimaryLanguageError) -> String {
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

pub(crate) fn with_recording_language_decision<T>(
    language_mode: Option<crate::jobs::RecordingLanguageMode>,
    language_bcp47: Option<&str>,
    catalog_revision: Option<&str>,
    catalog: &AsrCapabilityCatalog,
    commit: impl FnOnce(RecordingLanguageDecision) -> T,
) -> Result<T, RecordingLanguageDecisionError> {
    with_recording_language_decision_from(
        language_mode,
        language_bcp47,
        catalog_revision,
        catalog,
        persistence::load,
        commit,
    )
}

fn with_recording_language_decision_from<T>(
    language_mode: Option<crate::jobs::RecordingLanguageMode>,
    language_bcp47: Option<&str>,
    catalog_revision: Option<&str>,
    catalog: &AsrCapabilityCatalog,
    load_primary: impl FnOnce() -> Result<Option<String>, PrimaryLanguageError>,
    commit: impl FnOnce(RecordingLanguageDecision) -> T,
) -> Result<T, RecordingLanguageDecisionError> {
    let _mutation = persistence::lock_mutation().map_err(|error| {
        RecordingLanguageDecisionError::PreferenceUnavailable(preference_error_message(error))
    })?;
    let primary = load_primary()
        .map_err(|error| {
            RecordingLanguageDecisionError::PreferenceUnavailable(preference_error_message(error))
        })?
        .ok_or(RecordingLanguageDecisionError::PrimaryRequired)?;
    let decision = match (language_mode, language_bcp47, catalog_revision) {
        (
            None | Some(crate::jobs::RecordingLanguageMode::Fixed),
            Some(language),
            Some(revision),
        ) => {
            validate_confirmation(language, revision, catalog).map_err(|error| {
                RecordingLanguageDecisionError::SelectionInvalid(preference_error_message(error))
            })?;
            if language == primary {
                RecordingLanguageDecision::primary(language.into())
            } else {
                RecordingLanguageDecision::manual_override(language.into())
            }
            .map_err(|error| RecordingLanguageDecisionError::SelectionInvalid(error.to_string()))?
        }
        (Some(crate::jobs::RecordingLanguageMode::Dynamic), None, Some(revision)) => {
            if revision != catalog.catalog_revision {
                return Err(RecordingLanguageDecisionError::SelectionInvalid(
                    "Language capabilities changed. Refresh the list and choose again.".into(),
                ));
            }
            let decision = RecordingLanguageDecision::explicit_dynamic();
            if !catalog.supports_recording_decision(&decision) {
                return Err(RecordingLanguageDecisionError::SelectionInvalid(
                    "The current private server does not support automatic recording-language detection.".into(),
                ));
            }
            decision
        }
        (None, None, None) => {
            validate_confirmation(&primary, &catalog.catalog_revision, catalog).map_err(
                |error| {
                    RecordingLanguageDecisionError::PreferenceUnavailable(preference_error_message(
                        error,
                    ))
                },
            )?;
            RecordingLanguageDecision::primary(primary).map_err(|error| {
                RecordingLanguageDecisionError::PreferenceUnavailable(error.to_string())
            })?
        }
        _ => return Err(RecordingLanguageDecisionError::IncompleteSelection),
    };
    Ok(commit(decision))
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

    #[test]
    fn default_recording_language_must_still_exist_in_the_current_catalog() {
        let catalog = AsrCapabilityCatalog::parse_bounded(include_bytes!(
            "../../../../server/openapi/examples/asr-capabilities.ok.json"
        ))
        .unwrap();

        let error = with_recording_language_decision_from(
            None,
            None,
            None,
            &catalog,
            || Ok(Some("fr-FR".into())),
            |_| (),
        )
        .unwrap_err();

        assert_eq!(error.code(), "PRIMARY_LANGUAGE_UNAVAILABLE");
    }

    #[test]
    fn missing_primary_language_retains_its_actionable_command_code() {
        let catalog = AsrCapabilityCatalog::parse_bounded(include_bytes!(
            "../../../../server/openapi/examples/asr-capabilities.ok.json"
        ))
        .unwrap();

        let error =
            with_recording_language_decision_from(None, None, None, &catalog, || Ok(None), |_| ())
                .unwrap_err();

        assert_eq!(error.code(), "PRIMARY_LANGUAGE_REQUIRED");
        assert_eq!(
            error.to_string(),
            "Confirm a primary language in Settings before adding recordings."
        );
    }

    #[test]
    fn decision_disposition_uses_the_primary_value_held_through_commit() {
        let catalog = AsrCapabilityCatalog::parse_bounded(include_bytes!(
            "../../../../server/openapi/examples/asr-capabilities.ok.json"
        ))
        .unwrap();

        let decision = with_recording_language_decision_from(
            Some(crate::jobs::RecordingLanguageMode::Fixed),
            Some("en-US"),
            Some(&catalog.catalog_revision),
            &catalog,
            || Ok(Some("fr-FR".into())),
            |decision| decision,
        )
        .unwrap();

        assert_eq!(
            decision.disposition,
            crate::language::RecordingLanguageDisposition::ManualOverride
        );
    }

    #[test]
    fn explicit_dynamic_selection_requires_a_current_advertised_dynamic_route() {
        let mut catalog = AsrCapabilityCatalog::parse_bounded(include_bytes!(
            "../../../../server/openapi/examples/asr-capabilities.ok.json"
        ))
        .unwrap();
        let revision = catalog.catalog_revision.clone();
        let rejected = with_recording_language_decision_from(
            Some(crate::jobs::RecordingLanguageMode::Dynamic),
            None,
            Some(&revision),
            &catalog,
            || Ok(Some("en-US".into())),
            |decision| decision,
        )
        .unwrap_err();
        assert_eq!(rejected.code(), "LANGUAGE_SELECTION_INVALID");

        let mut dynamic = catalog.providers[0].capabilities[0].clone();
        dynamic.language_bcp47 = "und".into();
        dynamic.provider_language_code = "auto".into();
        dynamic.mode = serde_json::from_value(serde_json::json!("dynamicBatch")).unwrap();
        dynamic.segment_language_tags = true;
        dynamic.word_alignment = false;
        catalog.providers[0].capabilities.push(dynamic);
        let accepted = with_recording_language_decision_from(
            Some(crate::jobs::RecordingLanguageMode::Dynamic),
            None,
            Some(&revision),
            &catalog,
            || Ok(Some("en-US".into())),
            |decision| decision,
        )
        .unwrap();
        assert_eq!(
            accepted,
            crate::language::RecordingLanguageDecision::explicit_dynamic()
        );
    }

    #[test]
    fn live_catalog_status_never_combines_a_separately_loaded_offline_snapshot() {
        let loaded = std::cell::Cell::new(false);

        let last_known = last_known_only_when_offline(false, || {
            loaded.set(true);
            Err("a separately loaded origin must not be observed".into())
        })
        .unwrap();

        assert_eq!(last_known, None);
        assert!(!loaded.get());
    }
}
