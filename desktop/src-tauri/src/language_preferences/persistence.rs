use std::path::{Path, PathBuf};

use super::model::CURRENT_SCHEMA_VERSION;

pub(super) const MAX_PRIMARY_LANGUAGE_BYTES: usize = 4 * 1024;

#[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PersistedPrimaryLanguage {
    schema_version: u16,
    language_bcp47: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum PrimaryLanguageError {
    InvalidLocale,
    InvalidStoredPreference,
    IncompatibleSchema(u64),
    Access,
    Save,
    StaleCatalog,
    UnsupportedLocale,
}

pub(super) fn preference_path() -> PathBuf {
    crate::paths::app_data_dir().join("primary-language.json")
}

pub(super) fn load() -> Result<Option<String>, PrimaryLanguageError> {
    load_from_path(&preference_path())
}

pub(super) fn save(language_bcp47: &str) -> Result<String, PrimaryLanguageError> {
    save_to_path(language_bcp47, &preference_path())
}

pub(super) fn load_from_path(path: &Path) -> Result<Option<String>, PrimaryLanguageError> {
    let Some(parent) = path.parent() else {
        return Ok(None);
    };
    match std::fs::metadata(parent) {
        Ok(metadata) if metadata.is_dir() => {}
        Ok(_) => return Err(PrimaryLanguageError::Access),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(PrimaryLanguageError::Access),
    }
    let _lock = crate::server_connector::config::acquire_settings_access_lock(path)
        .map_err(|_| PrimaryLanguageError::Access)?;
    load_from_path_under_lock(path)
}

pub(super) fn save_to_path(
    language_bcp47: &str,
    path: &Path,
) -> Result<String, PrimaryLanguageError> {
    if !crate::language::valid_bcp47(language_bcp47) {
        return Err(PrimaryLanguageError::InvalidLocale);
    }
    let preference = PersistedPrimaryLanguage {
        schema_version: CURRENT_SCHEMA_VERSION,
        language_bcp47: language_bcp47.to_owned(),
    };
    let encoded = serde_json::to_vec_pretty(&preference).map_err(|_| PrimaryLanguageError::Save)?;
    if encoded.len() > MAX_PRIMARY_LANGUAGE_BYTES {
        return Err(PrimaryLanguageError::Save);
    }
    let parent = path.parent().ok_or(PrimaryLanguageError::Save)?;
    std::fs::create_dir_all(parent).map_err(|_| PrimaryLanguageError::Save)?;
    let _lock = crate::server_connector::config::acquire_settings_lock(path)
        .map_err(|_| PrimaryLanguageError::Save)?;
    ensure_existing_schema_compatible(path)?;
    crate::server_connector::config::write_atomically_locked_with_hooks(
        path,
        &encoded,
        |_, _| Ok(()),
        |_| Ok(()),
    )
    .map_err(|_| PrimaryLanguageError::Save)?;
    Ok(preference.language_bcp47)
}

fn load_from_path_under_lock(path: &Path) -> Result<Option<String>, PrimaryLanguageError> {
    let text = match crate::bounded_file::read_text(path, MAX_PRIMARY_LANGUAGE_BYTES) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(PrimaryLanguageError::Access),
    };
    let value: serde_json::Value =
        serde_json::from_str(&text).map_err(|_| PrimaryLanguageError::InvalidStoredPreference)?;
    ensure_schema_compatible(&value)?;
    let preference: PersistedPrimaryLanguage =
        serde_json::from_value(value).map_err(|_| PrimaryLanguageError::InvalidStoredPreference)?;
    if !crate::language::valid_bcp47(&preference.language_bcp47) {
        return Err(PrimaryLanguageError::InvalidStoredPreference);
    }
    Ok(Some(preference.language_bcp47))
}

fn ensure_existing_schema_compatible(path: &Path) -> Result<(), PrimaryLanguageError> {
    let text = match crate::bounded_file::read_text(path, MAX_PRIMARY_LANGUAGE_BYTES) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(_) => return Err(PrimaryLanguageError::Access),
    };
    if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
        ensure_schema_compatible(&value)?;
    }
    Ok(())
}

fn ensure_schema_compatible(value: &serde_json::Value) -> Result<(), PrimaryLanguageError> {
    if let Some(version) = value
        .get("schemaVersion")
        .and_then(serde_json::Value::as_u64)
    {
        if version != u64::from(CURRENT_SCHEMA_VERSION) {
            return Err(PrimaryLanguageError::IncompatibleSchema(version));
        }
    }
    Ok(())
}
