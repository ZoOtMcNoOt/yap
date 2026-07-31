pub fn downmix_to_mono(samples: &[f32], channels: usize) -> Vec<f32> {
    if channels == 0 {
        return Vec::new();
    }
    samples
        .chunks_exact(channels)
        .map(|frame| frame.iter().sum::<f32>() / channels as f32)
        .collect()
}

pub fn f32_to_i16_le_bytes(samples: &[f32]) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(samples.len() * 2);
    for sample in samples {
        let value = if *sample <= -1.0 {
            i16::MIN
        } else if *sample >= 1.0 {
            i16::MAX
        } else {
            (*sample * i16::MAX as f32).round() as i16
        };
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes
}

pub fn rms_level(samples: &[f32]) -> f32 {
    if samples.is_empty() {
        return 0.0;
    }
    let sum = samples.iter().map(|sample| sample * sample).sum::<f32>();
    (sum / samples.len() as f32).sqrt().clamp(0.0, 1.0)
}

// Ported from zachlatta/freeflow's LiveAudioLevelNormalizer (MIT).
pub struct AudioLevelNormalizer {
    noise_floor_db: f32,
    peak_ceiling_db: f32,
    display_level: f32,
}

impl AudioLevelNormalizer {
    const MINIMUM_RMS: f32 = 0.00001;
    const MIN_SPAN_DB: f32 = 18.0;
    const PEAK_HEADROOM_DB: f32 = 8.0;
    const SPEECH_GATE_MARGIN_DB: f32 = 3.0;
    const MINIMUM_VISIBLE_ACTIVE_LEVEL: f32 = 0.12;
    const NOISE_GATE_NORMALIZED_THRESHOLD: f32 = 0.06;
    const FLOOR_RISE_WINDOW_DB: f32 = 4.0;
    const FLOOR_FALL_BLEND: f32 = 0.12;
    const FLOOR_RISE_BLEND: f32 = 0.02;
    const PEAK_ATTACK_BLEND: f32 = 0.55;
    const PEAK_RELEASE_BLEND: f32 = 0.04;
    const DISPLAY_ATTACK_BLEND: f32 = 0.45;
    const DISPLAY_RELEASE_BLEND: f32 = 0.12;

    pub fn new() -> Self {
        Self {
            noise_floor_db: -55.0,
            peak_ceiling_db: -37.0,
            display_level: 0.0,
        }
    }

    pub fn normalized_level(&mut self, rms: f32) -> f32 {
        let level_db = 20.0 * rms.max(Self::MINIMUM_RMS).log10();

        self.update_noise_floor(level_db);
        self.update_peak_ceiling(level_db);

        let display_ceiling_db = self.peak_ceiling_db + Self::PEAK_HEADROOM_DB;
        let dynamic_span = (display_ceiling_db - self.noise_floor_db)
            .max(Self::MIN_SPAN_DB + Self::PEAK_HEADROOM_DB);
        let mut normalized = ((level_db - self.noise_floor_db) / dynamic_span).clamp(0.0, 1.0);
        let is_active_speech = level_db >= self.noise_floor_db + Self::SPEECH_GATE_MARGIN_DB;

        if normalized < Self::NOISE_GATE_NORMALIZED_THRESHOLD
            && level_db <= self.noise_floor_db + Self::SPEECH_GATE_MARGIN_DB
        {
            normalized = 0.0;
        } else if is_active_speech {
            normalized = normalized.max(Self::MINIMUM_VISIBLE_ACTIVE_LEVEL);
        }

        let blend = if normalized > self.display_level {
            Self::DISPLAY_ATTACK_BLEND
        } else {
            Self::DISPLAY_RELEASE_BLEND
        };
        self.display_level = mix(self.display_level, normalized, blend);
        self.display_level
    }

    fn update_noise_floor(&mut self, level_db: f32) {
        let ceiling_limited_level = level_db.min(self.peak_ceiling_db - Self::MIN_SPAN_DB);

        if ceiling_limited_level <= self.noise_floor_db {
            self.noise_floor_db = mix(
                self.noise_floor_db,
                ceiling_limited_level,
                Self::FLOOR_FALL_BLEND,
            );
        } else if ceiling_limited_level <= self.noise_floor_db + Self::FLOOR_RISE_WINDOW_DB {
            self.noise_floor_db = mix(
                self.noise_floor_db,
                ceiling_limited_level,
                Self::FLOOR_RISE_BLEND,
            );
        }
    }

    fn update_peak_ceiling(&mut self, level_db: f32) {
        let minimum_ceiling = self.noise_floor_db + Self::MIN_SPAN_DB;

        if level_db >= self.peak_ceiling_db {
            self.peak_ceiling_db = mix(self.peak_ceiling_db, level_db, Self::PEAK_ATTACK_BLEND);
        } else {
            self.peak_ceiling_db = mix(
                self.peak_ceiling_db,
                level_db.max(minimum_ceiling),
                Self::PEAK_RELEASE_BLEND,
            );
        }

        self.peak_ceiling_db = self.peak_ceiling_db.max(minimum_ceiling);
    }
}

impl Default for AudioLevelNormalizer {
    fn default() -> Self {
        Self::new()
    }
}

fn mix(current: f32, target: f32, blend: f32) -> f32 {
    current + (target - current) * blend
}

/// Windowed-sinc lowpass applied at the source rate before decimation. Picking
/// every Nth sample folds everything above the output Nyquist back onto the
/// speech band, and at the common 48 kHz capture rate the interpolation
/// fraction below is always exactly zero, so decimation is otherwise unfiltered.
struct DecimationLowpass {
    taps: Vec<f32>,
    history: Vec<f32>,
    position: usize,
}

impl DecimationLowpass {
    const TAPS: usize = 127;
    /// Passband edge as a fraction of the output Nyquist. Leaves room for the
    /// window's transition band to reach the stopband before the fold point.
    const PASSBAND_RATIO: f64 = 0.85;

    fn design(source_rate: u32, target_rate: u32) -> Option<Self> {
        if source_rate <= target_rate {
            return None;
        }
        let cutoff = (target_rate as f64 / 2.0) * Self::PASSBAND_RATIO / source_rate as f64;
        let center = (Self::TAPS - 1) as f64 / 2.0;
        let mut taps = Vec::with_capacity(Self::TAPS);
        let mut gain = 0.0;
        for index in 0..Self::TAPS {
            let offset = index as f64 - center;
            let sinc = if offset == 0.0 {
                2.0 * cutoff
            } else {
                (std::f64::consts::TAU * cutoff * offset).sin() / (std::f64::consts::PI * offset)
            };
            let window = 0.54
                - 0.46 * (std::f64::consts::TAU * index as f64 / (Self::TAPS - 1) as f64).cos();
            let value = sinc * window;
            gain += value;
            taps.push(value);
        }
        Some(Self {
            taps: taps.into_iter().map(|tap| (tap / gain) as f32).collect(),
            history: vec![0.0; Self::TAPS],
            position: 0,
        })
    }

    fn filter(&mut self, input: &[f32]) -> Vec<f32> {
        let span = self.history.len();
        let mut output = Vec::with_capacity(input.len());
        for sample in input {
            self.history[self.position] = *sample;
            self.position = (self.position + 1) % span;
            let mut sum = 0.0;
            for (offset, tap) in self.taps.iter().enumerate() {
                sum += self.history[(self.position + offset) % span] * tap;
            }
            output.push(sum);
        }
        output
    }
}

pub struct LinearResampler {
    lowpass: Option<DecimationLowpass>,
    buffered: Vec<f32>,
    source_rate: u32,
    target_rate: u32,
    cursor: f64,
}

impl LinearResampler {
    pub fn new(source_rate: u32, target_rate: u32) -> Self {
        let source_rate = source_rate.max(1);
        let target_rate = target_rate.max(1);
        Self {
            lowpass: DecimationLowpass::design(source_rate, target_rate),
            buffered: Vec::new(),
            source_rate,
            target_rate,
            cursor: 0.0,
        }
    }

    pub fn push(&mut self, input: &[f32]) -> Vec<f32> {
        if input.is_empty() {
            return Vec::new();
        }
        if self.source_rate == self.target_rate {
            return input.to_vec();
        }
        match self.lowpass.as_mut() {
            Some(lowpass) => self.buffered.extend_from_slice(&lowpass.filter(input)),
            None => self.buffered.extend_from_slice(input),
        }
        let step = self.source_rate as f64 / self.target_rate as f64;
        let mut output = Vec::new();
        while self.cursor < self.buffered.len() as f64 {
            let base = self.cursor.floor() as usize;
            let frac = (self.cursor - base as f64) as f32;
            if frac != 0.0 && base + 1 >= self.buffered.len() {
                break;
            }
            let a = self.buffered[base];
            let b = self.buffered.get(base + 1).copied().unwrap_or(a);
            output.push(a + (b - a) * frac);
            self.cursor += step;
        }
        let drop_count = (self.cursor.floor() as usize).min(self.buffered.len().saturating_sub(1));
        if drop_count > 0 {
            self.buffered.drain(..drop_count);
            self.cursor -= drop_count as f64;
        }
        output
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preprocess_pipeline_flows_through_shared_module_path() {
        let downmixed = crate::audio::preprocess::downmix_to_mono(&[1.0, 0.0, 0.0, 1.0], 2);
        let mut resampler = crate::audio::preprocess::LinearResampler::new(2, 1);
        let resampled = resampler.push(&downmixed);
        let pcm = crate::audio::preprocess::f32_to_i16_le_bytes(&resampled);

        assert_eq!(downmixed, vec![0.5, 0.5]);
        assert_eq!(resampled.len(), 1);
        assert_eq!(pcm.len(), 2);
    }

    #[test]
    fn mono_downmix_averages_channels() {
        assert_eq!(downmix_to_mono(&[1.0, 3.0, 2.0, 4.0], 2), vec![2.0, 3.0]);
    }

    #[test]
    fn pcm_conversion_clamps_to_i16() {
        assert_eq!(
            f32_to_i16_le_bytes(&[-2.0, 0.0, 2.0]),
            vec![0, 128, 0, 0, 255, 127]
        );
    }

    fn tone(rate: u32, hz: f64, samples: usize) -> Vec<f32> {
        (0..samples)
            .map(|index| (std::f64::consts::TAU * hz * index as f64 / rate as f64).sin() as f32)
            .collect()
    }

    fn peak(samples: &[f32]) -> f32 {
        samples.iter().fold(0.0f32, |peak, s| peak.max(s.abs()))
    }

    /// Decimation without a lowpass folds everything above the output Nyquist
    /// back onto the speech band. Capture is commonly 48 kHz, so this is the
    /// production path, not an edge case.
    #[test]
    fn downsampling_rejects_content_above_the_output_nyquist() {
        let source = tone(48_000, 12_000.0, 48_000);

        let mut resampler = LinearResampler::new(48_000, 16_000);
        let resampled = resampler.push(&source);

        let settled = &resampled[resampled.len() / 2..];
        assert!(
            peak(settled) < 0.02,
            "12 kHz survived decimation at {:.4}, aliasing onto 4 kHz",
            peak(settled)
        );
    }

    #[test]
    fn downsampling_preserves_speech_band_content() {
        let source = tone(48_000, 400.0, 48_000);

        let mut resampler = LinearResampler::new(48_000, 16_000);
        let resampled = resampler.push(&source);

        let settled = &resampled[resampled.len() / 2..];
        assert!(
            peak(settled) > 0.95,
            "400 Hz was attenuated to {:.4}",
            peak(settled)
        );
    }

    #[test]
    fn linear_resample_can_downsample() {
        let mut resampler = LinearResampler::new(4, 2);
        assert_eq!(resampler.push(&[0.0, 1.0, 0.0, -1.0]).len(), 2);
    }

    #[test]
    fn linear_resample_matches_split_callbacks() {
        let mut one_chunk = LinearResampler::new(2, 4);
        let expected = one_chunk.push(&[0.0, 1.0, 0.0]);

        let mut split = LinearResampler::new(2, 4);
        let mut actual = split.push(&[0.0, 1.0]);
        actual.extend(split.push(&[0.0]));

        assert_eq!(actual, expected);
    }

    #[test]
    fn live_level_normalizer_lifts_speech_without_lifting_floor() {
        let mut normalizer = AudioLevelNormalizer::new();

        for _ in 0..12 {
            assert_eq!(normalizer.normalized_level(0.00001), 0.0);
        }

        let speech = normalizer.normalized_level(0.02);

        assert!(speech >= AudioLevelNormalizer::MINIMUM_VISIBLE_ACTIVE_LEVEL);
        assert!(speech <= 1.0);
    }
}
