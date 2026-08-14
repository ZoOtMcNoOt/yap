use std::collections::HashSet;

use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::authorization::{
    AuthenticatedDispatchError, AuthenticatedRequestDispatcher, AuthenticatedResponse,
    RequestAuthorizationError,
};

const MAXIMUM_RESPONSE_BYTES: usize = 256 * 1024;
const MAXIMUM_FOCUS_CHARACTERS: usize = 1_024;
const MAXIMUM_FINDINGS: usize = 5;
const FINDING_KIND: &str = "potential-contradiction";
const FINDING_SUMMARY: &str = "These two current reviewed knowledge statements may conflict.";
const CITATIONS_PER_FINDING: usize = 2;
const MAXIMUM_CITATION_TEXT_CHARACTERS: usize = 2_000;
const MAXIMUM_CONCEPT_CHARACTERS: usize = 512;
const MAXIMUM_SOURCE_REVISION_CHARACTERS: usize = 512;
const MAXIMUM_REASON_CHARACTERS: usize = 64;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AuditorRequest {
    schema_version: u16,
    focus: String,
    maximum_findings: u8,
    expected_generation_sha256: Option<String>,
}

impl AuditorRequest {
    pub(crate) fn new(
        focus: String,
        maximum_findings: u8,
        expected_generation_sha256: Option<String>,
    ) -> Result<Self, AuditorClientError> {
        let request = Self {
            schema_version: 1,
            focus,
            maximum_findings,
            expected_generation_sha256,
        };
        if !request.is_valid() {
            return Err(AuditorClientError::InvalidRequest);
        }
        Ok(request)
    }

    fn is_valid(&self) -> bool {
        self.schema_version == 1
            && !self.focus.is_empty()
            && self.focus.trim() == self.focus
            && self.focus.chars().count() <= MAXIMUM_FOCUS_CHARACTERS
            && self
                .focus
                .chars()
                .any(|character| character.is_alphanumeric())
            && (1..=MAXIMUM_FINDINGS as u8).contains(&self.maximum_findings)
            && self
                .expected_generation_sha256
                .as_ref()
                .is_none_or(|value| valid_sha256(value))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct AuditorCitation {
    pub(crate) concept_id: String,
    pub(crate) source_revision: String,
    pub(crate) content_sha256: String,
    pub(crate) char_start: u64,
    pub(crate) char_end: u64,
    pub(crate) text: String,
}

impl AuditorCitation {
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
pub(crate) struct AuditorFinding {
    pub(crate) kind: String,
    pub(crate) summary: String,
    pub(crate) citations: Vec<AuditorCitation>,
    pub(crate) finding_sha256: String,
    pub(crate) requires_review: bool,
}

impl AuditorFinding {
    fn is_valid(&self) -> bool {
        if self.kind != FINDING_KIND
            || self.summary != FINDING_SUMMARY
            || self.citations.len() != CITATIONS_PER_FINDING
            || self.citations.iter().any(|citation| !citation.is_valid())
            || !valid_sha256(&self.finding_sha256)
            || !self.requires_review
        {
            return false;
        }
        let identities = self
            .citations
            .iter()
            .map(citation_identity)
            .collect::<HashSet<_>>();
        identities.len() == self.citations.len()
            && finding_sha256(self).as_deref() == Some(self.finding_sha256.as_str())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct AuditorReport {
    schema_version: u16,
    pub(crate) generation_sha256: String,
    pub(crate) source_admission_sha256: String,
    pub(crate) evidence_sha256: String,
    pub(crate) findings: Vec<AuditorFinding>,
    pub(crate) citation_sha256: String,
    canonical: bool,
    requires_review: bool,
    pub(crate) report_sha256: String,
}

impl AuditorReport {
    fn is_valid(&self) -> bool {
        if self.schema_version != 1
            || !valid_sha256(&self.generation_sha256)
            || !valid_sha256(&self.source_admission_sha256)
            || !valid_sha256(&self.evidence_sha256)
            || self.findings.is_empty()
            || self.findings.len() > MAXIMUM_FINDINGS
            || self.findings.iter().any(|finding| !finding.is_valid())
            || !valid_sha256(&self.report_sha256)
            || !valid_sha256(&self.citation_sha256)
            || self.canonical
            || !self.requires_review
        {
            return false;
        }
        let findings = self
            .findings
            .iter()
            .map(|finding| finding.finding_sha256.as_str())
            .collect::<HashSet<_>>();
        findings.len() == self.findings.len()
            && report_citation_sha256(&self.findings).as_deref()
                == Some(self.citation_sha256.as_str())
            && report_sha256(self).as_deref() == Some(self.report_sha256.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum AuditorReportStatus {
    Queued,
    Running,
    CancellationRequested,
    Complete,
    EvidenceUnavailable,
    Cancelled,
    Failed,
}

impl AuditorReportStatus {
    pub(crate) fn is_active(self) -> bool {
        matches!(
            self,
            Self::Queued | Self::Running | Self::CancellationRequested
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct AuditorReportJobView {
    schema_version: u16,
    pub(crate) request_id: String,
    pub(crate) status: AuditorReportStatus,
    pub(crate) report: Option<AuditorReport>,
    pub(crate) reason: Option<String>,
}

impl AuditorReportJobView {
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
            AuditorReportStatus::Complete => {
                self.reason.is_none() && self.report.as_ref().is_some_and(AuditorReport::is_valid)
            }
            AuditorReportStatus::Queued
            | AuditorReportStatus::Running
            | AuditorReportStatus::CancellationRequested => {
                self.report.is_none() && self.reason.is_none()
            }
            AuditorReportStatus::EvidenceUnavailable
            | AuditorReportStatus::Cancelled
            | AuditorReportStatus::Failed => self.report.is_none() && self.reason.is_some(),
        }
    }

    pub(crate) fn matches_request(&self, request: &AuditorRequest) -> bool {
        self.report.as_ref().is_none_or(|report| {
            report.findings.len() <= request.maximum_findings as usize
                && request
                    .expected_generation_sha256
                    .as_ref()
                    .is_none_or(|expected| expected == &report.generation_sha256)
        })
    }

    #[cfg(test)]
    pub(crate) fn for_test(
        request_id: String,
        status: AuditorReportStatus,
        reason: Option<String>,
    ) -> Self {
        let view = Self {
            schema_version: 1,
            request_id,
            status,
            report: None,
            reason,
        };
        assert!(view.is_valid());
        view
    }
}

#[derive(Debug)]
pub(crate) enum AuditorClientError {
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

impl std::fmt::Display for AuditorClientError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::InvalidRequest => "The audit-report request is invalid.",
            Self::InvalidOrigin => "The audit-report server origin is invalid.",
            Self::InvalidIdentifier => "The audit-report identity is invalid.",
            Self::Authorization(
                RequestAuthorizationError::Unavailable
                | RequestAuthorizationError::InvalidToken
                | RequestAuthorizationError::AccountChanged,
            ) => "The organization sign-in or server connection changed.",
            Self::Transport => "The organization audit-report server is unavailable.",
            Self::Api {
                status,
                code,
                retryable,
            } => {
                return write!(
                    formatter,
                    "Audit-report request was rejected ({status}, {code}, retryable={retryable})."
                );
            }
            Self::MalformedResponse => "The audit-report response is invalid.",
            Self::ResponseTooLarge => "The audit-report response is too large.",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for AuditorClientError {}

#[derive(Clone)]
pub(crate) struct AuditorApiClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}

impl AuditorApiClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, AuditorClientError> {
        let mut base_url = Url::parse(base_url).map_err(|_| AuditorClientError::InvalidOrigin)?;
        if !matches!(base_url.scheme(), "http" | "https")
            || base_url.cannot_be_a_base()
            || base_url.username() != ""
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            return Err(AuditorClientError::InvalidOrigin);
        }
        base_url.set_path("/");
        Ok(Self {
            authenticated,
            base_url,
        })
    }

    pub(crate) async fn submit(
        &self,
        request: &AuditorRequest,
    ) -> Result<AuditorReportJobView, AuditorClientError> {
        if !request.is_valid() {
            return Err(AuditorClientError::InvalidRequest);
        }
        let body = serde_json::to_vec(request).map_err(|_| AuditorClientError::InvalidRequest)?;
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
            return Err(AuditorClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn status(
        &self,
        request_id: &str,
    ) -> Result<AuditorReportJobView, AuditorClientError> {
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
            return Err(AuditorClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) async fn cancel(
        &self,
        request_id: &str,
    ) -> Result<AuditorReportJobView, AuditorClientError> {
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
            return Err(AuditorClientError::MalformedResponse);
        }
        Ok(view)
    }

    pub(crate) fn base_url_identity(&self) -> &str {
        self.base_url.as_str()
    }

    fn endpoint(&self, request_id: Option<&str>) -> Result<Url, AuditorClientError> {
        if request_id.is_some_and(|value| !valid_product_request_id(value)) {
            return Err(AuditorClientError::InvalidIdentifier);
        }
        let mut url = self.base_url.clone();
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| AuditorClientError::InvalidOrigin)?;
            path.clear().push("v1").push("auditor-reports");
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
) -> Result<AuditorReportJobView, AuditorClientError> {
    let status = response
        .status()
        .map_err(AuditorClientError::Authorization)?;
    let body = read_bounded(&mut response).await?;
    if !successes.contains(&status) {
        let error: ApiError =
            serde_json::from_slice(&body).map_err(|_| AuditorClientError::MalformedResponse)?;
        if !valid_identifier(&error.code)
            || error.message.is_empty()
            || error.message.len() > 512
            || !error.request_id.starts_with("req-")
            || !valid_identifier(&error.request_id)
        {
            return Err(AuditorClientError::MalformedResponse);
        }
        return Err(AuditorClientError::Api {
            status,
            code: error.code,
            retryable: error.retryable,
        });
    }
    let view = decode_job_view(body)?;
    response
        .ensure_current()
        .map_err(AuditorClientError::Authorization)?;
    Ok(view)
}

fn decode_job_view(body: Vec<u8>) -> Result<AuditorReportJobView, AuditorClientError> {
    let view: AuditorReportJobView =
        serde_json::from_slice(&body).map_err(|_| AuditorClientError::MalformedResponse)?;
    if !view.is_valid() {
        return Err(AuditorClientError::MalformedResponse);
    }
    Ok(view)
}

async fn read_bounded(response: &mut AuthenticatedResponse) -> Result<Vec<u8>, AuditorClientError> {
    if response
        .content_length()
        .map_err(AuditorClientError::Authorization)?
        .is_some_and(|length| length > MAXIMUM_RESPONSE_BYTES as u64)
    {
        return Err(AuditorClientError::ResponseTooLarge);
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(map_dispatch)? {
        if body.len().saturating_add(chunk.len()) > MAXIMUM_RESPONSE_BYTES {
            return Err(AuditorClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn map_dispatch(error: AuthenticatedDispatchError) -> AuditorClientError {
    match error {
        AuthenticatedDispatchError::Authorization(error) => {
            AuditorClientError::Authorization(error)
        }
        AuthenticatedDispatchError::Transport(_) => AuditorClientError::Transport,
    }
}

fn citation_identity(citation: &AuditorCitation) -> (&str, &str, &str, u64, u64) {
    (
        citation.concept_id.as_str(),
        citation.source_revision.as_str(),
        citation.content_sha256.as_str(),
        citation.char_start,
        citation.char_end,
    )
}

fn finding_sha256(finding: &AuditorFinding) -> Option<String> {
    canonical_sha256(&serde_json::json!({
        "citations": finding.citations,
        "kind": finding.kind,
        "summary": finding.summary,
    }))
}

fn report_citation_sha256(findings: &[AuditorFinding]) -> Option<String> {
    let value = findings
        .iter()
        .map(|finding| &finding.citations)
        .collect::<Vec<_>>();
    canonical_sha256(&value)
}

fn report_sha256(report: &AuditorReport) -> Option<String> {
    canonical_sha256(&serde_json::json!({
        "canonical": false,
        "citationSha256": report.citation_sha256,
        "evidenceSha256": report.evidence_sha256,
        "findings": report.findings,
        "generationSha256": report.generation_sha256,
        "requiresReview": true,
        "schemaVersion": 1,
        "sourceAdmissionSha256": report.source_admission_sha256,
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
    value.strip_prefix("auditor-report-").is_some_and(|suffix| {
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
