use crate::server_connector::{
    batch::{validate_vad_intervals, SourceVadInterval},
    LidPreflightCapability,
};

use super::LidPreflightError;

const MAX_SOURCE_SAMPLES: u64 = 16_000 * 4 * 60 * 60;
const STRATIFIED_PROBE_COUNT: usize = 5;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum LidManualReason {
    ShortRecording,
    StratifiedRegionUnavailable,
}

impl LidManualReason {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::ShortRecording => "short_recording",
            Self::StratifiedRegionUnavailable => "stratified_region_unavailable",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum LidProbeSelection {
    Selected {
        source_samples: u64,
        windows: Box<[LidProbeWindow; STRATIFIED_PROBE_COUNT]>,
    },
    Manual {
        source_samples: u64,
        reason: LidManualReason,
    },
}

impl LidProbeSelection {
    pub(crate) fn source_samples(&self) -> u64 {
        match self {
            Self::Selected { source_samples, .. } | Self::Manual { source_samples, .. } => {
                *source_samples
            }
        }
    }

    pub(crate) fn windows(&self) -> Option<&[LidProbeWindow; STRATIFIED_PROBE_COUNT]> {
        match self {
            Self::Selected { windows, .. } => Some(windows),
            Self::Manual { .. } => None,
        }
    }

    pub(crate) fn manual_reason(&self) -> Option<LidManualReason> {
        match self {
            Self::Manual { reason, .. } => Some(*reason),
            Self::Selected { .. } => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct LidProbeWindow {
    index: u16,
    source_start_sample: u64,
    source_end_sample: u64,
    voiced_samples: u64,
    pub(super) vad_intervals: Vec<LidVadInterval>,
}

impl LidProbeWindow {
    pub(crate) fn index(&self) -> u16 {
        self.index
    }

    pub(crate) fn source_start_sample(&self) -> u64 {
        self.source_start_sample
    }

    pub(crate) fn source_end_sample(&self) -> u64 {
        self.source_end_sample
    }

    pub(crate) fn voiced_samples(&self) -> u64 {
        self.voiced_samples
    }

    pub(crate) fn sample_count(&self) -> u64 {
        self.source_end_sample - self.source_start_sample
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct LidVadInterval {
    pub(super) start_sample: u64,
    pub(super) end_sample_exclusive: u64,
}

pub(crate) fn select_lid_probe_windows(
    capability: &LidPreflightCapability,
    source_samples: u64,
    vad_intervals: &[SourceVadInterval],
) -> Result<LidProbeSelection, LidPreflightError> {
    if !(1..=MAX_SOURCE_SAMPLES).contains(&source_samples) {
        return Err(LidPreflightError::invalid(
            "source duration is outside its bound",
        ));
    }
    validate_vad_intervals(vad_intervals, source_samples)
        .map_err(|_| LidPreflightError::invalid("VAD intervals are invalid"))?;
    let policy = &capability.policy;
    if source_samples < policy.minimum_source_samples {
        return Ok(LidProbeSelection::Manual {
            source_samples,
            reason: LidManualReason::ShortRecording,
        });
    }
    let timeline = VadTimeline::new(vad_intervals)?;
    let maximum_start = source_samples - policy.maximum_window_samples;
    let mut selected = Vec::with_capacity(STRATIFIED_PROBE_COUNT);
    for index in 0..STRATIFIED_PROBE_COUNT {
        let start = maximum_start
            .checked_mul(index as u64)
            .and_then(|value| value.checked_add(2))
            .ok_or_else(|| LidPreflightError::invalid("probe position overflowed"))?
            / 4;
        let Some(window) = candidate_window(
            index as u16,
            start,
            source_samples,
            policy.maximum_window_samples,
            policy.minimum_voiced_samples_per_window,
            &timeline,
        ) else {
            return Ok(LidProbeSelection::Manual {
                source_samples,
                reason: LidManualReason::StratifiedRegionUnavailable,
            });
        };
        selected.push(window);
    }
    let windows = selected
        .try_into()
        .map_err(|_| LidPreflightError::invalid("probe count is invalid"))?;
    Ok(LidProbeSelection::Selected {
        source_samples,
        windows: Box::new(windows),
    })
}

struct VadTimeline<'a> {
    intervals: &'a [SourceVadInterval],
    cumulative_voiced: Vec<u64>,
}

impl<'a> VadTimeline<'a> {
    fn new(intervals: &'a [SourceVadInterval]) -> Result<Self, LidPreflightError> {
        let mut cumulative_voiced = Vec::with_capacity(intervals.len() + 1);
        cumulative_voiced.push(0_u64);
        for interval in intervals {
            let length = interval.end_sample_exclusive - interval.start_sample;
            let next = cumulative_voiced
                .last()
                .copied()
                .and_then(|value| value.checked_add(length))
                .ok_or_else(|| LidPreflightError::invalid("VAD duration overflowed"))?;
            cumulative_voiced.push(next);
        }
        Ok(Self {
            intervals,
            cumulative_voiced,
        })
    }

    fn voiced_samples(&self, start: u64, end: u64) -> u64 {
        let first = self
            .intervals
            .partition_point(|interval| interval.end_sample_exclusive <= start);
        let stop = self
            .intervals
            .partition_point(|interval| interval.start_sample < end);
        if first >= stop {
            return 0;
        }
        let mut total = self.cumulative_voiced[stop] - self.cumulative_voiced[first];
        total = total.saturating_sub(start.saturating_sub(self.intervals[first].start_sample));
        total = total.saturating_sub(
            self.intervals[stop - 1]
                .end_sample_exclusive
                .saturating_sub(end),
        );
        total
    }

    fn clipped_intervals(&self, start: u64, end: u64) -> Vec<LidVadInterval> {
        self.intervals
            .iter()
            .filter_map(|interval| {
                let clipped_start = start.max(interval.start_sample);
                let clipped_end = end.min(interval.end_sample_exclusive);
                (clipped_start < clipped_end).then_some(LidVadInterval {
                    start_sample: clipped_start,
                    end_sample_exclusive: clipped_end,
                })
            })
            .collect()
    }
}

fn candidate_window(
    index: u16,
    start: u64,
    source_samples: u64,
    maximum_window_samples: u64,
    minimum_voiced_samples: u64,
    timeline: &VadTimeline<'_>,
) -> Option<LidProbeWindow> {
    if start >= source_samples {
        return None;
    }
    let end = source_samples.min(start.saturating_add(maximum_window_samples));
    let voiced_samples = timeline.voiced_samples(start, end);
    if voiced_samples < minimum_voiced_samples {
        return None;
    }
    Some(LidProbeWindow {
        index,
        source_start_sample: start,
        source_end_sample: end,
        voiced_samples,
        vad_intervals: timeline.clipped_intervals(start, end),
    })
}
