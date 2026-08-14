use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};

use super::authorization::{
    AuthenticatedDispatchError, AuthenticatedRequestDispatcher, AuthenticatedResponse,
    RequestAuthorizationError,
};

const MAXIMUM_RESPONSE_BYTES: usize = 256 * 1024;
const MAXIMUM_REVIEWED_CONTENT_CHARACTERS: usize = 2_048;
const MAXIMUM_SUBJECT_CHARACTERS: usize = 256;
const MAXIMUM_QUESTION_CHARACTERS: usize = 512;
const MAXIMUM_SUPPORT_QUOTE_CHARACTERS: usize = 1_024;
const MAXIMUM_REASON_CHARACTERS: usize = 64;
const QUESTION_PREFIX: &str = "What should you remember about ";

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CuratorSourceCitation {
    pub(crate) concept_id: String,
    pub(crate) source_revision: String,
    pub(crate) content_sha256: String,
    pub(crate) char_start: u64,
    pub(crate) char_end: u64,
}

impl CuratorSourceCitation {
    #[cfg(test)]
    pub(crate) fn new(
        concept_id: String,
        source_revision: String,
        content_sha256: String,
        char_start: u64,
        char_end: u64,
    ) -> Result<Self, CuratorClientError> {
        let value = Self {
            concept_id,
            source_revision,
            content_sha256,
            char_start,
            char_end,
        };
        if !value.is_valid() {
            return Err(CuratorClientError::InvalidRequest);
        }
        Ok(value)
    }

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
pub(crate) struct CuratorStudentQuestionSupport {
    pub(crate) source_citation: CuratorSourceCitation,
    pub(crate) support_quote: String,
    pub(crate) support_char_start: u64,
    pub(crate) support_char_end: u64,
}

impl CuratorStudentQuestionSupport {
    #[cfg(test)]
    pub(crate) fn new(
        source_citation: CuratorSourceCitation,
        support_quote: String,
        support_char_start: u64,
        support_char_end: u64,
    ) -> Result<Self, CuratorClientError> {
        let value = Self {
            source_citation,
            support_quote,
            support_char_start,
            support_char_end,
        };
        if !value.is_valid() {
            return Err(CuratorClientError::InvalidRequest);
        }
        Ok(value)
    }

    fn is_valid(&self) -> bool {
        self.source_citation.is_valid()
            && !self.support_quote.is_empty()
            && self.support_quote.trim() == self.support_quote
            && self.support_quote.chars().count() <= MAXIMUM_SUPPORT_QUOTE_CHARACTERS
            && self.support_char_start >= self.source_citation.char_start
            && self.support_char_end <= self.source_citation.char_end
            && self.support_char_end > self.support_char_start
            && self.support_char_end - self.support_char_start
                == self.support_quote.chars().count() as u64
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CuratorReviewedStudentQuestion {
    schema_version: u16,
    pub(crate) source_subject: String,
    pub(crate) question: String,
    pub(crate) source_supports: Vec<CuratorStudentQuestionSupport>,
}

impl CuratorReviewedStudentQuestion {
    #[cfg(test)]
    pub(crate) fn new(
        source_subject: String,
        question: String,
        source_support: CuratorStudentQuestionSupport,
    ) -> Result<Self, CuratorClientError> {
        let value = Self {
            schema_version: 3,
            source_subject,
            question,
            source_supports: vec![source_support],
        };
        if !value.is_valid() {
            return Err(CuratorClientError::InvalidRequest);
        }
        Ok(value)
    }

    fn is_valid(&self) -> bool {
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
            && self.source_supports[0].is_valid()
            && self.source_supports[0]
                .support_quote
                .match_indices(&self.source_subject)
                .count()
                == 1
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CuratorRequest {
    schema_version: u16,
    pub(crate) submission_id: String,
    trigger: CuratorTrigger,
    pub(crate) expected_generation_sha256: String,
    reviewed_content: String,
    student_question: CuratorReviewedStudentQuestion,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
enum CuratorTrigger {
    ReviewedStudentAnswer,
}

impl CuratorRequest {
    pub(crate) fn reviewed_student_answer(
        submission_id: String,
        expected_generation_sha256: String,
        reviewed_content: String,
        student_question: CuratorReviewedStudentQuestion,
    ) -> Result<Self, CuratorClientError> {
        let value = Self {
            schema_version: 1,
            submission_id,
            trigger: CuratorTrigger::ReviewedStudentAnswer,
            expected_generation_sha256,
            reviewed_content,
            student_question,
        };
        if !value.is_valid() {
            return Err(CuratorClientError::InvalidRequest);
        }
        Ok(value)
    }

    fn is_valid(&self) -> bool {
        self.schema_version == 1
            && valid_submission_id(&self.submission_id)
            && valid_sha256(&self.expected_generation_sha256)
            && !self.reviewed_content.is_empty()
            && self.reviewed_content.trim() == self.reviewed_content
            && self.reviewed_content.chars().count() <= MAXIMUM_REVIEWED_CONTENT_CHARACTERS
            && self.student_question.is_valid()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum CuratorProposalStatus {
    Queued,
    Running,
    CancellationRequested,
    Proposed,
    Rejected,
    Cancelled,
    Failed,
}

impl CuratorProposalStatus {
    pub(crate) fn is_active(self) -> bool {
        matches!(
            self,
            Self::Queued | Self::Running | Self::CancellationRequested
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CuratorProposalJobView {
    schema_version: u16,
    pub(crate) request_id: String,
    pub(crate) submission_id: String,
    pub(crate) status: CuratorProposalStatus,
    pub(crate) generation_sha256: String,
    pub(crate) evidence_sha256: Option<String>,
    pub(crate) proposal_id: Option<String>,
    pub(crate) reason: Option<String>,
}

impl CuratorProposalJobView {
    fn is_valid(&self) -> bool {
        if self.schema_version != 1
            || !valid_product_request_id(&self.request_id)
            || !valid_submission_id(&self.submission_id)
            || !valid_sha256(&self.generation_sha256)
            || self
                .evidence_sha256
                .as_ref()
                .is_some_and(|value| !valid_sha256(value))
            || self
                .proposal_id
                .as_ref()
                .is_some_and(|value| !valid_sha256(value))
            || self.reason.as_ref().is_some_and(|reason| {
                reason.is_empty()
                    || reason.len() > MAXIMUM_REASON_CHARACTERS
                    || !valid_identifier(reason)
            })
        {
            return false;
        }
        match self.status {
            CuratorProposalStatus::Queued
            | CuratorProposalStatus::Running
            | CuratorProposalStatus::CancellationRequested => {
                self.evidence_sha256.is_none()
                    && self.proposal_id.is_none()
                    && self.reason.is_none()
            }
            CuratorProposalStatus::Proposed => {
                self.evidence_sha256.is_some()
                    && self.proposal_id.is_some()
                    && self.reason.is_none()
            }
            CuratorProposalStatus::Rejected => {
                self.evidence_sha256.is_some()
                    && self.proposal_id.is_none()
                    && self.reason.as_deref() == Some("model-rejected")
            }
            CuratorProposalStatus::Cancelled | CuratorProposalStatus::Failed => {
                self.proposal_id.is_none() && self.reason.is_some()
            }
        }
    }

    pub(crate) fn matches_request(&self, request: &CuratorRequest) -> bool {
        self.submission_id == request.submission_id
            && self.generation_sha256 == request.expected_generation_sha256
    }

    #[cfg(test)]
    pub(crate) fn for_test(
        request_id: String,
        status: CuratorProposalStatus,
        reason: Option<String>,
    ) -> Self {
        let view = Self {
            schema_version: 1,
            request_id,
            submission_id: "submission-1".into(),
            status,
            generation_sha256: "a".repeat(64),
            evidence_sha256: None,
            proposal_id: None,
            reason,
        };
        assert!(view.is_valid());
        view
    }
}

#[derive(Debug)]
pub(crate) enum CuratorClientError {
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

impl std::fmt::Display for CuratorClientError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::InvalidRequest => "The reviewed knowledge proposal is invalid.",
            Self::InvalidOrigin => "The knowledge-proposal server origin is invalid.",
            Self::InvalidIdentifier => "The knowledge-proposal identity is invalid.",
            Self::Authorization(
                RequestAuthorizationError::Unavailable
                | RequestAuthorizationError::InvalidToken
                | RequestAuthorizationError::AccountChanged,
            ) => "The organization sign-in or server connection changed.",
            Self::Transport => "The organization knowledge-proposal server is unavailable.",
            Self::Api {
                status,
                code,
                retryable,
            } => {
                return write!(
                    formatter,
                    "Knowledge-proposal request was rejected ({status}, {code}, retryable={retryable})."
                );
            }
            Self::MalformedResponse => "The knowledge-proposal response is invalid.",
            Self::ResponseTooLarge => "The knowledge-proposal response is too large.",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for CuratorClientError {}

#[derive(Clone)]
pub(crate) struct CuratorApiClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}

impl CuratorApiClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, CuratorClientError> {
        let mut base_url = Url::parse(base_url).map_err(|_| CuratorClientError::InvalidOrigin)?;
        if !matches!(base_url.scheme(), "http" | "https")
            || base_url.cannot_be_a_base()
            || base_url.username() != ""
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            return Err(CuratorClientError::InvalidOrigin);
        }
        base_url.set_path("/");
        Ok(Self {
            authenticated,
            base_url,
        })
    }

    pub(crate) async fn submit(
        &self,
        request: &CuratorRequest,
    ) -> Result<CuratorProposalJobView, CuratorClientError> {
        if !request.is_valid() {
            return Err(CuratorClientError::InvalidRequest);
        }
        let body = serde_json::to_vec(request).map_err(|_| CuratorClientError::InvalidRequest)?;
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
            return Err(CuratorClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn status(
        &self,
        request_id: &str,
    ) -> Result<CuratorProposalJobView, CuratorClientError> {
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
            return Err(CuratorClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn cancel(
        &self,
        request_id: &str,
    ) -> Result<CuratorProposalJobView, CuratorClientError> {
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
            return Err(CuratorClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) fn base_url_identity(&self) -> &str {
        self.base_url.as_str()
    }

    fn endpoint(&self, request_id: Option<&str>) -> Result<Url, CuratorClientError> {
        if request_id.is_some_and(|value| !valid_product_request_id(value)) {
            return Err(CuratorClientError::InvalidIdentifier);
        }
        let mut url = self.base_url.clone();
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| CuratorClientError::InvalidOrigin)?;
            path.clear().push("v1").push("curator-proposals");
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
) -> Result<CuratorProposalJobView, CuratorClientError> {
    let status = response
        .status()
        .map_err(CuratorClientError::Authorization)?;
    let body = read_bounded(&mut response).await?;
    if !successes.contains(&status) {
        let error: ApiError =
            serde_json::from_slice(&body).map_err(|_| CuratorClientError::MalformedResponse)?;
        if !valid_identifier(&error.code)
            || error.message.is_empty()
            || error.message.len() > 512
            || !error.request_id.starts_with("req-")
            || !valid_identifier(&error.request_id)
        {
            return Err(CuratorClientError::MalformedResponse);
        }
        return Err(CuratorClientError::Api {
            status,
            code: error.code,
            retryable: error.retryable,
        });
    }
    let view = decode_job_view(body)?;
    response
        .ensure_current()
        .map_err(CuratorClientError::Authorization)?;
    Ok(view)
}

fn decode_job_view(body: Vec<u8>) -> Result<CuratorProposalJobView, CuratorClientError> {
    let view: CuratorProposalJobView =
        serde_json::from_slice(&body).map_err(|_| CuratorClientError::MalformedResponse)?;
    if !view.is_valid() {
        return Err(CuratorClientError::MalformedResponse);
    }
    Ok(view)
}

async fn read_bounded(response: &mut AuthenticatedResponse) -> Result<Vec<u8>, CuratorClientError> {
    if response
        .content_length()
        .map_err(CuratorClientError::Authorization)?
        .is_some_and(|length| length > MAXIMUM_RESPONSE_BYTES as u64)
    {
        return Err(CuratorClientError::ResponseTooLarge);
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(map_dispatch)? {
        if body.len().saturating_add(chunk.len()) > MAXIMUM_RESPONSE_BYTES {
            return Err(CuratorClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn map_dispatch(error: AuthenticatedDispatchError) -> CuratorClientError {
    match error {
        AuthenticatedDispatchError::Authorization(error) => {
            CuratorClientError::Authorization(error)
        }
        AuthenticatedDispatchError::Transport(_) => CuratorClientError::Transport,
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

fn valid_submission_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn valid_product_request_id(value: &str) -> bool {
    value
        .strip_prefix("curator-proposal-")
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
mod tests {
    use std::{
        io::{Read, Write},
        net::TcpListener,
        thread,
    };

    use super::*;
    use crate::server_connector::AuthenticatedRequestDispatcher;

    fn sha(character: char) -> String {
        character.to_string().repeat(64)
    }

    fn question() -> CuratorReviewedStudentQuestion {
        CuratorReviewedStudentQuestion::new(
            "crash safety".into(),
            "What should you remember about crash safety?".into(),
            CuratorStudentQuestionSupport::new(
                CuratorSourceCitation::new("meetings/job-1".into(), sha('b'), sha('c'), 0, 44)
                    .unwrap(),
                "crash safety".into(),
                29,
                41,
            )
            .unwrap(),
        )
        .unwrap()
    }

    fn request() -> CuratorRequest {
        CuratorRequest::reviewed_student_answer(
            "submission-1".into(),
            sha('a'),
            "Contain the worker before retrying.".into(),
            question(),
        )
        .unwrap()
    }

    #[test]
    fn reviewed_student_request_owns_only_content_and_exact_source_identity() {
        assert_eq!(
            serde_json::to_value(request()).unwrap(),
            serde_json::json!({
                "schemaVersion": 1,
                "submissionId": "submission-1",
                "trigger": "reviewed-student-answer",
                "expectedGenerationSha256": sha('a'),
                "reviewedContent": "Contain the worker before retrying.",
                "studentQuestion": {
                    "schemaVersion": 3,
                    "sourceSubject": "crash safety",
                    "question": "What should you remember about crash safety?",
                    "sourceSupports": [{
                        "sourceCitation": {
                            "conceptId": "meetings/job-1",
                            "sourceRevision": sha('b'),
                            "contentSha256": sha('c'),
                            "charStart": 0,
                            "charEnd": 44
                        },
                        "supportQuote": "crash safety",
                        "supportCharStart": 29,
                        "supportCharEnd": 41
                    }]
                }
            })
        );
        assert!(CuratorRequest::reviewed_student_answer(
            "bad submission".into(),
            sha('a'),
            "Reviewed answer".into(),
            question(),
        )
        .is_err());
        assert!(CuratorRequest::reviewed_student_answer(
            "submission-1".into(),
            sha('A'),
            "Reviewed answer".into(),
            question(),
        )
        .is_err());
    }

    #[test]
    fn authenticated_client_submits_and_decodes_one_bounded_view() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut bytes = [0_u8; 8192];
            let count = stream.read(&mut bytes).unwrap();
            let request_text = String::from_utf8_lossy(&bytes[..count]);
            assert!(request_text.starts_with("POST /v1/curator-proposals HTTP/1.1\r\n"));
            assert!(request_text
                .to_ascii_lowercase()
                .contains("authorization: bearer private-token"));
            assert!(request_text.contains("\"trigger\":\"reviewed-student-answer\""));
            let body = serde_json::json!({
                "schemaVersion": 1,
                "requestId": format!("curator-proposal-{}", "1".repeat(32)),
                "submissionId": "submission-1",
                "status": "queued",
                "generationSha256": sha('a')
            })
            .to_string();
            write!(
                stream,
                "HTTP/1.1 202 Accepted\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .unwrap();
        });

        let client = CuratorApiClient::new(
            AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
            &format!("http://{address}"),
        )
        .unwrap();
        let view = tauri::async_runtime::block_on(client.submit(&request())).unwrap();
        assert_eq!(view.status, CuratorProposalStatus::Queued);
        server.join().unwrap();
    }

    #[test]
    fn terminal_proposal_identity_and_exact_request_binding_fail_closed() {
        let value = serde_json::json!({
            "schemaVersion": 1,
            "requestId": format!("curator-proposal-{}", "1".repeat(32)),
            "submissionId": "submission-1",
            "status": "proposed",
            "generationSha256": sha('a'),
            "evidenceSha256": sha('d'),
            "proposalId": sha('e')
        });
        let view = decode_job_view(serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(view.matches_request(&request()));

        let mut malformed = value.clone();
        malformed["proposalId"] = serde_json::json!("proposal-1");
        assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());

        let mut mismatched = value;
        mismatched["submissionId"] = serde_json::json!("submission-2");
        assert!(!decode_job_view(serde_json::to_vec(&mismatched).unwrap())
            .unwrap()
            .matches_request(&request()));
    }

    #[test]
    fn status_and_cancel_reject_a_different_response_identity() {
        for (method, response_status, proposal_status) in [
            ("GET", "200 OK", "running"),
            ("DELETE", "202 Accepted", "cancellation-requested"),
        ] {
            let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
            let address = listener.local_addr().unwrap();
            let expected_request_id = format!("curator-proposal-{}", "1".repeat(32));
            let expected_path = format!("/v1/curator-proposals/{expected_request_id}");
            let server = thread::spawn(move || {
                let (mut stream, _) = listener.accept().unwrap();
                let mut bytes = [0_u8; 8192];
                let count = stream.read(&mut bytes).unwrap();
                let request_text = String::from_utf8_lossy(&bytes[..count]);
                assert!(request_text.starts_with(&format!("{method} {expected_path} HTTP/1.1\r\n")));
                let body = serde_json::json!({
                    "schemaVersion": 1,
                    "requestId": format!("curator-proposal-{}", "2".repeat(32)),
                    "submissionId": "submission-1",
                    "status": proposal_status,
                    "generationSha256": sha('a')
                })
                .to_string();
                write!(
                    stream,
                    "HTTP/1.1 {response_status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                )
                .unwrap();
            });

            let client = CuratorApiClient::new(
                AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
                &format!("http://{address}"),
            )
            .unwrap();
            let result = if method == "GET" {
                tauri::async_runtime::block_on(client.status(&expected_request_id))
            } else {
                tauri::async_runtime::block_on(client.cancel(&expected_request_id))
            };
            assert!(matches!(result, Err(CuratorClientError::MalformedResponse)));
            server.join().unwrap();
        }
    }
}
