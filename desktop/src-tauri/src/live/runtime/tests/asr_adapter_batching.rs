use super::asr_adapter_fixture::{
    empty_prepared_frame, prepared_frame_with_sample_count, ten_millisecond_prepared_frame,
    TEN_MILLISECOND_FRAME_SAMPLES,
};
use super::*;

#[test]
fn asr_adapter_forwards_the_last_accepted_frame_before_it_joins() {
    let (samples_tx, samples_rx) = mpsc::sync_channel(1);
    let mut adapter = SessionAsrAdapter::start(samples_tx, 7);
    let port = adapter.sink();
    port.try_send(prepared_frame(0.25)).unwrap();
    port.close();

    adapter.join_after_capture().unwrap();
    match samples_rx.recv_timeout(Duration::from_secs(1)).unwrap() {
        StreamMessage::PreparedFrames { session, frames } => {
            assert_eq!(session, 7);
            assert_eq!(frames.len(), 1);
            assert_eq!(&*frames[0].samples, &[0.25]);
        }
        StreamMessage::Finish { .. } => panic!("expected the accepted frame"),
    }
}

#[test]
fn pending_asr_adapter_keeps_bounded_pre_roll_until_the_model_is_ready() {
    let pending = PendingAsrAdapter::new();
    let port = pending.sink();
    port.try_send(prepared_frame(0.4)).unwrap();
    assert_eq!(port.high_water_mark(), 1);
    let (samples_tx, samples_rx) = mpsc::sync_channel(1);

    let mut adapter = pending.start(samples_tx, 11);
    port.close();
    adapter.join_after_capture().unwrap();

    match samples_rx.recv_timeout(Duration::from_secs(1)).unwrap() {
        StreamMessage::PreparedFrames { session, frames } => {
            assert_eq!(session, 11);
            assert_eq!(frames.len(), 1);
            assert_eq!(&*frames[0].samples, &[0.4]);
        }
        StreamMessage::Finish { .. } => panic!("expected queued pre-roll"),
    }
}

#[test]
fn batch_frame_count_stays_bounded_when_frames_have_no_samples() {
    let expected_frames = ASR_ADAPTER_MAX_BATCH_FRAMES + 1;
    let pending = PendingAsrAdapter::new();
    let port = pending.sink();
    for sequence in 0..expected_frames {
        port.try_send(empty_prepared_frame(sequence as u64))
            .unwrap();
    }
    let (samples_tx, samples_rx) = mpsc::sync_channel(1);
    let consumer = std::thread::spawn(move || {
        let mut batch_sizes = Vec::new();
        let mut sequences = Vec::new();
        loop {
            match samples_rx.recv_timeout(Duration::from_secs(1)).unwrap() {
                StreamMessage::PreparedFrames { session, frames } => {
                    assert_eq!(session, 19);
                    batch_sizes.push(frames.len());
                    sequences.extend(frames.into_iter().map(|frame| frame.metadata.sequence));
                }
                StreamMessage::Finish { session, done } => {
                    assert_eq!(session, 19);
                    done.send(StreamFinishStatus::Completed.into()).unwrap();
                    return (batch_sizes, sequences);
                }
            }
        }
    });

    let mut adapter = pending.start(samples_tx.clone(), 19);
    port.close();
    assert_eq!(
        adapter.drain_after_capture(Duration::from_secs(1)).unwrap(),
        AdapterDrainStatus::Drained
    );
    assert_eq!(
        StreamFinisher::new(samples_tx, 19).finish_session(),
        StreamFinishStatus::Completed
    );
    let (batch_sizes, sequences) = consumer.join().unwrap();

    assert_eq!(batch_sizes, vec![ASR_ADAPTER_MAX_BATCH_FRAMES, 1]);
    assert_eq!(sequences, (0..expected_frames as u64).collect::<Vec<_>>());
}

#[test]
fn batch_sample_target_preserves_a_whole_overshooting_frame() {
    let target_samples = stream::chunk_samples();
    let pending = PendingAsrAdapter::new();
    let port = pending.sink();
    port.try_send(prepared_frame_with_sample_count(0, target_samples - 20))
        .unwrap();
    port.try_send(prepared_frame_with_sample_count(1, 40))
        .unwrap();

    let (samples_tx, samples_rx) = mpsc::sync_channel(1);
    let consumer = std::thread::spawn(move || {
        let mut batches = Vec::new();
        loop {
            match samples_rx.recv_timeout(Duration::from_secs(1)).unwrap() {
                StreamMessage::PreparedFrames { session, frames } => {
                    assert_eq!(session, 21);
                    batches.push((
                        frames.len(),
                        frames
                            .iter()
                            .map(|frame| frame.samples.len())
                            .sum::<usize>(),
                    ));
                }
                StreamMessage::Finish { session, done } => {
                    assert_eq!(session, 21);
                    done.send(StreamFinishStatus::Completed.into()).unwrap();
                    return batches;
                }
            }
        }
    });

    let mut adapter = pending.start(samples_tx.clone(), 21);
    port.close();
    assert_eq!(
        adapter.drain_after_capture(Duration::from_secs(1)).unwrap(),
        AdapterDrainStatus::Drained
    );
    assert_eq!(
        StreamFinisher::new(samples_tx, 21).finish_session(),
        StreamFinishStatus::Completed
    );

    assert_eq!(consumer.join().unwrap(), vec![(2, target_samples + 20)]);
}

#[test]
fn finish_waits_for_the_final_forwarded_batch_to_leave_the_fifo() {
    let frames_per_batch = stream::chunk_samples().div_ceil(TEN_MILLISECOND_FRAME_SAMPLES);
    let expected_frames = frames_per_batch * 2;
    let pending = PendingAsrAdapter::new();
    let port = pending.sink();
    for sequence in 0..expected_frames {
        port.try_send(ten_millisecond_prepared_frame(sequence as u64))
            .unwrap();
    }

    let (samples_tx, samples_rx) = mpsc::sync_channel(1);
    let (first_batch_reached_tx, first_batch_reached_rx) = mpsc::channel();
    let (release_first_batch_tx, release_first_batch_rx) = mpsc::channel();
    let consumer = std::thread::spawn(move || {
        let mut delivered_sequences = Vec::new();
        let mut first_batch = true;
        loop {
            match samples_rx.recv_timeout(Duration::from_secs(1)) {
                Ok(StreamMessage::PreparedFrames { session, frames }) => {
                    assert_eq!(session, 23);
                    delivered_sequences
                        .extend(frames.into_iter().map(|frame| frame.metadata.sequence));
                    if first_batch {
                        first_batch = false;
                        first_batch_reached_tx.send(()).unwrap();
                        release_first_batch_rx.recv().unwrap();
                    }
                }
                Ok(StreamMessage::Finish { session, done }) => {
                    assert_eq!(session, 23);
                    done.send(StreamFinishStatus::Completed.into()).unwrap();
                    return delivered_sequences;
                }
                Err(error) => panic!("stream consumer stopped early: {error}"),
            }
        }
    });

    let mut adapter = pending.start(samples_tx.clone(), 23);
    port.close();
    first_batch_reached_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("consumer did not reach the first forwarded batch");
    assert_eq!(
        adapter.drain_after_capture(Duration::from_secs(2)).unwrap(),
        AdapterDrainStatus::Drained
    );
    let (finish_tx, finish_rx) = mpsc::channel();
    let finisher = std::thread::spawn(move || {
        finish_tx
            .send(StreamFinisher::new(samples_tx, 23).finish_session())
            .unwrap();
    });

    assert!(matches!(
        finish_rx.recv_timeout(Duration::from_millis(50)),
        Err(mpsc::RecvTimeoutError::Timeout)
    ));
    release_first_batch_tx.send(()).unwrap();
    assert_eq!(
        finish_rx.recv_timeout(Duration::from_secs(1)).unwrap(),
        StreamFinishStatus::Completed
    );
    finisher.join().unwrap();
    assert_eq!(
        consumer.join().unwrap(),
        (0..expected_frames as u64).collect::<Vec<_>>()
    );
}
