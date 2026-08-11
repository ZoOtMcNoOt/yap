#![cfg(unix)]

use std::ffi::OsString;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener as StdUnixListener;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::UnixStream;
use tokio::sync::oneshot;
use tokio::time::{sleep, timeout};
use yap_server_orchestrator::{
    parse_agent_admission_arguments, run_agent_admission_broker, write_private_snapshot,
    LifecycleState, ProviderService, ServiceSnapshot,
};

#[tokio::test]
async fn private_broker_admits_queues_cancels_and_cleans_up() {
    let root = private_temp_directory();
    let rapid_state = root.join("rapid-state.json");
    let complex_state = root.join("complex-state.json");
    write_private_snapshot(
        &rapid_state,
        &ready_snapshot(ProviderService::RapidAutomation),
    )
    .unwrap();
    write_private_snapshot(
        &complex_state,
        &ready_snapshot(ProviderService::ComplexOrchestration),
    )
    .unwrap();
    let socket_path = root.join("agent-admission.sock");
    let config =
        parse_agent_admission_arguments(arguments(&socket_path, &rapid_state, &complex_state))
            .unwrap();
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let broker = tokio::spawn(async move {
        run_agent_admission_broker(config, async move {
            let _ = shutdown_rx.await;
        })
        .await
    });
    wait_for_socket(&socket_path).await;

    assert_eq!(
        send(&socket_path, submit(0, "alice")).await["outcome"],
        "admitted"
    );
    assert_eq!(
        send(&socket_path, submit(1, "bob")).await,
        json!({"outcome": "queued", "schemaVersion": 1})
    );
    assert_eq!(
        send(&socket_path, control("cancel", 0)).await["outcome"],
        "cancellation-requested"
    );
    assert_eq!(
        send(&socket_path, control("acknowledge-cancellation", 0)).await,
        json!({"outcome": "cancelled", "schemaVersion": 1})
    );
    assert_eq!(
        send(&socket_path, control("status", 1)).await["outcome"],
        "admitted"
    );

    shutdown_tx.send(()).unwrap();
    timeout(Duration::from_secs(2), broker)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert!(!socket_path.exists());
    fs::remove_file(rapid_state).unwrap();
    fs::remove_file(complex_state).unwrap();
    fs::remove_dir(root).unwrap();
}

#[tokio::test]
async fn broker_never_replaces_an_existing_socket_owner() {
    let root = private_temp_directory();
    let rapid_state = root.join("rapid-state.json");
    let complex_state = root.join("complex-state.json");
    write_private_snapshot(
        &rapid_state,
        &ready_snapshot(ProviderService::RapidAutomation),
    )
    .unwrap();
    write_private_snapshot(
        &complex_state,
        &ready_snapshot(ProviderService::ComplexOrchestration),
    )
    .unwrap();
    let socket_path = root.join("agent-admission.sock");
    let existing = StdUnixListener::bind(&socket_path).unwrap();
    fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600)).unwrap();
    let before = fs::symlink_metadata(&socket_path).unwrap();
    let config =
        parse_agent_admission_arguments(arguments(&socket_path, &rapid_state, &complex_state))
            .unwrap();

    let error = run_agent_admission_broker(config, std::future::pending())
        .await
        .unwrap_err();
    assert!(error.to_string().contains("already exists"));
    let after = fs::symlink_metadata(&socket_path).unwrap();
    use std::os::unix::fs::MetadataExt;
    assert_eq!((after.dev(), after.ino()), (before.dev(), before.ino()));

    drop(existing);
    fs::remove_file(socket_path).unwrap();
    fs::remove_file(rapid_state).unwrap();
    fs::remove_file(complex_state).unwrap();
    fs::remove_dir(root).unwrap();
}

async fn send(socket_path: &Path, value: Value) -> Value {
    let mut stream = UnixStream::connect(socket_path).await.unwrap();
    let mut bytes = serde_json::to_vec(&value).unwrap();
    bytes.push(b'\n');
    stream.write_all(&bytes).await.unwrap();
    let mut response = Vec::new();
    timeout(Duration::from_secs(2), stream.read_to_end(&mut response))
        .await
        .unwrap()
        .unwrap();
    serde_json::from_slice(&response).unwrap()
}

async fn wait_for_socket(path: &Path) {
    timeout(Duration::from_secs(2), async {
        while !path.exists() {
            sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        fs::metadata(path).unwrap().permissions().mode() & 0o777,
        0o600
    );
}

fn submit(index: usize, subject: &str) -> Value {
    json!({
        "schemaVersion": 1,
        "command": "submit",
        "requestId": format!("agent-request-{index}"),
        "tenantId": "tenant-a",
        "subjectId": subject,
        "purpose": "transcript-correct",
        "role": "scribe",
        "sourceSha256": format!("{:064x}", index + 1),
        "route": "rapid-automation",
        "schedulingClass": "hot",
        "cancellationToken": format!("{index:064x}"),
        "remainingDeadlineMs": 60_000,
    })
}

fn control(command: &str, index: usize) -> Value {
    json!({
        "schemaVersion": 1,
        "command": command,
        "requestId": format!("agent-request-{index}"),
        "cancellationToken": format!("{index:064x}"),
    })
}

fn arguments(socket: &Path, rapid_state: &Path, complex_state: &Path) -> Vec<OsString> {
    let rapid_profile = profile_path("rapid-automation.json");
    let complex_profile = profile_path("complex-orchestration.json");
    vec![
        OsString::from("--socket-path"),
        socket.as_os_str().to_owned(),
        OsString::from("--candidate-lock"),
        candidate_lock_path().into_os_string(),
        OsString::from("--rapid-profile"),
        rapid_profile.as_os_str().to_owned(),
        OsString::from("--rapid-profile-sha256"),
        OsString::from(file_sha256(&rapid_profile)),
        OsString::from("--rapid-state-path"),
        rapid_state.as_os_str().to_owned(),
        OsString::from("--complex-profile"),
        complex_profile.as_os_str().to_owned(),
        OsString::from("--complex-profile-sha256"),
        OsString::from(file_sha256(&complex_profile)),
        OsString::from("--complex-state-path"),
        complex_state.as_os_str().to_owned(),
    ]
}

fn ready_snapshot(service: ProviderService) -> ServiceSnapshot {
    ServiceSnapshot {
        schema_version: 2,
        service,
        profile_id: service.as_str().to_owned(),
        profile_sha256: file_sha256(&profile_path(&format!("{}.json", service.as_str()))),
        candidate_lock_sha256: file_sha256(&candidate_lock_path()),
        state: LifecycleState::Ready,
        process_generation: 1,
        start_count: 1,
        restart_count: 0,
        consecutive_failure_count: 0,
        readiness_transition_count: 1,
    }
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

fn file_sha256(path: &Path) -> String {
    format!("{:x}", Sha256::digest(fs::read(path).unwrap()))
}

fn private_temp_directory() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "yap-agent-admission-broker-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir(&root).unwrap();
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
    root.canonicalize().unwrap()
}
