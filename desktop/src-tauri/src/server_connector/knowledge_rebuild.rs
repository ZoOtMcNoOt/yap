use super::authorization::{AuthenticatedDispatchError, AuthenticatedRequestDispatcher};
use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

const MAXIMUM_RESPONSE_BYTES: usize = 65_536;
#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(
    tag = "action",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub(crate) enum RebuildRequest {
    Source {},
    Stage {
        generation_sha256: String,
    },
    Embeddings {
        generation_sha256: String,
    },
    Inspect {
        generation_sha256: String,
    },
    Publish {
        generation_sha256: String,
        #[serde(deserialize_with = "nullable_hash")]
        expected_active_generation_sha256: Option<String>,
    },
    Restore {
        generation_sha256: String,
        #[serde(deserialize_with = "nullable_hash")]
        expected_active_generation_sha256: Option<String>,
    },
}
fn nullable_hash<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Option<String>, D::Error> {
    Option::<String>::deserialize(d)
}
impl RebuildRequest {
    pub(crate) fn mutates(&self) -> bool {
        !matches!(self, Self::Source {} | Self::Inspect { .. })
    }
    fn target(&self) -> Option<&str> {
        match self {
            Self::Source {} => None,
            Self::Stage { generation_sha256 }
            | Self::Embeddings { generation_sha256 }
            | Self::Inspect { generation_sha256 }
            | Self::Publish {
                generation_sha256, ..
            }
            | Self::Restore {
                generation_sha256, ..
            } => Some(generation_sha256),
        }
    }
    fn valid(&self) -> bool {
        self.target().is_none_or(hash)
            && match self {
                Self::Publish {
                    expected_active_generation_sha256,
                    ..
                }
                | Self::Restore {
                    expected_active_generation_sha256,
                    ..
                } => expected_active_generation_sha256
                    .as_deref()
                    .is_none_or(hash),
                _ => true,
            }
    }
}
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct RebuildError {
    pub(crate) code: &'static str,
    pub(crate) unconfirmed: bool,
}
impl RebuildError {
    pub(crate) fn new(code: &'static str, unconfirmed: bool) -> Self {
        Self { code, unconfirmed }
    }
}
#[derive(Debug, Serialize)]
pub(crate) struct RebuildResponse {
    kind: &'static str,
    value: Value,
}
fn hash(v: &str) -> bool {
    v.len() == 64
        && v.bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
fn text(v: &Value, max: usize) -> bool {
    v.as_str().is_some_and(|s| {
        !s.is_empty()
            && s.trim() == s
            && s.chars().count() <= max
            && !s.chars().any(char::is_control)
    })
}
fn reference(v: &Value) -> bool {
    v.is_null() || v.as_str().is_some_and(hash)
}
fn count(v: &Value) -> bool {
    v.as_u64().is_some_and(|n| n <= 1_000_000)
}
// Reject duplicate top-level receipt fields as well as missing/unknown fields.
struct Wire(Map<String, Value>);
impl<'de> Deserialize<'de> for Wire {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct Visitor;
        impl<'de> serde::de::Visitor<'de> for Visitor {
            type Value = Wire;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("a unique receipt object")
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(self, mut a: A) -> Result<Wire, A::Error> {
                let mut m = Map::new();
                while let Some((k, v)) = a.next_entry::<String, Value>()? {
                    if m.insert(k, v).is_some() {
                        return Err(serde::de::Error::custom("duplicate receipt field"));
                    }
                }
                Ok(Wire(m))
            }
        }
        d.deserialize_map(Visitor)
    }
}
fn decode(request: &RebuildRequest, body: &[u8]) -> Result<RebuildResponse, RebuildError> {
    let invalid = || RebuildError::new("invalidResponse", request.mutates());
    if body.len() > MAXIMUM_RESPONSE_BYTES {
        return Err(invalid());
    }
    let Wire(m) = serde_json::from_slice::<Wire>(body).map_err(|_| invalid())?;
    let fields = if matches!(request, RebuildRequest::Embeddings { .. }) {
        vec![
            "schemaVersion",
            "generationSha256",
            "status",
            "chunkCount",
            "embeddingModelId",
            "embeddingModelRevision",
            "changed",
        ]
    } else {
        let mut fields = vec![
            "schemaVersion",
            "generationSha256",
            "sourceRevision",
            "status",
            "activeGenerationSha256",
            "conceptCount",
            "chunkCount",
            "relationshipCount",
            "permissionCount",
        ];
        if matches!(
            request,
            RebuildRequest::Source {} | RebuildRequest::Stage { .. }
        ) {
            fields.push("sourcePath");
        }
        if request.mutates() {
            fields.push("changed");
        }
        if matches!(
            request,
            RebuildRequest::Publish { .. } | RebuildRequest::Restore { .. }
        ) {
            fields.push("previousActiveGenerationSha256");
        }
        fields
    };
    if m.len() != fields.len() || fields.iter().any(|f| !m.contains_key(*f)) {
        return Err(invalid());
    }
    let wire = Value::Object(m);
    if wire["schemaVersion"].as_u64() != Some(1)
        || !wire["generationSha256"].as_str().is_some_and(hash)
        || request
            .target()
            .is_some_and(|t| wire["generationSha256"].as_str() != Some(t))
        || !count(&wire["chunkCount"])
        || request.mutates() && !wire["changed"].is_boolean()
    {
        return Err(invalid());
    }
    let kind = match request {
        RebuildRequest::Embeddings { .. } => {
            if wire["status"] != "prepared"
                || !wire["embeddingModelId"].as_str().is_some_and(|s| {
                    !s.is_empty() && s.len() <= 128 && s.bytes().all(|c| c.is_ascii_graphic())
                })
                || !wire["embeddingModelRevision"].as_str().is_some_and(hash)
            {
                return Err(invalid());
            }
            "prepared"
        }
        _ => {
            if !text(&wire["sourceRevision"], 512)
                || !["conceptCount", "relationshipCount", "permissionCount"]
                    .iter()
                    .all(|f| count(&wire[*f]))
                || !reference(&wire["activeGenerationSha256"])
            {
                return Err(invalid());
            }
            let source = matches!(
                request,
                RebuildRequest::Source {} | RebuildRequest::Stage { .. }
            );
            if source && !text(&wire["sourcePath"], 512) {
                return Err(invalid());
            }
            let status = wire["status"].as_str().ok_or_else(invalid)?;
            if !(["staged", "active", "retained"].contains(&status)
                || matches!(request, RebuildRequest::Source {}) && status == "unadmitted")
                || (status == "active")
                    != (wire["activeGenerationSha256"] == wire["generationSha256"])
            {
                return Err(invalid());
            }
            match request {
                RebuildRequest::Publish {
                    expected_active_generation_sha256,
                    ..
                }
                | RebuildRequest::Restore {
                    expected_active_generation_sha256,
                    ..
                } => {
                    let previous = &wire["previousActiveGenerationSha256"];
                    let expected = if wire["changed"] == true {
                        serde_json::to_value(expected_active_generation_sha256)
                            .map_err(|_| invalid())?
                    } else {
                        wire["generationSha256"].clone()
                    };
                    if status != "active" || !reference(previous) || *previous != expected {
                        return Err(invalid());
                    }
                    "activated"
                }
                RebuildRequest::Stage { .. } => "staged",
                RebuildRequest::Source {} => "source",
                _ => "generation",
            }
        }
    };
    Ok(RebuildResponse { kind, value: wire })
}
pub(crate) struct RebuildClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}
impl RebuildClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, RebuildError> {
        let mut base_url = Url::parse(base_url).map_err(|_| RebuildError::new("invalid", false))?;
        if !matches!(base_url.scheme(), "http" | "https")
            || base_url.cannot_be_a_base()
            || !base_url.username().is_empty()
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            return Err(RebuildError::new("invalid", false));
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
        request: &RebuildRequest,
    ) -> Result<RebuildResponse, RebuildError> {
        if !request.valid() {
            return Err(RebuildError::new("invalid", false));
        }
        let uncertain = || RebuildError::new("unavailable", request.mutates());
        let identity_changed = |_| RebuildError::new("identityChanged", request.mutates());
        let dispatch_error = |error| match error {
            AuthenticatedDispatchError::Authorization(_) => {
                RebuildError::new("identityChanged", request.mutates())
            }
            AuthenticatedDispatchError::Transport(_) => uncertain(),
        };
        let mut url = self.base_url.clone();
        url.set_path(match request {
            RebuildRequest::Source {} | RebuildRequest::Stage { .. } => {
                "/v1/knowledge/source-preparations"
            }
            RebuildRequest::Embeddings { .. } => "/v1/knowledge/embedding-preparations",
            RebuildRequest::Restore { .. } => "/v1/knowledge/rollbacks",
            _ => "/v1/knowledge/publications",
        });
        let outgoing = if request.mutates() {
            let mut body = serde_json::json!({"schemaVersion":1});
            body[if matches!(request, RebuildRequest::Stage { .. }) {
                "expectedGenerationSha256"
            } else {
                "generationSha256"
            }] = Value::String(request.target().unwrap().to_owned());
            if let RebuildRequest::Publish {
                expected_active_generation_sha256,
                ..
            }
            | RebuildRequest::Restore {
                expected_active_generation_sha256,
                ..
            } = request
            {
                body["expectedActiveGenerationSha256"] =
                    serde_json::to_value(expected_active_generation_sha256)
                        .map_err(|_| RebuildError::new("invalid", false))?;
            }
            self.authenticated
                .post(url)
                .header(reqwest::header::CONTENT_TYPE, "application/json")
                .body(serde_json::to_vec(&body).map_err(|_| RebuildError::new("invalid", false))?)
        } else {
            if let RebuildRequest::Inspect { generation_sha256 } = request {
                url.query_pairs_mut()
                    .append_pair("generationSha256", generation_sha256);
            }
            self.authenticated.get(url)
        };
        // Override the health client's short request timeout; the provider has its own 10s ceiling.
        let mut response = self
            .authenticated
            .send(
                outgoing
                    .timeout(std::time::Duration::from_secs(18))
                    .header(reqwest::header::ACCEPT, "application/json"),
            )
            .await
            .map_err(dispatch_error)?;
        let status = response.status().map_err(identity_changed)?;
        if status != StatusCode::OK {
            return Err(match status {
                StatusCode::CONFLICT => RebuildError::new("knowledgeChanged", false),
                StatusCode::FORBIDDEN => RebuildError::new("denied", false),
                StatusCode::UNAUTHORIZED => RebuildError::new("identityChanged", request.mutates()),
                StatusCode::NOT_FOUND => RebuildError::new("notFound", false),
                StatusCode::BAD_REQUEST => RebuildError::new("invalid", false),
                _ => uncertain(),
            });
        }
        if response
            .content_length()
            .map_err(identity_changed)?
            .is_some_and(|n| n > MAXIMUM_RESPONSE_BYTES as u64)
        {
            return Err(RebuildError::new("invalidResponse", request.mutates()));
        }
        let mut body = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(dispatch_error)? {
            if body.len().saturating_add(chunk.len()) > MAXIMUM_RESPONSE_BYTES {
                return Err(RebuildError::new("invalidResponse", request.mutates()));
            }
            body.extend_from_slice(&chunk);
        }
        response.ensure_current().map_err(identity_changed)?;
        decode(request, &body)
    }
}
#[cfg(test)]
mod tests;
