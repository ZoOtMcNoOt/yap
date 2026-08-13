use std::collections::HashSet;

use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::authorization::{
    AuthenticatedDispatchError, AuthenticatedRequestDispatcher, AuthenticatedResponse,
    RequestAuthorizationError,
};

const MAXIMUM_RESPONSE_BYTES: usize = 256 * 1024;
const MAXIMUM_SEARCH_CHARACTERS: usize = 1_024;
const MAXIMUM_RESULTS: usize = 5;
const MAXIMUM_EVIDENCE_CHARACTERS: usize = 2_000;
const MAXIMUM_EVIDENCE_WIRE_BYTES: usize = 8_192;
const MAXIMUM_CONCEPT_CHARACTERS: usize = 512;
const MAXIMUM_SOURCE_REVISION_CHARACTERS: usize = 512;
const MAXIMUM_REASON_CHARACTERS: usize = 64;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LibrarianRequest {
    schema_version: u16,
    search_text: String,
    maximum_results: u8,
    expected_generation_sha256: Option<String>,
}

impl LibrarianRequest {
    pub(crate) fn new(
        search_text: String,
        maximum_results: u8,
        expected_generation_sha256: Option<String>,
    ) -> Result<Self, LibrarianClientError> {
        let request = Self {
            schema_version: 1,
            search_text,
            maximum_results,
            expected_generation_sha256,
        };
        if !request.is_valid() {
            return Err(LibrarianClientError::InvalidRequest);
        }
        Ok(request)
    }

    fn is_valid(&self) -> bool {
        self.schema_version == 1
            && !self.search_text.is_empty()
            && self.search_text.trim() == self.search_text
            && self.search_text.chars().count() <= MAXIMUM_SEARCH_CHARACTERS
            && self
                .search_text
                .chars()
                .any(|character| character.is_alphanumeric())
            && (1..=MAXIMUM_RESULTS as u8).contains(&self.maximum_results)
            && self
                .expected_generation_sha256
                .as_ref()
                .is_none_or(|value| valid_sha256(value))
    }

    pub(crate) fn expected_generation_sha256(&self) -> Option<&str> {
        self.expected_generation_sha256.as_deref()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LibrarianEvidenceItem {
    pub(crate) concept_id: String,
    pub(crate) source_revision: String,
    pub(crate) content_sha256: String,
    pub(crate) char_start: u64,
    pub(crate) char_end: u64,
    pub(crate) text: String,
}

impl LibrarianEvidenceItem {
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
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LibrarianEvidencePack {
    operation: String,
    pub(crate) generation_sha256: String,
    pub(crate) permission_hash: String,
    pub(crate) authorization_hash: String,
    pub(crate) evidence_sha256: String,
    pub(crate) items: Vec<LibrarianEvidenceItem>,
    pub(crate) output_budget_exhausted: bool,
}

impl LibrarianEvidencePack {
    fn is_valid(&self) -> bool {
        if self.operation != "search"
            || !valid_sha256(&self.generation_sha256)
            || !valid_sha256(&self.permission_hash)
            || !valid_sha256(&self.authorization_hash)
            || !valid_sha256(&self.evidence_sha256)
            || self.items.is_empty()
            || self.items.len() > MAXIMUM_RESULTS
            || self.items.iter().any(|item| !item.is_valid())
        {
            return false;
        }
        let identities = self
            .items
            .iter()
            .map(|item| {
                (
                    item.concept_id.as_str(),
                    item.source_revision.as_str(),
                    item.content_sha256.as_str(),
                    item.char_start,
                    item.char_end,
                )
            })
            .collect::<HashSet<_>>();
        let characters = self.items.iter().try_fold(0_usize, |total, item| {
            total
                .checked_add(item.concept_id.chars().count())?
                .checked_add(item.source_revision.chars().count())?
                .checked_add(item.content_sha256.len())?
                .checked_add(item.text.chars().count())
        });
        identities.len() == self.items.len()
            && characters.is_some_and(|value| value <= MAXIMUM_EVIDENCE_CHARACTERS)
            && serde_json::to_vec(self).is_ok_and(|wire| wire.len() <= MAXIMUM_EVIDENCE_WIRE_BYTES)
            && evidence_sha256(self).as_deref() == Some(self.evidence_sha256.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum LibrarianQueryStatus {
    Queued,
    Running,
    CancellationRequested,
    Complete,
    EvidenceUnavailable,
    Cancelled,
    Failed,
}

impl LibrarianQueryStatus {
    pub(crate) fn is_active(self) -> bool {
        matches!(
            self,
            Self::Queued | Self::Running | Self::CancellationRequested
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LibrarianQueryJobView {
    schema_version: u16,
    pub(crate) request_id: String,
    pub(crate) status: LibrarianQueryStatus,
    pub(crate) evidence_pack: Option<LibrarianEvidencePack>,
    pub(crate) reason: Option<String>,
}

impl LibrarianQueryJobView {
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
            LibrarianQueryStatus::Complete => {
                self.reason.is_none()
                    && self
                        .evidence_pack
                        .as_ref()
                        .is_some_and(LibrarianEvidencePack::is_valid)
            }
            LibrarianQueryStatus::Queued
            | LibrarianQueryStatus::Running
            | LibrarianQueryStatus::CancellationRequested => {
                self.evidence_pack.is_none() && self.reason.is_none()
            }
            LibrarianQueryStatus::EvidenceUnavailable
            | LibrarianQueryStatus::Cancelled
            | LibrarianQueryStatus::Failed => self.evidence_pack.is_none() && self.reason.is_some(),
        }
    }

    pub(crate) fn matches_request(&self, request: &LibrarianRequest) -> bool {
        self.evidence_pack.as_ref().is_none_or(|evidence| {
            evidence.items.len() <= request.maximum_results as usize
                && request
                    .expected_generation_sha256()
                    .is_none_or(|expected| evidence.generation_sha256 == expected)
        })
    }

    #[cfg(test)]
    pub(crate) fn for_test(
        request_id: String,
        status: LibrarianQueryStatus,
        reason: Option<String>,
    ) -> Self {
        let view = Self {
            schema_version: 1,
            request_id,
            status,
            evidence_pack: None,
            reason,
        };
        assert!(view.is_valid());
        view
    }
}

#[derive(Debug)]
pub(crate) enum LibrarianClientError {
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

impl std::fmt::Display for LibrarianClientError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::InvalidRequest => "The knowledge query is invalid.",
            Self::InvalidOrigin => "The knowledge query server origin is invalid.",
            Self::InvalidIdentifier => "The knowledge query identity is invalid.",
            Self::Authorization(
                RequestAuthorizationError::Unavailable
                | RequestAuthorizationError::InvalidToken
                | RequestAuthorizationError::AccountChanged,
            ) => "The organization sign-in or server connection changed.",
            Self::Transport => "The organization knowledge server is unavailable.",
            Self::Api {
                status,
                code,
                retryable,
            } => {
                return write!(
                    formatter,
                    "Knowledge query was rejected ({status}, {code}, retryable={retryable})."
                );
            }
            Self::MalformedResponse => "The knowledge query response is invalid.",
            Self::ResponseTooLarge => "The knowledge query response is too large.",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for LibrarianClientError {}

#[derive(Clone)]
pub(crate) struct LibrarianApiClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}

impl LibrarianApiClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, LibrarianClientError> {
        let mut base_url = Url::parse(base_url).map_err(|_| LibrarianClientError::InvalidOrigin)?;
        if !matches!(base_url.scheme(), "http" | "https")
            || base_url.cannot_be_a_base()
            || base_url.username() != ""
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            return Err(LibrarianClientError::InvalidOrigin);
        }
        base_url.set_path("/");
        Ok(Self {
            authenticated,
            base_url,
        })
    }

    pub(crate) async fn submit(
        &self,
        request: &LibrarianRequest,
    ) -> Result<LibrarianQueryJobView, LibrarianClientError> {
        if !request.is_valid() {
            return Err(LibrarianClientError::InvalidRequest);
        }
        let body = serde_json::to_vec(request).map_err(|_| LibrarianClientError::InvalidRequest)?;
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
            return Err(LibrarianClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn status(
        &self,
        request_id: &str,
    ) -> Result<LibrarianQueryJobView, LibrarianClientError> {
        let response = self
            .authenticated
            .send(
                self.authenticated
                    .get(self.endpoint(Some(request_id))?)
                    .header(reqwest::header::ACCEPT, "application/json"),
            )
            .await
            .map_err(map_dispatch)?;
        decode_response(response, &[StatusCode::OK]).await
    }

    pub(crate) async fn cancel(
        &self,
        request_id: &str,
    ) -> Result<LibrarianQueryJobView, LibrarianClientError> {
        let response = self
            .authenticated
            .send(
                self.authenticated
                    .delete(self.endpoint(Some(request_id))?)
                    .header(reqwest::header::ACCEPT, "application/json"),
            )
            .await
            .map_err(map_dispatch)?;
        decode_response(response, &[StatusCode::ACCEPTED]).await
    }

    pub(crate) fn base_url_identity(&self) -> &str {
        self.base_url.as_str()
    }

    fn endpoint(&self, request_id: Option<&str>) -> Result<Url, LibrarianClientError> {
        if request_id.is_some_and(|value| !valid_product_request_id(value)) {
            return Err(LibrarianClientError::InvalidIdentifier);
        }
        let mut url = self.base_url.clone();
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| LibrarianClientError::InvalidOrigin)?;
            path.clear().push("v1").push("librarian-queries");
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
) -> Result<LibrarianQueryJobView, LibrarianClientError> {
    let status = response
        .status()
        .map_err(LibrarianClientError::Authorization)?;
    let body = read_bounded(&mut response).await?;
    if !successes.contains(&status) {
        let error: ApiError =
            serde_json::from_slice(&body).map_err(|_| LibrarianClientError::MalformedResponse)?;
        if !valid_identifier(&error.code)
            || error.message.is_empty()
            || error.message.len() > 512
            || !error.request_id.starts_with("req-")
            || !valid_identifier(&error.request_id)
        {
            return Err(LibrarianClientError::MalformedResponse);
        }
        return Err(LibrarianClientError::Api {
            status,
            code: error.code,
            retryable: error.retryable,
        });
    }
    let view = decode_job_view(body)?;
    response
        .ensure_current()
        .map_err(LibrarianClientError::Authorization)?;
    Ok(view)
}

fn decode_job_view(body: Vec<u8>) -> Result<LibrarianQueryJobView, LibrarianClientError> {
    let view: LibrarianQueryJobView =
        serde_json::from_slice(&body).map_err(|_| LibrarianClientError::MalformedResponse)?;
    if !view.is_valid() {
        return Err(LibrarianClientError::MalformedResponse);
    }
    Ok(view)
}

async fn read_bounded(
    response: &mut AuthenticatedResponse,
) -> Result<Vec<u8>, LibrarianClientError> {
    if response
        .content_length()
        .map_err(LibrarianClientError::Authorization)?
        .is_some_and(|length| length > MAXIMUM_RESPONSE_BYTES as u64)
    {
        return Err(LibrarianClientError::ResponseTooLarge);
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(map_dispatch)? {
        if body.len().saturating_add(chunk.len()) > MAXIMUM_RESPONSE_BYTES {
            return Err(LibrarianClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn map_dispatch(error: AuthenticatedDispatchError) -> LibrarianClientError {
    match error {
        AuthenticatedDispatchError::Authorization(error) => {
            LibrarianClientError::Authorization(error)
        }
        AuthenticatedDispatchError::Transport(_) => LibrarianClientError::Transport,
    }
}

fn evidence_sha256(evidence: &LibrarianEvidencePack) -> Option<String> {
    let value = serde_json::json!({
        "authorizationHash": evidence.authorization_hash,
        "generationSha256": evidence.generation_sha256,
        "items": evidence.items,
        "operation": "search",
        "outputBudgetExhausted": evidence.output_budget_exhausted,
        "permissionHash": evidence.permission_hash,
    });
    let encoded = serde_json::to_vec(&value).ok()?;
    Some(
        Sha256::digest(encoded)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect(),
    )
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

fn valid_product_request_id(value: &str) -> bool {
    value
        .strip_prefix("librarian-query-")
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
