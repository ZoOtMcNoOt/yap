use std::sync::atomic::{AtomicU64, Ordering};

use super::{
    desktop::routing_preference_requires_write,
    model::{project_status, LiveLanguageRoutingPreferenceIssue, CURRENT_SCHEMA_VERSION},
    persistence::{
        load_for_update_from_path, load_from_path, normalize_selection, save_to_path,
        LiveLanguageRoutingError, LoadedRoutingPreference, MAX_ROUTING_PREFERENCE_BYTES,
    },
};

static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

fn temp_dir(name: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "yap-live-language-routing-{name}-{}-{}",
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
fn explicit_alternates_round_trip_in_deterministic_language_order() {
    let dir = temp_dir("round-trip");
    let path = dir.join("live-language-routing.json");

    let saved = save_to_path(vec!["pt-BR".into(), "ja-JP".into(), "fr-CA".into()], &path).unwrap();

    assert_eq!(saved.locales, ["fr-CA", "ja-JP", "pt-BR"]);
    assert_eq!(load_from_path(&path).unwrap(), saved);
    let persisted: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(persisted["schemaVersion"], CURRENT_SCHEMA_VERSION);
    assert_eq!(
        persisted["enabledAlternateLocales"],
        serde_json::json!(["fr-CA", "ja-JP", "pt-BR"])
    );
    assert!(persisted.get("regionalLocales").is_none());

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn absent_routing_preference_is_an_empty_explicit_selection() {
    let dir = temp_dir("absent");
    let path = dir.join("live-language-routing.json");

    assert!(load_from_path(&path).unwrap().locales.is_empty());
    assert!(!path.exists());
    assert!(!dir.exists());
}

#[test]
fn duplicate_language_family_and_unsupported_locales_are_rejected() {
    let dir = temp_dir("invalid-selections");
    let path = dir.join("live-language-routing.json");

    assert_eq!(
        save_to_path(vec!["fr-FR".into(), "fr-CA".into()], &path),
        Err(LiveLanguageRoutingError::InvalidSelection)
    );
    assert_eq!(
        save_to_path(vec!["el-GR".into()], &path),
        Err(LiveLanguageRoutingError::InvalidSelection)
    );
    assert!(!path.exists());
}

#[test]
fn legacy_regional_choices_migrate_without_enabling_other_model_languages() {
    let dir = temp_dir("legacy");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("live-language-routing.json");
    std::fs::write(
        &path,
        format!(
            "{{\"schemaVersion\":1,\"catalogRevision\":{:?},\"regionalLocales\":[\"fr-CA\"]}}",
            crate::language::live_catalog::LOCAL_LANGUAGE_ROUTING_REVISION
        ),
    )
    .unwrap();

    let loaded_for_update = load_for_update_from_path(&path).unwrap();
    assert_eq!(loaded_for_update.locales, ["fr-CA"]);
    assert!(loaded_for_update.requires_rewrite);
    let loaded = load_from_path(&path).unwrap();
    save_to_path(loaded.locales, &path).unwrap();
    assert!(!load_for_update_from_path(&path).unwrap().requires_rewrite);
    let migrated: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(migrated["schemaVersion"], CURRENT_SCHEMA_VERSION);
    assert_eq!(
        migrated["enabledAlternateLocales"],
        serde_json::json!(["fr-CA"])
    );

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn canonical_equivalent_selection_does_not_require_a_runtime_mutation() {
    let requested = normalize_selection(vec!["ja-JP".into(), "fr-CA".into()]).unwrap();
    let loaded = LoadedRoutingPreference {
        locales: vec!["fr-CA".into(), "ja-JP".into()],
        requires_rewrite: false,
    };

    assert!(!routing_preference_requires_write(Ok(loaded), &requested).unwrap());
}

#[test]
fn recoverable_or_legacy_preferences_still_require_a_canonical_write() {
    let requested = vec!["fr-CA".to_string()];
    let legacy = LoadedRoutingPreference {
        locales: requested.clone(),
        requires_rewrite: true,
    };

    assert!(routing_preference_requires_write(Ok(legacy), &requested).unwrap());
    assert!(routing_preference_requires_write(
        Err(LiveLanguageRoutingError::InvalidStoredPreference),
        &requested,
    )
    .unwrap());
    assert!(routing_preference_requires_write(
        Err(LiveLanguageRoutingError::StaleCatalog),
        &requested,
    )
    .unwrap());
}

#[test]
fn incompatible_routing_preferences_are_not_treated_as_recoverable_noops() {
    let error = routing_preference_requires_write(
        Err(LiveLanguageRoutingError::IncompatibleSchema(3)),
        &[],
    )
    .unwrap_err();

    assert_eq!(
        error,
        "Automatic-language settings were written by a newer Yap version."
    );
}

#[test]
fn future_schema_is_preserved_instead_of_overwritten() {
    let dir = temp_dir("future");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("live-language-routing.json");
    let future = br#"{
  "schemaVersion": 3,
  "catalogRevision": "future",
  "enabledAlternateLocales": ["fr-FR"],
  "futureField": true
}"#;
    std::fs::write(&path, future).unwrap();

    assert_eq!(
        save_to_path(vec!["fr-CA".into()], &path),
        Err(LiveLanguageRoutingError::IncompatibleSchema(3))
    );
    assert_eq!(std::fs::read(&path).unwrap(), future);

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn stale_catalog_requires_review_before_reuse() {
    let dir = temp_dir("stale");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("live-language-routing.json");
    std::fs::write(
        &path,
        br#"{"schemaVersion":2,"catalogRevision":"old","enabledAlternateLocales":["fr-FR"]}"#,
    )
    .unwrap();

    assert_eq!(
        load_from_path(&path),
        Err(LiveLanguageRoutingError::StaleCatalog)
    );

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn malformed_and_oversized_preferences_fail_closed() {
    let dir = temp_dir("malformed");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("live-language-routing.json");
    std::fs::write(&path, "not-json").unwrap();
    assert_eq!(
        load_from_path(&path),
        Err(LiveLanguageRoutingError::InvalidStoredPreference)
    );

    let oversized = vec![b'x'; MAX_ROUTING_PREFERENCE_BYTES + 1];
    std::fs::write(&path, &oversized).unwrap();
    assert_eq!(load_from_path(&path), Err(LiveLanguageRoutingError::Access));
    assert_eq!(
        save_to_path(vec!["fr-FR".into()], &path),
        Err(LiveLanguageRoutingError::Access)
    );
    assert_eq!(std::fs::read(&path).unwrap(), oversized);

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn linked_preference_fails_closed_without_touching_its_target() {
    let dir = temp_dir("linked");
    std::fs::create_dir_all(&dir).unwrap();
    let target = dir.join("outside.json");
    let path = dir.join("live-language-routing.json");
    let original =
        br#"{"schemaVersion":2,"catalogRevision":"outside","enabledAlternateLocales":[]}"#;
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

    assert_eq!(load_from_path(&path), Err(LiveLanguageRoutingError::Access));
    assert_eq!(
        save_to_path(vec!["fr-FR".into()], &path),
        Err(LiveLanguageRoutingError::Access)
    );
    assert_eq!(std::fs::read(&target).unwrap(), original);

    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn status_exposes_preview_options_without_enabling_them() {
    let status = project_status(Some("ja-JP".into()), &[], None).unwrap();

    assert_eq!(status.enabled_locales, ["ja-JP"]);
    assert_eq!(status.automatic_languages.len(), 27);
    assert_eq!(
        status
            .automatic_languages
            .iter()
            .map(|option| option.locales.len())
            .sum::<usize>(),
        31
    );
    assert!(status
        .automatic_languages
        .iter()
        .all(|option| option.selected_locale_bcp47.is_none()));
    assert_eq!(status.preference_issue, None);
}

#[test]
fn an_available_saved_preview_route_is_enabled_explicitly() {
    let status = project_status(Some("en-US".into()), &["fr-CA".into()], None).unwrap();

    assert_eq!(status.enabled_locales, ["en-US", "fr-CA"]);
    assert_eq!(status.preference_issue, None);
    assert_eq!(
        status
            .automatic_languages
            .iter()
            .find(|option| option.language_code == "fr")
            .and_then(|option| option.selected_locale_bcp47.as_deref()),
        Some("fr-CA")
    );
}

#[test]
fn invalid_preference_status_does_not_claim_any_automatic_routes() {
    let status = project_status(
        Some("en-US".into()),
        &[],
        Some(LiveLanguageRoutingPreferenceIssue::InvalidStoredPreference),
    )
    .unwrap();

    assert!(status.enabled_locales.is_empty());
    assert_eq!(
        status.preference_issue,
        Some(LiveLanguageRoutingPreferenceIssue::InvalidStoredPreference)
    );
}
