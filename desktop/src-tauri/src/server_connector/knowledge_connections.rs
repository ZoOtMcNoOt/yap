use super::{connection_candidate::ConnectionCandidate, curator::CuratorSourceCitation};
use reqwest::{StatusCode, Url};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

use super::authorization::{
    AuthenticatedDispatchError, AuthenticatedRequestDispatcher, RequestAuthorizationError,
};

const MAXIMUM_RESPONSE_BYTES: usize = 65_536;
// Match the OKF document byte ceiling; character offsets cannot exceed it.
const MAXIMUM_SOURCE_CHARACTERS: u64 = 1_000_000;

#[derive(Debug, Clone, Deserialize)]
#[serde(
    tag = "action",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub(crate) enum ConnectionsRequest {
    Proposal {
        proposal_id: String,
    },
    Discard {
        proposal_id: String,
    },
    Browse {
        search: String,
    },
    Read {
        concept_id: String,
        generation_sha256: String,
    },
}

impl ConnectionsRequest {
    fn is_valid(&self) -> bool {
        match self {
            Self::Proposal { proposal_id } | Self::Discard { proposal_id } => hash(proposal_id),
            Self::Browse { search } => {
                search.chars().count() <= 128
                    && search.trim() == search
                    && !search.chars().any(char::is_control)
            }
            Self::Read {
                concept_id,
                generation_sha256,
            } => text(concept_id, 512) && hash(generation_sha256),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ConnectionNode {
    concept_id: String,
    #[serde(rename = "type")]
    kind: String,
    title: String,
    source_path: String,
    source_revision: String,
    content_sha256: String,
}
impl ConnectionNode {
    fn is_valid(&self) -> bool {
        text(&self.concept_id, 512)
            && text(&self.kind, 128)
            && text(&self.title, 1024)
            && text(&self.source_path, 512)
            && text(&self.source_revision, 512)
            && hash(&self.content_sha256)
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ConnectionCitation {
    source_path: String,
    source_revision: String,
    content_sha256: String,
    #[serde(deserialize_with = "nullable_offset")]
    char_start: Option<u64>,
    #[serde(deserialize_with = "nullable_offset")]
    char_end: Option<u64>,
}
fn nullable_offset<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<u64>, D::Error> {
    Option::<u64>::deserialize(deserializer)
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum RelationshipAuthority {
    Asserted,
    HumanConfirmed,
    Derived,
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ConnectionRelationship {
    relationship_id: String,
    source_concept_id: String,
    target_concept_id: String,
    #[serde(rename = "type")]
    kind: String,
    authority: RelationshipAuthority,
    citation: ConnectionCitation,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ConceptPage {
    schema_version: u8,
    generation_sha256: String,
    permission_hash: String,
    authorization_hash: String,
    nodes: Vec<ConnectionNode>,
    has_more: bool,
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct KnowledgeNeighborhood {
    schema_version: u8,
    generation_sha256: String,
    permission_hash: String,
    authorization_hash: String,
    concept_id: String,
    nodes: Vec<ConnectionNode>,
    relationships: Vec<ConnectionRelationship>,
    has_more: bool,
}
#[derive(Debug, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "camelCase")]
pub(crate) enum ConnectionsResponse {
    Proposal(ConnectionProposal),
    Discarded(ConnectionProposalDisposition),
    Topics(ConceptPage),
    Neighborhood(KnowledgeNeighborhood),
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ConnectionProposalDisposition {
    schema_version: u8,
    generation_sha256: String,
    proposal_id: String,
    status: DiscardedStatus,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum DiscardedStatus {
    Discarded,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct ConnectionProposal {
    schema_version: u8,
    generation_sha256: String,
    permission_hash: String,
    authorization_hash: String,
    proposal_id: String,
    status: ProposalStatus,
    candidate: ProposalCandidate,
    sources: Vec<ProposalSource>,
}

// HTTP/native projections use camelCase; the persisted Curator candidate stays
// unchanged. Validation delegates to the shared storage contract.
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ProposalCandidate {
    schema_version: u16,
    source_concept_id: String,
    target_concept_id: String,
    relationship_type: String,
    rationale: String,
}
impl ProposalCandidate {
    fn is_valid(&self) -> bool {
        ConnectionCandidate {
            schema_version: self.schema_version,
            source_concept_id: self.source_concept_id.clone(),
            target_concept_id: self.target_concept_id.clone(),
            relationship_type: self.relationship_type.clone(),
            rationale: self.rationale.clone(),
        }
        .is_valid()
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum ProposalStatus {
    Proposed,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ProposalSource {
    node: ConnectionNode,
    citation: CuratorSourceCitation,
    text: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ConnectionsError {
    pub(crate) code: &'static str,
    pub(crate) retryable: bool,
}
impl ConnectionsError {
    pub(crate) fn new(code: &'static str, retryable: bool) -> Self {
        Self { code, retryable }
    }
}
fn invalid() -> ConnectionsError {
    ConnectionsError::new("invalidResponse", false)
}
fn text(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.trim() == value
        && value.chars().count() <= maximum
        && !value.chars().any(char::is_control)
}
fn hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
fn context(schema: u8, generation: &str, permission: &str, authorization: &str) -> bool {
    schema == 1
        && [generation, permission, authorization]
            .iter()
            .all(|v| hash(v))
}
fn valid_nodes(nodes: &[ConnectionNode], maximum: usize) -> bool {
    let mut ids = HashSet::new();
    nodes.len() <= maximum
        && nodes
            .iter()
            .all(|n| n.is_valid() && ids.insert(n.concept_id.as_str()))
}
fn decode(
    request: &ConnectionsRequest,
    body: &[u8],
) -> Result<ConnectionsResponse, ConnectionsError> {
    if body.len() > MAXIMUM_RESPONSE_BYTES {
        return Err(invalid());
    }
    match request {
        ConnectionsRequest::Discard { proposal_id } => {
            let disposition: ConnectionProposalDisposition =
                serde_json::from_slice(body).map_err(|_| invalid())?;
            if disposition.schema_version != 1
                || !hash(&disposition.generation_sha256)
                || !hash(&disposition.proposal_id)
                || disposition.proposal_id != *proposal_id
            {
                return Err(invalid());
            }
            Ok(ConnectionsResponse::Discarded(disposition))
        }
        ConnectionsRequest::Proposal { proposal_id } => {
            let proposal: ConnectionProposal =
                serde_json::from_slice(body).map_err(|_| invalid())?;
            let mut ids = HashSet::new();
            if !context(
                proposal.schema_version,
                &proposal.generation_sha256,
                &proposal.permission_hash,
                &proposal.authorization_hash,
            ) || proposal.proposal_id != *proposal_id
                || !hash(&proposal.proposal_id)
                || !proposal.candidate.is_valid()
                || proposal.sources.len() != 2
                || proposal.sources.iter().any(|source| {
                    !source.node.is_valid()
                        || !source.citation.is_valid()
                        || source.citation.char_end > MAXIMUM_SOURCE_CHARACTERS
                        || source.text.contains('\0')
                        || source.text.chars().count() > 1_024
                        || source.text.chars().count() as u64
                            != source.citation.char_end - source.citation.char_start
                        || source.node.concept_id != source.citation.concept_id
                        || source.node.source_revision != source.citation.source_revision
                        || source.node.content_sha256 != source.citation.content_sha256
                        || !ids.insert(source.node.concept_id.as_str())
                })
                || !ids.contains(proposal.candidate.source_concept_id.as_str())
                || !ids.contains(proposal.candidate.target_concept_id.as_str())
            {
                return Err(invalid());
            }
            Ok(ConnectionsResponse::Proposal(proposal))
        }
        ConnectionsRequest::Browse { .. } => {
            let page: ConceptPage = serde_json::from_slice(body).map_err(|_| invalid())?;
            if !context(
                page.schema_version,
                &page.generation_sha256,
                &page.permission_hash,
                &page.authorization_hash,
            ) || !valid_nodes(&page.nodes, 12)
                || (page.has_more && page.nodes.len() != 12)
            {
                return Err(invalid());
            }
            Ok(ConnectionsResponse::Topics(page))
        }
        ConnectionsRequest::Read {
            concept_id,
            generation_sha256,
        } => {
            let graph: KnowledgeNeighborhood =
                serde_json::from_slice(body).map_err(|_| invalid())?;
            if !context(
                graph.schema_version,
                &graph.generation_sha256,
                &graph.permission_hash,
                &graph.authorization_hash,
            ) || graph.concept_id != *concept_id
                || graph.generation_sha256 != *generation_sha256
                || !valid_nodes(&graph.nodes, 17)
                || graph.relationships.len() > 16
                || (graph.has_more && graph.relationships.len() != 16)
            {
                return Err(invalid());
            }
            let nodes: HashMap<_, _> = graph
                .nodes
                .iter()
                .map(|n| (n.concept_id.as_str(), n))
                .collect();
            if !nodes.contains_key(concept_id.as_str()) {
                return Err(invalid());
            }
            let mut edges = HashSet::new();
            let mut connected = HashSet::from([concept_id.as_str()]);
            for edge in &graph.relationships {
                let Some(source) = nodes.get(edge.source_concept_id.as_str()) else {
                    return Err(invalid());
                };
                if !nodes.contains_key(edge.target_concept_id.as_str())
                    || !hash(&edge.relationship_id)
                    || !edges.insert(edge.relationship_id.as_str())
                    || !text(&edge.kind, 128)
                    || (edge.source_concept_id != *concept_id
                        && edge.target_concept_id != *concept_id)
                    || edge.citation.source_path != source.source_path
                    || edge.citation.source_revision != source.source_revision
                    || edge.citation.content_sha256 != source.content_sha256
                    || !matches!(
                        (edge.citation.char_start, edge.citation.char_end),
                        (None, None)
                    ) && !matches!((edge.citation.char_start, edge.citation.char_end), (Some(start), Some(end)) if start < end && end <= MAXIMUM_SOURCE_CHARACTERS)
                {
                    return Err(invalid());
                }
                connected.insert(edge.source_concept_id.as_str());
                connected.insert(edge.target_concept_id.as_str());
            }
            if connected.len() != nodes.len() {
                return Err(invalid());
            }
            Ok(ConnectionsResponse::Neighborhood(graph))
        }
    }
}

pub(crate) struct ConnectionsClient {
    authenticated: AuthenticatedRequestDispatcher,
    base_url: Url,
}
impl ConnectionsClient {
    pub(crate) fn new(
        authenticated: AuthenticatedRequestDispatcher,
        base_url: &str,
    ) -> Result<Self, ConnectionsError> {
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
        request: &ConnectionsRequest,
    ) -> Result<ConnectionsResponse, ConnectionsError> {
        if !request.is_valid() {
            return Err(ConnectionsError::new("invalid", false));
        }
        let mut url = self.base_url.clone();
        match request {
            ConnectionsRequest::Proposal { proposal_id }
            | ConnectionsRequest::Discard { proposal_id } => {
                url.set_path("/v1/knowledge/connection-proposal");
                url.query_pairs_mut().append_pair("proposalId", proposal_id);
            }
            ConnectionsRequest::Browse { search } => {
                url.set_path("/v1/knowledge/concepts");
                url.query_pairs_mut().append_pair("search", search);
            }
            ConnectionsRequest::Read {
                concept_id,
                generation_sha256,
            } => {
                url.set_path("/v1/knowledge/connections");
                url.query_pairs_mut()
                    .append_pair("conceptId", concept_id)
                    .append_pair("generationSha256", generation_sha256);
            }
        }
        let outgoing = if matches!(request, ConnectionsRequest::Discard { .. }) {
            self.authenticated.delete(url)
        } else {
            self.authenticated.get(url)
        };
        let mut response = self
            .authenticated
            .send(outgoing.header(reqwest::header::ACCEPT, "application/json"))
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
        if status != StatusCode::OK {
            return Err(match status {
                StatusCode::CONFLICT => ConnectionsError::new("knowledgeChanged", false),
                StatusCode::UNAUTHORIZED => ConnectionsError::new("identityChanged", false),
                StatusCode::FORBIDDEN => ConnectionsError::new("denied", false),
                StatusCode::NOT_FOUND => ConnectionsError::new("notFound", false),
                StatusCode::BAD_REQUEST => ConnectionsError::new("invalid", false),
                StatusCode::SERVICE_UNAVAILABLE | StatusCode::TOO_MANY_REQUESTS => {
                    ConnectionsError::new("unavailable", true)
                }
                _ => invalid(),
            });
        }
        let result = decode(request, &body)?;
        response.ensure_current().map_err(map_authorization)?;
        Ok(result)
    }
}
fn map_authorization(_: RequestAuthorizationError) -> ConnectionsError {
    ConnectionsError::new("identityChanged", false)
}
fn map_dispatch(error: AuthenticatedDispatchError) -> ConnectionsError {
    match error {
        AuthenticatedDispatchError::Authorization(e) => map_authorization(e),
        AuthenticatedDispatchError::Transport(_) => ConnectionsError::new("unavailable", true),
    }
}
#[cfg(test)]
mod tests;
