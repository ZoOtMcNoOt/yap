use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
};

use crate::language::live_catalog::base_language;

use super::model::CURRENT_SCHEMA_VERSION;

pub(super) const MAX_ROUTING_PREFERENCE_BYTES: usize = 8 * 1024;
const LEGACY_SCHEMA_VERSION: u16 = 1;
const MAX_ENABLED_ALTERNATES: usize = 16;

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub(super) struct EnabledAlternateLocales {
    pub(super) locales: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PersistedLiveLanguageRouting {
    schema_version: u16,
    catalog_revision: String,
    enabled_alternate_locales: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LegacyRegionalLanguageRouting {
    schema_version: u16,
    catalog_revision: String,
    regional_locales: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum LiveLanguageRoutingError {
    InvalidSelection,
    InvalidStoredPreference,
    IncompatibleSchema(u64),
    StaleCatalog,
    Access,
    Save,
}

pub(super) fn preference_path() -> PathBuf {
    crate::paths::app_data_dir().join("live-language-routing.json")
}

pub(super) fn load() -> Result<EnabledAlternateLocales, LiveLanguageRoutingError> {
    load_from_path(&preference_path())
}

pub(super) fn save(
    enabled_alternate_locales: Vec<String>,
) -> Result<EnabledAlternateLocales, LiveLanguageRoutingError> {
    save_to_path(enabled_alternate_locales, &preference_path())
}

pub(super) fn load_from_path(
    path: &Path,
) -> Result<EnabledAlternateLocales, LiveLanguageRoutingError> {
    let Some(parent) = path.parent() else {
        return Ok(EnabledAlternateLocales::default());
    };
    match std::fs::metadata(parent) {
        Ok(metadata) if metadata.is_dir() => {}
        Ok(_) => return Err(LiveLanguageRoutingError::Access),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(EnabledAlternateLocales::default())
        }
        Err(_) => return Err(LiveLanguageRoutingError::Access),
    }
    let _lock = crate::server_connector::config::acquire_settings_access_lock(path)
        .map_err(|_| LiveLanguageRoutingError::Access)?;
    load_from_path_under_lock(path)
}

pub(super) fn save_to_path(
    enabled_alternate_locales: Vec<String>,
    path: &Path,
) -> Result<EnabledAlternateLocales, LiveLanguageRoutingError> {
    let enabled_alternate_locales = validate_and_sort(enabled_alternate_locales, false)?;
    let preference = PersistedLiveLanguageRouting {
        schema_version: CURRENT_SCHEMA_VERSION,
        catalog_revision: crate::language::live_catalog::LOCAL_LANGUAGE_ROUTING_REVISION.to_owned(),
        enabled_alternate_locales: enabled_alternate_locales.clone(),
    };
    let encoded =
        serde_json::to_vec_pretty(&preference).map_err(|_| LiveLanguageRoutingError::Save)?;
    if encoded.len() > MAX_ROUTING_PREFERENCE_BYTES {
        return Err(LiveLanguageRoutingError::Save);
    }
    let parent = path.parent().ok_or(LiveLanguageRoutingError::Save)?;
    std::fs::create_dir_all(parent).map_err(|_| LiveLanguageRoutingError::Save)?;
    let _lock = crate::server_connector::config::acquire_settings_lock(path)
        .map_err(|_| LiveLanguageRoutingError::Save)?;
    ensure_existing_schema_compatible(path)?;
    crate::server_connector::config::write_atomically_locked_with_hooks(
        path,
        &encoded,
        |_, _| Ok(()),
        |_| Ok(()),
    )
    .map_err(|_| LiveLanguageRoutingError::Save)?;
    Ok(EnabledAlternateLocales {
        locales: enabled_alternate_locales,
    })
}

fn load_from_path_under_lock(
    path: &Path,
) -> Result<EnabledAlternateLocales, LiveLanguageRoutingError> {
    let text = match crate::bounded_file::read_text(path, MAX_ROUTING_PREFERENCE_BYTES) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(EnabledAlternateLocales::default())
        }
        Err(_) => return Err(LiveLanguageRoutingError::Access),
    };
    let value: serde_json::Value = serde_json::from_str(&text)
        .map_err(|_| LiveLanguageRoutingError::InvalidStoredPreference)?;
    let schema_version = schema_version(&value)?;
    let (catalog_revision, locales) = match schema_version {
        CURRENT_SCHEMA_VERSION => {
            let preference: PersistedLiveLanguageRouting = serde_json::from_value(value)
                .map_err(|_| LiveLanguageRoutingError::InvalidStoredPreference)?;
            (
                preference.catalog_revision,
                preference.enabled_alternate_locales,
            )
        }
        LEGACY_SCHEMA_VERSION => {
            let preference: LegacyRegionalLanguageRouting = serde_json::from_value(value)
                .map_err(|_| LiveLanguageRoutingError::InvalidStoredPreference)?;
            (preference.catalog_revision, preference.regional_locales)
        }
        version => {
            return Err(LiveLanguageRoutingError::IncompatibleSchema(u64::from(
                version,
            )))
        }
    };
    if catalog_revision != crate::language::live_catalog::LOCAL_LANGUAGE_ROUTING_REVISION {
        return Err(LiveLanguageRoutingError::StaleCatalog);
    }
    Ok(EnabledAlternateLocales {
        locales: validate_and_sort(locales, true)?,
    })
}

fn validate_and_sort(
    mut enabled_alternate_locales: Vec<String>,
    stored: bool,
) -> Result<Vec<String>, LiveLanguageRoutingError> {
    let invalid = || {
        if stored {
            LiveLanguageRoutingError::InvalidStoredPreference
        } else {
            LiveLanguageRoutingError::InvalidSelection
        }
    };
    if enabled_alternate_locales.len() > MAX_ENABLED_ALTERNATES {
        return Err(invalid());
    }
    let mut language_codes = BTreeSet::new();
    for locale in &enabled_alternate_locales {
        if !crate::language::valid_bcp47(locale)
            || !crate::language::live_catalog::supports_local_asr_language(locale)
            || !language_codes.insert(base_language(locale).to_owned())
        {
            return Err(invalid());
        }
    }
    enabled_alternate_locales.sort_by(|left, right| {
        base_language(left)
            .cmp(base_language(right))
            .then_with(|| left.cmp(right))
    });
    Ok(enabled_alternate_locales)
}

fn ensure_existing_schema_compatible(path: &Path) -> Result<(), LiveLanguageRoutingError> {
    let text = match crate::bounded_file::read_text(path, MAX_ROUTING_PREFERENCE_BYTES) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(_) => return Err(LiveLanguageRoutingError::Access),
    };
    if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
        schema_version(&value)?;
    }
    Ok(())
}

fn schema_version(value: &serde_json::Value) -> Result<u16, LiveLanguageRoutingError> {
    let version = value
        .get("schemaVersion")
        .and_then(serde_json::Value::as_u64)
        .ok_or(LiveLanguageRoutingError::InvalidStoredPreference)?;
    if version > u64::from(CURRENT_SCHEMA_VERSION) {
        return Err(LiveLanguageRoutingError::IncompatibleSchema(version));
    }
    u16::try_from(version).map_err(|_| LiveLanguageRoutingError::IncompatibleSchema(version))
}
