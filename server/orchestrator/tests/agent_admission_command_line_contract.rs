use std::ffi::OsString;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};
use yap_server_orchestrator::parse_agent_admission_arguments;

#[test]
fn command_line_binds_two_exact_profiles_and_distinct_runtime_paths() {
    let values = arguments();
    let config = parse_agent_admission_arguments(values).unwrap();

    assert_eq!(config.socket_path(), runtime_path("agent-admission.sock"));
    assert_eq!(
        config.rapid_state_path(),
        runtime_path("rapid-service-state.json")
    );
    assert_eq!(
        config.complex_state_path(),
        runtime_path("complex-service-state.json")
    );
    config.new_scheduler().unwrap();
}

#[test]
fn command_line_rejects_missing_duplicate_and_unknown_controls() {
    let complete = arguments();
    for required in [
        "--socket-path",
        "--candidate-lock",
        "--rapid-profile",
        "--rapid-profile-sha256",
        "--rapid-state-path",
        "--complex-profile",
        "--complex-profile-sha256",
        "--complex-state-path",
    ] {
        let position = complete.iter().position(|value| value == required).unwrap();
        let mut missing = complete.clone();
        missing.drain(position..=position + 1);
        assert!(
            parse_agent_admission_arguments(missing).is_err(),
            "unexpectedly admitted missing {required}"
        );
    }

    let mut duplicate = complete.clone();
    duplicate.splice(
        0..0,
        [
            OsString::from("--socket-path"),
            runtime_path("other.sock").into_os_string(),
        ],
    );
    assert!(parse_agent_admission_arguments(duplicate).is_err());

    let mut unknown = complete;
    unknown.splice(
        0..0,
        [
            OsString::from("--automatic-fallback"),
            OsString::from("true"),
        ],
    );
    assert!(parse_agent_admission_arguments(unknown).is_err());
}

#[test]
fn command_line_rejects_swapped_profiles_and_changed_hashes() {
    let complete = arguments();
    let rapid_profile_position = complete
        .iter()
        .position(|value| value == "--rapid-profile")
        .unwrap();
    let mut swapped = complete.clone();
    swapped[rapid_profile_position + 1] = complex_profile_path().into_os_string();
    assert!(parse_agent_admission_arguments(swapped).is_err());

    let rapid_hash_position = complete
        .iter()
        .position(|value| value == "--rapid-profile-sha256")
        .unwrap();
    let mut changed = complete;
    changed[rapid_hash_position + 1] = OsString::from("0".repeat(64));
    assert!(parse_agent_admission_arguments(changed).is_err());
}

#[test]
fn command_line_rejects_relative_noncanonical_and_colliding_runtime_paths() {
    let complete = arguments();
    let socket_position = complete
        .iter()
        .position(|value| value == "--socket-path")
        .unwrap();

    let mut relative = complete.clone();
    relative[socket_position + 1] = OsString::from("agent-admission.sock");
    assert!(parse_agent_admission_arguments(relative).is_err());

    let mut noncanonical = complete.clone();
    noncanonical[socket_position + 1] = runtime_path("child")
        .join("..")
        .join("agent-admission.sock")
        .into_os_string();
    assert!(parse_agent_admission_arguments(noncanonical).is_err());

    let rapid_state_position = complete
        .iter()
        .position(|value| value == "--rapid-state-path")
        .unwrap();
    let mut collision = complete;
    collision[rapid_state_position + 1] = runtime_path("agent-admission.sock").into_os_string();
    assert!(parse_agent_admission_arguments(collision).is_err());
}

fn arguments() -> Vec<OsString> {
    vec![
        OsString::from("--socket-path"),
        runtime_path("agent-admission.sock").into_os_string(),
        OsString::from("--candidate-lock"),
        candidate_lock_path().into_os_string(),
        OsString::from("--rapid-profile"),
        rapid_profile_path().into_os_string(),
        OsString::from("--rapid-profile-sha256"),
        OsString::from(profile_sha256(&rapid_profile_path())),
        OsString::from("--rapid-state-path"),
        runtime_path("rapid-service-state.json").into_os_string(),
        OsString::from("--complex-profile"),
        complex_profile_path().into_os_string(),
        OsString::from("--complex-profile-sha256"),
        OsString::from(profile_sha256(&complex_profile_path())),
        OsString::from("--complex-state-path"),
        runtime_path("complex-service-state.json").into_os_string(),
    ]
}

fn rapid_profile_path() -> PathBuf {
    profile_path("rapid-automation.json")
}

fn complex_profile_path() -> PathBuf {
    profile_path("complex-orchestration.json")
}

fn profile_path(filename: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("agent-service-profiles")
        .join(filename)
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

fn profile_sha256(path: &Path) -> String {
    format!("{:x}", Sha256::digest(std::fs::read(path).unwrap()))
}

fn runtime_path(filename: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "yap-agent-admission-{}-{filename}",
        std::process::id()
    ))
}
