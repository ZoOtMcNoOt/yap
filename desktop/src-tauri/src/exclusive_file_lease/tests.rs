use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

use super::*;

const CHILD_LEASE_PATH: &str = "YAP_TEST_EXCLUSIVE_LEASE_PATH";
const CHILD_READY_PATH: &str = "YAP_TEST_EXCLUSIVE_LEASE_READY";
const CHILD_RELEASE_PATH: &str = "YAP_TEST_EXCLUSIVE_LEASE_RELEASE";

fn temp_dir(name: &str) -> std::path::PathBuf {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let directory = std::env::temp_dir().join(format!(
        "yap-exclusive-file-lease-{name}-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    std::fs::create_dir_all(&directory).unwrap();
    directory
}

fn wait_for_path(path: &Path, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if path.exists() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    false
}

fn wait_for_child(mut child: std::process::Child, timeout: Duration) -> std::process::Output {
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait().unwrap() {
            Some(_) => return child.wait_with_output().unwrap(),
            None if Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(5));
            }
            None => {
                child.kill().ok();
                let output = child.wait_with_output().unwrap();
                panic!(
                    "exclusive lease child exceeded {timeout:?}: stdout={} stderr={}",
                    String::from_utf8_lossy(&output.stdout),
                    String::from_utf8_lossy(&output.stderr)
                );
            }
        }
    }
}

#[cfg(unix)]
fn create_file_symlink(source: &Path, destination: &Path) -> io::Result<()> {
    std::os::unix::fs::symlink(source, destination)
}

#[cfg(windows)]
fn create_file_symlink(source: &Path, destination: &Path) -> io::Result<()> {
    std::os::windows::fs::symlink_file(source, destination)
}

fn test_symlink_is_unavailable(error: &io::Error) -> bool {
    cfg!(windows)
        && (error.kind() == io::ErrorKind::PermissionDenied || error.raw_os_error() == Some(1314))
}

#[test]
fn second_acquisition_is_nonblocking_and_drop_releases_the_lease() {
    let directory = temp_dir("contention");
    let path = directory.join("instance.lock");

    let first = try_acquire(&path).unwrap();
    assert!(matches!(
        try_acquire(&path),
        Err(TryAcquireExclusiveFileLeaseError::Contended)
    ));
    drop(first);
    try_acquire(&path).unwrap();

    std::fs::remove_dir_all(directory).ok();
}

#[test]
fn cross_process_holder_helper() {
    let Ok(path) = std::env::var(CHILD_LEASE_PATH) else {
        return;
    };
    let ready = std::path::PathBuf::from(std::env::var(CHILD_READY_PATH).unwrap());
    let release = std::path::PathBuf::from(std::env::var(CHILD_RELEASE_PATH).unwrap());
    let _lease = try_acquire(Path::new(&path)).unwrap();
    std::fs::write(&ready, b"locked").unwrap();
    assert!(wait_for_path(&release, Duration::from_secs(10)));
}

#[test]
fn another_process_cannot_acquire_the_same_lease() {
    let directory = temp_dir("cross-process-contention");
    let path = directory.join("instance.lock");
    let ready = directory.join("child.ready");
    let release = directory.join("child.release");
    let mut child = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "exclusive_file_lease::tests::cross_process_holder_helper",
            "--nocapture",
        ])
        .env(CHILD_LEASE_PATH, &path)
        .env(CHILD_READY_PATH, &ready)
        .env(CHILD_RELEASE_PATH, &release)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    if !wait_for_path(&ready, Duration::from_secs(10)) {
        child.kill().ok();
        let output = child.wait_with_output().unwrap();
        panic!(
            "exclusive lease child did not acquire the lock: stdout={} stderr={}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let started = Instant::now();
    assert!(matches!(
        try_acquire(&path),
        Err(TryAcquireExclusiveFileLeaseError::Contended)
    ));
    assert!(
        started.elapsed() < Duration::from_secs(1),
        "contended acquisition must not wait"
    );

    std::fs::write(&release, b"release").unwrap();
    let output = wait_for_child(child, Duration::from_secs(10));
    assert!(
        output.status.success(),
        "child stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    try_acquire(&path).unwrap();

    std::fs::remove_dir_all(directory).ok();
}

#[test]
fn lease_entry_must_be_a_regular_file() {
    let directory = temp_dir("directory-entry");
    let path = directory.join("instance.lock");
    std::fs::create_dir(&path).unwrap();

    let error = match try_acquire(&path) {
        Ok(_) => panic!("exclusive lease accepted a directory"),
        Err(TryAcquireExclusiveFileLeaseError::Io(error)) => error,
        Err(TryAcquireExclusiveFileLeaseError::Contended) => {
            panic!("directory was reported as lock contention")
        }
    };

    assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    assert!(error.to_string().contains("regular file"));
    std::fs::remove_dir_all(directory).ok();
}

#[cfg(any(windows, unix))]
#[test]
fn lease_entry_link_is_rejected_without_touching_its_target() {
    let directory = temp_dir("link-entry");
    let path = directory.join("instance.lock");
    let target = directory.join("outside-lock");
    std::fs::write(&target, b"outside lock").unwrap();
    if let Err(error) = create_file_symlink(&target, &path) {
        if test_symlink_is_unavailable(&error) {
            std::fs::remove_dir_all(directory).ok();
            return;
        }
        panic!("could not create test symlink: {error}");
    }

    assert!(matches!(
        try_acquire(&path),
        Err(TryAcquireExclusiveFileLeaseError::Io(_))
    ));
    assert_eq!(std::fs::read(&target).unwrap(), b"outside lock");
    std::fs::remove_dir_all(directory).ok();
}
