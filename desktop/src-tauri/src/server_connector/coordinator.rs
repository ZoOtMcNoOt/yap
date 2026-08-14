use std::collections::HashSet;

use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::authorization::{
    AuthenticatedDispatchError, AuthenticatedRequestDispatcher, AuthenticatedResponse,
    RequestAuthorizationError,
};

const MAXIMUM_RESPONSE_BYTES: usize = 256 * 1024;
const MAXIMUM_OBJECTIVE_CHARACTERS: usize = 1_024;
const MAXIMUM_ITEMS: usize = 5;
const MAXIMUM_PROPOSAL_CHARACTERS: usize = 2_048;
const MAXIMUM_CITATIONS_PER_ITEM: usize = 8;
const MAXIMUM_CITATION_TEXT_CHARACTERS: usize = 2_000;
const MAXIMUM_CONCEPT_CHARACTERS: usize = 512;
const MAXIMUM_SOURCE_REVISION_CHARACTERS: usize = 512;
const MAXIMUM_REASON_CHARACTERS: usize = 64;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CoordinatorRequest {
    schema_version: u16,
    objective: String,
    maximum_items: u8,
    expected_generation_sha256: Option<String>,
}

impl CoordinatorRequest {
    pub(crate) fn new(
        objective: String,
        maximum_items: u8,
        expected_generation_sha256: Option<String>,
    ) -> Result<Self, CoordinatorClientError> {
        let request = Self {
            schema_version: 1,
            objective,
            maximum_items,
            expected_generation_sha256,
        };
        if !request.is_valid() {
            return Err(CoordinatorClientError::InvalidRequest);
        }
        Ok(request)
    }

    fn is_valid(&self) -> bool {
        self.schema_version == 1
            && !self.objective.is_empty()
            && self.objective.trim() == self.objective
            && self.objective.chars().count() <= MAXIMUM_OBJECTIVE_CHARACTERS
            && self
                .objective
                .chars()
                .any(|character| character.is_alphanumeric())
            && (1..=MAXIMUM_ITEMS as u8).contains(&self.maximum_items)
            && self
                .expected_generation_sha256
                .as_ref()
                .is_none_or(|value| valid_sha256(value))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CoordinatorCitation {
    pub(crate) concept_id: String,
    pub(crate) source_revision: String,
    pub(crate) content_sha256: String,
    pub(crate) char_start: u64,
    pub(crate) char_end: u64,
    pub(crate) text: String,
}

impl CoordinatorCitation {
    fn is_valid(&self) -> bool {
        !self.concept_id.is_empty()
            && self.concept_id.trim() == self.concept_id
            && self.concept_id.chars().count() <= MAXIMUM_CONCEPT_CHARACTERS
            && !self.source_revision.is_empty()
            && self.source_revision.trim() == self.source_revision
            && self.source_revision.chars().count() <= MAXIMUM_SOURCE_REVISION_CHARACTERS
            && valid_sha256(&self.content_sha256)
            && self.char_end > self.char_start
            && self.char_end <= i64::MAX as u64
            && self.char_end - self.char_start == self.text.chars().count() as u64
            && !self.text.is_empty()
            && self.text.chars().count() <= MAXIMUM_CITATION_TEXT_CHARACTERS
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CoordinatorProposalBundleItem {
    pub(crate) proposal_id: String,
    pub(crate) proposal_type: String,
    pub(crate) proposed_content: String,
    pub(crate) citations: Vec<CoordinatorCitation>,
    pub(crate) citation_sha256: String,
    pub(crate) candidate_sha256: String,
}

impl CoordinatorProposalBundleItem {
    fn is_valid(&self) -> bool {
        if !valid_sha256(&self.proposal_id)
            || self.proposal_type != "summary"
            || self.proposed_content.is_empty()
            || self.proposed_content.trim() != self.proposed_content
            || self.proposed_content.chars().count() > MAXIMUM_PROPOSAL_CHARACTERS
            || self.citations.is_empty()
            || self.citations.len() > MAXIMUM_CITATIONS_PER_ITEM
            || self.citations.iter().any(|citation| !citation.is_valid())
            || !valid_sha256(&self.citation_sha256)
            || !valid_sha256(&self.candidate_sha256)
        {
            return false;
        }
        let identities = self
            .citations
            .iter()
            .map(citation_identity)
            .collect::<HashSet<_>>();
        identities.len() == self.citations.len()
            && citation_sha256(&self.citations).as_deref() == Some(self.citation_sha256.as_str())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CoordinatorProposalBundle {
    schema_version: u16,
    pub(crate) generation_sha256: String,
    pub(crate) evidence_sha256: String,
    pub(crate) items: Vec<CoordinatorProposalBundleItem>,
    pub(crate) bundle_sha256: String,
    pub(crate) citation_sha256: String,
    canonical: bool,
    requires_review: bool,
}

impl CoordinatorProposalBundle {
    fn is_valid(&self) -> bool {
        if self.schema_version != 1
            || !valid_sha256(&self.generation_sha256)
            || !valid_sha256(&self.evidence_sha256)
            || self.items.is_empty()
            || self.items.len() > MAXIMUM_ITEMS
            || self.items.iter().any(|item| !item.is_valid())
            || !valid_sha256(&self.bundle_sha256)
            || !valid_sha256(&self.citation_sha256)
            || self.canonical
            || !self.requires_review
        {
            return false;
        }
        let proposals = self
            .items
            .iter()
            .map(|item| item.proposal_id.as_str())
            .collect::<HashSet<_>>();
        proposals.len() == self.items.len()
            && bundle_citation_sha256(&self.items).as_deref() == Some(self.citation_sha256.as_str())
            && bundle_sha256(self).as_deref() == Some(self.bundle_sha256.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum CoordinatorBundleStatus {
    Queued,
    Running,
    CancellationRequested,
    Complete,
    EvidenceUnavailable,
    Cancelled,
    Failed,
}

impl CoordinatorBundleStatus {
    pub(crate) fn is_active(self) -> bool {
        matches!(
            self,
            Self::Queued | Self::Running | Self::CancellationRequested
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CoordinatorBundleJobView {
    schema_version: u16,
    pub(crate) request_id: String,
    pub(crate) status: CoordinatorBundleStatus,
    pub(crate) proposal_bundle: Option<CoordinatorProposalBundle>,
    pub(crate) reason: Option<String>,
}

impl CoordinatorBundleJobView {
    fn is_valid(&self) -> bool {
        if self.schema_version != 1
            || !valid_product_request_id(&self.request_id)
            || self.reason.as_ref().is_some_and(|reason| {
                reason.is_empty()
                    || reason.len() > MAXIMUM_REASON_CHARACTERS
                    || !valid_identifier(reason)
            })
        {
            return false;
        }
        match self.status {
            CoordinatorBundleStatus::Complete => {
                self.reason.is_none()
                    && self
                        .proposal_bundle
                        .as_ref()
                        .is_some_and(CoordinatorProposalBundle::is_valid)
            }
            CoordinatorBundleStatus::Queued
            | CoordinatorBundleStatus::Running
            | CoordinatorBundleStatus::CancellationRequested => {
                self.proposal_bundle.is_none() && self.reason.is_none()
            }
            CoordinatorBundleStatus::EvidenceUnavailable
            | CoordinatorBundleStatus::Cancelled
            | CoordinatorBundleStatus::Failed => {
                self.proposal_bundle.is_none() && self.reason.is_some()
            }
        }
    }

    pub(crate) fn matches_request(&self, request: &CoordinatorRequest) -> bool {
        self.proposal_bundle.as_ref().is_none_or(|bundle| {
            bundle.items.len() <= request.maximum_items as usize
                && request
                    .expected_generation_sha256
                    .as_ref()
                    .is_none_or(|expected| expected == &bundle.generation_sha256)
        })
    }

    #[cfg(test)]
    pub(crate) fn for_test(
        request_id: String,
        status: CoordinatorBundleStatus,
        reason: Option<String>,
    ) -> Self {
        let view = Self {
            schema_version: 1,
            request_id,
            status,
            proposal_bundle: None,
            reason,
        };
        assert!(view.is_valid());
        view
    }
}

#[derive(Debug)]
pub(crate) enum CoordinatorClientError {
    InvalidRequest,
    InvalidOrigin,
    InvalidIdentifier,
    Authorization(RequestAuthorizationError),
    Transport,
    Api {
        status: StatusCode,
        code: String,
        retryable: bool,
    },
    MalformedResponse,
    ResponseTooLarge,
}

impl std::fmt::Display for CoordinatorClientError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::InvalidRequest => "The coordination-bundle request is invalid.",
            Self::InvalidOrigin => "The coordination-bundle server origin is invalid.",
            Self::InvalidIdentifier => "The coordination-bundle identity is invalid.",
            Self::Authorization(
                RequestAuthorizationError::Unavailable
                | RequestAuthorizationError::InvalidToken
                | RequestAuthorizationError::AccountChanged,
            ) => "The organization sign-in or server connection changed.",
            Self::Transport => "The organization coordination-bundle server is unavailable.",
            Self::Api {
                status,
                code,
                retryable,
            } => {
                return write!(
                    formatter,
                    "Coordination-bundle request was rejected ({status}, {code}, retryable={retryable})."
                );
            }
            Self::MalformedResponse => "The coordination-bundle response is invalid.",
            Self::ResponseTooLarge => "The coordination-bundle response is too large.",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for CoordinatorClientError {}

#[derive(Clone)]
pub(crate) struct CoordinatorApiClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}

impl CoordinatorApiClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, CoordinatorClientError> {
        let mut base_url =
            Url::parse(base_url).map_err(|_| CoordinatorClientError::InvalidOrigin)?;
        if !matches!(base_url.scheme(), "http" | "https")
            || base_url.cannot_be_a_base()
            || base_url.username() != ""
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            return Err(CoordinatorClientError::InvalidOrigin);
        }
        base_url.set_path("/");
        Ok(Self {
            authenticated,
            base_url,
        })
    }

    pub(crate) async fn submit(
        &self,
        request: &CoordinatorRequest,
    ) -> Result<CoordinatorBundleJobView, CoordinatorClientError> {
        if !request.is_valid() {
            return Err(CoordinatorClientError::InvalidRequest);
        }
        let body =
            serde_json::to_vec(request).map_err(|_| CoordinatorClientError::InvalidRequest)?;
        let response = self
            .authenticated
            .send(
                self.authenticated
                    .post(self.endpoint(None)?)
                    .header(reqwest::header::ACCEPT, "application/json")
                    .header(reqwest::header::CONTENT_TYPE, "application/json")
                    .body(body),
            )
            .await
            .map_err(map_dispatch)?;
        let view = decode_response(response, &[StatusCode::ACCEPTED]).await?;
        if !view.matches_request(request) {
            return Err(CoordinatorClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn status(
        &self,
        request_id: &str,
    ) -> Result<CoordinatorBundleJobView, CoordinatorClientError> {
        let response = self
            .authenticated
            .send(
                self.authenticated
                    .get(self.endpoint(Some(request_id))?)
                    .header(reqwest::header::ACCEPT, "application/json"),
            )
            .await
            .map_err(map_dispatch)?;
        let view = decode_response(response, &[StatusCode::OK]).await?;
        if view.request_id != request_id {
            return Err(CoordinatorClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn cancel(
        &self,
        request_id: &str,
    ) -> Result<CoordinatorBundleJobView, CoordinatorClientError> {
        let response = self
            .authenticated
            .send(
                self.authenticated
                    .delete(self.endpoint(Some(request_id))?)
                    .header(reqwest::header::ACCEPT, "application/json"),
            )
            .await
            .map_err(map_dispatch)?;
        let view = decode_response(response, &[StatusCode::ACCEPTED]).await?;
        if view.request_id != request_id {
            return Err(CoordinatorClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) fn base_url_identity(&self) -> &str {
        self.base_url.as_str()
    }

    fn endpoint(&self, request_id: Option<&str>) -> Result<Url, CoordinatorClientError> {
        if request_id.is_some_and(|value| !valid_product_request_id(value)) {
            return Err(CoordinatorClientError::InvalidIdentifier);
        }
        let mut url = self.base_url.clone();
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| CoordinatorClientError::InvalidOrigin)?;
            path.clear().push("v1").push("coordinator-bundles");
            if let Some(request_id) = request_id {
                path.push(request_id);
            }
        }
        Ok(url)
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ApiError {
    code: String,
    message: String,
    retryable: bool,
    request_id: String,
}

async fn decode_response(
    mut response: AuthenticatedResponse,
    successes: &[StatusCode],
) -> Result<CoordinatorBundleJobView, CoordinatorClientError> {
    let status = response
        .status()
        .map_err(CoordinatorClientError::Authorization)?;
    let body = read_bounded(&mut response).await?;
    if !successes.contains(&status) {
        let error: ApiError =
            serde_json::from_slice(&body).map_err(|_| CoordinatorClientError::MalformedResponse)?;
        if !valid_identifier(&error.code)
            || error.message.is_empty()
            || error.message.len() > 512
            || !error.request_id.starts_with("req-")
            || !valid_identifier(&error.request_id)
        {
            return Err(CoordinatorClientError::MalformedResponse);
        }
        return Err(CoordinatorClientError::Api {
            status,
            code: error.code,
            retryable: error.retryable,
        });
    }
    let view = decode_job_view(body)?;
    response
        .ensure_current()
        .map_err(CoordinatorClientError::Authorization)?;
    Ok(view)
}

fn decode_job_view(body: Vec<u8>) -> Result<CoordinatorBundleJobView, CoordinatorClientError> {
    let view: CoordinatorBundleJobView =
        serde_json::from_slice(&body).map_err(|_| CoordinatorClientError::MalformedResponse)?;
    if !view.is_valid() {
        return Err(CoordinatorClientError::MalformedResponse);
    }
    Ok(view)
}

async fn read_bounded(
    response: &mut AuthenticatedResponse,
) -> Result<Vec<u8>, CoordinatorClientError> {
    if response
        .content_length()
        .map_err(CoordinatorClientError::Authorization)?
        .is_some_and(|length| length > MAXIMUM_RESPONSE_BYTES as u64)
    {
        return Err(CoordinatorClientError::ResponseTooLarge);
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(map_dispatch)? {
        if body.len().saturating_add(chunk.len()) > MAXIMUM_RESPONSE_BYTES {
            return Err(CoordinatorClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn map_dispatch(error: AuthenticatedDispatchError) -> CoordinatorClientError {
    match error {
        AuthenticatedDispatchError::Authorization(error) => {
            CoordinatorClientError::Authorization(error)
        }
        AuthenticatedDispatchError::Transport(_) => CoordinatorClientError::Transport,
    }
}

fn citation_identity(citation: &CoordinatorCitation) -> (&str, &str, &str, u64, u64) {
    (
        citation.concept_id.as_str(),
        citation.source_revision.as_str(),
        citation.content_sha256.as_str(),
        citation.char_start,
        citation.char_end,
    )
}

fn citation_sha256(citations: &[CoordinatorCitation]) -> Option<String> {
    let value = citations
        .iter()
        .map(|citation| {
            serde_json::json!({
                "charEnd": citation.char_end,
                "charStart": citation.char_start,
                "conceptId": citation.concept_id,
                "contentSha256": citation.content_sha256,
                "sourceRevision": citation.source_revision,
                "text": citation.text,
            })
        })
        .collect::<Vec<_>>();
    canonical_sha256(&value)
}

fn bundle_citation_sha256(items: &[CoordinatorProposalBundleItem]) -> Option<String> {
    let value = items
        .iter()
        .map(|item| {
            serde_json::json!({
                "citations": item.citations,
                "proposalId": item.proposal_id,
            })
        })
        .collect::<Vec<_>>();
    canonical_sha256(&value)
}

fn bundle_sha256(bundle: &CoordinatorProposalBundle) -> Option<String> {
    canonical_sha256(&serde_json::json!({
        "canonical": false,
        "citationSha256": bundle.citation_sha256,
        "evidenceSha256": bundle.evidence_sha256,
        "generationSha256": bundle.generation_sha256,
        "items": bundle.items,
        "requiresReview": true,
        "schemaVersion": 1,
    }))
}

fn canonical_sha256(value: &impl Serialize) -> Option<String> {
    let encoded = serde_json::to_vec(value).ok()?;
    Some(hex_sha256(&encoded))
}

fn hex_sha256(value: &[u8]) -> String {
    Sha256::digest(value)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

fn valid_product_request_id(value: &str) -> bool {
    value
        .strip_prefix("coordinator-bundle-")
        .is_some_and(|suffix| {
            suffix.len() == 32
                && suffix
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
        })
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

#[cfg(test)]
mod tests;
