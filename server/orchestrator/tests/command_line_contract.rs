use std::ffi::OsString;
use std::path::PathBuf;

use sha2::{Digest, Sha256};
use yap_server_orchestrator::{parse_supervised_service_arguments, ProviderService};

#[test]
fn command_line_requires_one_complete_explicit_service_configuration() {
    let launcher = std::env::current_exe().unwrap();
    let state_path = absolute_state_path("complete");
    let config = parse_supervised_service_arguments(arguments(
        &launcher,
        &state_path,
        &[
            OsString::from("--provider-option"),
            OsString::from("fixed-value"),
        ],
    ))
    .unwrap();

    assert_eq!(config.service(), ProviderService::RapidAutomation);
    assert_eq!(config.endpoint().authority(), "127.0.0.1:18100");
    assert_eq!(config.expected_model(), "nvidia/Qwen3.6-35B-A3B-NVFP4");
    assert_eq!(config.profile_id(), "rapid-automation");
    assert_eq!(config.profile_sha256(), profile_sha256().as_str());
    assert_eq!(
        config.candidate_lock_sha256(),
        "3e9218c8245863c5f1bda8166a629361b51ed23cec259d7c69f11b1dee83d013"
    );
    assert_eq!(config.state_path(), state_path);
    assert_eq!(config.command().program(), launcher);
    assert_eq!(
        config.command().arguments(),
        [
            OsString::from("--profile"),
            profile_path().into_os_string(),
            OsString::from("--profile-sha256"),
            OsString::from(profile_sha256()),
            OsString::from("--candidate-lock"),
            candidate_lock_path().into_os_string(),
            OsString::from("--provider-option"),
            OsString::from("fixed-value"),
        ]
    );
}

#[test]
fn command_line_rejects_missing_duplicate_and_unknown_controls() {
    let launcher = std::env::current_exe().unwrap();
    let state_path = absolute_state_path("invalid");
    let complete = arguments(&launcher, &state_path, &[]);

    for required_flag in [
        "--service",
        "--profile",
        "--profile-sha256",
        "--candidate-lock",
        "--state-path",
        "--launcher",
    ] {
        let position = complete
            .iter()
            .position(|value| value == required_flag)
            .unwrap();
        let mut missing = complete.clone();
        missing.drain(position..=position + 1);
        assert!(
            parse_supervised_service_arguments(missing).is_err(),
            "unexpectedly admitted missing {required_flag}",
        );
    }

    let mut duplicate = complete.clone();
    duplicate.splice(
        2..2,
        [
            OsString::from("--service"),
            OsString::from("complex-orchestration"),
        ],
    );
    assert!(parse_supervised_service_arguments(duplicate).is_err());

    let mut unknown = complete;
    unknown.splice(
        0..0,
        [
            OsString::from("--automatic-fallback"),
            OsString::from("true"),
        ],
    );
    assert!(parse_supervised_service_arguments(unknown).is_err());
}

#[test]
fn command_line_never_treats_post_separator_values_as_supervisor_controls() {
    let launcher = std::env::current_exe().unwrap();
    let state_path = absolute_state_path("separator");
    let provider_arguments = [
        OsString::from("--endpoint"),
        OsString::from("http://127.0.0.1:19000"),
        OsString::from("--expected-model"),
        OsString::from("ignored/provider-value"),
    ];
    let config =
        parse_supervised_service_arguments(arguments(&launcher, &state_path, &provider_arguments))
            .unwrap();

    assert_eq!(config.service(), ProviderService::RapidAutomation);
    assert_eq!(config.endpoint().authority(), "127.0.0.1:18100");
    assert!(config.command().arguments().ends_with(&provider_arguments));
}

#[test]
fn command_line_rejects_changed_profile_or_candidate_lock_bytes() {
    let launcher = std::env::current_exe().unwrap();
    let state_path = absolute_state_path("changed-input");
    let mut changed_profile = arguments(&launcher, &state_path, &[]);
    let profile_hash_position = changed_profile
        .iter()
        .position(|value| value == "--profile-sha256")
        .unwrap();
    changed_profile[profile_hash_position + 1] = OsString::from("0".repeat(64));
    assert!(parse_supervised_service_arguments(changed_profile).is_err());

    let temporary_lock = std::env::temp_dir().join(format!(
        "yap-agent-candidate-lock-{}.json",
        std::process::id(),
    ));
    std::fs::write(&temporary_lock, b"{}\n").unwrap();
    let mut changed_lock = arguments(&launcher, &state_path, &[]);
    let lock_position = changed_lock
        .iter()
        .position(|value| value == "--candidate-lock")
        .unwrap();
    changed_lock[lock_position + 1] = temporary_lock.as_os_str().to_owned();
    let result = parse_supervised_service_arguments(changed_lock);
    std::fs::remove_file(temporary_lock).unwrap();
    assert!(result.is_err());
}

#[test]
fn command_line_rejects_oversized_profile_inputs() {
    let launcher = std::env::current_exe().unwrap();
    let state_path = absolute_state_path("oversized-profile");
    let oversized_profile = std::env::temp_dir().join(format!(
        "yap-agent-oversized-profile-{}.json",
        std::process::id(),
    ));
    std::fs::write(&oversized_profile, vec![b' '; 1_048_577]).unwrap();
    let mut oversized = arguments(&launcher, &state_path, &[]);
    let path_position = oversized
        .iter()
        .position(|value| value == "--profile")
        .unwrap();
    oversized[path_position + 1] = oversized_profile.as_os_str().to_owned();
    let digest_position = oversized
        .iter()
        .position(|value| value == "--profile-sha256")
        .unwrap();
    oversized[digest_position + 1] =
        OsString::from(hex_sha256(&std::fs::read(&oversized_profile).unwrap()));
    let result = parse_supervised_service_arguments(oversized);
    std::fs::remove_file(oversized_profile).unwrap();

    assert!(result.is_err());
}

#[test]
fn command_line_rejects_a_noncanonical_launcher_identity() {
    let launcher = std::env::current_exe().unwrap();
    let noncanonical = launcher
        .parent()
        .unwrap()
        .join("..")
        .join(launcher.parent().unwrap().file_name().unwrap())
        .join(launcher.file_name().unwrap());

    assert!(parse_supervised_service_arguments(arguments(
        &noncanonical,
        &absolute_state_path("noncanonical"),
        &[],
    ))
    .is_err());
}

#[cfg(unix)]
#[test]
fn command_line_rejects_a_non_executable_launcher_file() {
    use std::fs;
    use std::os::unix::fs::PermissionsExt;

    let launcher = std::env::temp_dir().join(format!(
        "yap-non-executable-launcher-{}",
        std::process::id(),
    ));
    fs::write(&launcher, b"#!/bin/sh\n").unwrap();
    fs::set_permissions(&launcher, fs::Permissions::from_mode(0o600)).unwrap();
    let result = parse_supervised_service_arguments(arguments(
        &launcher,
        &absolute_state_path("non-executable"),
        &[],
    ));
    fs::remove_file(&launcher).unwrap();

    assert!(result.is_err());
}

fn arguments(
    launcher: &std::path::Path,
    state_path: &std::path::Path,
    tail: &[OsString],
) -> Vec<OsString> {
    let mut values = vec![
        OsString::from("--service"),
        OsString::from("rapid-automation"),
        OsString::from("--profile"),
        profile_path().into_os_string(),
        OsString::from("--profile-sha256"),
        OsString::from(profile_sha256()),
        OsString::from("--candidate-lock"),
        candidate_lock_path().into_os_string(),
        OsString::from("--state-path"),
        state_path.as_os_str().to_owned(),
        OsString::from("--launcher"),
        launcher.as_os_str().to_owned(),
        OsString::from("--"),
    ];
    values.extend_from_slice(tail);
    values
}

fn profile_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("agent-service-profiles")
        .join("rapid-automation.json")
        .canonicalize()
        .unwrap()
}

fn candidate_lock_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("agent-reasoning-candidates.lock.json")
        .canonicalize()
        .unwrap()
}

fn profile_sha256() -> String {
    hex_sha256(&std::fs::read(profile_path()).unwrap())
}

fn hex_sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn absolute_state_path(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "yap-supervised-service-cli-{}-{label}.json",
        std::process::id(),
    ))
}
