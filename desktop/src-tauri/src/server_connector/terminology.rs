use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};

use super::authorization::{
    AuthenticatedDispatchError, AuthenticatedRequestDispatcher, RequestAuthorizationError,
};

const MAXIMUM_RESPONSE_BYTES: usize = 4 * 1024 * 1024;

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct TerminologyScope {
    scope_id: String,
    kind: String,
    label: String,
    can_manage: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct TerminologyScopes {
    scopes: Vec<TerminologyScope>,
}

impl TerminologyScopes {
    fn is_valid(&self) -> bool {
        if !(1..=34).contains(&self.scopes.len()) {
            return false;
        }
        let mut seen = std::collections::HashSet::new();
        self.scopes.iter().all(|s| {
            valid_scope(&s.scope_id)
                && seen.insert(s.scope_id.as_str())
                && match s.kind.as_str() {
                    "personal" => s.scope_id == "personal" && s.can_manage,
                    "organization" => s.scope_id == "organization",
                    "team" => s.scope_id.starts_with("team:"),
                    _ => false,
                }
                && !s.label.is_empty()
                && s.label.trim() == s.label
                && s.label.chars().count() <= 128
                && !s.label.chars().any(char::is_control)
        }) && seen.contains("personal")
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(
    tag = "action",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub(crate) enum TerminologyRequest {
    Discover {},
    Read {
        scope_id: String,
        record_id: String,
    },
    List {
        scope_id: String,
        locale: String,
        after: Option<String>,
    },
    Create {
        scope_id: String,
        mutation_id: String,
        locale: String,
        canonical_form: String,
        variants: Vec<String>,
        sensitivity: Sensitivity,
    },
    Edit {
        scope_id: String,
        record_id: String,
        expected_version: u64,
        canonical_form: String,
        variants: Vec<String>,
        sensitivity: Sensitivity,
    },
    Delete {
        scope_id: String,
        record_id: String,
        expected_version: u64,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub(crate) enum Sensitivity {
    Public,
    Internal,
    Confidential,
    Restricted,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct Term {
    scope_id: String,
    record_id: String,
    locale: String,
    canonical_form: String,
    variants: Vec<String>,
    sensitivity: Sensitivity,
    version: u64,
    changed_at: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct TerminologyPage {
    scope_id: String,
    records: Vec<Term>,
    next_cursor: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct TerminologyDeleted {
    scope_id: String,
    record_id: String,
    version: u64,
    deleted: bool,
}

#[derive(Debug, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "camelCase")]
pub(crate) enum TerminologyResponse {
    Scopes(TerminologyScopes),
    Page(TerminologyPage),
    Record(Term),
    Deleted(TerminologyDeleted),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct TerminologyError {
    pub(crate) code: &'static str,
    pub(crate) retryable: bool,
}

impl TerminologyError {
    pub(crate) fn new(code: &'static str, retryable: bool) -> Self {
        Self { code, retryable }
    }
}

impl TerminologyRequest {
    fn scope_id(&self) -> Option<&str> {
        match self {
            Self::Discover {} => None,
            Self::Read { scope_id, .. }
            | Self::List { scope_id, .. }
            | Self::Create { scope_id, .. }
            | Self::Edit { scope_id, .. }
            | Self::Delete { scope_id, .. } => Some(scope_id),
        }
    }
    fn is_valid(&self) -> bool {
        if self.scope_id().is_some_and(|s| !valid_scope(s)) {
            return false;
        }
        match self {
            Self::Discover {} => true,
            Self::Read { record_id, .. } => valid_id(record_id),
            Self::List { locale, after, .. } => {
                valid_locale(locale) && after.as_ref().is_none_or(|v| valid_id(v))
            }
            Self::Create {
                mutation_id,
                locale,
                canonical_form,
                variants,
                ..
            } => {
                valid_uuid(mutation_id)
                    && valid_locale(locale)
                    && valid_content(canonical_form, variants)
            }
            Self::Edit {
                record_id,
                expected_version,
                canonical_form,
                variants,
                ..
            } => {
                valid_id(record_id)
                    && valid_version(*expected_version)
                    && valid_content(canonical_form, variants)
            }
            Self::Delete {
                record_id,
                expected_version,
                ..
            } => valid_id(record_id) && valid_version(*expected_version),
        }
    }
}

impl Term {
    fn is_valid(&self) -> bool {
        valid_scope(&self.scope_id)
            && valid_id(&self.record_id)
            && valid_locale(&self.locale)
            && valid_content(&self.canonical_form, &self.variants)
            && valid_version(self.version)
            && time::OffsetDateTime::parse(
                &self.changed_at,
                &time::format_description::well_known::Rfc3339,
            )
            .is_ok()
    }
}

#[derive(Clone)]
pub(crate) struct TerminologyClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}

impl TerminologyClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, TerminologyError> {
        let mut base_url = Url::parse(base_url).map_err(|_| invalid())?;
        if !matches!(base_url.scheme(), "http" | "https")
            || base_url.cannot_be_a_base()
            || !base_url.username().is_empty()
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            return Err(invalid());
        }
        base_url.set_path("/");
        Ok(Self {
            authenticated,
            base_url,
        })
    }

    pub(crate) fn base_url_identity(&self) -> &str {
        self.base_url.as_str()
    }

    pub(crate) async fn execute(
        &self,
        request: &TerminologyRequest,
    ) -> Result<TerminologyResponse, TerminologyError> {
        if !request.is_valid() {
            return Err(TerminologyError::new("invalid", false));
        }
        let mut url = self.base_url.clone();
        url.set_path("/v1/terminology");
        if let Some(scope) = request.scope_id() {
            url.query_pairs_mut().append_pair("scopeId", scope);
        }
        let builder = match request {
            TerminologyRequest::Discover {} => {
                url.set_path("/v1/terminology/scopes");
                self.authenticated.get(url)
            }
            TerminologyRequest::Read { record_id, .. } => {
                url.path_segments_mut()
                    .map_err(|_| invalid())?
                    .push(record_id);
                self.authenticated.get(url)
            }
            TerminologyRequest::List { locale, after, .. } => {
                url.query_pairs_mut().append_pair("locale", locale);
                if let Some(after) = after {
                    url.query_pairs_mut().append_pair("after", after);
                }
                self.authenticated.get(url)
            }
            TerminologyRequest::Create {
                mutation_id,
                locale,
                canonical_form,
                variants,
                sensitivity,
                ..
            } => json_body(
                self.authenticated.post(url),
                serde_json::json!({"mutationId":mutation_id,"locale":locale,"canonicalForm":canonical_form,"variants":variants,"sensitivity":sensitivity}),
            )?,
            TerminologyRequest::Edit {
                record_id,
                expected_version,
                canonical_form,
                variants,
                sensitivity,
                ..
            } => {
                url.path_segments_mut()
                    .map_err(|_| invalid())?
                    .push(record_id);
                json_body(
                    self.authenticated.put(url),
                    serde_json::json!({"expectedVersion":expected_version,"canonicalForm":canonical_form,"variants":variants,"sensitivity":sensitivity}),
                )?
            }
            TerminologyRequest::Delete {
                record_id,
                expected_version,
                ..
            } => {
                url.path_segments_mut()
                    .map_err(|_| invalid())?
                    .push(record_id);
                json_body(
                    self.authenticated.delete(url),
                    serde_json::json!({"expectedVersion":expected_version}),
                )?
            }
        };
        let mut response = self
            .authenticated
            .send(builder.header(reqwest::header::ACCEPT, "application/json"))
            .await
            .map_err(map_dispatch)?;
        let status = response.status().map_err(map_authorization)?;
        if response
            .content_length()
            .map_err(map_authorization)?
            .is_some_and(|n| n > MAXIMUM_RESPONSE_BYTES as u64)
        {
            return Err(invalid());
        }
        let mut body = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(map_dispatch)? {
            if body.len().saturating_add(chunk.len()) > MAXIMUM_RESPONSE_BYTES {
                return Err(invalid());
            }
            body.extend_from_slice(&chunk);
        }
        response.ensure_current().map_err(map_authorization)?;
        if !status.is_success() {
            return Err(match status {
                StatusCode::CONFLICT => TerminologyError::new("conflict", false),
                StatusCode::UNAUTHORIZED => TerminologyError::new("identityChanged", false),
                StatusCode::FORBIDDEN => TerminologyError::new("denied", false),
                StatusCode::NOT_FOUND => TerminologyError::new("notFound", false),
                StatusCode::BAD_REQUEST => TerminologyError::new("invalid", false),
                StatusCode::SERVICE_UNAVAILABLE | StatusCode::TOO_MANY_REQUESTS => {
                    TerminologyError::new("unavailable", true)
                }
                _ => invalid(),
            });
        }
        let result = decode_response(request, status, &body)?;
        response.ensure_current().map_err(map_authorization)?;
        Ok(result)
    }
}

fn decode_response(
    request: &TerminologyRequest,
    status: StatusCode,
    body: &[u8],
) -> Result<TerminologyResponse, TerminologyError> {
    let scope = request.scope_id();
    match request {
        TerminologyRequest::Discover {} if status == StatusCode::OK => {
            let scopes: TerminologyScopes = serde_json::from_slice(body).map_err(|_| invalid())?;
            if !scopes.is_valid() {
                return Err(invalid());
            }
            Ok(TerminologyResponse::Scopes(scopes))
        }
        TerminologyRequest::Read { record_id, .. } if status == StatusCode::OK => {
            let record: Term = serde_json::from_slice(body).map_err(|_| invalid())?;
            if Some(record.scope_id.as_str()) != scope
                || !record.is_valid()
                || record.record_id != *record_id
            {
                return Err(invalid());
            }
            Ok(TerminologyResponse::Record(record))
        }
        TerminologyRequest::List { locale, after, .. } if status == StatusCode::OK => {
            let page: TerminologyPage = serde_json::from_slice(body).map_err(|_| invalid())?;
            if Some(page.scope_id.as_str()) != scope
                || page.records.len() > 10
                || page.records.iter().any(|r| {
                    Some(r.scope_id.as_str()) != scope
                        || !r.is_valid()
                        || (r.locale != *locale && r.locale != "und")
                })
                || page
                    .records
                    .windows(2)
                    .any(|p| p[0].record_id >= p[1].record_id)
                || after.as_ref().is_some_and(|after| {
                    page.records.first().is_some_and(|r| r.record_id <= *after)
                })
                || page.next_cursor.as_ref().is_some_and(|c| {
                    page.records.len() != 10
                        || page.records.last().is_none_or(|r| r.record_id != *c)
                })
            {
                return Err(invalid());
            }
            Ok(TerminologyResponse::Page(page))
        }
        TerminologyRequest::Create {
            locale,
            canonical_form,
            variants,
            sensitivity,
            ..
        } if status == StatusCode::CREATED => {
            let record: Term = serde_json::from_slice(body).map_err(|_| invalid())?;
            if Some(record.scope_id.as_str()) != scope
                || !record.is_valid()
                || record.version != 1
                || record.locale != *locale
                || record.canonical_form != *canonical_form
                || record.variants != *variants
                || record.sensitivity != *sensitivity
            {
                return Err(invalid());
            }
            Ok(TerminologyResponse::Record(record))
        }
        TerminologyRequest::Edit {
            record_id,
            expected_version,
            canonical_form,
            variants,
            sensitivity,
            ..
        } if status == StatusCode::OK => {
            let record: Term = serde_json::from_slice(body).map_err(|_| invalid())?;
            if Some(record.scope_id.as_str()) != scope
                || !record.is_valid()
                || record.record_id != *record_id
                || record.version != expected_version + 1
                || record.canonical_form != *canonical_form
                || record.variants != *variants
                || record.sensitivity != *sensitivity
            {
                return Err(invalid());
            }
            Ok(TerminologyResponse::Record(record))
        }
        TerminologyRequest::Delete {
            record_id,
            expected_version,
            ..
        } if status == StatusCode::OK => {
            let receipt: TerminologyDeleted =
                serde_json::from_slice(body).map_err(|_| invalid())?;
            if Some(receipt.scope_id.as_str()) != scope
                || receipt.record_id != *record_id
                || receipt.version != expected_version + 1
                || !receipt.deleted
            {
                return Err(invalid());
            }
            Ok(TerminologyResponse::Deleted(receipt))
        }
        _ => Err(invalid()),
    }
}

fn json_body(
    builder: reqwest::RequestBuilder,
    body: serde_json::Value,
) -> Result<reqwest::RequestBuilder, TerminologyError> {
    Ok(builder
        .header(reqwest::header::CONTENT_TYPE, "application/json")
        .body(serde_json::to_vec(&body).map_err(|_| invalid())?))
}

fn valid_scope(v: &str) -> bool {
    matches!(v, "personal" | "organization") || v.strip_prefix("team:").is_some_and(valid_id)
}

fn valid_version(v: u64) -> bool {
    (1..i64::MAX as u64).contains(&v)
}
fn valid_id(v: &str) -> bool {
    !v.is_empty()
        && v.len() <= 128
        && v.as_bytes()[0].is_ascii_alphanumeric()
        && v.bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"._:-".contains(&c))
}
fn valid_uuid(v: &str) -> bool {
    v.len() == 36
        && v.bytes().enumerate().all(|(i, c)| {
            if [8, 13, 18, 23].contains(&i) {
                c == b'-'
            } else {
                c.is_ascii_digit() || (b'a'..=b'f').contains(&c)
            }
        })
}
fn valid_locale(v: &str) -> bool {
    if v == "und" {
        return true;
    }
    let mut parts = v.split('-');
    if !parts
        .next()
        .is_some_and(|p| (2..=3).contains(&p.len()) && p.bytes().all(|c| c.is_ascii_lowercase()))
    {
        return false;
    }
    let mut tail = parts.next();
    if tail.is_some_and(|p| {
        p.len() == 4
            && p.as_bytes()[0].is_ascii_uppercase()
            && p.as_bytes()[1..].iter().all(|c| c.is_ascii_lowercase())
    }) {
        tail = parts.next();
    }
    tail.is_none_or(|p| {
        (p.len() == 2 && p.bytes().all(|c| c.is_ascii_uppercase()))
            || (p.len() == 3 && p.bytes().all(|c| c.is_ascii_digit()))
    }) && parts.next().is_none()
}
fn valid_form(v: &str) -> bool {
    !v.is_empty() && v.trim() == v && v.chars().count() <= 512 && !v.contains(['\0', '\r', '\n'])
}
fn valid_content(form: &str, variants: &[String]) -> bool {
    valid_form(form) && (1..=64).contains(&variants.len()) && variants.iter().all(|v| valid_form(v))
}
fn invalid() -> TerminologyError {
    TerminologyError::new("invalidResponse", false)
}
fn map_authorization(_: RequestAuthorizationError) -> TerminologyError {
    TerminologyError::new("identityChanged", false)
}
fn map_dispatch(error: AuthenticatedDispatchError) -> TerminologyError {
    match error {
        AuthenticatedDispatchError::Authorization(e) => map_authorization(e),
        AuthenticatedDispatchError::Transport(_) => TerminologyError::new("unavailable", true),
    }
}

#[cfg(test)]
mod tests;
