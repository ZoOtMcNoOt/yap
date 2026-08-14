use std::collections::HashSet;

use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::authorization::{
    AuthenticatedDispatchError, AuthenticatedRequestDispatcher, AuthenticatedResponse,
    RequestAuthorizationError,
};

const MAXIMUM_RESPONSE_BYTES: usize = 256 * 1024;
const MAXIMUM_QUESTION_CHARACTERS: usize = 1_024;
const MAXIMUM_RESULTS: usize = 5;
const MAXIMUM_ANSWER_CHARACTERS: usize = 2_008;
const MAXIMUM_CITATION_TEXT_CHARACTERS: usize = 2_000;
const MAXIMUM_CONCEPT_CHARACTERS: usize = 512;
const MAXIMUM_SOURCE_REVISION_CHARACTERS: usize = 512;
const MAXIMUM_REASON_CHARACTERS: usize = 64;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AnalystRequest {
    schema_version: u16,
    question: String,
    maximum_results: u8,
    expected_generation_sha256: Option<String>,
}

impl AnalystRequest {
    pub(crate) fn new(
        question: String,
        maximum_results: u8,
        expected_generation_sha256: Option<String>,
    ) -> Result<Self, AnalystClientError> {
        let request = Self {
            schema_version: 1,
            question,
            maximum_results,
            expected_generation_sha256,
        };
        if !request.is_valid() {
            return Err(AnalystClientError::InvalidRequest);
        }
        Ok(request)
    }

    fn is_valid(&self) -> bool {
        self.schema_version == 1
            && !self.question.is_empty()
            && self.question.trim() == self.question
            && self.question.chars().count() <= MAXIMUM_QUESTION_CHARACTERS
            && self
                .question
                .chars()
                .any(|character| character.is_alphanumeric())
            && (1..=MAXIMUM_RESULTS as u8).contains(&self.maximum_results)
            && self
                .expected_generation_sha256
                .as_ref()
                .is_none_or(|value| valid_sha256(value))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct AnalystCitation {
    pub(crate) concept_id: String,
    pub(crate) source_revision: String,
    pub(crate) content_sha256: String,
    pub(crate) char_start: u64,
    pub(crate) char_end: u64,
    pub(crate) text: String,
}

impl AnalystCitation {
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
pub(crate) struct AnalystAnswer {
    schema_version: u16,
    pub(crate) answer: String,
    pub(crate) citations: Vec<AnalystCitation>,
    pub(crate) answer_sha256: String,
    pub(crate) citation_sha256: String,
    pub(crate) evidence_sha256: String,
}

impl AnalystAnswer {
    fn is_valid(&self) -> bool {
        if self.schema_version != 1
            || self.answer.is_empty()
            || self.answer.chars().count() > MAXIMUM_ANSWER_CHARACTERS
            || self.citations.is_empty()
            || self.citations.len() > MAXIMUM_RESULTS
            || self.citations.iter().any(|citation| !citation.is_valid())
            || !valid_sha256(&self.answer_sha256)
            || !valid_sha256(&self.citation_sha256)
            || !valid_sha256(&self.evidence_sha256)
        {
            return false;
        }
        let identities = self
            .citations
            .iter()
            .map(|citation| {
                (
                    citation.concept_id.as_str(),
                    citation.source_revision.as_str(),
                    citation.content_sha256.as_str(),
                    citation.char_start,
                    citation.char_end,
                )
            })
            .collect::<HashSet<_>>();
        let expected_answer = self
            .citations
            .iter()
            .map(|citation| citation.text.as_str())
            .collect::<Vec<_>>()
            .join("\n\n");
        identities.len() == self.citations.len()
            && self.answer == expected_answer
            && text_sha256(&self.answer) == self.answer_sha256
            && citation_sha256(&self.citations).as_deref() == Some(self.citation_sha256.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum AnalystAnswerStatus {
    Queued,
    Running,
    CancellationRequested,
    Complete,
    EvidenceUnavailable,
    Cancelled,
    Failed,
}

impl AnalystAnswerStatus {
    pub(crate) fn is_active(self) -> bool {
        matches!(
            self,
            Self::Queued | Self::Running | Self::CancellationRequested
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct AnalystAnswerJobView {
    schema_version: u16,
    pub(crate) request_id: String,
    pub(crate) status: AnalystAnswerStatus,
    pub(crate) cited_answer: Option<AnalystAnswer>,
    pub(crate) reason: Option<String>,
}

impl AnalystAnswerJobView {
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
            AnalystAnswerStatus::Complete => {
                self.reason.is_none()
                    && self
                        .cited_answer
                        .as_ref()
                        .is_some_and(AnalystAnswer::is_valid)
            }
            AnalystAnswerStatus::Queued
            | AnalystAnswerStatus::Running
            | AnalystAnswerStatus::CancellationRequested => {
                self.cited_answer.is_none() && self.reason.is_none()
            }
            AnalystAnswerStatus::EvidenceUnavailable
            | AnalystAnswerStatus::Cancelled
            | AnalystAnswerStatus::Failed => self.cited_answer.is_none() && self.reason.is_some(),
        }
    }

    pub(crate) fn matches_request(&self, request: &AnalystRequest) -> bool {
        self.cited_answer
            .as_ref()
            .is_none_or(|answer| answer.citations.len() <= request.maximum_results as usize)
    }

    #[cfg(test)]
    pub(crate) fn for_test(
        request_id: String,
        status: AnalystAnswerStatus,
        reason: Option<String>,
    ) -> Self {
        let view = Self {
            schema_version: 1,
            request_id,
            status,
            cited_answer: None,
            reason,
        };
        assert!(view.is_valid());
        view
    }
}

#[derive(Debug)]
pub(crate) enum AnalystClientError {
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

impl std::fmt::Display for AnalystClientError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::InvalidRequest => "The cited-answer request is invalid.",
            Self::InvalidOrigin => "The cited-answer server origin is invalid.",
            Self::InvalidIdentifier => "The cited-answer identity is invalid.",
            Self::Authorization(
                RequestAuthorizationError::Unavailable
                | RequestAuthorizationError::InvalidToken
                | RequestAuthorizationError::AccountChanged,
            ) => "The organization sign-in or server connection changed.",
            Self::Transport => "The organization cited-answer server is unavailable.",
            Self::Api {
                status,
                code,
                retryable,
            } => {
                return write!(
                    formatter,
                    "Cited-answer request was rejected ({status}, {code}, retryable={retryable})."
                );
            }
            Self::MalformedResponse => "The cited-answer response is invalid.",
            Self::ResponseTooLarge => "The cited-answer response is too large.",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for AnalystClientError {}

#[derive(Clone)]
pub(crate) struct AnalystApiClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}

impl AnalystApiClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, AnalystClientError> {
        let mut base_url = Url::parse(base_url).map_err(|_| AnalystClientError::InvalidOrigin)?;
        if !matches!(base_url.scheme(), "http" | "https")
            || base_url.cannot_be_a_base()
            || base_url.username() != ""
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            return Err(AnalystClientError::InvalidOrigin);
        }
        base_url.set_path("/");
        Ok(Self {
            authenticated,
            base_url,
        })
    }

    pub(crate) async fn submit(
        &self,
        request: &AnalystRequest,
    ) -> Result<AnalystAnswerJobView, AnalystClientError> {
        if !request.is_valid() {
            return Err(AnalystClientError::InvalidRequest);
        }
        let body = serde_json::to_vec(request).map_err(|_| AnalystClientError::InvalidRequest)?;
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
            return Err(AnalystClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn status(
        &self,
        request_id: &str,
    ) -> Result<AnalystAnswerJobView, AnalystClientError> {
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
            return Err(AnalystClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn cancel(
        &self,
        request_id: &str,
    ) -> Result<AnalystAnswerJobView, AnalystClientError> {
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
            return Err(AnalystClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) fn base_url_identity(&self) -> &str {
        self.base_url.as_str()
    }

    fn endpoint(&self, request_id: Option<&str>) -> Result<Url, AnalystClientError> {
        if request_id.is_some_and(|value| !valid_product_request_id(value)) {
            return Err(AnalystClientError::InvalidIdentifier);
        }
        let mut url = self.base_url.clone();
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| AnalystClientError::InvalidOrigin)?;
            path.clear().push("v1").push("analyst-answers");
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
) -> Result<AnalystAnswerJobView, AnalystClientError> {
    let status = response
        .status()
        .map_err(AnalystClientError::Authorization)?;
    let body = read_bounded(&mut response).await?;
    if !successes.contains(&status) {
        let error: ApiError =
            serde_json::from_slice(&body).map_err(|_| AnalystClientError::MalformedResponse)?;
        if !valid_identifier(&error.code)
            || error.message.is_empty()
            || error.message.len() > 512
            || !error.request_id.starts_with("req-")
            || !valid_identifier(&error.request_id)
        {
            return Err(AnalystClientError::MalformedResponse);
        }
        return Err(AnalystClientError::Api {
            status,
            code: error.code,
            retryable: error.retryable,
        });
    }
    let view = decode_job_view(body)?;
    response
        .ensure_current()
        .map_err(AnalystClientError::Authorization)?;
    Ok(view)
}

fn decode_job_view(body: Vec<u8>) -> Result<AnalystAnswerJobView, AnalystClientError> {
    let view: AnalystAnswerJobView =
        serde_json::from_slice(&body).map_err(|_| AnalystClientError::MalformedResponse)?;
    if !view.is_valid() {
        return Err(AnalystClientError::MalformedResponse);
    }
    Ok(view)
}

async fn read_bounded(response: &mut AuthenticatedResponse) -> Result<Vec<u8>, AnalystClientError> {
    if response
        .content_length()
        .map_err(AnalystClientError::Authorization)?
        .is_some_and(|length| length > MAXIMUM_RESPONSE_BYTES as u64)
    {
        return Err(AnalystClientError::ResponseTooLarge);
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(map_dispatch)? {
        if body.len().saturating_add(chunk.len()) > MAXIMUM_RESPONSE_BYTES {
            return Err(AnalystClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn map_dispatch(error: AuthenticatedDispatchError) -> AnalystClientError {
    match error {
        AuthenticatedDispatchError::Authorization(error) => {
            AnalystClientError::Authorization(error)
        }
        AuthenticatedDispatchError::Transport(_) => AnalystClientError::Transport,
    }
}

fn citation_sha256(citations: &[AnalystCitation]) -> Option<String> {
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
    let encoded = serde_json::to_vec(&value).ok()?;
    Some(hex_sha256(&encoded))
}

fn text_sha256(value: &str) -> String {
    hex_sha256(value.as_bytes())
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
    value.strip_prefix("analyst-answer-").is_some_and(|suffix| {
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
