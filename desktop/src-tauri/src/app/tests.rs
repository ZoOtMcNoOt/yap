use super::{
    acquire_instance_lease_at, begin_instance_activation_shutdown_at,
    complete_existing_instance_activation_handoff_at,
    consume_existing_instance_activation_request_at, exit_request_disposition,
    instance_lease_startup_message, is_allowed_app_navigation,
    prepare_primary_instance_activation_state_at, publish_existing_instance_activation_request_at,
    reopen_instance_activation_after_abandoned_shutdown_at, report_activation_request_result,
    request_existing_instance_activation_at,
    request_existing_instance_activation_at_with_before_publish,
    take_existing_instance_activation_request_at, try_acquire_instance_activation_handoff_lease_at,
    write_startup_migration_diagnostic, ExitRequestDisposition, InstanceActivationHandoff,
    INSTANCE_ACTIVATION_REQUEST, INSTANCE_ACTIVATION_REQUEST_FILE, INSTANCE_SHUTDOWN,
    INSTANCE_SHUTDOWN_FILE,
};
use std::{
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc, Arc, Barrier,
    },
    time::Duration,
};

#[test]
fn exit_request_requires_semantic_quit_authorization() {
    assert_eq!(
        exit_request_disposition(false),
        ExitRequestDisposition::PreventAndFinalize
    );
    assert_eq!(
        exit_request_disposition(true),
        ExitRequestDisposition::Allow
    );
}

#[test]
fn navigation_guard_allows_only_application_origins() {
    for allowed in [
        "tauri://localhost/index.html",
        "http://tauri.localhost/index.html",
        "https://tauri.localhost/live-overlay.html",
        "about:blank",
    ] {
        assert!(is_allowed_app_navigation(
            &tauri::Url::parse(allowed).unwrap()
        ));
    }
    for blocked in [
        "https://example.com/",
        "https://tauri.localhost.example.com/",
        "https://user@tauri.localhost/",
        "data:text/html,blocked",
        "file:///C:/private.txt",
    ] {
        assert!(!is_allowed_app_navigation(
            &tauri::Url::parse(blocked).unwrap()
        ));
    }
}

#[test]
fn startup_migration_diagnostic_is_created_outside_app_data() {
    let root = std::env::temp_dir().join(format!(
        "yap-startup-diagnostic-test-{}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(&root).unwrap();

    let path = write_startup_migration_diagnostic(&root, "migration conflict").unwrap();

    assert_eq!(path.parent(), Some(root.as_path()));
    assert!(std::fs::read_to_string(&path)
        .unwrap()
        .contains("migration conflict"));
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn startup_instance_lease_maps_contention_to_a_clear_existing_app_message() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-lease-app-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let first = acquire_instance_lease_at(&root).unwrap();

    let error = match acquire_instance_lease_at(&root) {
        Ok(_) => panic!("a second app startup acquired the instance lease"),
        Err(error) => error,
    };

    assert_eq!(error.kind(), std::io::ErrorKind::WouldBlock);
    let message = instance_lease_startup_message(&error);
    assert!(message.contains("Yap is already running"));
    assert!(message.contains("existing Yap tray app"));
    drop(first);
    acquire_instance_lease_at(&root).unwrap();
    std::fs::remove_dir_all(root).ok();
}

#[test]
fn startup_instance_lease_reports_access_errors_without_claiming_contention() {
    let error = std::io::Error::new(
        std::io::ErrorKind::PermissionDenied,
        "application data is not writable",
    );

    let message = instance_lease_startup_message(&error);

    assert!(message.contains("could not establish exclusive access"));
    assert!(message.contains("stopped before migration and runtime startup"));
    assert!(!message.contains("already running"));
}

#[test]
fn second_instance_activation_request_is_coalesced_and_consumed_once() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join(INSTANCE_ACTIVATION_REQUEST_FILE);

    assert!(!take_existing_instance_activation_request_at(&request).unwrap());
    request_existing_instance_activation_at(&request).unwrap();
    request_existing_instance_activation_at(&request).unwrap();
    assert!(std::fs::metadata(&request).unwrap().is_file());
    assert_eq!(
        std::fs::read(&request).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    assert!(take_existing_instance_activation_request_at(&request).unwrap());
    assert!(!take_existing_instance_activation_request_at(&request).unwrap());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn second_instance_waits_for_acknowledgment_while_primary_lease_is_stable() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-ack-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join(INSTANCE_ACTIVATION_REQUEST_FILE);
    request_existing_instance_activation_at(&request).unwrap();
    let request_to_acknowledge = request.clone();
    let root_to_acknowledge = root.clone();
    let mut lease_checks = 0;
    let handoff = complete_existing_instance_activation_handoff_at(
        &root,
        2,
        Duration::ZERO,
        || {
            lease_checks += 1;
            Ok::<Option<u8>, std::io::Error>(None)
        },
        |_| {
            assert!(
                consume_existing_instance_activation_request_at(&root_to_acknowledge, || {})
                    .unwrap()
            );
            assert!(!request_to_acknowledge.exists());
        },
    )
    .unwrap();

    assert!(matches!(handoff, InstanceActivationHandoff::Acknowledged));
    assert_eq!(lease_checks, 2);
    assert!(!request.exists());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn shutdown_publication_waits_for_an_inflight_handoff_decision() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-shutdown-serialization-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let decision_lease = try_acquire_instance_activation_handoff_lease_at(&root)
        .unwrap()
        .unwrap();
    let shutdown = root.join(INSTANCE_SHUTDOWN_FILE);
    let shutdown_root = root.clone();
    let (waiting_sender, waiting_receiver) = mpsc::channel();
    let (release_sender, release_receiver) = mpsc::channel();
    let shutdown_worker = std::thread::spawn(move || {
        begin_instance_activation_shutdown_at(&shutdown_root, 2, Duration::ZERO, |_| {
            waiting_sender.send(()).unwrap();
            release_receiver
                .recv_timeout(Duration::from_secs(5))
                .unwrap();
        })
    });

    waiting_receiver
        .recv_timeout(Duration::from_secs(5))
        .unwrap();
    assert!(
        !shutdown.exists(),
        "quit cannot publish across an active handoff decision"
    );
    drop(decision_lease);
    release_sender.send(()).unwrap();
    shutdown_worker.join().unwrap().unwrap();
    assert_eq!(std::fs::read(&shutdown).unwrap(), INSTANCE_SHUTDOWN);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn shutdown_marker_stops_primary_activation_consumption() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-shutdown-consumer-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join(INSTANCE_ACTIVATION_REQUEST_FILE);
    request_existing_instance_activation_at(&request).unwrap();
    begin_instance_activation_shutdown_at(&root, 1, Duration::ZERO, |_| {}).unwrap();
    let activated = AtomicBool::new(false);

    assert!(!consume_existing_instance_activation_request_at(&root, || {
        activated.store(true, Ordering::SeqCst);
    })
    .unwrap());
    assert!(!activated.load(Ordering::SeqCst));
    assert_eq!(
        std::fs::read(&request).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn abandoned_shutdown_reopens_activation_without_false_acknowledgment() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-shutdown-reopen-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    begin_instance_activation_shutdown_at(&root, 1, Duration::ZERO, |_| {}).unwrap();

    reopen_instance_activation_after_abandoned_shutdown_at(&root, 1, Duration::ZERO, |_| {})
        .unwrap();

    assert!(!root.join(INSTANCE_SHUTDOWN_FILE).exists());
    assert_eq!(
        std::fs::read(root.join(INSTANCE_ACTIVATION_REQUEST_FILE)).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    let activated = AtomicBool::new(false);
    assert!(consume_existing_instance_activation_request_at(&root, || {
        activated.store(true, Ordering::SeqCst);
    })
    .unwrap());
    assert!(activated.load(Ordering::SeqCst));
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn failed_shutdown_publication_reopen_still_requires_activation() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-shutdown-publication-reopen-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();

    reopen_instance_activation_after_abandoned_shutdown_at(&root, 1, Duration::ZERO, |_| {})
        .unwrap();

    assert_eq!(
        std::fs::read(root.join(INSTANCE_ACTIVATION_REQUEST_FILE)).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    assert!(consume_existing_instance_activation_request_at(&root, || {}).unwrap());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn shutdown_started_before_secondary_decision_forces_promotion() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-quit-handoff-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join(INSTANCE_ACTIVATION_REQUEST_FILE);
    request_existing_instance_activation_at(&request).unwrap();
    assert!(
        consume_existing_instance_activation_request_at(&root, || {}).unwrap(),
        "the primary first consumes the request"
    );
    begin_instance_activation_shutdown_at(&root, 1, Duration::ZERO, |_| {}).unwrap();

    let mut lease_checks = 0;
    let handoff = complete_existing_instance_activation_handoff_at(
        &root,
        2,
        Duration::ZERO,
        || {
            lease_checks += 1;
            Ok::<Option<u8>, std::io::Error>((lease_checks == 2).then_some(73))
        },
        |_| {},
    )
    .unwrap();

    assert_eq!(handoff, InstanceActivationHandoff::Acquired(73));
    assert_eq!(lease_checks, 2);
    assert!(!root.join(INSTANCE_SHUTDOWN_FILE).exists());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn released_primary_lease_promotes_secondary_and_clears_activation_marker() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-promotion-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join(INSTANCE_ACTIVATION_REQUEST_FILE);
    request_existing_instance_activation_at(&request).unwrap();
    let mut lease_checks = 0;
    let handoff = complete_existing_instance_activation_handoff_at(
        &root,
        2,
        Duration::ZERO,
        || {
            lease_checks += 1;
            Ok::<Option<u8>, std::io::Error>((lease_checks == 2).then_some(41))
        },
        |_| {},
    )
    .unwrap();

    assert!(matches!(handoff, InstanceActivationHandoff::Acquired(41)));
    assert!(!request.exists());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn two_concurrent_secondaries_share_one_primary_acknowledgment() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-two-secondaries-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join(INSTANCE_ACTIVATION_REQUEST_FILE);
    let (published_sender, published_receiver) = mpsc::channel();
    let (ready_sender, ready_receiver) = mpsc::channel();
    let mut starts = Vec::new();
    let mut releases = Vec::new();
    let mut secondaries = Vec::new();

    for secondary_id in 0..2 {
        let secondary_root = root.clone();
        let secondary_published = published_sender.clone();
        let secondary_ready = ready_sender.clone();
        let (start_sender, start_receiver) = mpsc::channel();
        let (release_sender, release_receiver) = mpsc::channel();
        starts.push(start_sender);
        releases.push(release_sender);
        secondaries.push(std::thread::spawn(move || {
            publish_existing_instance_activation_request_at(
                &secondary_root,
                500,
                Duration::from_millis(1),
                std::thread::sleep,
            )
            .unwrap();
            secondary_published.send(secondary_id).unwrap();
            start_receiver.recv_timeout(Duration::from_secs(5)).unwrap();
            let mut primary_release_observed = false;
            complete_existing_instance_activation_handoff_at(
                &secondary_root,
                500,
                Duration::from_millis(1),
                || Ok::<Option<u8>, std::io::Error>(None),
                |interval| {
                    if primary_release_observed {
                        std::thread::sleep(interval);
                    } else {
                        secondary_ready.send(secondary_id).unwrap();
                        release_receiver
                            .recv_timeout(Duration::from_secs(5))
                            .unwrap();
                        primary_release_observed = true;
                    }
                },
            )
        }));
    }

    let mut published = [
        published_receiver
            .recv_timeout(Duration::from_secs(5))
            .unwrap(),
        published_receiver
            .recv_timeout(Duration::from_secs(5))
            .unwrap(),
    ];
    published.sort_unstable();
    assert_eq!(published, [0, 1]);
    for start in starts {
        start.send(()).unwrap();
    }
    let mut waiting = [
        ready_receiver.recv_timeout(Duration::from_secs(5)).unwrap(),
        ready_receiver.recv_timeout(Duration::from_secs(5)).unwrap(),
    ];
    waiting.sort_unstable();
    assert_eq!(waiting, [0, 1]);
    let activations = Arc::new(AtomicUsize::new(0));
    let primary_activations = Arc::clone(&activations);
    assert!(
        consume_existing_instance_activation_request_at(&root, move || {
            primary_activations.fetch_add(1, Ordering::SeqCst);
        })
        .unwrap()
    );
    for release in releases {
        release.send(()).unwrap();
    }
    for secondary in secondaries {
        assert_eq!(
            secondary.join().unwrap().unwrap(),
            InstanceActivationHandoff::Acknowledged
        );
    }
    assert_eq!(activations.load(Ordering::SeqCst), 1);
    assert!(!request.exists());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn new_primary_clears_stale_shutdown_and_request_markers() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-stale-shutdown-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join(INSTANCE_ACTIVATION_REQUEST_FILE);
    let shutdown = root.join(INSTANCE_SHUTDOWN_FILE);
    request_existing_instance_activation_at(&request).unwrap();
    begin_instance_activation_shutdown_at(&root, 1, Duration::ZERO, |_| {}).unwrap();
    assert_eq!(std::fs::read(&shutdown).unwrap(), INSTANCE_SHUTDOWN);

    let instance_lease = acquire_instance_lease_at(&root).unwrap();
    prepare_primary_instance_activation_state_at(&root, 1, Duration::ZERO, |_| {}).unwrap();

    assert!(!shutdown.exists());
    assert!(!request.exists());
    drop(instance_lease);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn activation_handoff_timeout_fails_visibly_and_preserves_shared_request() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-timeout-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join(INSTANCE_ACTIVATION_REQUEST_FILE);
    request_existing_instance_activation_at(&request).unwrap();
    let error = complete_existing_instance_activation_handoff_at(
        &root,
        2,
        Duration::ZERO,
        || Ok::<Option<u8>, std::io::Error>(None),
        |_| {},
    )
    .unwrap_err();

    assert_eq!(error.kind(), std::io::ErrorKind::TimedOut);
    assert!(error.to_string().contains("acknowledge"));
    assert!(instance_lease_startup_message(&error).contains("Reason:"));
    assert_eq!(
        std::fs::read(&request).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn timed_out_secondary_does_not_delete_a_coalesced_activation_request() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-timeout-isolation-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join(INSTANCE_ACTIVATION_REQUEST_FILE);
    request_existing_instance_activation_at(&request).unwrap();
    request_existing_instance_activation_at(&request).unwrap();

    complete_existing_instance_activation_handoff_at(
        &root,
        1,
        Duration::ZERO,
        || Ok::<Option<u8>, std::io::Error>(None),
        |_| {},
    )
    .unwrap_err();

    assert_eq!(
        std::fs::read(&request).unwrap(),
        INSTANCE_ACTIVATION_REQUEST,
        "one timed-out secondary must not delete the shared request owned by another"
    );
    assert!(consume_existing_instance_activation_request_at(&root, || {}).unwrap());
    let other = complete_existing_instance_activation_handoff_at(
        &root,
        1,
        Duration::ZERO,
        || Ok::<Option<u8>, std::io::Error>(None),
        |_| {},
    )
    .unwrap();
    assert_eq!(other, InstanceActivationHandoff::Acknowledged);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn activation_handoff_lease_error_is_isolated_from_other_secondaries() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-error-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join(INSTANCE_ACTIVATION_REQUEST_FILE);
    request_existing_instance_activation_at(&request).unwrap();
    let error = complete_existing_instance_activation_handoff_at(
        &root,
        2,
        Duration::ZERO,
        || {
            Err::<Option<u8>, std::io::Error>(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                "synthetic lease access failure",
            ))
        },
        |_| {},
    )
    .unwrap_err();

    assert_eq!(error.kind(), std::io::ErrorKind::PermissionDenied);
    assert!(instance_lease_startup_message(&error).contains("synthetic lease access failure"));
    assert_eq!(
        std::fs::read(&request).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    assert!(consume_existing_instance_activation_request_at(&root, || {}).unwrap());
    let other = complete_existing_instance_activation_handoff_at(
        &root,
        1,
        Duration::ZERO,
        || Ok::<Option<u8>, std::io::Error>(None),
        |_| {},
    )
    .unwrap();
    assert_eq!(other, InstanceActivationHandoff::Acknowledged);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn in_progress_activation_publication_is_invisible_to_the_reader() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-publication-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join("instance-activation.request");
    let producer_request = request.clone();
    let (ready_sender, ready_receiver) = mpsc::channel();
    let (resume_sender, resume_receiver) = mpsc::channel();

    let producer = std::thread::spawn(move || {
        request_existing_instance_activation_at_with_before_publish(
            &producer_request,
            |temporary| {
                ready_sender.send(temporary.to_path_buf()).unwrap();
                resume_receiver
                    .recv_timeout(Duration::from_secs(5))
                    .unwrap();
            },
        )
    });

    let temporary = ready_receiver.recv_timeout(Duration::from_secs(5)).unwrap();
    assert!(temporary.is_file());
    assert_eq!(
        std::fs::read(&temporary).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    assert!(!request.exists());
    assert!(!take_existing_instance_activation_request_at(&request).unwrap());
    assert!(temporary.exists());
    assert!(!std::fs::read_dir(&root).unwrap().any(|entry| {
        entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .contains(".invalid-")
    }));

    resume_sender.send(()).unwrap();
    producer.join().unwrap().unwrap();
    assert!(!temporary.exists());
    assert_eq!(
        std::fs::read(&request).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    assert!(take_existing_instance_activation_request_at(&request).unwrap());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn concurrent_complete_activation_publications_coalesce_without_sidecars() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-concurrency-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join("instance-activation.request");
    let publication_barrier = Arc::new(Barrier::new(3));
    let producers = (0..2)
        .map(|_| {
            let producer_request = request.clone();
            let producer_barrier = Arc::clone(&publication_barrier);
            std::thread::spawn(move || {
                request_existing_instance_activation_at_with_before_publish(
                    &producer_request,
                    |_| {
                        producer_barrier.wait();
                    },
                )
            })
        })
        .collect::<Vec<_>>();

    publication_barrier.wait();
    for producer in producers {
        producer.join().unwrap().unwrap();
    }

    assert_eq!(
        std::fs::read(&request).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    let entries = std::fs::read_dir(&root)
        .unwrap()
        .map(|entry| entry.unwrap().file_name())
        .collect::<Vec<_>>();
    assert_eq!(entries, [request.file_name().unwrap()]);
    assert!(take_existing_instance_activation_request_at(&request).unwrap());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn second_instance_activation_request_recovers_wrong_file_and_directory_types() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-recovery-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join("instance-activation.request");

    std::fs::write(&request, b"stale-or-untyped").unwrap();
    request_existing_instance_activation_at(&request).unwrap();
    assert_eq!(
        std::fs::read(&request).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    assert!(take_existing_instance_activation_request_at(&request).unwrap());

    std::fs::create_dir(&request).unwrap();
    std::fs::write(request.join("must-not-be-recursively-deleted"), b"sentinel").unwrap();
    request_existing_instance_activation_at(&request).unwrap();
    assert_eq!(
        std::fs::read(&request).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    assert!(std::fs::read_dir(&root).unwrap().any(|entry| {
        let entry = entry.unwrap();
        entry.file_type().unwrap().is_dir()
            && entry
                .file_name()
                .to_string_lossy()
                .starts_with("instance-activation.request.invalid-")
    }));

    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn second_instance_activation_request_does_not_follow_redirected_files() {
    let root = std::env::temp_dir().join(format!(
        "yap-instance-activation-link-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let request = root.join("instance-activation.request");
    let target = root.join("redirect-target");
    std::fs::create_dir(&target).unwrap();
    std::fs::write(target.join("target-must-remain"), b"sentinel").unwrap();
    create_test_directory_link(&target, &request);

    request_existing_instance_activation_at(&request).unwrap();

    assert_eq!(
        std::fs::read(target.join("target-must-remain")).unwrap(),
        b"sentinel"
    );
    assert_eq!(
        std::fs::read(&request).unwrap(),
        INSTANCE_ACTIVATION_REQUEST
    );
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn repeated_activation_poll_errors_are_logged_once_until_recovery() {
    let logged = AtomicBool::new(false);
    let mut messages = Vec::new();
    for _ in 0..4 {
        assert!(!report_activation_request_result(
            Err(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                "blocked"
            )),
            &logged,
            |message| messages.push(message.to_string()),
        ));
    }
    assert_eq!(messages.len(), 1);
    assert!(!report_activation_request_result(
        Ok(false),
        &logged,
        |message| messages.push(message.to_string()),
    ));
    assert!(!report_activation_request_result(
        Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "blocked again"
        )),
        &logged,
        |message| messages.push(message.to_string()),
    ));
    assert_eq!(messages.len(), 2);
}

#[cfg(windows)]
fn create_test_directory_link(target: &std::path::Path, link: &std::path::Path) {
    let output = std::process::Command::new("cmd")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(link)
        .arg(target)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "could not create activation-request junction: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[cfg(unix)]
fn create_test_directory_link(target: &std::path::Path, link: &std::path::Path) {
    std::os::unix::fs::symlink(target, link).unwrap();
}
