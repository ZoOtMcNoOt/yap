//! Exact fixed-window feature extraction for NVIDIA AmberNet 1.12.0.
//!
//! The classifier was exported behind NeMo's preprocessor seam. These constants
//! and operations therefore form part of the locked model contract rather than
//! a tunable audio effect.

use std::sync::Arc;

use realfft::{num_complex::Complex32, FftError, RealFftPlanner, RealToComplex};

pub(super) const SAMPLE_RATE_HZ: usize = 16_000;
pub(super) const WINDOW_SAMPLES: usize = SAMPLE_RATE_HZ * 3;
pub(super) const MEL_BINS: usize = 80;
pub(super) const PADDED_FRAMES: usize = 304;

const FFT_SIZE: usize = 512;
const WINDOW_LENGTH: usize = 400;
const HOP_LENGTH: usize = 160;
const VALID_FRAMES: usize = 300;
const STFT_FRAMES: usize = 301;
const PREEMPHASIS: f32 = 0.97;
const LOG_GUARD: f32 = 5.960_464_5e-8;
const STANDARD_DEVIATION_GUARD: f32 = 1.0e-5;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum FeatureExtractionError {
    InvalidWindow,
    FftFailed,
}

impl std::fmt::Display for FeatureExtractionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::InvalidWindow => "AmberNet requires one finite three-second 16 kHz window",
            Self::FftFailed => "AmberNet feature extraction failed",
        })
    }
}

impl std::error::Error for FeatureExtractionError {}

impl From<FftError> for FeatureExtractionError {
    fn from(_: FftError) -> Self {
        Self::FftFailed
    }
}

pub(super) struct AmberNetFeatureExtractor {
    fft: Arc<dyn RealToComplex<f32>>,
    hann_window: Vec<f32>,
    mel_filterbank: Vec<f32>,
    emphasized: Vec<f32>,
    centered: Vec<f32>,
    fft_input: Vec<f32>,
    fft_output: Vec<Complex32>,
    power: Vec<f32>,
    logged_mel: Vec<f32>,
    output: Vec<f32>,
}

impl AmberNetFeatureExtractor {
    pub(super) fn new() -> Self {
        let mut hann_window = vec![0.0_f32; FFT_SIZE];
        let offset = (FFT_SIZE - WINDOW_LENGTH) / 2;
        for index in 0..WINDOW_LENGTH {
            let angle = 2.0 * std::f32::consts::PI * index as f32 / (WINDOW_LENGTH - 1) as f32;
            hann_window[offset + index] = 0.5 - 0.5 * angle.cos();
        }

        let mut planner = RealFftPlanner::<f32>::new();
        let fft = planner.plan_fft_forward(FFT_SIZE);
        let fft_input = fft.make_input_vec();
        let fft_output = fft.make_output_vec();
        Self {
            fft,
            hann_window,
            mel_filterbank: slaney_mel_filterbank(),
            emphasized: vec![0.0; WINDOW_SAMPLES],
            centered: vec![0.0; WINDOW_SAMPLES + FFT_SIZE],
            fft_input,
            fft_output,
            power: vec![0.0; STFT_FRAMES * (FFT_SIZE / 2 + 1)],
            logged_mel: vec![0.0; MEL_BINS * STFT_FRAMES],
            output: vec![0.0; MEL_BINS * PADDED_FRAMES],
        }
    }

    pub(super) fn process(&mut self, signal: &[f32]) -> Result<&[f32], FeatureExtractionError> {
        if signal.len() != WINDOW_SAMPLES
            || signal
                .iter()
                .any(|sample| !sample.is_finite() || sample.abs() > 2.0)
        {
            return Err(FeatureExtractionError::InvalidWindow);
        }

        self.emphasized[0] = signal[0];
        for index in 1..signal.len() {
            self.emphasized[index] = signal[index] - PREEMPHASIS * signal[index - 1];
        }
        self.centered.fill(0.0);
        self.centered[FFT_SIZE / 2..FFT_SIZE / 2 + signal.len()].copy_from_slice(&self.emphasized);

        let frequency_bins = FFT_SIZE / 2 + 1;
        for frame in 0..STFT_FRAMES {
            let start = frame * HOP_LENGTH;
            for sample in 0..FFT_SIZE {
                self.fft_input[sample] = self.centered[start + sample] * self.hann_window[sample];
            }
            self.fft
                .process(&mut self.fft_input, &mut self.fft_output)?;
            for (bin, value) in self.fft_output.iter().enumerate() {
                self.power[frame * frequency_bins + bin] =
                    value.re.mul_add(value.re, value.im * value.im);
            }
        }

        for mel in 0..MEL_BINS {
            for frame in 0..STFT_FRAMES {
                let mut energy = 0.0_f32;
                for bin in 0..frequency_bins {
                    energy += self.mel_filterbank[mel * frequency_bins + bin]
                        * self.power[frame * frequency_bins + bin];
                }
                self.logged_mel[mel * STFT_FRAMES + frame] = (energy + LOG_GUARD).ln();
            }
        }

        self.output.fill(0.0);
        for mel in 0..MEL_BINS {
            let valid = &self.logged_mel[mel * STFT_FRAMES..mel * STFT_FRAMES + VALID_FRAMES];
            let mean = valid.iter().copied().sum::<f32>() / VALID_FRAMES as f32;
            let variance = valid
                .iter()
                .map(|value| {
                    let centered = value - mean;
                    centered * centered
                })
                .sum::<f32>()
                / (VALID_FRAMES - 1) as f32;
            let standard_deviation = variance.sqrt() + STANDARD_DEVIATION_GUARD;
            for (frame, value) in valid.iter().copied().enumerate() {
                self.output[mel * PADDED_FRAMES + frame] = (value - mean) / standard_deviation;
            }
        }
        Ok(&self.output)
    }
}

fn slaney_mel_filterbank() -> Vec<f32> {
    let mel_min = hertz_to_mel(0.0);
    let mel_max = hertz_to_mel(SAMPLE_RATE_HZ as f64 / 2.0);
    let mel_frequencies = (0..MEL_BINS + 2)
        .map(|index| {
            let fraction = index as f64 / (MEL_BINS + 1) as f64;
            mel_to_hertz(mel_min + fraction * (mel_max - mel_min))
        })
        .collect::<Vec<_>>();
    let fft_frequencies = (0..=FFT_SIZE / 2)
        .map(|bin| bin as f64 * SAMPLE_RATE_HZ as f64 / FFT_SIZE as f64)
        .collect::<Vec<_>>();
    let frequency_bins = FFT_SIZE / 2 + 1;
    let mut weights = vec![0.0_f32; MEL_BINS * frequency_bins];
    for mel in 0..MEL_BINS {
        let lower_width = mel_frequencies[mel + 1] - mel_frequencies[mel];
        let upper_width = mel_frequencies[mel + 2] - mel_frequencies[mel + 1];
        let normalization = 2.0 / (mel_frequencies[mel + 2] - mel_frequencies[mel]);
        for (bin, &frequency) in fft_frequencies.iter().enumerate() {
            let lower = (frequency - mel_frequencies[mel]) / lower_width;
            let upper = (mel_frequencies[mel + 2] - frequency) / upper_width;
            weights[mel * frequency_bins + bin] =
                (normalization * lower.min(upper).max(0.0)) as f32;
        }
    }
    weights
}

fn hertz_to_mel(frequency: f64) -> f64 {
    let linear_scale = 200.0 / 3.0;
    if frequency >= 1_000.0 {
        15.0 + (frequency / 1_000.0).ln() / (6.4_f64.ln() / 27.0)
    } else {
        frequency / linear_scale
    }
}

fn mel_to_hertz(mel: f64) -> f64 {
    let linear_scale = 200.0 / 3.0;
    if mel >= 15.0 {
        1_000.0 * ((6.4_f64.ln() / 27.0) * (mel - 15.0)).exp()
    } else {
        linear_scale * mel
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fixed_frontend_rejects_wrong_or_non_finite_windows() {
        let mut frontend = AmberNetFeatureExtractor::new();
        assert_eq!(
            frontend.process(&vec![0.0; WINDOW_SAMPLES - 1]),
            Err(FeatureExtractionError::InvalidWindow)
        );
        let mut non_finite = vec![0.0; WINDOW_SAMPLES];
        non_finite[17] = f32::NAN;
        assert_eq!(
            frontend.process(&non_finite),
            Err(FeatureExtractionError::InvalidWindow)
        );
    }

    #[test]
    fn fixed_frontend_returns_finite_normalized_padded_features() {
        let mut frontend = AmberNetFeatureExtractor::new();
        let signal = (0..WINDOW_SAMPLES)
            .map(|index| {
                let phase =
                    index as f32 * 2.0 * std::f32::consts::PI * 440.0 / SAMPLE_RATE_HZ as f32;
                phase.sin() * 0.1
            })
            .collect::<Vec<_>>();

        let features = frontend.process(&signal).unwrap();

        assert_eq!(features.len(), MEL_BINS * PADDED_FRAMES);
        assert!(features.iter().all(|value| value.is_finite()));
        for mel in 0..MEL_BINS {
            assert_eq!(
                &features[mel * PADDED_FRAMES + VALID_FRAMES..mel * PADDED_FRAMES + PADDED_FRAMES],
                &[0.0; PADDED_FRAMES - VALID_FRAMES]
            );
        }
    }

    #[test]
    fn fixed_frontend_matches_independent_nemo_verified_synthetic_golden() {
        // This integer waveform contains no source audio. The expected values
        // were produced by an independent NumPy reconstruction that was first
        // checked against NeMo 2.7.3's emitted frontend tensor.
        let signal = (0..WINDOW_SAMPLES)
            .map(|index| (((index as i64 * 37) % 257) - 128) as f32 / 16_384.0)
            .collect::<Vec<_>>();
        let mut frontend = AmberNetFeatureExtractor::new();
        let features = frontend.process(&signal).unwrap();

        let expected_points = [
            (0, 15.338_389_f32),
            (1, -0.169_457_85),
            (37, 0.214_556_26),
            (299, 2.058_683_9),
            (304, 3.522_122_6),
            (1_216, -3.540_054_3),
            (9_728, 1.195_339_2),
            (24_000, -0.231_142_03),
            (24_315, -0.188_641_8),
        ];
        for (index, expected) in expected_points {
            assert!(
                (features[index] - expected).abs() <= 5.0e-4,
                "frontend golden diverged at {index}: actual={} expected={expected}",
                features[index]
            );
        }

        let expected_buckets = [
            (1009.2630_f64, -213.1222_f64),
            (1130.6772, 74.2757),
            (1331.9121, -1.1978),
            (1342.4864, -9.9746),
            (1334.8470, -2.8110),
            (1340.4138, -26.7318),
            (1258.2326, -104.0404),
            (1334.3925, -32.1692),
            (989.9510, -79.4217),
            (631.9591, -53.8054),
            (754.9135, 141.5336),
            (314.1071, 187.0682),
            (536.1103, 171.1817),
            (441.3966, 169.5389),
            (317.5011, 192.8200),
            (402.2564, 186.7663),
        ];
        assert_eq!(features.len() % expected_buckets.len(), 0);
        let bucket_size = features.len() / expected_buckets.len();
        for (bucket, ((expected_l1, expected_weighted), values)) in expected_buckets
            .into_iter()
            .zip(features.chunks_exact(bucket_size))
            .enumerate()
        {
            let l1 = values.iter().map(|value| value.abs() as f64).sum::<f64>();
            let weighted = values
                .iter()
                .enumerate()
                .map(|(index, value)| {
                    let weight = (index % 31) as i32 - 15;
                    (*value * weight as f32) as f64
                })
                .sum::<f64>();
            assert!(
                (l1 - expected_l1).abs() <= 0.05,
                "frontend L1 golden diverged in bucket {bucket}: actual={l1} expected={expected_l1}"
            );
            assert!(
                (weighted - expected_weighted).abs() <= 0.05,
                "frontend weighted golden diverged in bucket {bucket}: actual={weighted} expected={expected_weighted}"
            );
        }
    }
}
