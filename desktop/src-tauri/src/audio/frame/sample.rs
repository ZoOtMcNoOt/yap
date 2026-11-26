use std::sync::Arc;

use crate::audio::session::{SessionId, TrackId};

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GapCause {
    CallbackPoolExhausted,
    OversizedCallback,
    DeviceDiscontinuity,
    SinkUnavailable,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AudioGap {
    pub session_id: SessionId,
    pub track_id: TrackId,
    pub start_ms: u64,
    pub duration_ms: u32,
    pub source_position_frames: u64,
    pub dropped_frames: u64,
    pub cause: GapCause,
    pub generation: u64,
}

impl AudioGap {
    pub fn end_ms(&self) -> Option<u64> {
        self.start_ms.checked_add(u64::from(self.duration_ms))
    }

    pub(super) fn covers(
        &self,
        session_id: &SessionId,
        track_id: &TrackId,
        start_ms: u64,
        end_ms: u64,
    ) -> bool {
        self.session_id == *session_id
            && self.track_id == *track_id
            && self.end_ms().is_some_and(|gap_end_ms| {
                self.start_ms == start_ms && gap_end_ms == end_ms && gap_end_ms > self.start_ms
            })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TrackConfigurationRevision {
    pub(crate) track_id: TrackId,
    pub(crate) revision: u32,
    pub(crate) effective_at_ms: u64,
    pub(crate) sample_rate_hz: u32,
}

impl TrackConfigurationRevision {
    pub fn new(
        track_id: TrackId,
        revision: u32,
        effective_at_ms: u64,
        sample_rate_hz: u32,
    ) -> Result<Self, ManifestError> {
        if revision == 0 || sample_rate_hz == 0 {
            return Err(ManifestError::InvalidConfigurationRevision);
        }
        Ok(Self {
            track_id,
            revision,
            effective_at_ms,
            sample_rate_hz,
        })
    }
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct TrackConfigurationRevisionWire {
    track_id: TrackId,
    revision: u32,
    effective_at_ms: u64,
    sample_rate_hz: u32,
}

impl<'de> serde::Deserialize<'de> for TrackConfigurationRevision {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let wire = TrackConfigurationRevisionWire::deserialize(deserializer)?;
        Self::new(
            wire.track_id,
            wire.revision,
            wire.effective_at_ms,
            wire.sample_rate_hz,
        )
        .map_err(serde::de::Error::custom)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ManifestError {
    EmptyFrames,
    SessionMismatch,
    TrackMismatch,
    InvalidFrameTiming,
    OverlappingFrameTiming,
    SequenceDiscontinuity,
    TimingDiscontinuity,
    MixedSampleRates,
    MissingConversionRevision,
    InvalidConfigurationRevision,
    InvalidRouteForOrigin,
    InvalidArtifactId,
    EmptyEncodedAudio,
    InvalidVadTiming,
    InvalidGapTiming,
    DurationOverflow,
    SessionTrackReferenceMismatch,
    SessionMetadataMismatch,
}

impl std::fmt::Display for ManifestError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ManifestError {}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AudioFrame {
    pub session_id: SessionId,
    pub track_id: TrackId,
    pub sequence: u64,
    pub sample_rate_hz: u32,
    pub channels: u16,
    pub start_ms: u64,
    pub duration_ms: u32,
    pub sample_count: usize,
}

#[derive(Debug, Clone)]
pub struct PreparedFrame {
    pub metadata: AudioFrame,
    pub samples: Arc<[f32]>,
}

/// Position of a prepared mono frame on the 16 kHz language timeline.
#[derive(Clone, Copy)]
pub(crate) struct PreparedFramePosition {
    pub(crate) start_sample: u64,
    pub(crate) end_sample: u64,
    end_ms: u64,
}

impl PreparedFrame {
    pub(crate) fn source_position(
        &self,
        previous: Option<PreparedFramePosition>,
    ) -> Option<PreparedFramePosition> {
        const RATE: u32 = crate::language::span_contract::LANGUAGE_SPAN_SAMPLE_RATE_HZ;
        const SAMPLES_PER_MS: u64 = (RATE / 1000) as u64;
        if self.metadata.sample_rate_hz != RATE
            || self.metadata.channels != 1
            || self.metadata.sample_count != self.samples.len()
        {
            return None;
        }
        let start_ms = self.metadata.start_ms;
        let observed = start_ms.checked_mul(SAMPLES_PER_MS)?;
        // CPAL timestamps are projected to whole milliseconds. Adjacent packets
        // retain the fractional millisecond already counted in the samples.
        let start_sample = previous
            .filter(|prior| {
                (prior.end_ms == start_ms || prior.end_sample / SAMPLES_PER_MS == start_ms)
                    && prior.end_sample.abs_diff(observed) <= SAMPLES_PER_MS
            })
            .map_or(observed, |prior| prior.end_sample);
        Some(PreparedFramePosition {
            start_sample,
            end_sample: start_sample.checked_add(u64::try_from(self.samples.len()).ok()?)?,
            end_ms: start_ms.checked_add(u64::from(self.metadata.duration_ms))?,
        })
    }
}

impl AudioFrame {
    pub fn duration_ms_from_samples(sample_count: usize, sample_rate_hz: u32) -> u32 {
        if sample_rate_hz == 0 {
            return 0;
        }

        ((sample_count as u128) * 1_000 / u128::from(sample_rate_hz)) as u32
    }

    pub fn end_ms(&self) -> u64 {
        self.start_ms.saturating_add(u64::from(self.duration_ms))
    }

    pub(crate) fn checked_end_ms(&self) -> Result<u64, ManifestError> {
        if self.duration_ms == 0 {
            return Err(ManifestError::InvalidFrameTiming);
        }
        self.start_ms
            .checked_add(u64::from(self.duration_ms))
            .ok_or(ManifestError::DurationOverflow)
    }
}
