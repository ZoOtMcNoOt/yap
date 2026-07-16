use std::collections::HashSet;
use std::fmt::Write as _;

use sha2::{Digest, Sha256};

use super::config;

const MAX_CATALOG_BYTES: usize = 256 * 1024;
const MAX_PROVIDERS: usize = 8;
const MAX_CAPABILITIES_PER_PROVIDER: usize = 256;

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
pub struct AsrCapabilityCatalog {
    pub schema_version: u16,
    pub catalog_revision: String,
    pub providers: Vec<AsrProviderCapabilities>,
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
    base_url: &str,
    allow_insecure_private: bool,
) -> Result<AsrCapabilityCatalog, AsrCatalogError> {
    let normalized = config::validate_base_url(base_url, allow_insecure_private)
        .map_err(|_| AsrCatalogError::InvalidOrigin)?;
    let mut url = reqwest::Url::parse(&normalized).map_err(|_| AsrCatalogError::InvalidOrigin)?;
    url.set_path("/v1/asr/capabilities");
    url.set_query(None);
    url.set_fragment(None);
    let mut response = client
        .get(url)
        .header(reqwest::header::ACCEPT, "application/json")
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
        Ok(())
    }

    fn computed_revision(&self) -> Result<String, AsrCatalogError> {
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

fn provider_language_code(value: &str) -> bool {
    value.len() == 2 && value.bytes().all(|byte| byte.is_ascii_lowercase())
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

fn valid_bcp47(value: &str) -> bool {
    if value.len() > 35 || !value.is_ascii() {
        return false;
    }
    let parts = value.split('-').collect::<Vec<_>>();
    let Some(language) = parts.first() else {
        return false;
    };
    if !(2..=3).contains(&language.len()) || !language.bytes().all(|byte| byte.is_ascii_lowercase())
    {
        return false;
    }

    let mut index = 1;
    if parts.get(index).is_some_and(|part| {
        part.len() == 4
            && part.as_bytes()[0].is_ascii_uppercase()
            && part.as_bytes()[1..]
                .iter()
                .all(|byte| byte.is_ascii_lowercase())
    }) {
        index += 1;
    }
    if parts.get(index).is_some_and(|part| {
        (part.len() == 2 && part.bytes().all(|byte| byte.is_ascii_uppercase()))
            || (part.len() == 3 && part.bytes().all(|byte| byte.is_ascii_digit()))
    }) {
        index += 1;
    }
    parts[index..].iter().all(|part| {
        ((5..=8).contains(&part.len()) || (part.len() == 4 && part.as_bytes()[0].is_ascii_digit()))
            && part.bytes().all(|byte| byte.is_ascii_alphanumeric())
    })
}

#[cfg(test)]
mod tests {
    use std::io::{Read, Write};
    use std::net::TcpListener;

    use super::{fetch_asr_capabilities, AsrCapabilityCatalog, AsrCatalogError, MAX_CATALOG_BYTES};
    use crate::server_connector::client::bounded_client;

    const REPOSITORY_EXAMPLE: &[u8] =
        include_bytes!("../../../../server/openapi/examples/asr-capabilities.ok.json");

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
    fn oversized_catalog_is_rejected_before_json_parsing() {
        assert_eq!(
            AsrCapabilityCatalog::parse_bounded(&vec![b' '; MAX_CATALOG_BYTES + 1]),
            Err(AsrCatalogError::ResponseTooLarge)
        );
    }

    #[test]
    fn altered_capability_cannot_reuse_the_server_fingerprint() {
        let mut value: serde_json::Value = serde_json::from_slice(REPOSITORY_EXAMPLE).unwrap();
        value["providers"][0]["capabilities"][0]["wordAlignment"] = true.into();
        let body = serde_json::to_vec(&value).unwrap();

        assert_eq!(
            AsrCapabilityCatalog::parse_bounded(&body),
            Err(AsrCatalogError::RevisionMismatch)
        );
    }

    #[test]
    fn dynamic_mode_requires_segment_language_tags() {
        let mut value: serde_json::Value = serde_json::from_slice(REPOSITORY_EXAMPLE).unwrap();
        value["providers"][0]["capabilities"][0]["mode"] = "dynamicBatch".into();
        let body = serde_json::to_vec(&value).unwrap();

        assert_eq!(
            AsrCapabilityCatalog::parse_bounded(&body),
            Err(AsrCatalogError::Malformed)
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
    fn native_fetch_projects_the_separately_bounded_catalog_endpoint() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0_u8; 2048];
            let read = stream.read(&mut request).unwrap();
            assert!(String::from_utf8_lossy(&request[..read])
                .starts_with("GET /v1/asr/capabilities HTTP/1.1"));
            let headers = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                REPOSITORY_EXAMPLE.len()
            );
            stream.write_all(headers.as_bytes()).unwrap();
            stream.write_all(REPOSITORY_EXAMPLE).unwrap();
        });

        let catalog = tauri::async_runtime::block_on(fetch_asr_capabilities(
            &bounded_client().unwrap(),
            &format!("http://{address}"),
            false,
        ))
        .expect("verified catalog endpoint should project");
        server.join().unwrap();

        assert_eq!(catalog.providers[0].provider_id, "cohere");
    }
}
