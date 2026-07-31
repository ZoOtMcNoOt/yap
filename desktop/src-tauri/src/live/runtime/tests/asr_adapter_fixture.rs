use super::*;

pub(super) const TEN_MILLISECOND_FRAME_SAMPLES: usize = 160;

pub(super) fn ten_millisecond_prepared_frame(sequence: u64) -> PreparedFrame {
    PreparedFrame {
        metadata: AudioFrame {
            session_id: SessionId::new("adapter-pre-roll-test").unwrap(),
            track_id: TrackId::new("microphone").unwrap(),
            sequence,
            sample_rate_hz: 16_000,
            channels: 1,
            start_ms: sequence * 10,
            duration_ms: 10,
            sample_count: TEN_MILLISECOND_FRAME_SAMPLES,
        },
        samples: Arc::from(vec![sequence as f32; TEN_MILLISECOND_FRAME_SAMPLES]),
    }
}

pub(super) fn assert_ten_millisecond_frame(frame: &PreparedFrame) {
    let sequence = frame.metadata.sequence;
    assert_eq!(frame.metadata.session_id.as_str(), "adapter-pre-roll-test");
    assert_eq!(frame.metadata.track_id.as_str(), "microphone");
    assert_eq!(frame.metadata.sample_rate_hz, 16_000);
    assert_eq!(frame.metadata.channels, 1);
    assert_eq!(frame.metadata.start_ms, sequence * 10);
    assert_eq!(frame.metadata.duration_ms, 10);
    assert_eq!(frame.metadata.sample_count, TEN_MILLISECOND_FRAME_SAMPLES);
    assert_eq!(frame.samples.len(), TEN_MILLISECOND_FRAME_SAMPLES);
    assert!(frame
        .samples
        .iter()
        .all(|sample| *sample == sequence as f32));
}

pub(super) fn prepared_frame_with_sample_count(
    sequence: u64,
    sample_count: usize,
) -> PreparedFrame {
    PreparedFrame {
        metadata: AudioFrame {
            session_id: SessionId::new("adapter-batch-target-test").unwrap(),
            track_id: TrackId::new("microphone").unwrap(),
            sequence,
            sample_rate_hz: 16_000,
            channels: 1,
            start_ms: sequence * 2_000,
            duration_ms: AudioFrame::duration_ms_from_samples(sample_count, 16_000),
            sample_count,
        },
        samples: Arc::from(vec![sequence as f32; sample_count]),
    }
}

pub(super) fn empty_prepared_frame(sequence: u64) -> PreparedFrame {
    PreparedFrame {
        metadata: AudioFrame {
            session_id: SessionId::new("adapter-empty-frame-test").unwrap(),
            track_id: TrackId::new("microphone").unwrap(),
            sequence,
            sample_rate_hz: 16_000,
            channels: 1,
            start_ms: sequence,
            duration_ms: 0,
            sample_count: 0,
        },
        samples: Arc::from([]),
    }
}
