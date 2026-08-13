use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};

use super::authorization::{
    AuthenticatedDispatchError, AuthenticatedRequestDispatcher, AuthenticatedResponse,
    RequestAuthorizationError,
};

const MAXIMUM_RESPONSE_BYTES: usize = 64 * 1024;
const MAXIMUM_REASON_CHARACTERS: usize = 64;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ArchivistIngestionRequest {
    schema_version: u16,
    job_id: String,
    expected_result_sha256: String,
}

impl ArchivistIngestionRequest {
    pub(crate) fn new(
        job_id: String,
        expected_result_sha256: String,
    ) -> Result<Self, ArchivistClientError> {
        let request = Self {
            schema_version: 1,
            job_id,
            expected_result_sha256,
        };
        if !request.is_valid() {
            return Err(ArchivistClientError::InvalidRequest);
        }
        Ok(request)
    }

    fn is_valid(&self) -> bool {
        self.schema_version == 1
            && valid_identifier(&self.job_id)
            && valid_sha256(&self.expected_result_sha256)
    }

    pub(crate) fn job_id(&self) -> &str {
        &self.job_id
    }

    pub(crate) fn expected_result_sha256(&self) -> &str {
        &self.expected_result_sha256
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum ArchivistIngestionStatus {
    Queued,
    Running,
    CancellationRequested,
    Staged,
    Cancelled,
    Failed,
}

impl ArchivistIngestionStatus {
    pub(crate) fn is_active(self) -> bool {
        matches!(
            self,
            Self::Queued | Self::Running | Self::CancellationRequested
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ArchivistIngestionJobView {
    schema_version: u16,
    pub(crate) request_id: String,
    pub(crate) status: ArchivistIngestionStatus,
    pub(crate) job_id: String,
    pub(crate) result_sha256: String,
    pub(crate) capture_sha256: Option<String>,
    pub(crate) source_admission_sha256: Option<String>,
    pub(crate) generation_sha256: Option<String>,
    pub(crate) concept_count: Option<u64>,
    pub(crate) permission_count: Option<u64>,
    pub(crate) reason: Option<String>,
}

impl ArchivistIngestionJobView {
    fn is_valid(&self) -> bool {
        if self.schema_version != 1
            || !valid_product_request_id(&self.request_id)
            || !valid_identifier(&self.job_id)
            || !valid_sha256(&self.result_sha256)
            || self.reason.as_ref().is_some_and(|reason| {
                reason.is_empty()
                    || reason.chars().count() > MAXIMUM_REASON_CHARACTERS
                    || !valid_identifier(reason)
            })
        {
            return false;
        }
        let outputs = [
            self.capture_sha256.as_deref(),
            self.source_admission_sha256.as_deref(),
            self.generation_sha256.as_deref(),
        ];
        match self.status {
            ArchivistIngestionStatus::Queued
            | ArchivistIngestionStatus::Running
            | ArchivistIngestionStatus::CancellationRequested => {
                outputs.iter().all(Option::is_none)
                    && self.concept_count.is_none()
                    && self.permission_count.is_none()
                    && self.reason.is_none()
            }
            ArchivistIngestionStatus::Staged => {
                outputs.iter().all(|value| value.is_some_and(valid_sha256))
                    && self.concept_count.is_some_and(|value| value > 0)
                    && self.permission_count.is_some_and(|value| value > 0)
                    && self.reason.is_none()
            }
            ArchivistIngestionStatus::Cancelled | ArchivistIngestionStatus::Failed => {
                outputs.iter().all(Option::is_none)
                    && self.concept_count.is_none()
                    && self.permission_count.is_none()
                    && self.reason.is_some()
            }
        }
    }

    pub(crate) fn matches_request(&self, request: &ArchivistIngestionRequest) -> bool {
        self.job_id == request.job_id() && self.result_sha256 == request.expected_result_sha256()
    }

    #[cfg(test)]
    pub(crate) fn for_test(
        request_id: String,
        status: ArchivistIngestionStatus,
        job_id: String,
        result_sha256: String,
        reason: Option<String>,
    ) -> Self {
        let view = Self {
            schema_version: 1,
            request_id,
            status,
            job_id,
            result_sha256,
            capture_sha256: None,
            source_admission_sha256: None,
            generation_sha256: None,
            concept_count: None,
            permission_count: None,
            reason,
        };
        assert!(view.is_valid());
        view
    }
}

#[derive(Debug)]
pub(crate) enum ArchivistClientError {
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

impl std::fmt::Display for ArchivistClientError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidRequest => {
                formatter.write_str("The knowledge staging request is invalid.")
            }
            Self::InvalidOrigin => {
                formatter.write_str("The knowledge staging server origin is invalid.")
            }
            Self::InvalidIdentifier => {
                formatter.write_str("The knowledge staging identity is invalid.")
            }
            Self::Authorization(
                RequestAuthorizationError::Unavailable
                | RequestAuthorizationError::InvalidToken
                | RequestAuthorizationError::AccountChanged,
            ) => formatter.write_str("The organization sign-in or server connection changed."),
            Self::Transport => {
                formatter.write_str("The organization knowledge server is unavailable.")
            }
            Self::Api {
                status,
                code,
                retryable,
            } => write!(
                formatter,
                "Knowledge staging was rejected ({status}, {code}, retryable={retryable})."
            ),
            Self::MalformedResponse => {
                formatter.write_str("The knowledge staging response is invalid.")
            }
            Self::ResponseTooLarge => {
                formatter.write_str("The knowledge staging response is too large.")
            }
        }
    }
}

impl std::error::Error for ArchivistClientError {}

#[derive(Clone)]
pub(crate) struct ArchivistApiClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}

impl ArchivistApiClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, ArchivistClientError> {
        let mut base_url = Url::parse(base_url).map_err(|_| ArchivistClientError::InvalidOrigin)?;
        if !matches!(base_url.scheme(), "http" | "https")
            || base_url.cannot_be_a_base()
            || base_url.username() != ""
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            return Err(ArchivistClientError::InvalidOrigin);
        }
        base_url.set_path("/");
        Ok(Self {
            authenticated,
            base_url,
        })
    }

    pub(crate) async fn submit(
        &self,
        request: &ArchivistIngestionRequest,
    ) -> Result<ArchivistIngestionJobView, ArchivistClientError> {
        if !request.is_valid() {
            return Err(ArchivistClientError::InvalidRequest);
        }
        let body = serde_json::to_vec(request).map_err(|_| ArchivistClientError::InvalidRequest)?;
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
            return Err(ArchivistClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn status(
        &self,
        request_id: &str,
    ) -> Result<ArchivistIngestionJobView, ArchivistClientError> {
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
    ) -> Result<ArchivistIngestionJobView, ArchivistClientError> {
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

    fn endpoint(&self, request_id: Option<&str>) -> Result<Url, ArchivistClientError> {
        if request_id.is_some_and(|value| !valid_product_request_id(value)) {
            return Err(ArchivistClientError::InvalidIdentifier);
        }
        let mut url = self.base_url.clone();
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| ArchivistClientError::InvalidOrigin)?;
            path.clear().push("v1").push("archivist-ingestions");
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
) -> Result<ArchivistIngestionJobView, ArchivistClientError> {
    let status = response
        .status()
        .map_err(ArchivistClientError::Authorization)?;
    let body = read_bounded(&mut response).await?;
    if !successes.contains(&status) {
        let error: ApiError =
            serde_json::from_slice(&body).map_err(|_| ArchivistClientError::MalformedResponse)?;
        if !valid_identifier(&error.code)
            || error.message.is_empty()
            || error.message.len() > 512
            || !error.request_id.starts_with("req-")
            || !valid_identifier(&error.request_id)
        {
            return Err(ArchivistClientError::MalformedResponse);
        }
        return Err(ArchivistClientError::Api {
            status,
            code: error.code,
            retryable: error.retryable,
        });
    }
    let view = decode_job_view(body)?;
    response
        .ensure_current()
        .map_err(ArchivistClientError::Authorization)?;
    Ok(view)
}

fn decode_job_view(body: Vec<u8>) -> Result<ArchivistIngestionJobView, ArchivistClientError> {
    let view: ArchivistIngestionJobView =
        serde_json::from_slice(&body).map_err(|_| ArchivistClientError::MalformedResponse)?;
    if !view.is_valid() {
        return Err(ArchivistClientError::MalformedResponse);
    }
    Ok(view)
}

async fn read_bounded(
    response: &mut AuthenticatedResponse,
) -> Result<Vec<u8>, ArchivistClientError> {
    if response
        .content_length()
        .map_err(ArchivistClientError::Authorization)?
        .is_some_and(|length| length > MAXIMUM_RESPONSE_BYTES as u64)
    {
        return Err(ArchivistClientError::ResponseTooLarge);
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(map_dispatch)? {
        if body.len().saturating_add(chunk.len()) > MAXIMUM_RESPONSE_BYTES {
            return Err(ArchivistClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn map_dispatch(error: AuthenticatedDispatchError) -> ArchivistClientError {
    match error {
        AuthenticatedDispatchError::Authorization(error) => {
            ArchivistClientError::Authorization(error)
        }
        AuthenticatedDispatchError::Transport(_) => ArchivistClientError::Transport,
    }
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

fn valid_product_request_id(value: &str) -> bool {
    value
        .strip_prefix("archivist-ingestion-")
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
