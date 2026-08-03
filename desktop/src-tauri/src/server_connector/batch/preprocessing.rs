use serde::{Deserialize, Serialize};

mod stage_projection;

use super::validation::valid_sha256;

// 2 adds normalization.decodedFrom, which records that the admitted canonical
// source was produced by decoding a compressed import rather than copied from
// an already-canonical file.
pub(crate) const PREPROCESSING_EVIDENCE_SCHEMA_VERSION: u16 = 2;
const SAMPLE_RATE_HZ: u64 = 16_000;
const SAMPLES_PER_MILLISECOND: u64 = SAMPLE_RATE_HZ / 1_000;
const MAX_SOURCE_SAMPLES: u64 = SAMPLE_RATE_HZ * 4 * 60 * 60;
pub(crate) const MAX_VAD_INTERVALS: usize = 4_096;
const MAX_PREPROCESSING_EVIDENCE_BYTES: usize = 512 * 1_024;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct SourceVadInterval {
    pub(crate) start_sample: u64,
    pub(crate) end_sample_exclusive: u64,
    pub(crate) start_ms: u64,
    pub(crate) end_ms: u64,
}

impl SourceVadInterval {
    pub(crate) fn from_samples(
        start_sample: u64,
        end_sample_exclusive: u64,
    ) -> Result<Self, &'static str> {
        if start_sample >= end_sample_exclusive {
            return Err("invalid_interval");
        }
        let start_ms = start_sample / SAMPLES_PER_MILLISECOND;
        let end_ms = end_sample_exclusive
            .checked_add(SAMPLES_PER_MILLISECOND - 1)
            .ok_or("invalid_interval")?
            / SAMPLES_PER_MILLISECOND;
        Ok(Self {
            start_sample,
            end_sample_exclusive,
            start_ms,
            end_ms,
        })
    }

    #[cfg(test)]
    pub(crate) fn for_test(start_sample: u64, end_sample_exclusive: u64) -> Self {
        Self::from_samples(start_sample, end_sample_exclusive)
            .expect("test VAD interval must be valid")
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct VadComponentEvidence {
    id: String,
    revision: String,
    model_id: String,
    model_revision: String,
    artifact_sha256: String,
}

impl VadComponentEvidence {
    pub(crate) fn pinned_silero() -> Self {
        Self {
            id: "sherpa-onnx-silero-vad".into(),
            revision: "sherpa-onnx-1.13.4".into(),
            model_id: "k2-fsa/silero_vad.onnx".into(),
            model_revision: "github-release-asset-271935959".into(),
            artifact_sha256: "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"
                .into(),
        }
    }

    #[cfg(test)]
    pub(crate) fn for_test(id: &str, revision: &str) -> Self {
        Self {
            id: id.into(),
            revision: revision.into(),
            model_id: "test-model".into(),
            model_revision: "test-model-revision".into(),
            artifact_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                .into(),
        }
    }

    fn is_valid(&self) -> bool {
        valid_component_text(&self.id, 128)
            && valid_component_text(&self.revision, 128)
            && valid_component_text(&self.model_id, 256)
            && valid_component_text(&self.model_revision, 256)
            && valid_sha256(&self.artifact_sha256)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct DecodedSourceEvidence {
    codec: String,
    sample_rate_hz: u32,
    channels: u16,
    frame_count: u64,
}

impl DecodedSourceEvidence {
    pub(crate) fn new(
        codec: String,
        sample_rate_hz: u32,
        channels: u16,
        frame_count: u64,
    ) -> Result<Self, &'static str> {
        if codec.is_empty() || codec.len() > 64 {
            return Err("invalid_decoded_codec");
        }
        if !(8_000..=384_000).contains(&sample_rate_hz) {
            return Err("invalid_decoded_sample_rate");
        }
        if !(1..=8).contains(&channels) {
            return Err("invalid_decoded_channels");
        }
        if frame_count == 0 {
            return Err("invalid_decoded_frame_count");
        }
        Ok(Self {
            codec,
            sample_rate_hz,
            channels,
            frame_count,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct NormalizationEvidence {
    status: String,
    component_id: String,
    component_revision: String,
    method: String,
    input_source_sha256: String,
    source_pcm_sha256: String,
    output_pcm_sha256: String,
    audio_codec: String,
    sample_rate_hz: u32,
    channels: u16,
    source_sample_count: u64,
    output_sample_count: u64,
    padding_samples: u16,
    gain_applied_milli_db: i32,
    samples_modified: u64,
    source_time_preserved: bool,
    /// Present only when the admitted canonical source was decoded from a
    /// compressed import. Absent means the source was already canonical, so its
    /// absence is itself a claim and must stay accurate.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    decoded_from: Option<DecodedSourceEvidence>,
}

impl NormalizationEvidence {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn canonical_pcm16_identity(
        input_source_sha256: String,
        source_pcm_sha256: String,
        output_pcm_sha256: String,
        source_sample_count: u64,
        output_sample_count: u64,
        padding_samples: u16,
    ) -> Self {
        Self {
            status: "complete".into(),
            component_id: "yap-imported-audio-normalizer".into(),
            component_revision: "canonical-pcm16-normalization-v1".into(),
            method: "canonical_pcm16_identity".into(),
            input_source_sha256,
            source_pcm_sha256,
            output_pcm_sha256,
            audio_codec: "pcm_s16le".into(),
            sample_rate_hz: SAMPLE_RATE_HZ as u32,
            channels: 1,
            source_sample_count,
            output_sample_count,
            padding_samples,
            gain_applied_milli_db: 0,
            samples_modified: 0,
            source_time_preserved: true,
            decoded_from: None,
        }
    }

    /// The admitted source here was decoded from a compressed import, so the
    /// normalization from it is still an identity copy: what the decode changed
    /// is recorded in `decoded_from` rather than hidden behind an unqualified
    /// identity claim.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn decoded_to_canonical_pcm16(
        input_source_sha256: String,
        source_pcm_sha256: String,
        output_pcm_sha256: String,
        source_sample_count: u64,
        output_sample_count: u64,
        padding_samples: u16,
        decoded_from: DecodedSourceEvidence,
    ) -> Self {
        Self {
            component_revision: "decoded-canonical-pcm16-normalization-v1".into(),
            method: "decoded_to_canonical_pcm16".into(),
            decoded_from: Some(decoded_from),
            ..Self::canonical_pcm16_identity(
                input_source_sha256,
                source_pcm_sha256,
                output_pcm_sha256,
                source_sample_count,
                output_sample_count,
                padding_samples,
            )
        }
    }

    /// Each method owns exactly one component revision, so a record cannot
    /// claim one provenance while carrying the other's revision.
    fn method_matches_revision(&self) -> bool {
        match self.method.as_str() {
            "canonical_pcm16_identity" => {
                self.component_revision == "canonical-pcm16-normalization-v1"
            }
            "decoded_to_canonical_pcm16" => {
                self.component_revision == "decoded-canonical-pcm16-normalization-v1"
            }
            _ => false,
        }
    }

    /// The decoded method must carry its source facts, and the identity method
    /// must not, so absence stays a meaningful claim in both directions.
    fn decoded_from_matches_method(&self) -> bool {
        match (self.method.as_str(), self.decoded_from.as_ref()) {
            ("decoded_to_canonical_pcm16", Some(decoded)) => DecodedSourceEvidence::new(
                decoded.codec.clone(),
                decoded.sample_rate_hz,
                decoded.channels,
                decoded.frame_count,
            )
            .is_ok(),
            ("canonical_pcm16_identity", None) => true,
            _ => false,
        }
    }

    fn is_valid(&self, output_sample_count: u64) -> bool {
        self.status == "complete"
            && self.component_id == "yap-imported-audio-normalizer"
            && self.method_matches_revision()
            && self.decoded_from_matches_method()
            && valid_sha256(&self.input_source_sha256)
            && valid_sha256(&self.source_pcm_sha256)
            && valid_sha256(&self.output_pcm_sha256)
            && self.audio_codec == "pcm_s16le"
            && self.sample_rate_hz == SAMPLE_RATE_HZ as u32
            && self.channels == 1
            && (1..=MAX_SOURCE_SAMPLES).contains(&self.source_sample_count)
            && self.output_sample_count == output_sample_count
            && self.output_sample_count <= MAX_SOURCE_SAMPLES
            && self.padding_samples < SAMPLES_PER_MILLISECOND as u16
            && self
                .source_sample_count
                .checked_add(u64::from(self.padding_samples))
                == Some(self.output_sample_count)
            && self.gain_applied_milli_db == 0
            && self.samples_modified == 0
            && self.source_time_preserved
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct VadEvidence {
    status: String,
    component: VadComponentEvidence,
    source_sample_count: u64,
    intervals: Vec<SourceVadInterval>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error_code: Option<String>,
}

impl VadEvidence {
    pub(crate) fn complete(
        component: VadComponentEvidence,
        source_sample_count: u64,
        intervals: Vec<SourceVadInterval>,
    ) -> Self {
        Self {
            status: "complete".into(),
            component,
            source_sample_count,
            intervals,
            error_code: None,
        }
    }

    pub(crate) fn error(
        component: VadComponentEvidence,
        source_sample_count: u64,
        error_code: &'static str,
    ) -> Self {
        Self {
            status: "error".into(),
            component,
            source_sample_count,
            intervals: Vec::new(),
            error_code: Some(error_code.into()),
        }
    }

    fn replace_with_error(&mut self, error_code: &'static str) {
        self.status = "error".into();
        self.intervals.clear();
        self.error_code = Some(error_code.into());
    }

    fn is_valid(&self, source_sample_count: u64) -> bool {
        if !self.component.is_valid()
            || self.source_sample_count != source_sample_count
            || self.intervals.len() > MAX_VAD_INTERVALS
        {
            return false;
        }
        match self.status.as_str() {
            "complete" if self.error_code.is_none() => {}
            "error"
                if self.intervals.is_empty()
                    && self.error_code.as_deref().is_some_and(valid_error_code) => {}
            _ => return false,
        }
        validate_intervals(&self.intervals, source_sample_count).is_ok()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct PreprocessingEvidence {
    schema_version: u16,
    normalization: NormalizationEvidence,
    vad: VadEvidence,
}

impl PreprocessingEvidence {
    pub(crate) fn new(normalization: NormalizationEvidence, vad: VadEvidence) -> Self {
        Self {
            schema_version: PREPROCESSING_EVIDENCE_SCHEMA_VERSION,
            normalization,
            vad,
        }
    }

    pub(crate) fn discard_vad_intervals(&mut self, error_code: &'static str) {
        self.vad.replace_with_error(error_code);
    }

    pub(crate) fn is_valid_for_output_samples(&self, output_sample_count: u64) -> bool {
        self.schema_version == PREPROCESSING_EVIDENCE_SCHEMA_VERSION
            && self.normalization.is_valid(output_sample_count)
            && self.vad.is_valid(self.normalization.source_sample_count)
            && serde_json::to_vec(self)
                .is_ok_and(|encoded| encoded.len() <= MAX_PREPROCESSING_EVIDENCE_BYTES)
    }
}

pub(crate) fn validate_vad_intervals(
    intervals: &[SourceVadInterval],
    source_sample_count: u64,
) -> Result<(), &'static str> {
    validate_intervals(intervals, source_sample_count)
}

fn validate_intervals(
    intervals: &[SourceVadInterval],
    source_sample_count: u64,
) -> Result<(), &'static str> {
    if intervals.len() > MAX_VAD_INTERVALS {
        return Err("segment_limit_exceeded");
    }
    let mut previous_end = 0_u64;
    for interval in intervals {
        let expected =
            SourceVadInterval::from_samples(interval.start_sample, interval.end_sample_exclusive)?;
        if *interval != expected
            || interval.end_sample_exclusive > source_sample_count
            || interval.start_sample < previous_end
        {
            return Err("invalid_interval");
        }
        previous_end = interval.end_sample_exclusive;
    }
    Ok(())
}

fn valid_component_text(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'/' | b':')
        })
}

fn valid_error_code(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}
