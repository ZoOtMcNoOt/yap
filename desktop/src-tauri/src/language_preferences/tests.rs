use std::sync::atomic::{AtomicU64, Ordering};

use super::model::{
    canonical_os_locale, project_status, validate_confirmation, CURRENT_SCHEMA_VERSION,
};
use super::persistence::{
    load_from_path, lock_mutation, save_to_path, PrimaryLanguageError, MAX_PRIMARY_LANGUAGE_BYTES,
};
use crate::server_connector::AsrCapabilityCatalog;

static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

const REPOSITORY_EXAMPLE: &[u8] =
    include_bytes!("../../../../server/openapi/examples/asr-capabilities.ok.json");

fn temp_dir(name: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "yap-primary-language-{name}-{}-{}",
        std::process::id(),
        NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
    ))
}

#[cfg(unix)]
fn create_file_symlink(
    source: &std::path::Path,
    destination: &std::path::Path,
) -> std::io::Result<()> {
    std::os::unix::fs::symlink(source, destination)
}

#[cfg(windows)]
fn create_file_symlink(
    source: &std::path::Path,
    destination: &std::path::Path,
) -> std::io::Result<()> {
    std::os::windows::fs::symlink_file(source, destination)
}

#[test]
fn exact_supported_os_locale_is_only_an_unconfirmed_suggestion() {
    let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();

    let status = project_status(None, Some("en-US"), Some(catalog), None, None);

    assert_eq!(status.confirmed_language_bcp47, None);
    assert_eq!(status.suggested_language_bcp47.as_deref(), Some("en-US"));
    assert!(status.requires_confirmation);
}

#[test]
fn last_known_catalog_explains_offline_state_without_authorizing_a_choice() {
    let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();
    let last_known = crate::server_connector::LastKnownAsrCapabilities {
        observed_at_ms: 42,
        catalog: catalog.clone(),
    };

    let status = project_status(None, Some("en-US"), None, Some(last_known.clone()), None);

    assert_eq!(status.capability_catalog, None);
    assert_eq!(status.suggested_language_bcp47, None);
    assert_eq!(status.confirmed_language_available, None);
    assert_eq!(status.last_known_capabilities, Some(last_known));
    assert!(status.requires_confirmation);
}

#[test]
fn platform_locale_spelling_is_canonicalized_without_defaulting() {
    assert_eq!(
        canonical_os_locale(Some("pt_BR.UTF-8")).as_deref(),
        Some("pt-BR")
    );
    assert_eq!(canonical_os_locale(None), None);
    assert_eq!(canonical_os_locale(Some("C")), None);
}

#[test]
fn confirmed_primary_language_round_trips_versioned_state() {
    let dir = temp_dir("round-trip");
    let path = dir.join("primary-language.json");

    assert_eq!(save_to_path("en-US", &path).unwrap(), "en-US");
    assert_eq!(load_from_path(&path).unwrap().as_deref(), Some("en-US"));
    let persisted: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(persisted["schemaVersion"], CURRENT_SCHEMA_VERSION);
    assert_eq!(persisted["languageBcp47"], "en-US");

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn absent_preference_load_does_not_create_a_saved_decision() {
    let dir = temp_dir("absent");
    let path = dir.join("primary-language.json");

    assert_eq!(load_from_path(&path), Ok(None));
    assert!(!path.exists());
    assert!(!dir.exists());
}

#[test]
fn os_locale_does_not_guess_a_nearby_country_variant() {
    let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();

    let status = project_status(None, Some("en-CA"), Some(catalog), None, None);

    assert_eq!(status.suggested_language_bcp47, None);
    assert!(status.requires_confirmation);
}

#[test]
fn confirmed_primary_language_suppresses_os_suggestion() {
    let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();

    let status = project_status(
        Some("fr-FR".into()),
        Some("en-US"),
        Some(catalog),
        None,
        None,
    );

    assert_eq!(status.confirmed_language_bcp47.as_deref(), Some("fr-FR"));
    assert_eq!(status.suggested_language_bcp47, None);
    assert!(!status.requires_confirmation);
    assert_eq!(status.confirmed_language_available, Some(false));
}

#[test]
fn future_schema_is_preserved_instead_of_overwritten() {
    let dir = temp_dir("future");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("primary-language.json");
    let future = br#"{
  "schemaVersion": 2,
  "languageBcp47": "fr-FR",
  "futureField": true
}"#;
    std::fs::write(&path, future).unwrap();

    assert_eq!(
        save_to_path("en-US", &path),
        Err(PrimaryLanguageError::IncompatibleSchema(2))
    );
    assert_eq!(std::fs::read(&path).unwrap(), future);

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn malformed_persisted_preference_requires_explicit_recovery() {
    let dir = temp_dir("invalid");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("primary-language.json");
    std::fs::write(&path, "not-json").unwrap();

    assert_eq!(
        load_from_path(&path),
        Err(PrimaryLanguageError::InvalidStoredPreference)
    );
    assert_eq!(std::fs::read_to_string(&path).unwrap(), "not-json");

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn oversized_preference_fails_closed_without_replacement() {
    let dir = temp_dir("oversized");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("primary-language.json");
    let oversized = vec![b'x'; MAX_PRIMARY_LANGUAGE_BYTES + 1];
    std::fs::write(&path, &oversized).unwrap();

    assert_eq!(load_from_path(&path), Err(PrimaryLanguageError::Access));
    assert_eq!(
        save_to_path("en-US", &path),
        Err(PrimaryLanguageError::Access)
    );
    assert_eq!(std::fs::read(&path).unwrap(), oversized);

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn linked_preference_fails_closed_without_touching_target() {
    let dir = temp_dir("linked");
    std::fs::create_dir_all(&dir).unwrap();
    let target = dir.join("outside.json");
    let path = dir.join("primary-language.json");
    let original = br#"{"schemaVersion":1,"languageBcp47":"fr-FR"}"#;
    std::fs::write(&target, original).unwrap();
    if let Err(error) = create_file_symlink(&target, &path) {
        if cfg!(windows)
            && (error.kind() == std::io::ErrorKind::PermissionDenied
                || error.raw_os_error() == Some(1314))
        {
            std::fs::remove_dir_all(dir).unwrap();
            return;
        }
        panic!("failed to create preference symlink: {error}");
    }

    assert_eq!(load_from_path(&path), Err(PrimaryLanguageError::Access));
    assert_eq!(
        save_to_path("en-US", &path),
        Err(PrimaryLanguageError::Access)
    );
    assert_eq!(std::fs::read(&target).unwrap(), original);

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn confirmation_rejects_language_missing_from_current_fixed_batch_catalog() {
    let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();

    assert_eq!(
        validate_confirmation("fr-FR", &catalog.catalog_revision, &catalog),
        Err(PrimaryLanguageError::UnsupportedLocale)
    );
}

#[test]
fn confirmation_rejects_stale_catalog_revision() {
    let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();

    assert_eq!(
        validate_confirmation("en-US", &"0".repeat(64), &catalog),
        Err(PrimaryLanguageError::StaleCatalog)
    );
}

#[test]
fn primary_language_mutations_are_serialized_through_their_durable_commit() {
    let first = lock_mutation().unwrap();
    let (attempting, attempted) = std::sync::mpsc::channel();
    let (committed, observed) = std::sync::mpsc::channel();
    let contender = std::thread::spawn(move || {
        attempting.send(()).unwrap();
        let _second = lock_mutation().unwrap();
        committed.send(()).unwrap();
    });

    attempted
        .recv_timeout(std::time::Duration::from_secs(1))
        .unwrap();
    assert!(observed
        .recv_timeout(std::time::Duration::from_millis(50))
        .is_err());
    drop(first);
    observed
        .recv_timeout(std::time::Duration::from_secs(1))
        .unwrap();
    contender.join().unwrap();
}
