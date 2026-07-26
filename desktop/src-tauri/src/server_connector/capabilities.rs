use std::collections::HashSet;
use std::fmt::Write as _;

use sha2::{Digest, Sha256};

use super::config;
use crate::{
    jobs::{RecordingLanguageDecision, RecordingLanguageMode},
    language::valid_bcp47,
};

pub(super) const MAX_CATALOG_BYTES: usize = 256 * 1024;
const MAX_PROVIDERS: usize = 8;
const MAX_CAPABILITIES_PER_PROVIDER: usize = 256;
const LID_PREFLIGHT_MEDIA_TYPE: &str = "application/vnd.yap.lid-preflight.v1+octet-stream";
const MAX_LID_PREFLIGHT_BODY_BYTES: u64 = 1024 * 1024;
const MAX_LID_PREFLIGHT_MANIFEST_BYTES: u64 = 32 * 1024;
const LID_SAMPLE_RATE_HZ: u64 = 16_000;
const LID_MINIMUM_SOURCE_SAMPLES: u64 = LID_SAMPLE_RATE_HZ * 30;
const LID_MAXIMUM_WINDOW_SAMPLES: u64 = LID_SAMPLE_RATE_HZ * 6;
const LID_MINIMUM_VOICED_SAMPLES: u64 = 51_200;
const LID_STRATIFIED_REGION_COUNT: u16 = 5;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum AsrExecutionMode {
    LocalLive,
    ServerLive,
    FixedBatch,
    DynamicBatch,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum AsrQualityTier {
    TranscriptionReady,
    BroadCoverage,
    Preview,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AsrCapability {
    pub language_bcp47: String,
    pub provider_language_code: String,
    pub mode: AsrExecutionMode,
    pub quality_tier: AsrQualityTier,
    pub language_suggestion: bool,
    pub segment_language_tags: bool,
    pub word_alignment: bool,
    pub promotion_evidence_revision: String,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AsrProviderCapabilities {
    pub provider_id: String,
    pub pool_id: String,
    pub model_id: String,
    pub model_revision: String,
    pub model_license: String,
    pub model_source: String,
    pub capabilities: Vec<AsrCapability>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LidPreflightRuntimeCapability {
    pub python_version: String,
    pub cpu_only: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LidPreflightModelCapability {
    pub id: String,
    pub revision: String,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LidPreflightTransportCapability {
    pub media_type: String,
    pub maximum_body_bytes: u64,
    pub maximum_manifest_bytes: u64,
    pub maximum_response_seconds: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LidPreflightPolicyCapability {
    pub revision: String,
    pub sample_rate_hz: u64,
    pub channel_count: u16,
    pub sample_width_bytes: u16,
    pub minimum_source_samples: u64,
    pub maximum_windows: u16,
    pub maximum_window_samples: u64,
    pub minimum_voiced_samples_per_window: u64,
    pub score_semantics: String,
    pub user_confirmation_required: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LidPreflightCapability {
    pub schema_version: u16,
    pub component_id: String,
    pub runtime: LidPreflightRuntimeCapability,
    pub model: LidPreflightModelCapability,
    pub transport: LidPreflightTransportCapability,
    pub policy: LidPreflightPolicyCapability,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AsrCapabilityCatalog {
    pub schema_version: u16,
    pub catalog_revision: String,
    pub providers: Vec<AsrProviderCapabilities>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub language_preflight: Option<LidPreflightCapability>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum AsrCatalogError {
    InvalidOrigin,
    Transport,
    Unavailable,
    ResponseTooLarge,
    Malformed,
    RevisionMismatch,
}

pub(crate) async fn fetch_asr_capabilities(
    client: &reqwest::Client,
    authorization: &super::RequestAuthorization,
    base_url: &str,
    allow_insecure_private: bool,
) -> Result<AsrCapabilityCatalog, AsrCatalogError> {
    let normalized = config::validate_base_url(base_url, allow_insecure_private)
        .map_err(|_| AsrCatalogError::InvalidOrigin)?;
    let mut url = reqwest::Url::parse(&normalized).map_err(|_| AsrCatalogError::InvalidOrigin)?;
    url.set_path("/v1/asr/capabilities");
    url.set_query(None);
    url.set_fragment(None);
    let mut response = authorization
        .authorize(
            client
                .get(url)
                .header(reqwest::header::ACCEPT, "application/json"),
        )
        .await
        .map_err(|_| AsrCatalogError::Unavailable)?
        .send()
        .await
        .map_err(|_| AsrCatalogError::Transport)?;
    if response.status() != reqwest::StatusCode::OK {
        return Err(AsrCatalogError::Unavailable);
    }
    if response
        .content_length()
        .is_some_and(|length| length > MAX_CATALOG_BYTES as u64)
    {
        return Err(AsrCatalogError::ResponseTooLarge);
    }
    let mut body = Vec::with_capacity(
        response
            .content_length()
            .unwrap_or_default()
            .min(MAX_CATALOG_BYTES as u64) as usize,
    );
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| AsrCatalogError::Transport)?
    {
        if body.len().saturating_add(chunk.len()) > MAX_CATALOG_BYTES {
            return Err(AsrCatalogError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    AsrCapabilityCatalog::parse_bounded(&body)
}

impl AsrCapabilityCatalog {
    pub(crate) fn parse_bounded(body: &[u8]) -> Result<Self, AsrCatalogError> {
        if body.is_empty() || body.len() > MAX_CATALOG_BYTES {
            return Err(AsrCatalogError::ResponseTooLarge);
        }
        let catalog: Self = serde_json::from_slice(body).map_err(|_| AsrCatalogError::Malformed)?;
        catalog.validate()?;
        if catalog.computed_revision()? != catalog.catalog_revision {
            return Err(AsrCatalogError::RevisionMismatch);
        }
        Ok(catalog)
    }

    pub(crate) fn supports_fixed_batch(&self, language_bcp47: &str) -> bool {
        self.providers.iter().any(|provider| {
            provider.capabilities.iter().any(|capability| {
                capability.language_bcp47 == language_bcp47
                    && capability.mode == AsrExecutionMode::FixedBatch
            })
        })
    }

    pub(crate) fn lid_preflight(&self) -> Option<&LidPreflightCapability> {
        self.language_preflight.as_ref()
    }

    pub(crate) fn supports_recording_decision(&self, decision: &RecordingLanguageDecision) -> bool {
        match (decision.mode, decision.language_bcp47.as_deref()) {
            (RecordingLanguageMode::Fixed, Some(language_bcp47)) => self
                .providers
                .iter()
                .flat_map(|provider| &provider.capabilities)
                .any(|capability| {
                    capability.language_bcp47 == language_bcp47
                        && capability.mode == AsrExecutionMode::FixedBatch
                }),
            (RecordingLanguageMode::Dynamic, None) => self
                .providers
                .iter()
                .flat_map(|provider| &provider.capabilities)
                .any(|capability| capability.mode == AsrExecutionMode::DynamicBatch),
            _ => false,
        }
    }

    fn validate(&self) -> Result<(), AsrCatalogError> {
        if self.schema_version != 1
            || !lower_hex(&self.catalog_revision, 64)
            || !(1..=MAX_PROVIDERS).contains(&self.providers.len())
        {
            return Err(AsrCatalogError::Malformed);
        }
        let mut provider_ids = HashSet::new();
        let mut pool_ids = HashSet::new();
        for provider in &self.providers {
            if !bounded_text(&provider.provider_id, 64)
                || !bounded_text(&provider.pool_id, 64)
                || !bounded_text(&provider.model_id, 256)
                || !lower_hex(&provider.model_revision, 40)
                || !bounded_text(&provider.model_license, 128)
                || !valid_model_source(&provider.model_source)
                || !(1..=MAX_CAPABILITIES_PER_PROVIDER).contains(&provider.capabilities.len())
                || !provider_ids.insert(provider.provider_id.as_str())
                || !pool_ids.insert(provider.pool_id.as_str())
            {
                return Err(AsrCatalogError::Malformed);
            }
            let mut locale_modes = HashSet::new();
            for capability in &provider.capabilities {
                if !valid_bcp47(&capability.language_bcp47)
                    || !provider_language_code(&capability.provider_language_code)
                    || !lower_hex(&capability.promotion_evidence_revision, 40)
                    || (capability.mode == AsrExecutionMode::DynamicBatch
                        && !capability.segment_language_tags)
                    || !locale_modes.insert((capability.language_bcp47.as_str(), capability.mode))
                {
                    return Err(AsrCatalogError::Malformed);
                }
            }
        }
        if self
            .language_preflight
            .as_ref()
            .is_some_and(|capability| !capability.is_valid())
        {
            return Err(AsrCatalogError::Malformed);
        }
        Ok(())
    }

    pub(super) fn computed_revision(&self) -> Result<String, AsrCatalogError> {
        #[derive(serde::Serialize)]
        #[serde(rename_all = "camelCase")]
        struct RevisionSource<'a> {
            schema_version: u16,
            providers: &'a [AsrProviderCapabilities],
        }

        let source = serde_json::to_value(RevisionSource {
            schema_version: self.schema_version,
            providers: &self.providers,
        })
        .map_err(|_| AsrCatalogError::Malformed)?;
        let canonical = serde_json::to_vec(&source).map_err(|_| AsrCatalogError::Malformed)?;
        let digest = Sha256::digest(canonical);
        let mut revision = String::with_capacity(64);
        for byte in digest {
            write!(&mut revision, "{byte:02x}").map_err(|_| AsrCatalogError::Malformed)?;
        }
        Ok(revision)
    }
}

impl LidPreflightCapability {
    fn is_valid(&self) -> bool {
        self.schema_version == 1
            && bounded_text(&self.component_id, 128)
            && valid_python_312_patch(&self.runtime.python_version)
            && self.runtime.cpu_only
            && bounded_text(&self.model.id, 256)
            && immutable_lid_model_revision(&self.model.revision)
            && self.transport.media_type == LID_PREFLIGHT_MEDIA_TYPE
            && (5..=MAX_LID_PREFLIGHT_BODY_BYTES).contains(&self.transport.maximum_body_bytes)
            && (1..=MAX_LID_PREFLIGHT_MANIFEST_BYTES)
                .contains(&self.transport.maximum_manifest_bytes)
            && (1..=300).contains(&self.transport.maximum_response_seconds)
            && self
                .transport
                .maximum_manifest_bytes
                .checked_add(4)
                .is_some_and(|value| value <= self.transport.maximum_body_bytes)
            && bounded_text(&self.policy.revision, 128)
            && self.policy.sample_rate_hz == LID_SAMPLE_RATE_HZ
            && self.policy.channel_count == 1
            && self.policy.sample_width_bytes == 2
            && self.policy.minimum_source_samples == LID_MINIMUM_SOURCE_SAMPLES
            && self.policy.maximum_windows == LID_STRATIFIED_REGION_COUNT
            && self.policy.maximum_window_samples == LID_MAXIMUM_WINDOW_SAMPLES
            && self.policy.minimum_voiced_samples_per_window == LID_MINIMUM_VOICED_SAMPLES
            && self.policy.score_semantics == "mean-logit-log-softmax"
            && self
                .policy
                .maximum_window_samples
                .checked_mul(u64::from(self.policy.maximum_windows))
                .is_some_and(|minimum| minimum <= self.policy.minimum_source_samples)
            && self
                .policy
                .maximum_window_samples
                .checked_mul(u64::from(self.policy.sample_width_bytes))
                .and_then(|bytes| bytes.checked_mul(u64::from(self.policy.maximum_windows)))
                .and_then(|bytes| bytes.checked_add(self.transport.maximum_manifest_bytes))
                .and_then(|bytes| bytes.checked_add(4))
                .is_some_and(|maximum| maximum <= self.transport.maximum_body_bytes)
            && self.policy.user_confirmation_required
    }
}

fn bounded_text(value: &str, maximum: usize) -> bool {
    let length = value.chars().count();
    (1..=maximum).contains(&length) && value.bytes().all(|byte| (b' '..=b'~').contains(&byte))
}

fn lower_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn immutable_lid_model_revision(value: &str) -> bool {
    if lower_hex(value, 40) {
        return true;
    }
    let parts = value.split('.').collect::<Vec<_>>();
    parts.len() == 3
        && parts.iter().all(|part| {
            !part.is_empty()
                && part.bytes().all(|byte| byte.is_ascii_digit())
                && (part == &"0" || !part.starts_with('0'))
        })
}

fn provider_language_code(value: &str) -> bool {
    value == "auto" || valid_bcp47(value)
}

fn valid_python_312_patch(value: &str) -> bool {
    value
        .strip_prefix("3.12.")
        .is_some_and(|patch| !patch.is_empty() && patch.bytes().all(|byte| byte.is_ascii_digit()))
}

fn valid_model_source(value: &str) -> bool {
    bounded_text(value, 2048)
        && reqwest::Url::parse(value).is_ok_and(|url| {
            matches!(url.scheme(), "http" | "https")
                && url.host_str().is_some()
                && url.username().is_empty()
                && url.password().is_none()
        })
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    use super::{
        fetch_asr_capabilities, provider_language_code, AsrCapabilityCatalog, AsrCatalogError,
        LID_PREFLIGHT_MEDIA_TYPE, MAX_CATALOG_BYTES,
    };
    use crate::server_connector::client::bounded_client;

    const REPOSITORY_EXAMPLE: &[u8] =
        include_bytes!("../../../../server/openapi/examples/asr-capabilities.ok.json");
    const INVALID_CASES: &[u8] = include_bytes!(
        "../../../../server/openapi/examples/asr-capability-catalog.invalid-cases.json"
    );

    #[derive(serde::Deserialize)]
    #[serde(rename_all = "camelCase", deny_unknown_fields)]
    struct InvalidCatalogFixture {
        schema_version: u8,
        base_example: String,
        cases: Vec<InvalidCatalogCase>,
    }

    #[derive(serde::Deserialize)]
    #[serde(rename_all = "camelCase", deny_unknown_fields)]
    struct InvalidCatalogCase {
        id: String,
        mutations: Vec<CatalogMutation>,
        expected_native_error: String,
        violates_open_api_schema: bool,
    }

    #[derive(serde::Deserialize)]
    #[serde(rename_all = "camelCase", deny_unknown_fields)]
    struct CatalogMutation {
        pointer: String,
        value: serde_json::Value,
    }

    #[test]
    fn repository_example_projects_as_a_bounded_verified_catalog() {
        let catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE)
            .expect("repository capability example should be valid");

        assert_eq!(catalog.schema_version, 1);
        assert_eq!(catalog.providers.len(), 1);
        assert_eq!(catalog.providers[0].capabilities.len(), 1);
        assert_eq!(catalog.providers[0].capabilities[0].language_bcp47, "en-US");
    }

    #[test]
    fn shared_invalid_catalog_cases_fail_at_the_native_trust_boundary() {
        let fixture: InvalidCatalogFixture = serde_json::from_slice(INVALID_CASES).unwrap();
        assert_eq!(fixture.schema_version, 1);
        assert_eq!(fixture.base_example, "asr-capabilities.ok.json");
        let mut case_ids = HashSet::new();
        let mut schema_invalid_cases = 0_usize;

        for case in fixture.cases {
            assert!(
                case_ids.insert(case.id.clone()),
                "duplicate case {}",
                case.id
            );
            schema_invalid_cases += usize::from(case.violates_open_api_schema);
            let mut candidate: serde_json::Value =
                serde_json::from_slice(REPOSITORY_EXAMPLE).unwrap();
            for mutation in case.mutations {
                *candidate
                    .pointer_mut(&mutation.pointer)
                    .unwrap_or_else(|| panic!("invalid fixture pointer {}", mutation.pointer)) =
                    mutation.value;
            }
            let actual =
                AsrCapabilityCatalog::parse_bounded(&serde_json::to_vec(&candidate).unwrap());
            let expected = match case.expected_native_error.as_str() {
                "malformed" => AsrCatalogError::Malformed,
                "revisionMismatch" => AsrCatalogError::RevisionMismatch,
                other => panic!("unsupported expected native error {other}"),
            };
            assert_eq!(actual, Err(expected), "case {}", case.id);
        }

        assert_eq!(case_ids.len(), 6);
        assert_eq!(schema_invalid_cases, 4);
    }

    #[test]
    fn provider_prompt_accepts_exact_locales_and_explicit_auto_only() {
        assert!(provider_language_code("en"));
        assert!(provider_language_code("en-US"));
        assert!(provider_language_code("auto"));
        assert!(!provider_language_code("EN-us"));
        assert!(!provider_language_code("../en-US"));
    }

    #[test]
    fn oversized_catalog_is_rejected_before_json_parsing() {
        assert_eq!(
            AsrCapabilityCatalog::parse_bounded(&vec![b' '; MAX_CATALOG_BYTES + 1]),
            Err(AsrCatalogError::ResponseTooLarge)
        );
    }

    #[test]
    fn identity_and_provenance_text_must_be_printable_ascii() {
        let mut catalog = AsrCapabilityCatalog::parse_bounded(REPOSITORY_EXAMPLE).unwrap();
        catalog.providers[0].model_license = "Apache-é".into();
        catalog.catalog_revision = catalog.computed_revision().unwrap();
        let body = serde_json::to_vec(&catalog).unwrap();

        assert_eq!(
            AsrCapabilityCatalog::parse_bounded(&body),
            Err(AsrCatalogError::Malformed)
        );
    }

    #[test]
    fn verified_lid_policy_is_optional_and_does_not_rewrite_provider_revision() {
        let mut value: serde_json::Value = serde_json::from_slice(REPOSITORY_EXAMPLE).unwrap();
        let original_revision = value["catalogRevision"].as_str().unwrap().to_owned();
        value["languagePreflight"] = lid_capability_value();
        let catalog = AsrCapabilityCatalog::parse_bounded(&serde_json::to_vec(&value).unwrap())
            .expect("verified LID policy should extend the live catalog");

        assert_eq!(catalog.catalog_revision, original_revision);
        assert_eq!(catalog.computed_revision().unwrap(), original_revision);
        let lid = catalog.lid_preflight().unwrap();
        assert_eq!(lid.policy.revision, "ambernet-stratified-five-region-v1");
        assert!(lid.runtime.cpu_only);
    }

    #[test]
    fn weakened_or_gpu_lid_policy_is_rejected() {
        for field in ["runtime.cpuOnly", "policy.userConfirmationRequired"] {
            let mut value: serde_json::Value = serde_json::from_slice(REPOSITORY_EXAMPLE).unwrap();
            value["languagePreflight"] = lid_capability_value();
            match field {
                "runtime.cpuOnly" => {
                    value["languagePreflight"]["runtime"]["cpuOnly"] = false.into()
                }
                "policy.userConfirmationRequired" => {
                    value["languagePreflight"]["policy"]["userConfirmationRequired"] = false.into()
                }
                _ => unreachable!(),
            }
            assert_eq!(
                AsrCapabilityCatalog::parse_bounded(&serde_json::to_vec(&value).unwrap()),
                Err(AsrCatalogError::Malformed),
                "{field} must fail closed"
            );
        }
    }

    #[test]
    fn native_fetch_projects_the_separately_bounded_catalog_endpoint() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0_u8; 2048];
            let read = stream.read(&mut request).unwrap();
            let request = String::from_utf8_lossy(&request[..read]);
            assert!(request.starts_with("GET /v1/asr/capabilities HTTP/1.1"));
            assert!(request
                .to_ascii_lowercase()
                .contains("authorization: bearer capability-token"));
            let headers = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                REPOSITORY_EXAMPLE.len()
            );
            stream.write_all(headers.as_bytes()).unwrap();
            stream.write_all(REPOSITORY_EXAMPLE).unwrap();
        });

        let catalog = tauri::async_runtime::block_on(fetch_asr_capabilities(
            &bounded_client().unwrap(),
            &crate::server_connector::RequestAuthorization::fixed("capability-token"),
            &format!("http://{address}"),
            false,
        ))
        .expect("verified catalog endpoint should project");
        server.join().unwrap();

        assert_eq!(catalog.providers[0].provider_id, "cohere");
    }

    fn lid_capability_value() -> serde_json::Value {
        serde_json::json!({
            "schemaVersion": 1,
            "componentId": "ambernet-batch-language-preflight",
            "runtime": {"pythonVersion": "3.12.13", "cpuOnly": true},
            "model": {
                "id": "nvidia/nemo/langid_ambernet",
                "revision": "1.12.0"
            },
            "transport": {
                "mediaType": LID_PREFLIGHT_MEDIA_TYPE,
                "maximumBodyBytes": 1_048_576,
                "maximumManifestBytes": 32_768,
                "maximumResponseSeconds": 120
            },
            "policy": {
                "revision": "ambernet-stratified-five-region-v1",
                "sampleRateHz": 16_000,
                "channelCount": 1,
                "sampleWidthBytes": 2,
                "minimumSourceSamples": 480_000,
                "maximumWindows": 5,
                "maximumWindowSamples": 96_000,
                "minimumVoicedSamplesPerWindow": 51_200,
                "scoreSemantics": "mean-logit-log-softmax",
                "userConfirmationRequired": true
            }
        })
    }
}
