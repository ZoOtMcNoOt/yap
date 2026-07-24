use crate::language::{
    RecordingLanguageDecision, RecordingLanguageDisposition, RecordingLanguageMode,
};

use super::JobLedgerError;

impl RecordingLanguageDecision {
    pub(crate) fn from_db(
        mode: &str,
        language_bcp47: Option<String>,
        disposition: &str,
    ) -> Result<Self, JobLedgerError> {
        Self::try_new(
            RecordingLanguageMode::from_db(mode)?,
            language_bcp47,
            RecordingLanguageDisposition::from_db(disposition)?,
        )
        .map_err(|_| corrupt("language_decision", disposition))
    }
}

impl RecordingLanguageMode {
    pub(crate) const fn as_db(self) -> &'static str {
        match self {
            Self::Fixed => "fixed",
            Self::Dynamic => "dynamic",
        }
    }

    fn from_db(value: &str) -> Result<Self, JobLedgerError> {
        match value {
            "fixed" => Ok(Self::Fixed),
            "dynamic" => Ok(Self::Dynamic),
            _ => Err(corrupt("language_mode", value)),
        }
    }
}

impl RecordingLanguageDisposition {
    pub(crate) const fn as_db(self) -> &'static str {
        match self {
            Self::Primary => "primary",
            Self::ManualOverride => "manual_override",
            Self::DetectedSuggestionConfirmed => "detected_suggestion_confirmed",
            Self::ExplicitDynamic => "explicit_dynamic",
            Self::LegacyImplicitEnglishDefault => "legacy_implicit_english_default",
        }
    }

    fn from_db(value: &str) -> Result<Self, JobLedgerError> {
        match value {
            "primary" => Ok(Self::Primary),
            "manual_override" => Ok(Self::ManualOverride),
            "detected_suggestion_confirmed" => Ok(Self::DetectedSuggestionConfirmed),
            "explicit_dynamic" => Ok(Self::ExplicitDynamic),
            "legacy_implicit_english_default" => Ok(Self::LegacyImplicitEnglishDefault),
            _ => Err(corrupt("language_disposition", value)),
        }
    }
}

fn corrupt(field: &'static str, value: &str) -> JobLedgerError {
    JobLedgerError::CorruptValue {
        field,
        value: value.into(),
    }
}
