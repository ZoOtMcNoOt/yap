use super::*;

#[test]
fn stalled_recognizer_times_out_stop_without_enqueuing_finish() {
    let (samples_tx, samples_rx) = mpsc::sync_channel(1);
    samples_tx
        .try_send(StreamMessage::from_prepared_frame(7, prepared_frame(0.0)))
        .unwrap();
    let mut adapter = SessionAsrAdapter::start(samples_tx.clone(), 7);
    let port = adapter.sink();
    port.try_send(prepared_frame(0.25)).unwrap();
    port.close();
    let finisher = StreamFinisher::new(samples_tx, 7);

    let started = Instant::now();
    let status = stop_after_capture_for_test(&mut adapter, &finisher, Duration::from_millis(25));

    assert_eq!(status, StreamFinishStatus::TimedOut);
    assert!(started.elapsed() < Duration::from_millis(250));
    assert!(!adapter.retains_cleanup_ownership());
    assert!(matches!(
        samples_rx.recv_timeout(Duration::from_secs(1)).unwrap(),
        StreamMessage::PreparedFrames { .. }
    ));
    assert!(matches!(
        samples_rx.recv_timeout(Duration::from_millis(25)),
        Err(mpsc::RecvTimeoutError::Timeout)
    ));
}

#[test]
fn reaper_spawn_failure_retains_adapter_ownership_and_reports_a_bounded_stop() {
    let (samples_tx, samples_rx) = mpsc::sync_channel(1);
    samples_tx
        .try_send(StreamMessage::from_prepared_frame(7, prepared_frame(0.0)))
        .unwrap();
    let completion_gate = Arc::new(Barrier::new(2));
    let mut adapter = SessionAsrAdapter::start_with_completion_gate_for_test(
        samples_tx.clone(),
        7,
        Arc::clone(&completion_gate),
    );
    let port = adapter.sink();
    port.try_send(prepared_frame(0.25)).unwrap();
    port.close();
    let finisher = StreamFinisher::new(samples_tx, 7);

    set_reaper_spawn_failure_for_test();
    let started = Instant::now();
    let status = stop_after_capture_for_test(&mut adapter, &finisher, Duration::from_millis(25));

    assert_eq!(status, StreamFinishStatus::TimedOut);
    assert!(started.elapsed() < Duration::from_millis(250));
    assert!(adapter.retains_cleanup_ownership_for_test());
    assert!(matches!(
        samples_rx.recv_timeout(Duration::from_secs(1)).unwrap(),
        StreamMessage::PreparedFrames { .. }
    ));
    assert!(matches!(
        samples_rx.recv_timeout(Duration::from_millis(25)),
        Err(mpsc::RecvTimeoutError::Timeout)
    ));

    completion_gate.wait();
    adapter.cancel_and_join().unwrap();
}

#[test]
fn two_capture_sessions_use_fresh_asr_ports_and_finish_each_once_in_fifo_order() {
    let (samples_tx, samples_rx) = mpsc::sync_channel(8);
    let delivered = Arc::new(Mutex::new(Vec::new()));
    let delivered_for_worker = Arc::clone(&delivered);
    let recognizer = std::thread::spawn(move || {
        let mut finishes = 0;
        while finishes < 2 {
            match samples_rx.recv_timeout(Duration::from_secs(1)).unwrap() {
                StreamMessage::PreparedFrames { session, frames } => {
                    let mut delivered = delivered_for_worker.lock().unwrap();
                    for frame in frames {
                        delivered.push((session, frame.samples.to_vec()));
                    }
                }
                StreamMessage::Finish { session, done } => {
                    delivered_for_worker
                        .lock()
                        .unwrap()
                        .push((session, Vec::new()));
                    finishes += 1;
                    done.send(StreamFinishStatus::Completed.into()).unwrap();
                }
            }
        }
    });

    let mut first = SessionAsrAdapter::start(samples_tx.clone(), 1);
    let first_port = first.sink();
    first_port.try_send(prepared_frame(0.25)).unwrap();
    first_port.close();
    first.join_after_capture().unwrap();
    assert_eq!(
        StreamFinisher::new(samples_tx.clone(), 1).finish_session(),
        StreamFinishStatus::Completed
    );
    assert_eq!(first_port.outcome().accepted_frames, 1);
    assert_eq!(first_port.outcome().dropped_frames, 0);
    assert_eq!(first_port.outcome().error, None);

    let mut second = SessionAsrAdapter::start(samples_tx.clone(), 2);
    let second_port = second.sink();
    assert!(matches!(
        first_port.try_send(prepared_frame(0.5)),
        Err(crate::audio::coordinator::SinkSendError::Closed)
    ));
    second_port.try_send(prepared_frame(0.75)).unwrap();
    second_port.close();
    second.join_after_capture().unwrap();
    assert_eq!(
        StreamFinisher::new(samples_tx, 2).finish_session(),
        StreamFinishStatus::Completed
    );
    assert_eq!(second_port.outcome().accepted_frames, 1);
    assert_eq!(second_port.outcome().dropped_frames, 0);
    assert_eq!(second_port.outcome().error, None);

    recognizer.join().unwrap();
    assert_eq!(
        *delivered.lock().unwrap(),
        vec![
            (1, vec![0.25]),
            (1, Vec::new()),
            (2, vec![0.75]),
            (2, Vec::new()),
        ]
    );
}
