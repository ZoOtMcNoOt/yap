use std::ffi::OsString;
use std::path::PathBuf;

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
    assert_eq!(config.endpoint().authority(), "127.0.0.1:18000");
    assert_eq!(config.expected_model(), "example/model");
    assert_eq!(config.state_path(), state_path);
    assert_eq!(config.command().program(), launcher);
    assert_eq!(
        config.command().arguments(),
        [
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
        "--endpoint",
        "--expected-model",
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
        OsString::from("--service"),
        OsString::from("complex-orchestration"),
        OsString::from("--endpoint"),
        OsString::from("http://127.0.0.1:19000"),
    ];
    let config =
        parse_supervised_service_arguments(arguments(&launcher, &state_path, &provider_arguments))
            .unwrap();

    assert_eq!(config.service(), ProviderService::RapidAutomation);
    assert_eq!(config.endpoint().authority(), "127.0.0.1:18000");
    assert_eq!(config.command().arguments(), provider_arguments);
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
        OsString::from("--endpoint"),
        OsString::from("http://127.0.0.1:18000"),
        OsString::from("--expected-model"),
        OsString::from("example/model"),
        OsString::from("--state-path"),
        state_path.as_os_str().to_owned(),
        OsString::from("--launcher"),
        launcher.as_os_str().to_owned(),
        OsString::from("--"),
    ];
    values.extend_from_slice(tail);
    values
}

fn absolute_state_path(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "yap-supervised-service-cli-{}-{label}.json",
        std::process::id(),
    ))
}
