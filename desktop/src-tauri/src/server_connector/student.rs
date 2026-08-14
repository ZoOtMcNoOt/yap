use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};

use super::authorization::{
    AuthenticatedDispatchError, AuthenticatedRequestDispatcher, AuthenticatedResponse,
    RequestAuthorizationError,
};

const MAXIMUM_RESPONSE_BYTES: usize = 256 * 1024;
const MAXIMUM_TOPIC_CHARACTERS: usize = 128;
const MAXIMUM_SUBJECT_CHARACTERS: usize = 256;
const MAXIMUM_QUESTION_CHARACTERS: usize = 512;
const MAXIMUM_SUPPORT_QUOTE_CHARACTERS: usize = 1_024;
const MAXIMUM_REASON_CHARACTERS: usize = 64;
const QUESTION_PREFIX: &str = "What should you remember about ";

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct StudentRequest {
    schema_version: u16,
    conversation_concept_id: String,
    expected_generation_sha256: String,
    topic: String,
}

impl StudentRequest {
    pub(crate) fn new(
        conversation_concept_id: String,
        expected_generation_sha256: String,
        topic: String,
    ) -> Result<Self, StudentClientError> {
        let request = Self {
            schema_version: 2,
            conversation_concept_id,
            expected_generation_sha256,
            topic,
        };
        if !request.is_valid() {
            return Err(StudentClientError::InvalidRequest);
        }
        Ok(request)
    }

    fn is_valid(&self) -> bool {
        self.schema_version == 2
            && valid_conversation_concept_id(&self.conversation_concept_id)
            && valid_sha256(&self.expected_generation_sha256)
            && !self.topic.is_empty()
            && self.topic.trim() == self.topic
            && self.topic.chars().count() <= MAXIMUM_TOPIC_CHARACTERS
            && !self.topic.contains(['?', '\r', '\n'])
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct StudentSourceCitation {
    pub(crate) concept_id: String,
    pub(crate) source_revision: String,
    pub(crate) content_sha256: String,
    pub(crate) char_start: u64,
    pub(crate) char_end: u64,
}

impl StudentSourceCitation {
    fn is_valid(&self) -> bool {
        valid_conversation_concept_id(&self.concept_id)
            && valid_sha256(&self.source_revision)
            && valid_sha256(&self.content_sha256)
            && self.char_end > self.char_start
            && self.char_end <= i64::MAX as u64
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct StudentQuestionSupport {
    pub(crate) source_citation: StudentSourceCitation,
    pub(crate) support_quote: String,
    pub(crate) support_char_start: u64,
    pub(crate) support_char_end: u64,
}

impl StudentQuestionSupport {
    fn is_valid(&self, conversation_concept_id: &str, source_subject: &str) -> bool {
        self.source_citation.is_valid()
            && self.source_citation.concept_id == conversation_concept_id
            && !self.support_quote.is_empty()
            && self.support_quote.trim() == self.support_quote
            && self
                .support_quote
                .chars()
                .all(|character| !character.is_control())
            && self.support_quote.chars().count() <= MAXIMUM_SUPPORT_QUOTE_CHARACTERS
            && self.support_quote.match_indices(source_subject).count() == 1
            && self.support_char_start >= self.source_citation.char_start
            && self.support_char_end <= self.source_citation.char_end
            && self.support_char_end > self.support_char_start
            && self.support_char_end - self.support_char_start
                == self.support_quote.chars().count() as u64
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct StudentQuestion {
    schema_version: u16,
    pub(crate) source_subject: String,
    pub(crate) question: String,
    pub(crate) source_supports: Vec<StudentQuestionSupport>,
}

impl StudentQuestion {
    fn is_valid(&self, conversation_concept_id: &str) -> bool {
        self.schema_version == 3
            && !self.source_subject.is_empty()
            && self.source_subject.trim() == self.source_subject
            && self.source_subject.chars().count() <= MAXIMUM_SUBJECT_CHARACTERS
            && self
                .source_subject
                .chars()
                .all(|character| !character.is_control())
            && !self.source_subject.contains('?')
            && self.question == format!("{QUESTION_PREFIX}{}?", self.source_subject)
            && self.question.chars().count() <= MAXIMUM_QUESTION_CHARACTERS
            && self.source_supports.len() == 1
            && self.source_supports[0].is_valid(conversation_concept_id, &self.source_subject)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum StudentQuestionStatus {
    Queued,
    Running,
    CancellationRequested,
    Complete,
    EvidenceUnavailable,
    Cancelled,
    Failed,
}

impl StudentQuestionStatus {
    pub(crate) fn is_active(self) -> bool {
        matches!(
            self,
            Self::Queued | Self::Running | Self::CancellationRequested
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct StudentQuestionJobView {
    schema_version: u16,
    pub(crate) request_id: String,
    pub(crate) status: StudentQuestionStatus,
    pub(crate) conversation_concept_id: String,
    pub(crate) generation_sha256: String,
    pub(crate) evidence_sha256: Option<String>,
    pub(crate) questions: Vec<StudentQuestion>,
    pub(crate) output_budget_exhausted: bool,
    pub(crate) reason: Option<String>,
}

impl StudentQuestionJobView {
    fn is_valid(&self) -> bool {
        if self.schema_version != 1
            || !valid_product_request_id(&self.request_id)
            || !valid_conversation_concept_id(&self.conversation_concept_id)
            || !valid_sha256(&self.generation_sha256)
            || self
                .evidence_sha256
                .as_ref()
                .is_some_and(|value| !valid_sha256(value))
            || self.reason.as_ref().is_some_and(|reason| {
                reason.is_empty()
                    || reason.len() > MAXIMUM_REASON_CHARACTERS
                    || !valid_identifier(reason)
            })
            || self
                .questions
                .iter()
                .any(|question| !question.is_valid(&self.conversation_concept_id))
        {
            return false;
        }
        match self.status {
            StudentQuestionStatus::Complete => {
                self.reason.is_none() && self.evidence_sha256.is_some() && self.questions.len() == 1
            }
            StudentQuestionStatus::Queued
            | StudentQuestionStatus::Running
            | StudentQuestionStatus::CancellationRequested => {
                self.evidence_sha256.is_none()
                    && self.questions.is_empty()
                    && !self.output_budget_exhausted
                    && self.reason.is_none()
            }
            StudentQuestionStatus::EvidenceUnavailable
            | StudentQuestionStatus::Cancelled
            | StudentQuestionStatus::Failed => self.questions.is_empty() && self.reason.is_some(),
        }
    }

    pub(crate) fn matches_request(&self, request: &StudentRequest) -> bool {
        self.conversation_concept_id == request.conversation_concept_id
            && self.generation_sha256 == request.expected_generation_sha256
    }

    #[cfg(test)]
    pub(crate) fn for_test(
        request_id: String,
        status: StudentQuestionStatus,
        reason: Option<String>,
    ) -> Self {
        let view = Self {
            schema_version: 1,
            request_id,
            status,
            conversation_concept_id: "meetings/job-1".into(),
            generation_sha256: "a".repeat(64),
            evidence_sha256: None,
            questions: Vec::new(),
            output_budget_exhausted: false,
            reason,
        };
        assert!(view.is_valid());
        view
    }
}

#[derive(Debug)]
pub(crate) enum StudentClientError {
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

impl std::fmt::Display for StudentClientError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::InvalidRequest => "The learning-question request is invalid.",
            Self::InvalidOrigin => "The learning-question server origin is invalid.",
            Self::InvalidIdentifier => "The learning-question identity is invalid.",
            Self::Authorization(
                RequestAuthorizationError::Unavailable
                | RequestAuthorizationError::InvalidToken
                | RequestAuthorizationError::AccountChanged,
            ) => "The organization sign-in or server connection changed.",
            Self::Transport => "The organization learning-question server is unavailable.",
            Self::Api {
                status,
                code,
                retryable,
            } => {
                return write!(
                    formatter,
                    "Learning-question request was rejected ({status}, {code}, retryable={retryable})."
                );
            }
            Self::MalformedResponse => "The learning-question response is invalid.",
            Self::ResponseTooLarge => "The learning-question response is too large.",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for StudentClientError {}

#[derive(Clone)]
pub(crate) struct StudentApiClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}

impl StudentApiClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, StudentClientError> {
        let mut base_url = Url::parse(base_url).map_err(|_| StudentClientError::InvalidOrigin)?;
        if !matches!(base_url.scheme(), "http" | "https")
            || base_url.cannot_be_a_base()
            || base_url.username() != ""
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            return Err(StudentClientError::InvalidOrigin);
        }
        base_url.set_path("/");
        Ok(Self {
            authenticated,
            base_url,
        })
    }

    pub(crate) async fn submit(
        &self,
        request: &StudentRequest,
    ) -> Result<StudentQuestionJobView, StudentClientError> {
        if !request.is_valid() {
            return Err(StudentClientError::InvalidRequest);
        }
        let body = serde_json::to_vec(request).map_err(|_| StudentClientError::InvalidRequest)?;
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
            return Err(StudentClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn status(
        &self,
        request_id: &str,
    ) -> Result<StudentQuestionJobView, StudentClientError> {
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
    ) -> Result<StudentQuestionJobView, StudentClientError> {
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

    fn endpoint(&self, request_id: Option<&str>) -> Result<Url, StudentClientError> {
        if request_id.is_some_and(|value| !valid_product_request_id(value)) {
            return Err(StudentClientError::InvalidIdentifier);
        }
        let mut url = self.base_url.clone();
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| StudentClientError::InvalidOrigin)?;
            path.clear().push("v1").push("student-questions");
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
) -> Result<StudentQuestionJobView, StudentClientError> {
    let status = response
        .status()
        .map_err(StudentClientError::Authorization)?;
    let body = read_bounded(&mut response).await?;
    if !successes.contains(&status) {
        let error: ApiError =
            serde_json::from_slice(&body).map_err(|_| StudentClientError::MalformedResponse)?;
        if !valid_identifier(&error.code)
            || error.message.is_empty()
            || error.message.len() > 512
            || !error.request_id.starts_with("req-")
            || !valid_identifier(&error.request_id)
        {
            return Err(StudentClientError::MalformedResponse);
        }
        return Err(StudentClientError::Api {
            status,
            code: error.code,
            retryable: error.retryable,
        });
    }
    let view = decode_job_view(body)?;
    response
        .ensure_current()
        .map_err(StudentClientError::Authorization)?;
    Ok(view)
}

fn decode_job_view(body: Vec<u8>) -> Result<StudentQuestionJobView, StudentClientError> {
    let view: StudentQuestionJobView =
        serde_json::from_slice(&body).map_err(|_| StudentClientError::MalformedResponse)?;
    if !view.is_valid() {
        return Err(StudentClientError::MalformedResponse);
    }
    Ok(view)
}

async fn read_bounded(response: &mut AuthenticatedResponse) -> Result<Vec<u8>, StudentClientError> {
    if response
        .content_length()
        .map_err(StudentClientError::Authorization)?
        .is_some_and(|length| length > MAXIMUM_RESPONSE_BYTES as u64)
    {
        return Err(StudentClientError::ResponseTooLarge);
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(map_dispatch)? {
        if body.len().saturating_add(chunk.len()) > MAXIMUM_RESPONSE_BYTES {
            return Err(StudentClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn map_dispatch(error: AuthenticatedDispatchError) -> StudentClientError {
    match error {
        AuthenticatedDispatchError::Authorization(error) => {
            StudentClientError::Authorization(error)
        }
        AuthenticatedDispatchError::Transport(_) => StudentClientError::Transport,
    }
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

fn valid_conversation_concept_id(value: &str) -> bool {
    value.strip_prefix("meetings/").is_some_and(|suffix| {
        !suffix.is_empty()
            && suffix.len() <= 128
            && suffix.as_bytes()[0].is_ascii_alphanumeric()
            && suffix
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    })
}

fn valid_product_request_id(value: &str) -> bool {
    value
        .strip_prefix("student-question-")
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
