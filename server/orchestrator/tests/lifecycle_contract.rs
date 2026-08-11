use std::collections::BTreeSet;
use std::fs;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};
use std::path::PathBuf;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use yap_server_orchestrator::{
    write_private_snapshot, LifecycleState, LifecycleTracker, NumericLoopbackEndpoint,
    ProviderService, RestartDecision,
};

#[test]
fn numeric_loopback_endpoint_is_canonical_and_hostname_free() {
    let ipv4 = NumericLoopbackEndpoint::parse("http://127.0.0.1:30000").unwrap();
    assert_eq!(
        ipv4.socket_addr(),
        SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 30000)
    );
    assert_eq!(ipv4.authority(), "127.0.0.1:30000");

    let ipv6 = NumericLoopbackEndpoint::parse("http://[::1]:30001").unwrap();
    assert_eq!(
        ipv6.socket_addr(),
        SocketAddr::new(IpAddr::V6(Ipv6Addr::LOCALHOST), 30001)
    );
    assert_eq!(ipv6.authority(), "[::1]:30001");

    for invalid in [
        "http://localhost:30000",
        "https://127.0.0.1:30000",
        "http://127.0.0.1:0",
        "http://127.0.0.1:30000/health",
        "http://user@127.0.0.1:30000",
        "http://192.0.2.1:30000",
        "http://127.0.0.1:30000?query=1",
        "http://127.0.0.1:30000#fragment",
    ] {
        assert!(
            NumericLoopbackEndpoint::parse(invalid).is_err(),
            "unexpectedly admitted {invalid}"
        );
    }
}

#[test]
fn route_service_identity_never_falls_back() {
    assert_eq!(
        ProviderService::parse("rapid-automation").unwrap(),
        ProviderService::RapidAutomation
    );
    assert_eq!(
        ProviderService::parse("complex-orchestration").unwrap(),
        ProviderService::ComplexOrchestration
    );
    assert!(ProviderService::parse("automatic").is_err());
    assert!(ProviderService::parse("universal-agent").is_err());
    assert_eq!(
        ProviderService::RapidAutomation.as_str(),
        "rapid-automation"
    );
    assert_eq!(
        ProviderService::ComplexOrchestration.as_str(),
        "complex-orchestration"
    );
}

#[test]
fn lifecycle_tracks_ready_restart_and_exact_counts() {
    let mut tracker = new_tracker(ProviderService::RapidAutomation);
    assert_eq!(tracker.snapshot().state, LifecycleState::Starting);
    assert_eq!(tracker.snapshot().process_generation, 0);

    tracker.record_start().unwrap();
    tracker.record_ready().unwrap();
    assert_eq!(tracker.snapshot().state, LifecycleState::Ready);
    assert_eq!(tracker.snapshot().process_generation, 1);
    assert_eq!(tracker.snapshot().start_count, 1);
    assert_eq!(tracker.snapshot().readiness_transition_count, 1);

    assert_eq!(
        tracker.record_unexpected_exit(Duration::from_secs(10)),
        RestartDecision::After(Duration::from_secs(1))
    );
    assert_eq!(tracker.snapshot().state, LifecycleState::RestartBackoff);
    assert_eq!(tracker.snapshot().restart_count, 1);
    assert_eq!(tracker.snapshot().consecutive_failure_count, 1);

    tracker.record_start().unwrap();
    tracker.record_ready().unwrap();
    assert_eq!(tracker.snapshot().process_generation, 2);
    assert_eq!(tracker.snapshot().start_count, 2);
    assert_eq!(tracker.snapshot().readiness_transition_count, 2);
    assert_eq!(tracker.snapshot().consecutive_failure_count, 0);
}

#[test]
fn restart_window_exhausts_and_later_recovers() {
    let mut tracker = new_tracker(ProviderService::ComplexOrchestration);
    tracker.record_start().unwrap();
    tracker.record_ready().unwrap();

    for (observed_at, expected_backoff) in [(1, 1), (2, 2), (3, 4)] {
        assert_eq!(
            tracker.record_unexpected_exit(Duration::from_secs(observed_at)),
            RestartDecision::After(Duration::from_secs(expected_backoff))
        );
        tracker.record_start().unwrap();
        tracker.record_ready().unwrap();
    }
    assert_eq!(
        tracker.record_unexpected_exit(Duration::from_secs(4)),
        RestartDecision::Exhausted
    );
    assert_eq!(tracker.snapshot().state, LifecycleState::Failed);
    assert_eq!(tracker.snapshot().restart_count, 3);

    let mut recovered = new_tracker(ProviderService::ComplexOrchestration);
    recovered.record_start().unwrap();
    recovered.record_ready().unwrap();
    for observed_at in [1, 2, 3] {
        assert!(matches!(
            recovered.record_unexpected_exit(Duration::from_secs(observed_at)),
            RestartDecision::After(_)
        ));
        recovered.record_start().unwrap();
        recovered.record_ready().unwrap();
    }
    assert_eq!(
        recovered.record_unexpected_exit(Duration::from_secs(64)),
        RestartDecision::After(Duration::from_secs(1))
    );
}

#[test]
fn stop_state_is_terminal_and_cannot_restart() {
    let mut tracker = new_tracker(ProviderService::RapidAutomation);
    tracker.record_start().unwrap();
    tracker.record_ready().unwrap();
    tracker.record_stopping().unwrap();
    tracker.record_stopped().unwrap();
    assert_eq!(tracker.snapshot().state, LifecycleState::Stopped);
    assert!(tracker.record_start().is_err());
    assert!(tracker.record_ready().is_err());
    assert_eq!(
        tracker.record_unexpected_exit(Duration::from_secs(1)),
        RestartDecision::Exhausted
    );
}

#[test]
fn snapshot_schema_is_exact_and_secret_free() {
    let mut tracker = new_tracker(ProviderService::RapidAutomation);
    tracker.record_start().unwrap();
    tracker.record_ready().unwrap();
    let value = serde_json::to_value(tracker.snapshot()).unwrap();
    let object = value.as_object().unwrap();
    let keys = object.keys().cloned().collect::<BTreeSet<_>>();
    assert_eq!(
        keys,
        BTreeSet::from([
            "consecutiveFailureCount".to_owned(),
            "candidateLockSha256".to_owned(),
            "processGeneration".to_owned(),
            "profileId".to_owned(),
            "profileSha256".to_owned(),
            "readinessTransitionCount".to_owned(),
            "restartCount".to_owned(),
            "schemaVersion".to_owned(),
            "service".to_owned(),
            "startCount".to_owned(),
            "state".to_owned(),
        ])
    );
    let rendered = serde_json::to_string(&value).unwrap();
    for forbidden in [
        "apiKey",
        "credential",
        "endpoint",
        "modelPath",
        "prompt",
        "response",
        "token",
    ] {
        assert!(!rendered.contains(forbidden));
    }
}

#[test]
fn private_snapshot_write_is_atomic_regular_and_owner_private() {
    let root = unique_temp_directory();
    fs::create_dir(&root).unwrap();
    set_private_directory_permissions(&root);
    let path = root.join("service-state.json");
    let mut tracker = new_tracker(ProviderService::RapidAutomation);
    tracker.record_start().unwrap();
    write_private_snapshot(&path, tracker.snapshot()).unwrap();

    let first: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    assert_eq!(first["state"], "starting");
    assert_eq!(first["processGeneration"], 1);
    assert!(fs::symlink_metadata(&path).unwrap().file_type().is_file());
    assert_owner_private_file(&path);

    tracker.record_ready().unwrap();
    write_private_snapshot(&path, tracker.snapshot()).unwrap();
    let second: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    assert_eq!(second["state"], "ready");
    assert_eq!(second["readinessTransitionCount"], 1);
    assert_owner_private_file(&path);

    fs::remove_file(&path).unwrap();
    fs::remove_dir(&root).unwrap();
}

fn unique_temp_directory() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!(
        "yap-orchestrator-contract-{}-{nonce}",
        std::process::id()
    ))
}

fn new_tracker(service: ProviderService) -> LifecycleTracker {
    LifecycleTracker::new(
        service,
        service.as_str().to_owned(),
        "1".repeat(64),
        "2".repeat(64),
    )
}

#[cfg(unix)]
fn set_private_directory_permissions(path: &std::path::Path) {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
}

#[cfg(not(unix))]
fn set_private_directory_permissions(_path: &std::path::Path) {}

#[cfg(unix)]
fn assert_owner_private_file(path: &std::path::Path) {
    use std::os::unix::fs::PermissionsExt;
    assert_eq!(
        fs::metadata(path).unwrap().permissions().mode() & 0o777,
        0o600
    );
}

#[cfg(not(unix))]
fn assert_owner_private_file(_path: &std::path::Path) {}
