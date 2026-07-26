use crate::language::live_evidence::{LiveLanguageDegradation, LiveLanguageMode};

use super::super::{
    language_pipeline::{load_resident_language_pipeline, ResidentLanguagePipeline},
    stream::LiveStreamEngine,
};
use crate::language_preferences::live_routing::live_language_configuration_for_warmup;

/// The one warm, stream-owned local inference bundle.
///
/// Nemotron is mandatory for local dictation. Acoustic LID is isolated behind
/// the language pipeline seam and degrades to the confirmed primary locale if
/// its explicitly installed artifacts are unavailable.
pub(super) struct LiveInferenceBundle {
    pub(super) engine: LiveStreamEngine,
    pub(super) language_pipeline: Option<ResidentLanguagePipeline>,
    pub(super) initial_language_degradation: Option<LiveLanguageDegradation>,
    pub(super) language_mode: LiveLanguageMode,
    pub(super) primary_language_bcp47: String,
}

impl LiveInferenceBundle {
    pub(super) fn load() -> Result<Self, String> {
        let configuration = live_language_configuration_for_warmup()?;
        let primary_language_bcp47 = configuration.primary_language_bcp47;
        let engine = LiveStreamEngine::new_for_language(&primary_language_bcp47).map_err(|error| {
            match error {
                crate::stt::error::SttError::BadLang => format!(
                    "The installed local fallback does not support {primary_language_bcp47}. Choose a supported live language or use server dictation when available."
                ),
                _ => error.user_message().to_string(),
            }
        })?;
        let (language_pipeline, initial_language_degradation, language_mode) =
            match configuration.catalog {
                Some(catalog) => match load_resident_language_pipeline(catalog) {
                    Ok(pipeline) => (Some(pipeline), None, LiveLanguageMode::Automatic),
                    Err(error) => {
                        crate::diagnostics::log(&format!(
                            "live language routing unavailable code={}",
                            error.code()
                        ));
                        (
                            None,
                            Some(match error {
                                crate::stt::error::SttError::ModelMissing
                                | crate::stt::error::SttError::ModelCorrupt => {
                                    LiveLanguageDegradation::ArtifactsUnavailable
                                }
                                _ => LiveLanguageDegradation::DetectorFailed,
                            }),
                            LiveLanguageMode::Automatic,
                        )
                    }
                },
                None if configuration.routing_issue_code.is_some() => {
                    crate::diagnostics::log(&format!(
                        "live language routing unavailable code={}",
                        configuration
                            .routing_issue_code
                            .unwrap_or("preference_unavailable")
                    ));
                    (
                        None,
                        Some(LiveLanguageDegradation::DetectorFailed),
                        LiveLanguageMode::Automatic,
                    )
                }
                None => (None, None, LiveLanguageMode::FixedPrimary),
            };
        Ok(Self {
            engine,
            language_pipeline,
            initial_language_degradation,
            language_mode,
            primary_language_bcp47,
        })
    }
}
