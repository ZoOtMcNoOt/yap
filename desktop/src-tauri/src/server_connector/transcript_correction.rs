use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::authorization::{
    AuthenticatedDispatchError, AuthenticatedRequestDispatcher, AuthenticatedResponse,
    RequestAuthorizationError,
};

const MAXIMUM_RESPONSE_BYTES: usize = 256 * 1024;
const MAXIMUM_SOURCE_CHARACTERS: usize = 32_768;
const MAXIMUM_SEGMENTS: usize = 64;
const MAXIMUM_SEGMENT_CHARACTERS: usize = 32_768;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct TranscriptCorrectionSegment {
    pub(crate) segment_id: String,
    pub(crate) start_character: usize,
    pub(crate) end_character: usize,
    pub(crate) start_milliseconds: u64,
    pub(crate) end_milliseconds: u64,
    pub(crate) language_bcp47: String,
    pub(crate) text: String,
    pub(crate) text_sha256: String,
}

impl TranscriptCorrectionSegment {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        segment_id: String,
        start_character: usize,
        end_character: usize,
        start_milliseconds: u64,
        end_milliseconds: u64,
        language_bcp47: String,
        text: String,
        text_sha256: String,
    ) -> Result<Self, TranscriptCorrectionClientError> {
        let segment = Self {
            segment_id,
            start_character,
            end_character,
            start_milliseconds,
            end_milliseconds,
            language_bcp47,
            text,
            text_sha256,
        };
        if !segment.is_valid() {
            return Err(TranscriptCorrectionClientError::InvalidRequest);
        }
        Ok(segment)
    }

    fn is_valid(&self) -> bool {
        valid_identifier(&self.segment_id)
            && self.end_character > self.start_character
            && self.end_character - self.start_character == self.text.chars().count()
            && !self.text.is_empty()
            && self.text.chars().count() <= MAXIMUM_SEGMENT_CHARACTERS
            && valid_sha256(&self.text_sha256)
            && valid_language(&self.language_bcp47)
            && self.end_milliseconds > self.start_milliseconds
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct TranscriptCorrectionRequest {
    schema_version: u16,
    source_revision_sha256: String,
    source_sha256: String,
    segments: Vec<TranscriptCorrectionSegment>,
}

impl TranscriptCorrectionRequest {
    pub(crate) fn from_finalized_segments(
        source_revision_sha256: String,
        segments: Vec<TranscriptCorrectionSegment>,
    ) -> Result<Self, TranscriptCorrectionClientError> {
        let source = segments
            .iter()
            .map(|segment| segment.text.as_str())
            .collect::<String>();
        Self::new(source_revision_sha256, sha256_text(&source), segments)
    }

    pub(crate) fn new(
        source_revision_sha256: String,
        source_sha256: String,
        segments: Vec<TranscriptCorrectionSegment>,
    ) -> Result<Self, TranscriptCorrectionClientError> {
        let request = Self {
            schema_version: 1,
            source_revision_sha256,
            source_sha256,
            segments,
        };
        if !request.is_valid() {
            return Err(TranscriptCorrectionClientError::InvalidRequest);
        }
        Ok(request)
    }

    fn is_valid(&self) -> bool {
        if self.schema_version != 1
            || !valid_sha256(&self.source_revision_sha256)
            || !valid_sha256(&self.source_sha256)
            || self.segments.is_empty()
            || self.segments.len() > MAXIMUM_SEGMENTS
        {
            return false;
        }
        let mut end = 0_usize;
        let mut characters = 0_usize;
        let mut prior_end_milliseconds = None;
        let mut source = String::new();
        for segment in &self.segments {
            if !segment.is_valid()
                || sha256_text(&segment.text) != segment.text_sha256
                || segment.start_character != end
                || prior_end_milliseconds.is_some_and(|prior| segment.start_milliseconds < prior)
            {
                return false;
            }
            end = segment.end_character;
            prior_end_milliseconds = Some(segment.end_milliseconds);
            characters = match characters.checked_add(segment.text.chars().count()) {
                Some(value) => value,
                None => return false,
            };
            source.push_str(&segment.text);
        }
        characters == end
            && characters <= MAXIMUM_SOURCE_CHARACTERS
            && sha256_text(&source) == self.source_sha256
    }

    pub(crate) fn source_revision_sha256(&self) -> &str {
        &self.source_revision_sha256
    }

    pub(crate) fn source_sha256(&self) -> &str {
        &self.source_sha256
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum TranscriptCorrectionStatus {
    Queued,
    Running,
    CancellationRequested,
    Cancelled,
    Complete,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct TranscriptCorrectionJobView {
    schema_version: u16,
    pub(crate) request_id: String,
    pub(crate) status: TranscriptCorrectionStatus,
    pub(crate) source_revision_sha256: String,
    pub(crate) source_sha256: String,
    pub(crate) terminology_snapshot_sha256: String,
    pub(crate) applied: bool,
    pub(crate) corrected_text: Option<String>,
    pub(crate) reason: Option<String>,
}

impl TranscriptCorrectionJobView {
    fn is_valid(&self) -> bool {
        if self.schema_version != 1
            || !valid_identifier(&self.request_id)
            || !valid_sha256(&self.source_revision_sha256)
            || !valid_sha256(&self.source_sha256)
            || !valid_sha256(&self.terminology_snapshot_sha256)
            || self
                .corrected_text
                .as_ref()
                .is_some_and(|text| text.chars().count() > MAXIMUM_SOURCE_CHARACTERS)
            || self.reason.as_ref().is_some_and(|reason| {
                reason.is_empty() || reason.len() > 64 || !valid_identifier(reason)
            })
        {
            return false;
        }
        match self.status {
            TranscriptCorrectionStatus::Complete => {
                self.corrected_text.is_some() && (!self.applied || self.reason.is_none())
            }
            TranscriptCorrectionStatus::Failed => {
                !self.applied && self.corrected_text.is_none() && self.reason.is_some()
            }
            TranscriptCorrectionStatus::Queued
            | TranscriptCorrectionStatus::Running
            | TranscriptCorrectionStatus::CancellationRequested
            | TranscriptCorrectionStatus::Cancelled => {
                !self.applied && self.corrected_text.is_none()
            }
        }
    }

    #[cfg(test)]
    pub(crate) fn for_test(
        request_id: String,
        status: TranscriptCorrectionStatus,
        source_revision_sha256: String,
        source_sha256: String,
        applied: bool,
        corrected_text: Option<String>,
        reason: Option<String>,
    ) -> Self {
        let view = Self {
            schema_version: 1,
            request_id,
            status,
            source_revision_sha256,
            source_sha256,
            terminology_snapshot_sha256: "c".repeat(64),
            applied,
            corrected_text,
            reason,
        };
        assert!(view.is_valid());
        view
    }
}

#[derive(Debug)]
pub(crate) enum TranscriptCorrectionClientError {
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

impl std::fmt::Display for TranscriptCorrectionClientError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::InvalidRequest => "The committed transcript cannot be corrected.",
            Self::InvalidOrigin => "The transcript correction server origin is invalid.",
            Self::InvalidIdentifier => "The transcript correction request identity is invalid.",
            Self::Authorization(
                RequestAuthorizationError::Unavailable
                | RequestAuthorizationError::InvalidToken
                | RequestAuthorizationError::AccountChanged,
            ) => "The organization sign-in or server connection changed.",
            Self::Transport => "The transcript correction server is unavailable.",
            Self::Api {
                status,
                code,
                retryable,
            } => {
                return write!(
                    formatter,
                    "Transcript correction was rejected ({status}, {code}, retryable={retryable})."
                );
            }
            Self::MalformedResponse => "The transcript correction response is invalid.",
            Self::ResponseTooLarge => "The transcript correction response is too large.",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for TranscriptCorrectionClientError {}

#[derive(Clone)]
pub(crate) struct TranscriptCorrectionApiClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}

impl TranscriptCorrectionApiClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, TranscriptCorrectionClientError> {
        let mut base_url =
            Url::parse(base_url).map_err(|_| TranscriptCorrectionClientError::InvalidOrigin)?;
        if !matches!(base_url.scheme(), "http" | "https")
            || base_url.cannot_be_a_base()
            || base_url.username() != ""
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            return Err(TranscriptCorrectionClientError::InvalidOrigin);
        }
        base_url.set_path("/");
        Ok(Self {
            authenticated,
            base_url,
        })
    }

    pub(crate) async fn submit(
        &self,
        request: &TranscriptCorrectionRequest,
    ) -> Result<TranscriptCorrectionJobView, TranscriptCorrectionClientError> {
        if !request.is_valid() {
            return Err(TranscriptCorrectionClientError::InvalidRequest);
        }
        let body = serde_json::to_vec(request)
            .map_err(|_| TranscriptCorrectionClientError::InvalidRequest)?;
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
        decode_response(response, &[StatusCode::ACCEPTED]).await
    }

    pub(crate) async fn status(
        &self,
        request_id: &str,
    ) -> Result<TranscriptCorrectionJobView, TranscriptCorrectionClientError> {
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
    ) -> Result<TranscriptCorrectionJobView, TranscriptCorrectionClientError> {
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

    fn endpoint(&self, request_id: Option<&str>) -> Result<Url, TranscriptCorrectionClientError> {
        if request_id.is_some_and(|value| !valid_identifier(value)) {
            return Err(TranscriptCorrectionClientError::InvalidIdentifier);
        }
        let mut url = self.base_url.clone();
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| TranscriptCorrectionClientError::InvalidOrigin)?;
            path.clear().push("v1").push("transcript-corrections");
            if let Some(request_id) = request_id {
                path.push(request_id);
            }
        }
        Ok(url)
    }
}

pub(crate) fn sha256_text(value: &str) -> String {
    Sha256::digest(value.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
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
) -> Result<TranscriptCorrectionJobView, TranscriptCorrectionClientError> {
    let status = response
        .status()
        .map_err(TranscriptCorrectionClientError::Authorization)?;
    let body = read_bounded(&mut response).await?;
    if !successes.contains(&status) {
        let error: ApiError = serde_json::from_slice(&body)
            .map_err(|_| TranscriptCorrectionClientError::MalformedResponse)?;
        if !valid_identifier(&error.code)
            || error.message.is_empty()
            || error.message.len() > 512
            || !error.request_id.starts_with("req-")
            || !valid_identifier(&error.request_id)
        {
            return Err(TranscriptCorrectionClientError::MalformedResponse);
        }
        return Err(TranscriptCorrectionClientError::Api {
            status,
            code: error.code,
            retryable: error.retryable,
        });
    }
    let view = decode_job_view(body)?;
    response
        .ensure_current()
        .map_err(TranscriptCorrectionClientError::Authorization)?;
    Ok(view)
}

fn decode_job_view(
    body: Vec<u8>,
) -> Result<TranscriptCorrectionJobView, TranscriptCorrectionClientError> {
    let view: TranscriptCorrectionJobView = serde_json::from_slice(&body)
        .map_err(|_| TranscriptCorrectionClientError::MalformedResponse)?;
    if !view.is_valid() {
        return Err(TranscriptCorrectionClientError::MalformedResponse);
    }
    Ok(view)
}

async fn read_bounded(
    response: &mut AuthenticatedResponse,
) -> Result<Vec<u8>, TranscriptCorrectionClientError> {
    if response
        .content_length()
        .map_err(TranscriptCorrectionClientError::Authorization)?
        .is_some_and(|length| length > MAXIMUM_RESPONSE_BYTES as u64)
    {
        return Err(TranscriptCorrectionClientError::ResponseTooLarge);
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(map_dispatch)? {
        if body.len().saturating_add(chunk.len()) > MAXIMUM_RESPONSE_BYTES {
            return Err(TranscriptCorrectionClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn map_dispatch(error: AuthenticatedDispatchError) -> TranscriptCorrectionClientError {
    match error {
        AuthenticatedDispatchError::Authorization(error) => {
            TranscriptCorrectionClientError::Authorization(error)
        }
        AuthenticatedDispatchError::Transport(_) => TranscriptCorrectionClientError::Transport,
    }
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn valid_language(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 35
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
}

#[cfg(test)]
mod tests;
