use crate::{language::valid_bcp47, server_connector::LidPreflightCapability};

use super::LidPreflightError;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum LidPreflightStatus {
    Suggestion,
    Manual,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LidPreflightObservation {
    pub(crate) index: u16,
    pub(crate) probe_sha256: String,
    pub(crate) source_start_sample: u64,
    pub(crate) source_end_sample: u64,
    pub(crate) voiced_samples: u64,
    pub(crate) raw_label: String,
    pub(crate) top_score: f64,
    pub(crate) score_margin: f64,
    pub(crate) mapped_locale: Option<String>,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LidPreflightResult {
    pub(crate) schema_version: u16,
    pub(crate) request_id: String,
    pub(crate) status: LidPreflightStatus,
    pub(crate) reason: String,
    pub(crate) suggested_locale: Option<String>,
    pub(crate) user_confirmation_required: bool,
    pub(crate) source_samples: u64,
    pub(crate) source_pcm_sha256: String,
    pub(crate) catalog_revision: String,
    pub(crate) component: LidComponentEvidence,
    pub(crate) observations: Vec<LidPreflightObservation>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LidComponentEvidence {
    pub(crate) id: String,
    pub(crate) runtime: LidRuntimeEvidence,
    pub(crate) model: LidModelEvidence,
    pub(crate) policy_revision: String,
    pub(crate) score_semantics: String,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LidRuntimeEvidence {
    pub(crate) python_version: String,
    pub(crate) cpu_only: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LidModelEvidence {
    pub(crate) id: String,
    pub(crate) revision: String,
}

pub(super) struct ExpectedLidResponse {
    pub(super) request_id: String,
    pub(super) source_samples: u64,
    pub(super) source_pcm_sha256: String,
    pub(super) catalog_revision: String,
    pub(super) capability: LidPreflightCapability,
    pub(super) supported_fixed_locales: Vec<String>,
    pub(super) observations: [ExpectedObservation; 5],
}

pub(super) struct ExpectedObservation {
    pub(super) index: u16,
    pub(super) source_start_sample: u64,
    pub(super) source_end_sample: u64,
    pub(super) voiced_samples: u64,
    pub(super) wav_sha256: String,
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LidResponseWire {
    schema_version: u16,
    request_id: String,
    status: LidPreflightStatus,
    reason: String,
    suggested_locale: Option<String>,
    user_confirmation_required: bool,
    source_samples: u64,
    source_pcm_sha256: String,
    catalog_revision: String,
    component: LidComponentWire,
    observations: Vec<LidObservationWire>,
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LidComponentWire {
    id: String,
    runtime: LidRuntimeWire,
    model: LidModelWire,
    policy_revision: String,
    score_semantics: String,
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LidRuntimeWire {
    python_version: String,
    cpu_only: bool,
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LidModelWire {
    id: String,
    revision: String,
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LidObservationWire {
    index: u16,
    probe_sha256: String,
    source_start_sample: u64,
    source_end_sample: u64,
    voiced_samples: u64,
    raw_label: String,
    top_score: f64,
    score_margin: f64,
    mapped_locale: Option<String>,
}

pub(super) fn decode_lid_response(
    body: &[u8],
    expected: &ExpectedLidResponse,
) -> Result<LidPreflightResult, LidPreflightError> {
    let wire: LidResponseWire =
        serde_json::from_slice(body).map_err(|_| LidPreflightError::MalformedResponse)?;
    let capability = &expected.capability;
    if wire.schema_version != 1
        || wire.request_id != expected.request_id
        || wire.source_samples != expected.source_samples
        || wire.source_pcm_sha256 != expected.source_pcm_sha256
        || wire.catalog_revision != expected.catalog_revision
        || !wire.user_confirmation_required
        || wire.component.id != capability.component_id
        || wire.component.runtime.python_version != capability.runtime.python_version
        || wire.component.runtime.cpu_only != capability.runtime.cpu_only
        || wire.component.model.id != capability.model.id
        || wire.component.model.revision != capability.model.revision
        || wire.component.policy_revision != capability.policy.revision
        || wire.component.score_semantics != capability.policy.score_semantics
        || wire.observations.len() != expected.observations.len()
    {
        return Err(LidPreflightError::MalformedResponse);
    }

    let mut observations = Vec::with_capacity(expected.observations.len());
    let mut detected_codes = Vec::with_capacity(expected.observations.len());
    let mut ambiguous_model_output = false;
    for (wire_observation, expected_observation) in
        wire.observations.into_iter().zip(&expected.observations)
    {
        if wire_observation.index != expected_observation.index
            || wire_observation.probe_sha256 != expected_observation.wav_sha256
            || wire_observation.source_start_sample != expected_observation.source_start_sample
            || wire_observation.source_end_sample != expected_observation.source_end_sample
            || wire_observation.voiced_samples != expected_observation.voiced_samples
            || !valid_sha256(&wire_observation.probe_sha256)
            || !valid_raw_label(&wire_observation.raw_label)
            || !wire_observation.top_score.is_finite()
            || wire_observation.top_score > 0.0
            || !wire_observation.score_margin.is_finite()
            || wire_observation.score_margin < 0.0
        {
            return Err(LidPreflightError::MalformedResponse);
        }
        let code = language_code(&wire_observation.raw_label);
        let expected_mapping = code.as_deref().and_then(|code| {
            let candidates = expected
                .supported_fixed_locales
                .iter()
                .filter(|locale| locale.split('-').next() == Some(code))
                .collect::<Vec<_>>();
            (candidates.len() == 1).then(|| candidates[0].clone())
        });
        if wire_observation.mapped_locale != expected_mapping
            || wire_observation
                .mapped_locale
                .as_deref()
                .is_some_and(|locale| !valid_bcp47(locale))
        {
            return Err(LidPreflightError::MalformedResponse);
        }
        detected_codes.push(code);
        ambiguous_model_output |= wire_observation.score_margin == 0.0;
        observations.push(LidPreflightObservation {
            index: wire_observation.index,
            probe_sha256: wire_observation.probe_sha256,
            source_start_sample: wire_observation.source_start_sample,
            source_end_sample: wire_observation.source_end_sample,
            voiced_samples: wire_observation.voiced_samples,
            raw_label: wire_observation.raw_label,
            top_score: wire_observation.top_score,
            score_margin: wire_observation.score_margin,
            mapped_locale: wire_observation.mapped_locale,
        });
    }

    let (expected_status, expected_reason, expected_suggestion) = expected_decision(
        &detected_codes,
        ambiguous_model_output,
        &expected.supported_fixed_locales,
    );
    if wire.status != expected_status
        || wire.reason != expected_reason
        || wire.suggested_locale != expected_suggestion
        || wire
            .suggested_locale
            .as_deref()
            .is_some_and(|locale| !valid_bcp47(locale))
    {
        return Err(LidPreflightError::MalformedResponse);
    }
    Ok(LidPreflightResult {
        schema_version: wire.schema_version,
        request_id: wire.request_id,
        status: wire.status,
        reason: wire.reason,
        suggested_locale: wire.suggested_locale,
        user_confirmation_required: wire.user_confirmation_required,
        source_samples: wire.source_samples,
        source_pcm_sha256: wire.source_pcm_sha256,
        catalog_revision: wire.catalog_revision,
        component: LidComponentEvidence {
            id: wire.component.id,
            runtime: LidRuntimeEvidence {
                python_version: wire.component.runtime.python_version,
                cpu_only: wire.component.runtime.cpu_only,
            },
            model: LidModelEvidence {
                id: wire.component.model.id,
                revision: wire.component.model.revision,
            },
            policy_revision: wire.component.policy_revision,
            score_semantics: wire.component.score_semantics,
        },
        observations,
    })
}

fn expected_decision(
    codes: &[Option<String>],
    ambiguous_model_output: bool,
    supported_fixed_locales: &[String],
) -> (LidPreflightStatus, &'static str, Option<String>) {
    if ambiguous_model_output {
        return (LidPreflightStatus::Manual, "ambiguous_model_output", None);
    }
    if codes.iter().any(Option::is_none) {
        return (LidPreflightStatus::Manual, "invalid_model_label", None);
    }
    if codes.iter().skip(1).any(|code| code != &codes[0]) {
        return (LidPreflightStatus::Manual, "language_disagreement", None);
    }
    let code = codes[0].as_deref().expect("checked language code");
    let candidates = supported_fixed_locales
        .iter()
        .filter(|locale| locale.split('-').next() == Some(code))
        .collect::<Vec<_>>();
    match candidates.as_slice() {
        [] => (LidPreflightStatus::Manual, "unsupported_language", None),
        [locale] => (
            LidPreflightStatus::Suggestion,
            "mapped_language_agreement",
            Some((*locale).clone()),
        ),
        _ => (LidPreflightStatus::Manual, "ambiguous_locale", None),
    }
}

fn language_code(raw_label: &str) -> Option<String> {
    if !(2..=3).contains(&raw_label.len())
        || !raw_label.bytes().all(|byte| byte.is_ascii_lowercase())
    {
        return None;
    }
    Some(
        match raw_label {
            "in" => "id",
            "iw" => "he",
            "ji" => "yi",
            "jw" => "jv",
            "mo" => "ro",
            value => value,
        }
        .to_owned(),
    )
}

fn valid_raw_label(value: &str) -> bool {
    let length = value.chars().count();
    (1..=128).contains(&length) && !value.chars().any(char::is_control)
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
