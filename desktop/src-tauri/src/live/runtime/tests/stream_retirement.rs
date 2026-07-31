use super::*;

#[test]
fn timed_out_recognizer_blocks_replacement_until_its_worker_is_reaped() {
    let mut inner = LiveRuntimeInner::for_test();
    let release_worker = Arc::new(Barrier::new(2));
    let worker_released = Arc::clone(&release_worker);
    let worker = std::thread::spawn(move || {
        worker_released.wait();
    });
    inner.set_stream_for_test(SessionStream::from_worker_for_test(1, worker, false));

    inner.retire_stream_detached_reader();
    assert_eq!(
        inner.reap_retiring_stream_for_test(),
        Err("Previous live transcription is still stopping.".into())
    );

    release_worker.wait();
    let deadline = Instant::now() + Duration::from_secs(1);
    while !inner.retiring_stream_is_finished_for_test() {
        assert!(
            Instant::now() < deadline,
            "retired recognizer did not finish"
        );
        std::thread::yield_now();
    }
    assert_eq!(inner.reap_retiring_stream_for_test(), Ok(()));
    assert!(!inner.has_retiring_stream_for_test());
}

#[test]
fn idle_cleanup_does_not_join_a_still_stalled_recognizer() {
    let mut inner = LiveRuntimeInner::for_test();
    let release_worker = Arc::new(Barrier::new(2));
    let worker_released = Arc::clone(&release_worker);
    let worker = std::thread::spawn(move || {
        worker_released.wait();
    });
    inner.set_retiring_stream_for_test(SessionStream::from_worker_for_test(1, worker, true));
    let (done_tx, done_rx) = mpsc::channel();
    let cleanup = std::thread::spawn(move || {
        inner.retire_stream();
        done_tx.send(()).unwrap();
        inner
    });

    let completed_without_joining = done_rx.recv_timeout(Duration::from_secs(1));
    release_worker.wait();
    let mut inner = cleanup.join().unwrap();

    assert!(completed_without_joining.is_ok());
    assert!(inner.has_retiring_stream_for_test());
    let deadline = Instant::now() + Duration::from_secs(1);
    while !inner.retiring_stream_is_finished_for_test() {
        assert!(
            Instant::now() < deadline,
            "retired recognizer did not finish"
        );
        std::thread::yield_now();
    }
    assert_eq!(inner.reap_retiring_stream_for_test(), Ok(()));
    assert!(!inner.has_retiring_stream_for_test());
}
