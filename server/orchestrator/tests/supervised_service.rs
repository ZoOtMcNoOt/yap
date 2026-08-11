use std::ffi::OsString;
use std::fs;
use std::net::{Ipv4Addr, SocketAddrV4, TcpListener};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU16, AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use tokio::sync::oneshot;
use tokio::time::{sleep, timeout};
use yap_server_orchestrator::{
    run_supervised_service, CommandSpec, LifecycleState, NumericLoopbackEndpoint, ProviderService,
    ServiceProfileIdentity, ServiceSnapshot, SupervisedServiceConfig,
};

const MODEL: &str = "nvidia/Qwen3.6-35B-A3B-NVFP4";
static TEMP_NONCE: AtomicU64 = AtomicU64::new(0);
static NEXT_PORT: AtomicU16 = AtomicU16::new(32_000);

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn service_becomes_ready_and_stops_after_reaping_one_child() {
    let fixture = TestFixture::new(None, MODEL);
    let (shutdown_sender, shutdown_receiver) = oneshot::channel();
    let state_path = fixture.state_path.clone();
    let task = tokio::spawn(run_supervised_service(fixture.config(), async move {
        let _ = shutdown_receiver.await;
    }));

    let ready = wait_for_state(&state_path, LifecycleState::Ready).await;
    assert_eq!(ready.process_generation, 1);
    assert_eq!(ready.schema_version, 2);
    assert_eq!(ready.profile_id, "rapid-automation");
    assert_eq!(ready.profile_sha256, "1".repeat(64));
    assert_eq!(ready.candidate_lock_sha256, "2".repeat(64));
    assert_eq!(ready.start_count, 1);
    assert_eq!(ready.readiness_transition_count, 1);
    shutdown_sender.send(()).unwrap();
    timeout(Duration::from_secs(5), task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();

    let stopped = read_snapshot(&state_path);
    assert_eq!(stopped.state, LifecycleState::Stopped);
    assert_eq!(stopped.start_count, 1);
    assert_eq!(fixture.started_process_count(), 1);
    fixture.cleanup();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unexpected_exit_restarts_without_cross_route_substitution() {
    let fixture = TestFixture::new(Some(1_500), MODEL);
    let (shutdown_sender, shutdown_receiver) = oneshot::channel();
    let state_path = fixture.state_path.clone();
    let task = tokio::spawn(run_supervised_service(fixture.config(), async move {
        let _ = shutdown_receiver.await;
    }));

    let restarted = wait_for_generation(&state_path, 2).await;
    assert_eq!(restarted.service, ProviderService::RapidAutomation);
    assert_eq!(restarted.restart_count, 1);
    assert_eq!(restarted.start_count, 2);
    assert_eq!(restarted.readiness_transition_count, 2);
    shutdown_sender.send(()).unwrap();
    timeout(Duration::from_secs(5), task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(fixture.started_process_count(), 2);
    fixture.cleanup();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shutdown_during_restart_backoff_is_a_clean_terminal_stop() {
    let fixture = TestFixture::new(Some(500), MODEL);
    let (shutdown_sender, shutdown_receiver) = oneshot::channel();
    let state_path = fixture.state_path.clone();
    let task = tokio::spawn(run_supervised_service(fixture.config(), async move {
        let _ = shutdown_receiver.await;
    }));

    let backoff = wait_for_state(&state_path, LifecycleState::RestartBackoff).await;
    assert_eq!(backoff.start_count, 1);
    assert_eq!(backoff.restart_count, 1);
    shutdown_sender.send(()).unwrap();
    timeout(Duration::from_secs(5), task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();

    let stopped = read_snapshot(&state_path);
    assert_eq!(stopped.state, LifecycleState::Stopped);
    assert_eq!(stopped.start_count, 1);
    assert_eq!(fixture.started_process_count(), 1);
    fixture.cleanup();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn repeated_exit_exhausts_the_fixed_restart_window() {
    let fixture = TestFixture::new(Some(500), "wrong-model");
    let (_shutdown_sender, shutdown_receiver) = oneshot::channel::<()>();
    let state_path = fixture.state_path.clone();
    let result = timeout(
        Duration::from_secs(30),
        run_supervised_service(fixture.config(), async move {
            let _ = shutdown_receiver.await;
        }),
    )
    .await
    .unwrap();
    assert!(result.is_err());

    let failed = read_snapshot(&state_path);
    assert_eq!(failed.state, LifecycleState::Failed);
    assert_eq!(failed.restart_count, 3);
    assert_eq!(failed.start_count, 4);
    assert_eq!(failed.readiness_transition_count, 0);
    assert_eq!(fixture.started_process_count(), 4);
    fixture.cleanup();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unhealthy_endpoint_never_transitions_to_ready() {
    let fixture = TestFixture::new(Some(100), MODEL).with_unhealthy_endpoint();
    let (_shutdown_sender, shutdown_receiver) = oneshot::channel::<()>();
    let state_path = fixture.state_path.clone();
    let result = timeout(
        Duration::from_secs(30),
        run_supervised_service(fixture.config(), async move {
            let _ = shutdown_receiver.await;
        }),
    )
    .await
    .unwrap();
    assert!(result.is_err());

    let failed = read_snapshot(&state_path);
    assert_eq!(failed.state, LifecycleState::Failed);
    assert_eq!(failed.start_count, 4);
    assert_eq!(failed.readiness_transition_count, 0);
    assert_eq!(fixture.started_process_count(), 4);
    fixture.cleanup();
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn restart_rejects_a_replaced_launcher_identity() {
    use std::os::unix::fs::{symlink, PermissionsExt};

    let mut fixture = TestFixture::new(Some(500), MODEL);
    let owned_launcher = fixture.root.join("owned-launcher");
    fs::copy(fixture.launcher_path(), &owned_launcher).unwrap();
    fs::set_permissions(&owned_launcher, fs::Permissions::from_mode(0o700)).unwrap();
    fixture.launcher_path = owned_launcher.clone();

    let (_shutdown_sender, shutdown_receiver) = oneshot::channel::<()>();
    let state_path = fixture.state_path.clone();
    let task = tokio::spawn(run_supervised_service(fixture.config(), async move {
        let _ = shutdown_receiver.await;
    }));

    wait_for_state(&state_path, LifecycleState::RestartBackoff).await;
    fs::remove_file(&owned_launcher).unwrap();
    symlink(
        PathBuf::from(env!("CARGO_BIN_EXE_yap-supervised-service-fixture")),
        &owned_launcher,
    )
    .unwrap();

    let result = timeout(Duration::from_secs(15), task)
        .await
        .unwrap()
        .unwrap();
    assert!(result.is_err());
    assert_eq!(read_snapshot(&state_path).state, LifecycleState::Failed);
    assert_eq!(fixture.started_process_count(), 1);
    fixture.cleanup();
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ignored_graceful_stop_is_forced_and_reaped_before_stopped() {
    let fixture = TestFixture::new(None, MODEL).with_ignored_termination();
    let (shutdown_sender, shutdown_receiver) = oneshot::channel();
    let state_path = fixture.state_path.clone();
    let task = tokio::spawn(run_supervised_service(fixture.config(), async move {
        let _ = shutdown_receiver.await;
    }));

    wait_for_state(&state_path, LifecycleState::Ready).await;
    let stop_started = std::time::Instant::now();
    shutdown_sender.send(()).unwrap();
    timeout(Duration::from_secs(20), task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();

    assert!(stop_started.elapsed() >= Duration::from_secs(10));
    assert_eq!(read_snapshot(&state_path).state, LifecycleState::Stopped);
    assert_eq!(fixture.started_process_count(), 1);
    fixture.cleanup();
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shutdown_reaps_an_ignored_descendant_in_the_owned_process_group() {
    let fixture = TestFixture::new(None, MODEL).with_ignored_descendant();
    let descendant_path = fixture.descendant_path.clone();
    let (shutdown_sender, shutdown_receiver) = oneshot::channel();
    let state_path = fixture.state_path.clone();
    let task = tokio::spawn(run_supervised_service(fixture.config(), async move {
        let _ = shutdown_receiver.await;
    }));

    wait_for_state(&state_path, LifecycleState::Ready).await;
    let descendant = fs::read_to_string(&descendant_path)
        .unwrap()
        .trim()
        .parse::<u32>()
        .unwrap();
    shutdown_sender.send(()).unwrap();
    timeout(Duration::from_secs(20), task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();

    wait_for_process_absence(descendant).await;
    assert_eq!(read_snapshot(&state_path).state, LifecycleState::Stopped);
    fixture.cleanup();
}

struct TestFixture {
    root: PathBuf,
    state_path: PathBuf,
    counter_path: PathBuf,
    port: u16,
    model: String,
    exit_after_milliseconds: Option<u64>,
    unhealthy_endpoint: bool,
    ignore_termination: bool,
    spawn_ignored_descendant: bool,
    descendant_path: PathBuf,
    launcher_path: PathBuf,
}

impl TestFixture {
    fn new(exit_after_milliseconds: Option<u64>, model: &str) -> Self {
        let root = unique_temp_directory();
        fs::create_dir(&root).unwrap();
        set_private_directory_permissions(&root);
        Self {
            state_path: root.join("service-state.json"),
            counter_path: root.join("starts.txt"),
            port: free_loopback_port(),
            model: model.to_owned(),
            exit_after_milliseconds,
            unhealthy_endpoint: false,
            ignore_termination: false,
            spawn_ignored_descendant: false,
            descendant_path: root.join("descendant.pid"),
            launcher_path: PathBuf::from(env!("CARGO_BIN_EXE_yap-supervised-service-fixture")),
            root,
        }
    }

    fn with_unhealthy_endpoint(mut self) -> Self {
        self.unhealthy_endpoint = true;
        self
    }

    #[cfg(unix)]
    fn with_ignored_termination(mut self) -> Self {
        self.ignore_termination = true;
        self
    }

    #[cfg(unix)]
    fn with_ignored_descendant(mut self) -> Self {
        self.spawn_ignored_descendant = true;
        self
    }

    fn config(&self) -> SupervisedServiceConfig {
        let mut arguments = vec![
            OsString::from("--port"),
            OsString::from(self.port.to_string()),
            OsString::from("--model"),
            OsString::from(&self.model),
            OsString::from("--counter-file"),
            self.counter_path.as_os_str().to_owned(),
        ];
        if let Some(milliseconds) = self.exit_after_milliseconds {
            arguments.extend([
                OsString::from("--exit-after-ready-ms"),
                OsString::from(milliseconds.to_string()),
            ]);
        }
        if self.unhealthy_endpoint {
            arguments.push(OsString::from("--unhealthy"));
        }
        if self.ignore_termination {
            arguments.push(OsString::from("--ignore-termination"));
        }
        if self.spawn_ignored_descendant {
            arguments.extend([
                OsString::from("--ignored-descendant-pid-file"),
                self.descendant_path.as_os_str().to_owned(),
            ]);
        }
        let identity = ServiceProfileIdentity::new(
            ProviderService::RapidAutomation,
            NumericLoopbackEndpoint::parse(&format!("http://127.0.0.1:{}", self.port)).unwrap(),
            MODEL.to_owned(),
            "rapid-automation".to_owned(),
            "1".repeat(64),
            "2".repeat(64),
        )
        .unwrap();
        SupervisedServiceConfig::new(
            identity,
            self.state_path.clone(),
            CommandSpec::new(self.launcher_path.clone(), arguments).unwrap(),
        )
        .unwrap()
    }

    fn started_process_count(&self) -> usize {
        fs::read_to_string(&self.counter_path)
            .unwrap()
            .lines()
            .count()
    }

    #[cfg(unix)]
    fn launcher_path(&self) -> &Path {
        &self.launcher_path
    }

    fn cleanup(&self) {
        if self.state_path.exists() {
            let _ = fs::remove_file(&self.state_path);
        }
        if self.counter_path.exists() {
            let _ = fs::remove_file(&self.counter_path);
        }
        if self.launcher_path.starts_with(&self.root) && self.launcher_path.exists() {
            let _ = fs::remove_file(&self.launcher_path);
        }
        #[cfg(unix)]
        if self.descendant_path.exists() {
            if let Some(process_id) = fs::read_to_string(&self.descendant_path)
                .ok()
                .and_then(|value| value.trim().parse::<i32>().ok())
            {
                unsafe {
                    libc::kill(process_id, libc::SIGKILL);
                }
            }
            let _ = fs::remove_file(&self.descendant_path);
        }
        let _ = fs::remove_dir(&self.root);
    }
}

impl Drop for TestFixture {
    fn drop(&mut self) {
        self.cleanup();
    }
}

async fn wait_for_state(path: &Path, expected: LifecycleState) -> ServiceSnapshot {
    timeout(Duration::from_secs(5), async {
        loop {
            if path.exists() {
                let snapshot = read_snapshot(path);
                if snapshot.state == expected {
                    return snapshot;
                }
            }
            sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap()
}

async fn wait_for_generation(path: &Path, expected: u64) -> ServiceSnapshot {
    timeout(Duration::from_secs(5), async {
        loop {
            if path.exists() {
                let snapshot = read_snapshot(path);
                if snapshot.process_generation >= expected
                    && snapshot.state == LifecycleState::Ready
                {
                    return snapshot;
                }
            }
            sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap()
}

#[cfg(unix)]
async fn wait_for_process_absence(process_id: u32) {
    timeout(Duration::from_secs(5), async {
        while Path::new(&format!("/proc/{process_id}")).exists() {
            sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
}

fn read_snapshot(path: &Path) -> ServiceSnapshot {
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}

fn free_loopback_port() -> u16 {
    loop {
        let port = NEXT_PORT.fetch_add(1, Ordering::Relaxed);
        if TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port)).is_ok() {
            return port;
        }
    }
}

fn unique_temp_directory() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let sequence = TEMP_NONCE.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "yap-supervised-service-{}-{nonce}-{sequence}",
        std::process::id(),
    ))
}

#[cfg(unix)]
fn set_private_directory_permissions(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
}

#[cfg(not(unix))]
fn set_private_directory_permissions(_path: &Path) {}
