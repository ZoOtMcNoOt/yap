#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RecordingLanguageError;

impl std::fmt::Display for RecordingLanguageError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("recording language decision is inconsistent")
    }
}

impl std::error::Error for RecordingLanguageError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub enum RecordingLanguageMode {
    Fixed,
    Dynamic,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub enum RecordingLanguageDisposition {
    Primary,
    ManualOverride,
    DetectedSuggestionConfirmed,
    ExplicitDynamic,
    LegacyPhase5Default,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RecordingLanguageDecision {
    pub mode: RecordingLanguageMode,
    pub language_bcp47: Option<String>,
    pub disposition: RecordingLanguageDisposition,
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecordingLanguageDecisionWire {
    mode: RecordingLanguageMode,
    language_bcp47: Option<String>,
    disposition: RecordingLanguageDisposition,
}

impl<'de> serde::Deserialize<'de> for RecordingLanguageDecision {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let wire = RecordingLanguageDecisionWire::deserialize(deserializer)?;
        Self::try_new(wire.mode, wire.language_bcp47, wire.disposition)
            .map_err(serde::de::Error::custom)
    }
}

impl RecordingLanguageDecision {
    pub fn try_new(
        mode: RecordingLanguageMode,
        language_bcp47: Option<String>,
        disposition: RecordingLanguageDisposition,
    ) -> Result<Self, RecordingLanguageError> {
        let valid = match (mode, language_bcp47.as_deref(), disposition) {
            (
                RecordingLanguageMode::Fixed,
                Some(language),
                RecordingLanguageDisposition::Primary
                | RecordingLanguageDisposition::ManualOverride
                | RecordingLanguageDisposition::DetectedSuggestionConfirmed,
            ) => valid_bcp47(language),
            (
                RecordingLanguageMode::Fixed,
                Some("en-US"),
                RecordingLanguageDisposition::LegacyPhase5Default,
            ) => true,
            (
                RecordingLanguageMode::Dynamic,
                None,
                RecordingLanguageDisposition::ExplicitDynamic,
            ) => true,
            _ => false,
        };
        if !valid {
            return Err(RecordingLanguageError);
        }
        Ok(Self {
            mode,
            language_bcp47,
            disposition,
        })
    }

    pub fn primary(language_bcp47: String) -> Result<Self, RecordingLanguageError> {
        Self::try_new(
            RecordingLanguageMode::Fixed,
            Some(language_bcp47),
            RecordingLanguageDisposition::Primary,
        )
    }

    pub fn manual_override(language_bcp47: String) -> Result<Self, RecordingLanguageError> {
        Self::try_new(
            RecordingLanguageMode::Fixed,
            Some(language_bcp47),
            RecordingLanguageDisposition::ManualOverride,
        )
    }

    pub fn explicit_dynamic() -> Self {
        Self {
            mode: RecordingLanguageMode::Dynamic,
            language_bcp47: None,
            disposition: RecordingLanguageDisposition::ExplicitDynamic,
        }
    }

    pub(crate) fn legacy_phase5_default() -> Self {
        Self {
            mode: RecordingLanguageMode::Fixed,
            language_bcp47: Some("en-US".into()),
            disposition: RecordingLanguageDisposition::LegacyPhase5Default,
        }
    }

    pub(crate) fn is_legacy_phase5_default(&self) -> bool {
        self.mode == RecordingLanguageMode::Fixed
            && self.language_bcp47.as_deref() == Some("en-US")
            && self.disposition == RecordingLanguageDisposition::LegacyPhase5Default
    }
}

pub(crate) fn valid_bcp47(value: &str) -> bool {
    if value.len() > 35 || !value.is_ascii() {
        return false;
    }
    let parts = value.split('-').collect::<Vec<_>>();
    let Some(language) = parts.first() else {
        return false;
    };
    if !(2..=3).contains(&language.len()) || !language.bytes().all(|byte| byte.is_ascii_lowercase())
    {
        return false;
    }

    let mut index = 1;
    if parts.get(index).is_some_and(|part| {
        part.len() == 4
            && part.as_bytes()[0].is_ascii_uppercase()
            && part.as_bytes()[1..]
                .iter()
                .all(|byte| byte.is_ascii_lowercase())
    }) {
        index += 1;
    }
    if parts.get(index).is_some_and(|part| {
        (part.len() == 2 && part.bytes().all(|byte| byte.is_ascii_uppercase()))
            || (part.len() == 3 && part.bytes().all(|byte| byte.is_ascii_digit()))
    }) {
        index += 1;
    }
    parts[index..].iter().all(|part| {
        ((5..=8).contains(&part.len()) || (part.len() == 4 && part.as_bytes()[0].is_ascii_digit()))
            && part.bytes().all(|byte| byte.is_ascii_alphanumeric())
    })
}
