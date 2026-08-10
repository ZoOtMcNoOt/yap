from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re

from psycopg import Connection
from psycopg.types.json import Jsonb

from yap_server.auth.principal import PrincipalKey

from .postgres_permission_view import authorize_knowledge_query


_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CLASSIFICATION_ORDER = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


@dataclass(frozen=True, slots=True)
class ProposalCitation:
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class KnowledgeProposal:
    tenant_id: str
    proposal_id: str
    generation_sha256: str
    proposal_type: str
    proposed_content: str
    source_citations: tuple[ProposalCitation, ...]
    inherited_permission_sha256: str
    status: str


def install_knowledge_proposal_schema(connection: Connection[object]) -> None:
    with connection.transaction():
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_proposals (
                tenant_id text NOT NULL,
                proposal_id text NOT NULL,
                generation_sha256 text NOT NULL,
                proposer_subject_id text NOT NULL,
                proposer_agent_id text NOT NULL,
                proposal_type text NOT NULL,
                proposed_content text NOT NULL,
                source_citations jsonb NOT NULL,
                inherited_policy jsonb NOT NULL,
                inherited_permission_sha256 text NOT NULL,
                status text NOT NULL CHECK (status = 'proposed'),
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                PRIMARY KEY (tenant_id, proposal_id),
                FOREIGN KEY (tenant_id, generation_sha256)
                    REFERENCES yap_knowledge_builds
            )"""
        )


def store_knowledge_proposal(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_id: str,
    agent_capabilities: frozenset[str],
    proposal_type: str,
    proposed_content: str,
    source_citations: tuple[ProposalCitation, ...],
    expected_generation_sha256: str | None = None,
) -> KnowledgeProposal:
    """Store a noncanonical proposal with exact provenance and inherited policy."""

    _proposal_input(agent_id, proposal_type, proposed_content, source_citations)
    authorized = authorize_knowledge_query(
        connection,
        principal=principal,
        purpose=purpose,
        agent_capabilities=agent_capabilities,
        required_capability="knowledge.propose",
        expected_generation_sha256=expected_generation_sha256,
    )
    citation_ids = tuple(item.concept_id for item in source_citations)
    if not set(citation_ids) <= set(authorized.visible_concept_ids):
        raise PermissionError("proposal source is not visible")
    rows = connection.execute(
        """SELECT c.concept_id, b.source_revision, c.content_sha256,
                  c.body, p.permission_sha256, p.policy
           FROM yap_knowledge_concepts c
           JOIN yap_knowledge_builds b
             ON b.tenant_id = c.tenant_id
            AND b.generation_sha256 = c.generation_sha256
           JOIN yap_knowledge_permissions p
             ON p.tenant_id = c.tenant_id
            AND p.generation_sha256 = c.generation_sha256
            AND p.path_prefix = c.permission_path_prefix
           WHERE c.tenant_id = %s AND c.generation_sha256 = %s
             AND c.concept_id = ANY(%s)""",
        (principal.tenant_id, authorized.generation_sha256, list(citation_ids)),
    ).fetchall()
    by_concept = {str(row[0]): row for row in rows}
    policies: list[dict[str, object]] = []
    for citation in source_citations:
        row = by_concept.get(citation.concept_id)
        if row is None:
            raise ValueError("proposal citation does not exist")
        body = str(row[3])
        if (
            citation.source_revision != row[1]
            or citation.content_sha256 != row[2]
            or citation.char_start < 0
            or citation.char_end <= citation.char_start
            or citation.char_end > len(body)
        ):
            raise ValueError("proposal citation identity is stale or invalid")
        policies.append(dict(row[5]))
    inherited = _strictest_policy(tuple(policies))
    inherited_hash = _sha256(inherited)
    canonical = {
        "tenantId": principal.tenant_id,
        "generationSha256": authorized.generation_sha256,
        "proposerSubjectId": principal.subject_id,
        "proposerAgentId": agent_id,
        "proposalType": proposal_type,
        "proposedContent": proposed_content,
        "sourceCitations": [asdict(item) for item in source_citations],
        "inheritedPermissionSha256": inherited_hash,
    }
    proposal_id = _sha256(canonical)
    with connection.transaction():
        connection.execute(
            """INSERT INTO yap_knowledge_proposals (
                   tenant_id, proposal_id, generation_sha256,
                   proposer_subject_id, proposer_agent_id, proposal_type,
                   proposed_content, source_citations, inherited_policy,
                   inherited_permission_sha256, status
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'proposed')""",
            (
                principal.tenant_id,
                proposal_id,
                authorized.generation_sha256,
                principal.subject_id,
                agent_id,
                proposal_type,
                proposed_content,
                Jsonb(canonical["sourceCitations"]),
                Jsonb(inherited),
                inherited_hash,
            ),
        )
    return KnowledgeProposal(
        principal.tenant_id,
        proposal_id,
        authorized.generation_sha256,
        proposal_type,
        proposed_content,
        source_citations,
        inherited_hash,
        "proposed",
    )


def _strictest_policy(policies: tuple[dict[str, object], ...]) -> dict[str, object]:
    audiences = [
        {
            (str(item["tenantId"]), str(item["subjectId"]))
            for item in policy["audience"]  # type: ignore[union-attr]
        }
        for policy in policies
    ]
    purposes = [set(map(str, policy["purposes"])) for policy in policies]  # type: ignore[arg-type]
    denials = {
        (str(item["tenantId"]), str(item["subjectId"]))
        for policy in policies
        for item in policy["denials"]  # type: ignore[union-attr]
    }
    audience = set.intersection(*audiences) - denials
    classification = max(
        (str(policy["classification"]) for policy in policies),
        key=_CLASSIFICATION_ORDER.__getitem__,
    )
    return {
        "audience": [
            {"tenantId": tenant, "subjectId": subject}
            for tenant, subject in sorted(audience)
        ],
        "denials": [
            {"tenantId": tenant, "subjectId": subject}
            for tenant, subject in sorted(denials)
        ],
        "purposes": sorted(set.intersection(*purposes)),
        "classification": classification,
        "canonical": False,
    }


def _proposal_input(
    agent_id: str,
    proposal_type: str,
    proposed_content: str,
    citations: tuple[ProposalCitation, ...],
) -> None:
    if not _IDENTITY.fullmatch(agent_id) or proposal_type not in {
        "summary",
        "relationship",
    }:
        raise ValueError("knowledge proposal identity is invalid")
    if (
        not isinstance(proposed_content, str)
        or not proposed_content
        or proposed_content.strip() != proposed_content
        or len(proposed_content) > 100_000
    ):
        raise ValueError("knowledge proposal content is invalid")
    if not isinstance(citations, tuple) or not citations or len(citations) > 100:
        raise ValueError("knowledge proposal citations are invalid")
    if len({(item.concept_id, item.char_start, item.char_end) for item in citations}) != len(citations):
        raise ValueError("knowledge proposal citation is duplicated")


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


__all__ = [
    "KnowledgeProposal",
    "ProposalCitation",
    "install_knowledge_proposal_schema",
    "store_knowledge_proposal",
]
