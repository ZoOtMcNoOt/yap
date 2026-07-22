//! Bounded source-time audio ownership for live language decisions.
//!
//! Frames remain shared until a detector or ASR actually needs contiguous
//! samples. A caller may drain each source sample exactly once on either side
//! of an accepted language boundary.

use std::{collections::VecDeque, sync::Arc};

use crate::audio::frame::PreparedFrame;

const SAMPLE_RATE_HZ: u32 = 16_000;
const SAMPLES_PER_MILLISECOND: u64 = (SAMPLE_RATE_HZ / 1_000) as u64;
const MAX_FRAME_CLOCK_SKEW_SAMPLES: u64 = SAMPLES_PER_MILLISECOND;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct SourceSampleRange {
    pub(super) start_sample: u64,
    pub(super) end_sample: u64,
}

impl SourceSampleRange {
    pub(super) fn len(self) -> u64 {
        self.end_sample - self.start_sample
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct SourceAudioChunk {
    pub(super) range: SourceSampleRange,
    pub(super) samples: Vec<f32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum SourceAudioError {
    InvalidCapacity,
    InvalidFrame,
    SourcePositionOverflow,
    Discontinuity {
        expected_sample: u64,
        observed_sample: u64,
    },
    CapacityExceeded,
    RangeUnavailable,
}

impl std::fmt::Display for SourceAudioError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidCapacity => formatter.write_str("source audio capacity is invalid"),
            Self::InvalidFrame => formatter.write_str("source audio frame is invalid"),
            Self::SourcePositionOverflow => {
                formatter.write_str("source audio position overflowed")
            }
            Self::Discontinuity {
                expected_sample,
                observed_sample,
            } => write!(
                formatter,
                "source audio is discontinuous: expected {expected_sample}, observed {observed_sample}"
            ),
            Self::CapacityExceeded => formatter.write_str("source audio holdback is full"),
            Self::RangeUnavailable => formatter.write_str("source audio range is unavailable"),
        }
    }
}

impl std::error::Error for SourceAudioError {}

#[derive(Debug, Clone)]
struct SharedAudioSlice {
    start_sample: u64,
    offset: usize,
    samples: Arc<[f32]>,
}

impl SharedAudioSlice {
    fn len(&self) -> usize {
        self.samples.len() - self.offset
    }

    fn end_sample(&self) -> u64 {
        self.start_sample + self.len() as u64
    }
}

/// A single contiguous, bounded source-time range.
#[derive(Clone)]
pub(super) struct SourceAudioHoldback {
    maximum_samples: usize,
    retained_samples: usize,
    next_sample: Option<u64>,
    slices: VecDeque<SharedAudioSlice>,
}

impl SourceAudioHoldback {
    pub(super) fn new(maximum_samples: usize) -> Result<Self, SourceAudioError> {
        if maximum_samples == 0 || maximum_samples > SAMPLE_RATE_HZ as usize * 60 {
            return Err(SourceAudioError::InvalidCapacity);
        }
        Ok(Self {
            maximum_samples,
            retained_samples: 0,
            next_sample: None,
            slices: VecDeque::new(),
        })
    }

    pub(super) fn push(
        &mut self,
        frame: PreparedFrame,
    ) -> Result<SourceSampleRange, SourceAudioError> {
        let observed = observed_frame_range(&frame)?;
        let observed_start = observed.start_sample;
        let start_sample = match self.next_sample {
            Some(expected) if within_clock_skew(expected, observed_start) => expected,
            Some(expected) => {
                return Err(SourceAudioError::Discontinuity {
                    expected_sample: expected,
                    observed_sample: observed_start,
                })
            }
            None => observed_start,
        };
        let end_sample = start_sample
            .checked_add(frame.samples.len() as u64)
            .ok_or(SourceAudioError::SourcePositionOverflow)?;
        let retained_samples = self
            .retained_samples
            .checked_add(frame.samples.len())
            .ok_or(SourceAudioError::CapacityExceeded)?;
        if retained_samples > self.maximum_samples {
            return Err(SourceAudioError::CapacityExceeded);
        }

        self.slices.push_back(SharedAudioSlice {
            start_sample,
            offset: 0,
            samples: frame.samples,
        });
        self.retained_samples = retained_samples;
        self.next_sample = Some(end_sample);
        Ok(SourceSampleRange {
            start_sample,
            end_sample,
        })
    }

    pub(super) fn retained_range(&self) -> Option<SourceSampleRange> {
        Some(SourceSampleRange {
            start_sample: self.slices.front()?.start_sample,
            end_sample: self.slices.back()?.end_sample(),
        })
    }

    pub(super) fn source_end_sample(&self) -> Option<u64> {
        self.next_sample
    }

    pub(super) fn copy_range(
        &self,
        range: SourceSampleRange,
    ) -> Result<SourceAudioChunk, SourceAudioError> {
        self.validate_available_range(range)?;
        let length =
            usize::try_from(range.len()).map_err(|_| SourceAudioError::RangeUnavailable)?;
        let mut samples = Vec::with_capacity(length);
        for slice in &self.slices {
            let overlap_start = range.start_sample.max(slice.start_sample);
            let overlap_end = range.end_sample.min(slice.end_sample());
            if overlap_start >= overlap_end {
                continue;
            }
            let start = slice.offset + (overlap_start - slice.start_sample) as usize;
            let end = start + (overlap_end - overlap_start) as usize;
            samples.extend_from_slice(&slice.samples[start..end]);
        }
        if samples.len() != length {
            return Err(SourceAudioError::RangeUnavailable);
        }
        Ok(SourceAudioChunk { range, samples })
    }

    pub(super) fn drain_before(
        &mut self,
        end_sample: u64,
    ) -> Result<SourceAudioChunk, SourceAudioError> {
        let retained = self
            .retained_range()
            .ok_or(SourceAudioError::RangeUnavailable)?;
        let range = SourceSampleRange {
            start_sample: retained.start_sample,
            end_sample,
        };
        let chunk = self.copy_range(range)?;
        self.consume_prefix(chunk.samples.len())?;
        Ok(chunk)
    }

    /// Releases detector-only history without copying samples that have
    /// already been routed independently to ASR.
    pub(super) fn discard_before(&mut self, end_sample: u64) -> Result<(), SourceAudioError> {
        let retained = self
            .retained_range()
            .ok_or(SourceAudioError::RangeUnavailable)?;
        if end_sample < retained.start_sample || end_sample > retained.end_sample {
            return Err(SourceAudioError::RangeUnavailable);
        }
        let count = usize::try_from(end_sample - retained.start_sample)
            .map_err(|_| SourceAudioError::RangeUnavailable)?;
        self.consume_prefix(count)
    }

    fn consume_prefix(&mut self, mut remaining: usize) -> Result<(), SourceAudioError> {
        while remaining > 0 {
            let front_len = self
                .slices
                .front()
                .map(SharedAudioSlice::len)
                .ok_or(SourceAudioError::RangeUnavailable)?;
            if remaining >= front_len {
                self.slices.pop_front();
                self.retained_samples -= front_len;
                remaining -= front_len;
            } else {
                let front = self
                    .slices
                    .front_mut()
                    .ok_or(SourceAudioError::RangeUnavailable)?;
                front.offset += remaining;
                front.start_sample += remaining as u64;
                self.retained_samples -= remaining;
                remaining = 0;
            }
        }
        Ok(())
    }

    pub(super) fn reset(&mut self) {
        self.slices.clear();
        self.retained_samples = 0;
        self.next_sample = None;
    }

    fn validate_available_range(&self, range: SourceSampleRange) -> Result<(), SourceAudioError> {
        let retained = self
            .retained_range()
            .ok_or(SourceAudioError::RangeUnavailable)?;
        if range.start_sample > range.end_sample
            || range.start_sample < retained.start_sample
            || range.end_sample > retained.end_sample
        {
            return Err(SourceAudioError::RangeUnavailable);
        }
        Ok(())
    }
}

pub(super) fn observed_frame_range(
    frame: &PreparedFrame,
) -> Result<SourceSampleRange, SourceAudioError> {
    validate_frame(frame)?;
    let start_sample = frame
        .metadata
        .start_ms
        .checked_mul(SAMPLES_PER_MILLISECOND)
        .ok_or(SourceAudioError::SourcePositionOverflow)?;
    let end_sample = start_sample
        .checked_add(frame.samples.len() as u64)
        .ok_or(SourceAudioError::SourcePositionOverflow)?;
    Ok(SourceSampleRange {
        start_sample,
        end_sample,
    })
}

fn within_clock_skew(expected: u64, observed: u64) -> bool {
    expected.abs_diff(observed) <= MAX_FRAME_CLOCK_SKEW_SAMPLES
}

fn validate_frame(frame: &PreparedFrame) -> Result<(), SourceAudioError> {
    if frame.metadata.sample_rate_hz != SAMPLE_RATE_HZ
        || frame.metadata.channels != 1
        || frame.samples.is_empty()
        || frame.metadata.sample_count != frame.samples.len()
        || frame.samples.len() > SAMPLE_RATE_HZ as usize * 30
    {
        Err(SourceAudioError::InvalidFrame)
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::audio::{
        frame::AudioFrame,
        session::{SessionId, TrackId},
    };

    fn frame(start_ms: u64, sequence: u64, samples: &[f32]) -> PreparedFrame {
        PreparedFrame {
            metadata: AudioFrame {
                session_id: SessionId::new("language-holdback-test").unwrap(),
                track_id: TrackId::new("microphone").unwrap(),
                sequence,
                sample_rate_hz: SAMPLE_RATE_HZ,
                channels: 1,
                start_ms,
                duration_ms: AudioFrame::duration_ms_from_samples(samples.len(), SAMPLE_RATE_HZ),
                sample_count: samples.len(),
            },
            samples: Arc::from(samples),
        }
    }

    #[test]
    fn boundary_split_drains_every_source_sample_exactly_once() {
        let mut holdback = SourceAudioHoldback::new(32).unwrap();
        holdback.push(frame(0, 0, &[0.0, 1.0, 2.0, 3.0])).unwrap();
        holdback.push(frame(0, 1, &[4.0, 5.0, 6.0, 7.0])).unwrap();
        holdback.push(frame(0, 2, &[8.0, 9.0, 10.0, 11.0])).unwrap();

        let before = holdback.drain_before(5).unwrap();
        let after = holdback.drain_before(12).unwrap();

        assert_eq!(
            before.range,
            SourceSampleRange {
                start_sample: 0,
                end_sample: 5
            }
        );
        assert_eq!(before.samples, vec![0.0, 1.0, 2.0, 3.0, 4.0]);
        assert_eq!(
            after.range,
            SourceSampleRange {
                start_sample: 5,
                end_sample: 12
            }
        );
        assert_eq!(after.samples, vec![5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0]);
        assert_eq!(holdback.retained_range(), None);
    }

    #[test]
    fn overlapping_detector_windows_do_not_consume_holdback_audio() {
        let mut holdback = SourceAudioHoldback::new(32).unwrap();
        holdback.push(frame(100, 0, &[0.0, 1.0, 2.0, 3.0])).unwrap();
        holdback.push(frame(100, 1, &[4.0, 5.0, 6.0, 7.0])).unwrap();

        assert_eq!(
            holdback
                .copy_range(SourceSampleRange {
                    start_sample: 1_602,
                    end_sample: 1_606
                })
                .unwrap()
                .samples,
            vec![2.0, 3.0, 4.0, 5.0]
        );
        assert_eq!(
            holdback
                .copy_range(SourceSampleRange {
                    start_sample: 1_604,
                    end_sample: 1_608
                })
                .unwrap()
                .samples,
            vec![4.0, 5.0, 6.0, 7.0]
        );
        assert_eq!(
            holdback.retained_range(),
            Some(SourceSampleRange {
                start_sample: 1_600,
                end_sample: 1_608
            })
        );
    }

    #[test]
    fn discontinuity_and_capacity_fail_without_mutating_the_retained_range() {
        let mut holdback = SourceAudioHoldback::new(8).unwrap();
        holdback.push(frame(0, 0, &[1.0, 2.0, 3.0, 4.0])).unwrap();
        let retained = holdback.retained_range();

        assert!(matches!(
            holdback.push(frame(20, 1, &[5.0, 6.0])),
            Err(SourceAudioError::Discontinuity { .. })
        ));
        assert_eq!(holdback.retained_range(), retained);
        assert_eq!(
            holdback.push(frame(0, 2, &[5.0, 6.0, 7.0, 8.0, 9.0])),
            Err(SourceAudioError::CapacityExceeded)
        );
        assert_eq!(holdback.retained_range(), retained);
    }

    #[test]
    fn one_millisecond_clock_rounding_is_aligned_but_larger_overlap_is_rejected() {
        let mut holdback = SourceAudioHoldback::new(64).unwrap();
        holdback.push(frame(0, 0, &[0.0; 17])).unwrap();
        let aligned = holdback.push(frame(1, 1, &[1.0; 4])).unwrap();
        assert_eq!(aligned.start_sample, 17);

        assert!(matches!(
            holdback.push(frame(0, 2, &[2.0; 4])),
            Err(SourceAudioError::Discontinuity { .. })
        ));
    }

    #[test]
    fn reset_starts_a_new_contiguous_source_run() {
        let mut holdback = SourceAudioHoldback::new(16).unwrap();
        holdback.push(frame(0, 0, &[1.0, 2.0])).unwrap();
        holdback.reset();

        let range = holdback.push(frame(5_000, 1, &[3.0, 4.0])).unwrap();
        assert_eq!(
            range,
            SourceSampleRange {
                start_sample: 80_000,
                end_sample: 80_002
            }
        );
    }
}
