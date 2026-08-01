use std::sync::atomic::{AtomicU64, Ordering};

use super::*;

static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);
const REPOSITORY_EXAMPLE: &[u8] =
    include_bytes!("../../../../../server/openapi/examples/asr-capabilities.ok.json");

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
fn near_limit_verified_catalog_still_fits_the_snapshot_envelope() {
    let directory = temp_dir("near-limit");
    let path = directory.join("asr-capabilities-snapshot.json");
    let mut catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();
    let provider_template = catalog.providers[0].clone();
    catalog.catalog_revision = "0".repeat(64);
    catalog.providers = (0..8)
        .map(|provider_index| {
            let mut provider = provider_template.clone();
            provider.provider_id = format!("provider-{provider_index}");
            provider.pool_id = format!("pool-{provider_index}");
            provider.capabilities.clear();
            provider
        })
        .collect();

    'fill: for capability_index in 0..256 {
        for provider_index in 0..catalog.providers.len() {
            let mut capability = provider_template.capabilities[0].clone();
            capability.language_bcp47 = format!("en-v{capability_index:04}");
            catalog.providers[provider_index]
                .capabilities
                .push(capability);
            if serde_json::to_vec(&catalog).unwrap().len()
                > super::super::capabilities::MAX_CATALOG_BYTES - 512
            {
                catalog.providers[provider_index].capabilities.pop();
                break 'fill;
            }
        }
    }
    catalog.catalog_revision = catalog.computed_revision().unwrap();
    let encoded_catalog = serde_json::to_vec(&catalog).unwrap();
    assert!(encoded_catalog.len() > super::super::capabilities::MAX_CATALOG_BYTES - 4 * 1024);
    let verified = AsrCapabilityCatalog::parse_bounded(&encoded_catalog).unwrap();

    save_to_path("http://127.0.0.1:18765", 42, &verified, &path).unwrap();
    assert_eq!(
        load_from_path("http://127.0.0.1:18765", &path)
            .unwrap()
            .unwrap()
            .catalog,
        verified
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
