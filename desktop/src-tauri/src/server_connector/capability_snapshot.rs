use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use super::AsrCapabilityCatalog;

const CURRENT_SCHEMA_VERSION: u16 = 1;
const MAX_SNAPSHOT_BYTES: usize = super::capabilities::MAX_CATALOG_BYTES + 4 * 1024;

#[derive(serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PersistedCapabilitySnapshot {
    schema_version: u16,
    origin: String,
    observed_at_ms: u64,
    catalog: AsrCapabilityCatalog,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LastKnownAsrCapabilities {
    pub observed_at_ms: u64,
    pub catalog: AsrCapabilityCatalog,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum CapabilitySnapshotError {
    Access,
    Invalid,
    IncompatibleSchema(u64),
    Save,
}

pub(super) fn snapshot_path() -> PathBuf {
    crate::paths::app_data_dir().join("asr-capabilities-snapshot.json")
}

pub(super) fn save(
    origin: &str,
    catalog: &AsrCapabilityCatalog,
) -> Result<LastKnownAsrCapabilities, CapabilitySnapshotError> {
    let observed_at_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| CapabilitySnapshotError::Save)?
        .as_millis()
        .try_into()
        .map_err(|_| CapabilitySnapshotError::Save)?;
    save_to_path(origin, observed_at_ms, catalog, &snapshot_path())?;
    Ok(LastKnownAsrCapabilities {
        observed_at_ms,
        catalog: catalog.clone(),
    })
}

pub(super) fn load(
    origin: &str,
) -> Result<Option<LastKnownAsrCapabilities>, CapabilitySnapshotError> {
    load_from_path(origin, &snapshot_path())
}

pub(super) fn save_to_path(
    origin: &str,
    observed_at_ms: u64,
    catalog: &AsrCapabilityCatalog,
    path: &Path,
) -> Result<(), CapabilitySnapshotError> {
    validate_origin(origin)?;
    validate_catalog(catalog)?;
    if observed_at_ms == 0 {
        return Err(CapabilitySnapshotError::Invalid);
    }
    let persisted = PersistedCapabilitySnapshot {
        schema_version: CURRENT_SCHEMA_VERSION,
        origin: origin.to_owned(),
        observed_at_ms,
        catalog: catalog.clone(),
    };
    let encoded =
        serde_json::to_vec_pretty(&persisted).map_err(|_| CapabilitySnapshotError::Save)?;
    if encoded.len() > MAX_SNAPSHOT_BYTES {
        return Err(CapabilitySnapshotError::Save);
    }
    let parent = path.parent().ok_or(CapabilitySnapshotError::Save)?;
    std::fs::create_dir_all(parent).map_err(|_| CapabilitySnapshotError::Save)?;
    let _lock = crate::server_connector::config::acquire_settings_lock(path)
        .map_err(|_| CapabilitySnapshotError::Save)?;
    ensure_existing_schema_compatible(path)?;
    crate::server_connector::config::write_atomically_locked_with_limit_and_hooks(
        path,
        &encoded,
        MAX_SNAPSHOT_BYTES,
        |_, _| Ok(()),
        |_| Ok(()),
    )
    .map_err(|_| CapabilitySnapshotError::Save)
}

pub(super) fn load_from_path(
    origin: &str,
    path: &Path,
) -> Result<Option<LastKnownAsrCapabilities>, CapabilitySnapshotError> {
    validate_origin(origin)?;
    let Some(parent) = path.parent() else {
        return Ok(None);
    };
    match std::fs::metadata(parent) {
        Ok(metadata) if metadata.is_dir() => {}
        Ok(_) => return Err(CapabilitySnapshotError::Access),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(CapabilitySnapshotError::Access),
    }
    let _lock = crate::server_connector::config::acquire_settings_access_lock(path)
        .map_err(|_| CapabilitySnapshotError::Access)?;
    let text = match crate::bounded_file::read_text(path, MAX_SNAPSHOT_BYTES) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(CapabilitySnapshotError::Access),
    };
    let value: serde_json::Value =
        serde_json::from_str(&text).map_err(|_| CapabilitySnapshotError::Invalid)?;
    ensure_schema_compatible(&value)?;
    let persisted: PersistedCapabilitySnapshot =
        serde_json::from_value(value).map_err(|_| CapabilitySnapshotError::Invalid)?;
    validate_origin(&persisted.origin)?;
    if persisted.origin != origin {
        return Ok(None);
    }
    if persisted.observed_at_ms == 0 {
        return Err(CapabilitySnapshotError::Invalid);
    }
    validate_catalog(&persisted.catalog)?;
    Ok(Some(LastKnownAsrCapabilities {
        observed_at_ms: persisted.observed_at_ms,
        catalog: persisted.catalog,
    }))
}

fn validate_origin(origin: &str) -> Result<(), CapabilitySnapshotError> {
    match super::config::validate_base_url(origin, true) {
        Ok(normalized) if normalized == origin => Ok(()),
        _ => Err(CapabilitySnapshotError::Invalid),
    }
}

fn validate_catalog(catalog: &AsrCapabilityCatalog) -> Result<(), CapabilitySnapshotError> {
    let encoded = serde_json::to_vec(catalog).map_err(|_| CapabilitySnapshotError::Invalid)?;
    let verified = AsrCapabilityCatalog::parse_bounded(&encoded)
        .map_err(|_| CapabilitySnapshotError::Invalid)?;
    if &verified != catalog {
        return Err(CapabilitySnapshotError::Invalid);
    }
    Ok(())
}

fn ensure_existing_schema_compatible(path: &Path) -> Result<(), CapabilitySnapshotError> {
    let text = match crate::bounded_file::read_text(path, MAX_SNAPSHOT_BYTES) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(_) => return Err(CapabilitySnapshotError::Access),
    };
    if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
        ensure_schema_compatible(&value)?;
    }
    Ok(())
}

fn ensure_schema_compatible(value: &serde_json::Value) -> Result<(), CapabilitySnapshotError> {
    if let Some(version) = value
        .get("schemaVersion")
        .and_then(serde_json::Value::as_u64)
    {
        if version != u64::from(CURRENT_SCHEMA_VERSION) {
            return Err(CapabilitySnapshotError::IncompatibleSchema(version));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicU64, Ordering};

    use super::*;

    static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);
    const REPOSITORY_EXAMPLE: &[u8] =
        include_bytes!("../../../../server/openapi/examples/asr-capabilities.ok.json");

    #[cfg(unix)]
    fn create_file_symlink(source: &Path, destination: &Path) -> std::io::Result<()> {
        std::os::unix::fs::symlink(source, destination)
    }

    #[cfg(windows)]
    fn create_file_symlink(source: &Path, destination: &Path) -> std::io::Result<()> {
        std::os::windows::fs::symlink_file(source, destination)
    }

    #[test]
    fn verified_snapshot_round_trips_only_for_its_exact_origin() {
        let directory = temp_dir("round-trip");
        let path = directory.join("asr-capabilities-snapshot.json");
        let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();

        save_to_path("http://127.0.0.1:18765", 42, &catalog, &path).unwrap();

        assert_eq!(
            load_from_path("http://127.0.0.1:18765", &path).unwrap(),
            Some(LastKnownAsrCapabilities {
                observed_at_ms: 42,
                catalog: catalog.clone(),
            })
        );
        assert_eq!(
            load_from_path("http://127.0.0.1:18766", &path).unwrap(),
            None
        );

        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn tampered_catalog_fingerprint_is_not_available_offline() {
        let directory = temp_dir("tampered");
        let path = directory.join("asr-capabilities-snapshot.json");
        let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();
        save_to_path("http://127.0.0.1:18765", 42, &catalog, &path).unwrap();
        let mut value: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        value["catalog"]["providers"][0]["capabilities"][0]["wordAlignment"] = true.into();
        std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();

        assert_eq!(
            load_from_path("http://127.0.0.1:18765", &path),
            Err(CapabilitySnapshotError::Invalid)
        );

        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn future_snapshot_schema_is_preserved() {
        let directory = temp_dir("future");
        std::fs::create_dir_all(&directory).unwrap();
        let path = directory.join("asr-capabilities-snapshot.json");
        let future = br#"{"schemaVersion":2,"future":true}"#;
        std::fs::write(&path, future).unwrap();
        let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();

        assert_eq!(
            save_to_path("http://127.0.0.1:18765", 42, &catalog, &path),
            Err(CapabilitySnapshotError::IncompatibleSchema(2))
        );
        assert_eq!(std::fs::read(&path).unwrap(), future);

        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn oversized_snapshot_is_preserved_and_unavailable() {
        let directory = temp_dir("oversized");
        std::fs::create_dir_all(&directory).unwrap();
        let path = directory.join("asr-capabilities-snapshot.json");
        let oversized = vec![b'x'; MAX_SNAPSHOT_BYTES + 1];
        std::fs::write(&path, &oversized).unwrap();
        let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();

        assert_eq!(
            load_from_path("http://127.0.0.1:18765", &path),
            Err(CapabilitySnapshotError::Access)
        );
        assert_eq!(
            save_to_path("http://127.0.0.1:18765", 42, &catalog, &path),
            Err(CapabilitySnapshotError::Access)
        );
        assert_eq!(std::fs::read(&path).unwrap(), oversized);

        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn linked_snapshot_fails_closed_without_touching_its_target() {
        let directory = temp_dir("linked");
        std::fs::create_dir_all(&directory).unwrap();
        let target = directory.join("outside.json");
        let path = directory.join("asr-capabilities-snapshot.json");
        let original = br#"{"outside":true}"#;
        std::fs::write(&target, original).unwrap();
        if let Err(error) = create_file_symlink(&target, &path) {
            if cfg!(windows)
                && (error.kind() == std::io::ErrorKind::PermissionDenied
                    || error.raw_os_error() == Some(1314))
            {
                std::fs::remove_dir_all(directory).unwrap();
                return;
            }
            panic!("failed to create capability snapshot symlink: {error}");
        }
        let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();

        assert_eq!(
            load_from_path("http://127.0.0.1:18765", &path),
            Err(CapabilitySnapshotError::Access)
        );
        assert_eq!(
            save_to_path("http://127.0.0.1:18765", 42, &catalog, &path),
            Err(CapabilitySnapshotError::Access)
        );
        assert_eq!(std::fs::read(&target).unwrap(), original);

        std::fs::remove_dir_all(directory).unwrap();
    }

    fn temp_dir(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "yap-asr-capability-snapshot-{label}-{}-{}",
            std::process::id(),
            NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
        ))
    }
}
