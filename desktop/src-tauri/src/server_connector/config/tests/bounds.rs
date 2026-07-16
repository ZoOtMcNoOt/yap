use super::super::persistence::{
    acquire_settings_lock, snapshot_destination, write_atomically_locked_with_limit_and_hooks,
    write_atomically_with_before_publish,
};
use super::*;

#[test]
fn oversized_server_url_is_rejected_before_parsing() {
    let error = validate_base_url(&"x".repeat(2049), false).unwrap_err();

    assert!(error.to_string().contains("too long"), "{error}");
}

#[test]
fn oversized_origin_approval_fails_closed_and_is_preserved() {
    let dir = temp_dir("oversized-origin-approval");
    let path = dir.join("server-origin-approval.json");
    let oversized = vec![b' '; 64 * 1024 + 1];
    std::fs::write(&path, &oversized).unwrap();

    let error = origin_is_approved_at(&path, "https://approved.example", false).unwrap_err();

    assert!(error.to_string().contains("too large"), "{error}");
    assert_eq!(
        std::fs::metadata(&path).unwrap().len(),
        oversized.len() as u64
    );
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn oversized_settings_file_fails_closed_and_is_preserved() {
    let dir = temp_dir("oversized-settings");
    let path = dir.join("server-settings.json");
    let oversized = vec![b' '; 64 * 1024 + 1];
    std::fs::write(&path, &oversized).unwrap();

    let error = load_from_path(&path, false).unwrap_err();

    assert!(error.to_string().contains("too large"));
    assert_eq!(
        std::fs::metadata(&path).unwrap().len(),
        oversized.len() as u64
    );
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn save_refuses_to_replace_an_oversized_settings_file() {
    let dir = temp_dir("oversized-settings-save");
    let path = dir.join("server-settings.json");
    let oversized = vec![b' '; 64 * 1024 + 1];
    std::fs::write(&path, &oversized).unwrap();

    let error = save_to_path(&ServerSettings::default(), &path, false).unwrap_err();

    assert!(error.to_string().contains("too large"), "{error}");
    assert_eq!(std::fs::read(&path).unwrap(), oversized);
    assert_eq!(partial_files(&dir), Vec::<String>::new());
    assert_eq!(recovery_files(&dir), Vec::<PathBuf>::new());
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn destination_snapshot_rejects_oversized_configuration() {
    let dir = temp_dir("oversized-destination-snapshot");
    let path = dir.join("server-settings.json");
    let oversized = vec![b' '; 64 * 1024 + 1];
    std::fs::write(&path, &oversized).unwrap();

    let error = snapshot_destination(&path).unwrap_err();

    assert!(error.to_string().contains("too large"), "{error}");
    assert_eq!(std::fs::read(&path).unwrap(), oversized);
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn atomic_writer_rejects_oversized_configuration_before_staging() {
    let dir = temp_dir("oversized-atomic-write");
    let path = dir.join("server-settings.json");
    let oversized = vec![b' '; 64 * 1024 + 1];

    let error = write_atomically_with_before_publish(&path, &oversized, |_, _| Ok(())).unwrap_err();

    assert!(error.to_string().contains("too large"), "{error}");
    assert!(!path.exists());
    assert_eq!(partial_files(&dir), Vec::<String>::new());
    assert_eq!(recovery_files(&dir), Vec::<PathBuf>::new());
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn limit_aware_atomic_writer_supports_a_larger_bounded_snapshot() {
    let dir = temp_dir("larger-bounded-snapshot");
    let path = dir.join("asr-capabilities-snapshot.json");
    let contents = vec![b'x'; 64 * 1024 + 1];
    let _lock = acquire_settings_lock(&path).unwrap();

    write_atomically_locked_with_limit_and_hooks(
        &path,
        &contents,
        contents.len(),
        |_, _| Ok(()),
        |_| Ok(()),
    )
    .unwrap();

    assert_eq!(std::fs::read(&path).unwrap(), contents);
    drop(_lock);
    std::fs::remove_dir_all(dir).ok();
}
