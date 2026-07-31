use super::asr_adapter_fixture::{
    assert_ten_millisecond_frame, ten_millisecond_prepared_frame, TEN_MILLISECOND_FRAME_SAMPLES,
};
use super::*;

#[test]
fn full_pre_roll_drains_faster_than_live_capture_rate() {
    let pending = PendingAsrAdapter::new();
    let port = pending.sink();
    for sequence in 0..crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY {
        port.try_send(ten_millisecond_prepared_frame(sequence as u64))
            .unwrap();
    }
    assert_eq!(
        port.high_water_mark(),
        crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY
    );

    let (samples_tx, samples_rx) = mpsc::sync_channel(1);
    let consumer = std::thread::spawn(move || {
        let mut delivered_sequences = Vec::new();
        let mut delivered_samples = 0;
        let mut batches = 0;
        loop {
            match samples_rx.recv_timeout(Duration::from_secs(1)) {
                Ok(StreamMessage::PreparedFrames { session, frames }) => {
                    assert_eq!(session, 17);
                    assert!(!frames.is_empty());
                    assert!(frames.len() <= ASR_ADAPTER_MAX_BATCH_FRAMES);
                    assert!(
                        frames
                            .iter()
                            .map(|frame| frame.samples.len())
                            .sum::<usize>()
                            <= stream::chunk_samples()
                    );
                    delivered_samples += frames
                        .iter()
                        .map(|frame| frame.samples.len())
                        .sum::<usize>();
                    for frame in frames {
                        assert_ten_millisecond_frame(&frame);
                        delivered_sequences.push(frame.metadata.sequence);
                    }
                    batches += 1;
                    std::thread::sleep(Duration::from_millis(2));
                }
                Ok(StreamMessage::Finish { session, done }) => {
                    assert_eq!(session, 17);
                    done.send(StreamFinishStatus::Completed.into()).unwrap();
                    return (delivered_sequences, delivered_samples, batches);
                }
                Err(error) => panic!("stream consumer stopped early: {error}"),
            }
        }
    });

    let mut adapter = pending.start(samples_tx.clone(), 17);
    port.close();
    let status = adapter.drain_after_capture(Duration::from_secs(2)).unwrap();
    assert_eq!(
        StreamFinisher::new(samples_tx, 17).finish_session(),
        StreamFinishStatus::Completed
    );
    let (delivered_sequences, delivered_samples, batches) = consumer.join().unwrap();

    assert_eq!(status, AdapterDrainStatus::Drained);
    assert_eq!(
        delivered_sequences,
        (0..crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY as u64).collect::<Vec<_>>()
    );
    assert_eq!(
        delivered_samples,
        crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY * TEN_MILLISECOND_FRAME_SAMPLES
    );
    let frames_per_batch = stream::chunk_samples()
        .div_ceil(TEN_MILLISECOND_FRAME_SAMPLES)
        .min(ASR_ADAPTER_MAX_BATCH_FRAMES);
    assert_eq!(
        batches,
        crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY.div_ceil(frames_per_batch)
    );
    assert_eq!(port.outcome().dropped_frames, 0);
}

#[test]
fn full_pre_roll_catches_up_after_adapter_spawn_while_capture_continues() {
    const TOTAL_FRAMES: usize = 3_000;

    let pending = PendingAsrAdapter::new();
    let port = pending.sink();
    for sequence in 0..crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY {
        port.try_send(ten_millisecond_prepared_frame(sequence as u64))
            .unwrap();
    }

    let (samples_tx, samples_rx) = mpsc::sync_channel(1);
    let (batch_consumed_tx, batch_consumed_rx) = mpsc::channel();
    let (release_consumer_tx, release_consumer_rx) = mpsc::channel();
    let (production_complete_tx, production_complete_rx) = mpsc::channel();
    let consumer = std::thread::spawn(move || {
        let mut delivered_sequences = Vec::with_capacity(TOTAL_FRAMES);
        let mut gate_for_continued_capture = true;
        loop {
            match samples_rx.recv_timeout(Duration::from_secs(1)) {
                Ok(StreamMessage::PreparedFrames { session, frames }) => {
                    assert_eq!(session, 18);
                    for frame in frames {
                        assert_ten_millisecond_frame(&frame);
                        delivered_sequences.push(frame.metadata.sequence);
                    }
                    if delivered_sequences.len() < TOTAL_FRAMES && gate_for_continued_capture {
                        batch_consumed_tx.send(()).unwrap();
                        gate_for_continued_capture = release_consumer_rx
                            .recv_timeout(Duration::from_secs(1))
                            .expect("continued capture did not release the stream consumer");
                    }
                }
                Ok(StreamMessage::Finish { session, done }) => {
                    assert_eq!(session, 18);
                    done.send(StreamFinishStatus::Completed.into()).unwrap();
                    return delivered_sequences;
                }
                Err(error) => panic!("stream consumer stopped early: {error}"),
            }
        }
    });

    let frames_per_batch = stream::chunk_samples()
        .div_ceil(TEN_MILLISECOND_FRAME_SAMPLES)
        .min(ASR_ADAPTER_MAX_BATCH_FRAMES);
    let continued_capture_burst = (frames_per_batch / 2).max(1);
    let continued_capture = port.clone();
    let producer = std::thread::spawn(move || {
        let mut sequence = crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY;
        while sequence < TOTAL_FRAMES {
            batch_consumed_rx
                .recv_timeout(Duration::from_secs(1))
                .expect("stream consumer did not make bounded progress");
            let burst_end = (sequence + continued_capture_burst).min(TOTAL_FRAMES);
            while sequence < burst_end {
                continued_capture
                    .try_send(ten_millisecond_prepared_frame(sequence as u64))
                    .unwrap();
                sequence += 1;
            }
            let capture_continues = sequence < TOTAL_FRAMES;
            release_consumer_tx.send(capture_continues).unwrap();
        }
        continued_capture.close();
        production_complete_tx.send(()).unwrap();
    });

    let mut adapter = pending.start(samples_tx.clone(), 18);
    production_complete_rx
        .recv_timeout(Duration::from_secs(3))
        .expect("continued capture did not finish its bounded source");

    assert_eq!(
        adapter.drain_after_capture(Duration::from_secs(3)).unwrap(),
        AdapterDrainStatus::Drained
    );
    producer.join().unwrap();
    assert_eq!(
        StreamFinisher::new(samples_tx, 18).finish_session(),
        StreamFinishStatus::Completed
    );
    assert_eq!(
        consumer.join().unwrap(),
        (0..TOTAL_FRAMES as u64).collect::<Vec<_>>()
    );
    assert_eq!(
        port.outcome(),
        crate::audio::coordinator::SinkOutcome {
            kind: SinkKind::LocalAsr,
            accepted_frames: TOTAL_FRAMES as u64,
            dropped_frames: 0,
            closed: true,
            error: None,
        }
    );
}

#[test]
fn pre_roll_overflow_is_bounded_and_fail_visible() {
    let pending = PendingAsrAdapter::new();
    let port = pending.sink();
    for sequence in 0..crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY {
        port.try_send(ten_millisecond_prepared_frame(sequence as u64))
            .unwrap();
    }
    assert_eq!(
        port.try_send(ten_millisecond_prepared_frame(
            crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY as u64,
        )),
        Err(crate::audio::coordinator::SinkSendError::Full)
    );
    assert_eq!(
        port.outcome(),
        crate::audio::coordinator::SinkOutcome {
            kind: SinkKind::LocalAsr,
            accepted_frames: crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY as u64,
            dropped_frames: 1,
            closed: false,
            error: Some("sink queue is full".into()),
        }
    );

    let (samples_tx, samples_rx) = mpsc::sync_channel(1);
    let consumer = std::thread::spawn(move || {
        let mut delivered_frames = 0;
        loop {
            match samples_rx.recv_timeout(Duration::from_secs(1)).unwrap() {
                StreamMessage::PreparedFrames { session, frames } => {
                    assert_eq!(session, 20);
                    delivered_frames += frames.len();
                }
                StreamMessage::Finish { session, done } => {
                    assert_eq!(session, 20);
                    done.send(StreamFinishStatus::Completed.into()).unwrap();
                    return delivered_frames;
                }
            }
        }
    });
    let mut adapter = pending.start(samples_tx.clone(), 20);
    port.close();
    assert_eq!(
        adapter.drain_after_capture(Duration::from_secs(2)).unwrap(),
        AdapterDrainStatus::Drained
    );
    assert_eq!(
        StreamFinisher::new(samples_tx, 20).finish_session(),
        StreamFinishStatus::Completed
    );
    assert_eq!(
        consumer.join().unwrap(),
        crate::audio::coordinator::LOCAL_ASR_QUEUE_CAPACITY
    );
}
