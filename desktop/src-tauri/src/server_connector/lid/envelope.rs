use std::{collections::BTreeSet, time::Duration};

use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::server_connector::{
    capabilities::AsrExecutionMode, AsrCapabilityCatalog, LidPreflightCapability,
};

use super::{
    response::{decode_lid_response, ExpectedLidResponse, ExpectedObservation},
    LidPreflightError, LidPreflightResult, LidProbeSelection,
};

const MAX_SOURCE_SAMPLES: u64 = 16_000 * 4 * 60 * 60;
const RESPONSE_TIMEOUT_GRACE_SECONDS: u64 = 5;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct LidPreflightSourceIdentity {
    request_id: String,
    source_samples: u64,
    source_pcm_sha256: String,
}

impl LidPreflightSourceIdentity {
    pub(crate) fn try_new(
        request_id: String,
        source_samples: u64,
        source_pcm_sha256: String,
    ) -> Result<Self, LidPreflightError> {
        if !valid_request_id(&request_id) {
            return Err(LidPreflightError::invalid("request ID is invalid"));
        }
        if !(1..=MAX_SOURCE_SAMPLES).contains(&source_samples) {
            return Err(LidPreflightError::invalid(
                "source duration is outside its bound",
            ));
        }
        if !valid_sha256(&source_pcm_sha256) {
            return Err(LidPreflightError::invalid("source PCM digest is invalid"));
        }
        Ok(Self {
            request_id,
            source_samples,
            source_pcm_sha256,
        })
    }
}

pub(crate) struct LidPreflightRequest {
    body: Vec<u8>,
    media_type: String,
    timeout: Duration,
    expected: ExpectedLidResponse,
}

impl LidPreflightRequest {
    pub(crate) fn from_selected_probes(
        catalog: &AsrCapabilityCatalog,
        source: LidPreflightSourceIdentity,
        selection: &LidProbeSelection,
        pcm_probes: [Vec<u8>; 2],
    ) -> Result<Self, LidPreflightError> {
        let capability = catalog.lid_preflight().ok_or_else(|| {
            LidPreflightError::invalid("server did not advertise language preflight")
        })?;
        let Some(windows) = selection.windows() else {
            return Err(LidPreflightError::invalid(
                "manual selection cannot be dispatched",
            ));
        };
        if selection.source_samples() != source.source_samples
            || source.source_samples < capability.policy.minimum_source_samples
        {
            return Err(LidPreflightError::invalid(
                "probe selection differs from its source",
            ));
        }

        let mut encoded_probes = Vec::with_capacity(2);
        let mut expected_observations = Vec::with_capacity(2);
        for (position, (window, pcm)) in windows.iter().zip(pcm_probes.iter()).enumerate() {
            if usize::from(window.index()) != position {
                return Err(LidPreflightError::invalid(
                    "probe indexes are not contiguous",
                ));
            }
            let expected_bytes = window
                .sample_count()
                .checked_mul(u64::from(capability.policy.sample_width_bytes))
                .ok_or_else(|| LidPreflightError::invalid("probe length overflowed"))?;
            if u64::try_from(pcm.len()).ok() != Some(expected_bytes) {
                return Err(LidPreflightError::invalid(
                    "probe PCM length differs from its window",
                ));
            }
            let pcm_sha256 = format_sha256(Sha256::digest(pcm));
            let wav_sha256 = canonical_wav_sha256(pcm, capability)?;
            encoded_probes.push(ProbeManifest {
                index: window.index(),
                source_start_sample: window.source_start_sample(),
                source_end_sample: window.source_end_sample(),
                voiced_samples: window.voiced_samples(),
                pcm_byte_length: expected_bytes,
                pcm_sha256,
                vad_intervals: window
                    .vad_intervals
                    .iter()
                    .map(|interval| VadIntervalManifest {
                        start_sample: interval.start_sample,
                        end_sample_exclusive: interval.end_sample_exclusive,
                    })
                    .collect(),
            });
            expected_observations.push(ExpectedObservation {
                index: window.index(),
                source_start_sample: window.source_start_sample(),
                source_end_sample: window.source_end_sample(),
                voiced_samples: window.voiced_samples(),
                wav_sha256,
            });
        }

        let manifest = LidManifest {
            schema_version: 1,
            request_id: &source.request_id,
            source_samples: source.source_samples,
            source_pcm_sha256: &source.source_pcm_sha256,
            catalog_revision: &catalog.catalog_revision,
            policy_revision: &capability.policy.revision,
            probes: &encoded_probes,
        };
        let manifest = serde_json::to_vec(&manifest).map_err(LidPreflightError::Encode)?;
        if manifest.is_empty()
            || manifest.len() as u64 > capability.transport.maximum_manifest_bytes
            || manifest.len() > u32::MAX as usize
        {
            return Err(LidPreflightError::invalid(
                "probe manifest exceeds its bound",
            ));
        }
        let body_length = 4_usize
            .checked_add(manifest.len())
            .and_then(|length| {
                pcm_probes
                    .iter()
                    .try_fold(length, |total, pcm| total.checked_add(pcm.len()))
            })
            .ok_or_else(|| LidPreflightError::invalid("probe envelope length overflowed"))?;
        if body_length as u64 > capability.transport.maximum_body_bytes {
            return Err(LidPreflightError::invalid(
                "probe envelope exceeds its bound",
            ));
        }
        let mut body = Vec::with_capacity(body_length);
        body.extend_from_slice(&(manifest.len() as u32).to_be_bytes());
        body.extend_from_slice(&manifest);
        for pcm in pcm_probes {
            body.extend_from_slice(&pcm);
        }

        let supported_fixed_locales = catalog
            .providers
            .iter()
            .flat_map(|provider| &provider.capabilities)
            .filter(|capability| capability.mode == AsrExecutionMode::FixedBatch)
            .map(|capability| capability.language_bcp47.clone())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        if supported_fixed_locales.is_empty() || supported_fixed_locales.len() > 256 {
            return Err(LidPreflightError::invalid(
                "fixed-language catalog is invalid",
            ));
        }
        let expected = ExpectedLidResponse {
            request_id: source.request_id,
            source_samples: source.source_samples,
            source_pcm_sha256: source.source_pcm_sha256,
            catalog_revision: catalog.catalog_revision.clone(),
            capability: capability.clone(),
            supported_fixed_locales,
            observations: expected_observations
                .try_into()
                .map_err(|_| LidPreflightError::invalid("probe observation count is invalid"))?,
        };
        Ok(Self {
            body,
            media_type: capability.transport.media_type.clone(),
            timeout: Duration::from_secs(
                capability
                    .transport
                    .maximum_response_seconds
                    .saturating_add(RESPONSE_TIMEOUT_GRACE_SECONDS),
            ),
            expected,
        })
    }

    pub(crate) fn request_id(&self) -> &str {
        &self.expected.request_id
    }

    pub(in crate::server_connector) fn body(&self) -> &[u8] {
        &self.body
    }

    pub(in crate::server_connector) fn media_type(&self) -> &str {
        &self.media_type
    }

    pub(in crate::server_connector) fn timeout(&self) -> Duration {
        self.timeout
    }

    pub(in crate::server_connector) fn decode_response(
        &self,
        body: &[u8],
    ) -> Result<LidPreflightResult, LidPreflightError> {
        decode_lid_response(body, &self.expected)
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LidManifest<'a> {
    schema_version: u16,
    request_id: &'a str,
    source_samples: u64,
    source_pcm_sha256: &'a str,
    catalog_revision: &'a str,
    policy_revision: &'a str,
    probes: &'a [ProbeManifest],
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ProbeManifest {
    index: u16,
    source_start_sample: u64,
    source_end_sample: u64,
    voiced_samples: u64,
    pcm_byte_length: u64,
    pcm_sha256: String,
    vad_intervals: Vec<VadIntervalManifest>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct VadIntervalManifest {
    start_sample: u64,
    end_sample_exclusive: u64,
}

fn canonical_wav_sha256(
    pcm: &[u8],
    capability: &LidPreflightCapability,
) -> Result<String, LidPreflightError> {
    let data_length = u32::try_from(pcm.len())
        .map_err(|_| LidPreflightError::invalid("probe PCM exceeds WAV limits"))?;
    let riff_length = data_length
        .checked_add(36)
        .ok_or_else(|| LidPreflightError::invalid("probe WAV length overflowed"))?;
    let channels = capability.policy.channel_count;
    let sample_width = capability.policy.sample_width_bytes;
    let sample_rate = u32::try_from(capability.policy.sample_rate_hz)
        .map_err(|_| LidPreflightError::invalid("probe sample rate is invalid"))?;
    let block_align = channels
        .checked_mul(sample_width)
        .ok_or_else(|| LidPreflightError::invalid("probe block alignment overflowed"))?;
    let byte_rate = sample_rate
        .checked_mul(u32::from(block_align))
        .ok_or_else(|| LidPreflightError::invalid("probe byte rate overflowed"))?;
    let bits_per_sample = sample_width
        .checked_mul(8)
        .ok_or_else(|| LidPreflightError::invalid("probe sample width overflowed"))?;
    let mut digest = Sha256::new();
    digest.update(b"RIFF");
    digest.update(riff_length.to_le_bytes());
    digest.update(b"WAVEfmt ");
    digest.update(16_u32.to_le_bytes());
    digest.update(1_u16.to_le_bytes());
    digest.update(channels.to_le_bytes());
    digest.update(sample_rate.to_le_bytes());
    digest.update(byte_rate.to_le_bytes());
    digest.update(block_align.to_le_bytes());
    digest.update(bits_per_sample.to_le_bytes());
    digest.update(b"data");
    digest.update(data_length.to_le_bytes());
    digest.update(pcm);
    Ok(format_sha256(digest.finalize()))
}

pub(super) fn valid_request_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=128).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn format_sha256(value: impl AsRef<[u8]>) -> String {
    value
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
