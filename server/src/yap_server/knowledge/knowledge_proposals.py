from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import threading
import time
from typing import TYPE_CHECKING

from psycopg import Connection
from psycopg.errors import QueryCanceled
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey
from yap_server.private_postgres_connection import PrivatePostgresConnectionFactory

from .cancellable_database_operation import run_cancellable_database_operation
from .knowledge_tool_audit import record_knowledge_tool_audit
from .postgres_permission_view import _authorize_knowledge_query
from .knowledge_tool_contract import (
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
    MAX_PROPOSAL_CHARACTERS,
    MAX_PROPOSAL_CITATIONS,
    ProposalCitation,
    validate_bounded_text,
)

if TYPE_CHECKING:
    from yap_server.agents.coordinator import (
        CoordinatorEvidencePack,
        CoordinatorRequest,
    )


_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LEXICAL_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLASSIFICATION_ORDER = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}
MAX_UNRESOLVED_PROPOSALS_PER_SUBJECT = 64


class KnowledgeProposalCapacityExceeded(RuntimeError):
    pass


class CoordinatorEvidenceChanged(ValueError):
    """The Coordinator's source proposals changed before terminal publication."""


class PostgresCoordinatorEvidenceReader:
    """Read a bounded, current, owner-scoped set of reviewed Curator proposals."""

    def __init__(self, connection_factory: PrivatePostgresConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def read(
        self,
        request: CoordinatorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CoordinatorEvidencePack:
        from yap_server.agents.coordinator import CoordinatorRequest

        if (
            not isinstance(request, CoordinatorRequest)
            or not isinstance(principal, AuthenticatedPrincipal)
            or not isinstance(cancellation, threading.Event)
        ):
            raise TypeError("coordinator evidence read is invalid")
        started = time.monotonic()
        with self._connection_factory() as connection:
            try:
                with connection.transaction():
                    evidence = run_cancellable_database_operation(
                        connection,
                        cancellation,
                        lambda: read_coordinator_evidence_in_transaction(
                            connection,
                            request,
                            principal=principal,
                        ),
                    )
                    record_knowledge_tool_audit(
                        connection,
                        principal=principal.key,
                        agent_id="coordinator",
                        operation="open-proposal-evidence",
                        outcome="succeeded",
                        result_count=len(evidence.candidates),
                        generation_sha256=evidence.generation_sha256,
                        permission_hash=evidence.permission_hash,
                        authorization_hash=evidence.authorization_hash,
                        duration_milliseconds=_duration(started),
                    )
                return evidence
            except KnowledgeToolCancelled:
                _record_coordinator_evidence_failure(
                    self._connection_factory,
                    principal,
                    "cancelled",
                    started,
                )
                raise
            except KnowledgeToolCancellationFailed:
                _record_coordinator_evidence_failure(
                    self._connection_factory,
                    principal,
                    "failed",
                    started,
                )
                raise
            except QueryCanceled as error:
                if cancellation.is_set():
                    _record_coordinator_evidence_failure(
                        self._connection_factory,
                        principal,
                        "cancelled",
                        started,
                    )
                    raise KnowledgeToolCancelled(
                        "coordinator evidence read was cancelled"
                    ) from error
                _record_coordinator_evidence_failure(
                    self._connection_factory,
                    principal,
                    "timed_out",
                    started,
                )
                raise KnowledgeToolTimedOut(
                    "coordinator evidence read timed out"
                ) from error
            except Exception:
                _record_coordinator_evidence_failure(
                    self._connection_factory,
                    principal,
                    "failed",
                    started,
                )
                raise

    def verify(
        self,
        request: CoordinatorRequest,
        evidence: CoordinatorEvidencePack,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> None:
        current = self.read(
            request,
            principal=principal,
            cancellation=cancellation,
        )
        if current != evidence:
            raise CoordinatorEvidenceChanged(
                "coordinator evidence changed before result publication"
            )


@dataclass(frozen=True, slots=True)
class KnowledgeProposal:
    tenant_id: str
    proposal_id: str
    generation_sha256: str
    proposal_type: str
    proposed_content: str
    source_citations: tuple[ProposalCitation, ...]
    inherited_permission_sha256: str
    permission_hash: str
    authorization_hash: str
    status: str


@dataclass(frozen=True, slots=True)
class KnowledgeProposalDisposition:
    tenant_id: str
    proposal_id: str
    generation_sha256: str
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
                status text NOT NULL
                    CHECK (status IN ('proposed', 'discarded')),
                discarded_at timestamptz,
                CHECK (
                    (status = 'proposed' AND discarded_at IS NULL)
                    OR (status = 'discarded' AND discarded_at IS NOT NULL)
                ),
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                PRIMARY KEY (tenant_id, proposal_id),
                FOREIGN KEY (tenant_id, generation_sha256)
                    REFERENCES yap_knowledge_builds ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS yap_knowledge_proposals_unresolved_owner
               ON yap_knowledge_proposals (tenant_id, proposer_subject_id)
               WHERE status = 'proposed'"""
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

    with connection.transaction():
        return store_knowledge_proposal_in_transaction(
            connection,
            principal=principal,
            purpose=purpose,
            agent_id=agent_id,
            agent_capabilities=agent_capabilities,
            proposal_type=proposal_type,
            proposed_content=proposed_content,
            source_citations=source_citations,
            expected_generation_sha256=expected_generation_sha256,
        )


def store_knowledge_proposal_in_transaction(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_id: str,
    agent_capabilities: frozenset[str],
    proposal_type: str,
    proposed_content: str,
    source_citations: tuple[ProposalCitation, ...],
    expected_generation_sha256: str | None,
) -> KnowledgeProposal:
    """Store one proposal inside a transaction owned by the calling workflow."""

    if connection.info.transaction_status == TransactionStatus.IDLE:
        raise RuntimeError("knowledge proposal requires an owned transaction")
    _proposal_input(agent_id, proposal_type, proposed_content, source_citations)
    authorized = _authorize_knowledge_query(
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
        "sourceCitations": [item.model_dump(mode="json") for item in source_citations],
        "inheritedPermissionSha256": inherited_hash,
    }
    proposal_id = _sha256(canonical)
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))",
        (
            json.dumps(
                [principal.tenant_id, principal.subject_id],
                separators=(",", ":"),
            ),
        ),
    )
    stored = connection.execute(
        """SELECT generation_sha256, proposer_subject_id,
                  proposer_agent_id, proposal_type, proposed_content,
                  source_citations, inherited_permission_sha256, status
           FROM yap_knowledge_proposals
           WHERE tenant_id = %s AND proposal_id = %s""",
        (principal.tenant_id, proposal_id),
    ).fetchone()
    expected_row = (
        authorized.generation_sha256,
        principal.subject_id,
        agent_id,
        proposal_type,
        proposed_content,
        canonical["sourceCitations"],
        inherited_hash,
        "proposed",
    )
    if stored is not None:
        if tuple(stored) != expected_row:
            raise ValueError("knowledge proposal conflicts with stored truth")
        return KnowledgeProposal(
            principal.tenant_id,
            proposal_id,
            authorized.generation_sha256,
            proposal_type,
            proposed_content,
            source_citations,
            inherited_hash,
            authorized.permission_hash,
            authorized.authorization_hash,
            "proposed",
        )
    unresolved = connection.execute(
        """SELECT count(*)
           FROM yap_knowledge_proposals
           WHERE tenant_id = %s AND proposer_subject_id = %s
             AND status = 'proposed'""",
        (principal.tenant_id, principal.subject_id),
    ).fetchone()
    if (
        unresolved is None
        or isinstance(unresolved[0], bool)
        or not isinstance(unresolved[0], int)
    ):
        raise RuntimeError("knowledge proposal capacity was not observed")
    if unresolved[0] >= MAX_UNRESOLVED_PROPOSALS_PER_SUBJECT:
        raise KnowledgeProposalCapacityExceeded(
            "knowledge proposal capacity is temporarily unavailable"
        )
    row = connection.execute(
        """INSERT INTO yap_knowledge_proposals (
               tenant_id, proposal_id, generation_sha256,
               proposer_subject_id, proposer_agent_id, proposal_type,
               proposed_content, source_citations, inherited_policy,
               inherited_permission_sha256, status
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'proposed')
           ON CONFLICT (tenant_id, proposal_id) DO NOTHING
           RETURNING generation_sha256, proposer_subject_id,
                     proposer_agent_id, proposal_type, proposed_content,
                     source_citations, inherited_permission_sha256, status""",
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
    ).fetchone()
    if row is None:
        row = connection.execute(
            """SELECT generation_sha256, proposer_subject_id,
                      proposer_agent_id, proposal_type, proposed_content,
                      source_citations, inherited_permission_sha256, status
               FROM yap_knowledge_proposals
               WHERE tenant_id = %s AND proposal_id = %s""",
            (principal.tenant_id, proposal_id),
        ).fetchone()
    if row is None or tuple(row) != expected_row:
        raise ValueError("knowledge proposal conflicts with stored truth")
    return KnowledgeProposal(
        principal.tenant_id,
        proposal_id,
        authorized.generation_sha256,
        proposal_type,
        proposed_content,
        source_citations,
        inherited_hash,
        authorized.permission_hash,
        authorized.authorization_hash,
        "proposed",
    )


def discard_knowledge_proposal(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    proposal_id: str,
) -> KnowledgeProposalDisposition:
    """Release one caller-owned proposal without granting canonical mutation."""

    if not _IDENTITY.fullmatch(proposal_id):
        raise ValueError("knowledge proposal identity is invalid")
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (principal.tenant_id,),
        )
        row = connection.execute(
            """UPDATE yap_knowledge_proposals
               SET status = 'discarded', discarded_at = transaction_timestamp()
               WHERE tenant_id = %s AND proposal_id = %s
                 AND proposer_subject_id = %s AND status = 'proposed'
               RETURNING tenant_id, proposal_id, generation_sha256, status""",
            (principal.tenant_id, proposal_id, principal.subject_id),
        ).fetchone()
        if row is None:
            row = connection.execute(
                """SELECT tenant_id, proposal_id, generation_sha256, status
                   FROM yap_knowledge_proposals
                   WHERE tenant_id = %s AND proposal_id = %s
                     AND proposer_subject_id = %s""",
                (principal.tenant_id, proposal_id, principal.subject_id),
            ).fetchone()
        if row is None:
            raise LookupError("knowledge proposal does not exist")
        disposition = KnowledgeProposalDisposition(*row)
        if disposition.status != "discarded":
            raise ValueError("knowledge proposal disposition is invalid")
    return disposition


def read_coordinator_evidence_in_transaction(
    connection: Connection[object],
    request: CoordinatorRequest,
    *,
    principal: AuthenticatedPrincipal,
) -> CoordinatorEvidencePack:
    """Rebind Coordinator input to current authorization and Curator success."""

    from yap_server.agents.coordinator import (
        COORDINATOR_MAXIMUM_CANDIDATES,
        CoordinatorEvidencePack,
        CoordinatorProposalCandidate,
        CoordinatorRequest,
    )
    from yap_server.agents.librarian import LibrarianEvidenceItem

    if connection.info.transaction_status == TransactionStatus.IDLE:
        raise RuntimeError("coordinator evidence requires an owned transaction")
    if not isinstance(request, CoordinatorRequest):
        raise TypeError("coordinator request type is invalid")
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("coordinator principal type is invalid")
    authorized = _authorize_knowledge_query(
        connection,
        principal=principal.key,
        purpose="knowledge.read",
        agent_capabilities=frozenset({"knowledge.read"}),
        required_capability="knowledge.read",
        expected_generation_sha256=request.expected_generation_sha256,
    )
    rows = connection.execute(
        """SELECT p.proposal_id, p.generation_sha256, p.proposal_type,
                  p.proposed_content, p.source_citations, p.inherited_policy,
                  p.inherited_permission_sha256, a.request_id, a.submission_id,
                  a.request_sha256, a.work_sha256, a.evidence_sha256,
                  a.permission_hash, a.authorization_hash,
                  a.proposal_permission_hash, a.proposal_authorization_hash,
                  a.provider_generation, a.candidate_id, a.model,
                  a.model_revision, a.runtime_id, a.profile_sha256,
                  a.candidate_lock_sha256
           FROM yap_knowledge_proposals p
           JOIN LATERAL (
               SELECT request_id, submission_id, request_sha256, work_sha256,
                      evidence_sha256, permission_hash, authorization_hash,
                      proposal_permission_hash, proposal_authorization_hash,
                      provider_generation, candidate_id, model, model_revision,
                      runtime_id, profile_sha256, candidate_lock_sha256
               FROM yap_curator_result_audit a
               WHERE a.tenant_id = p.tenant_id
                 AND a.subject_id = p.proposer_subject_id
                 AND a.proposal_id = p.proposal_id
                 AND a.generation_sha256 = p.generation_sha256
                 AND a.outcome = 'succeeded' AND a.reason IS NULL
                 AND a.result_count = 1
               ORDER BY a.audit_id DESC
               LIMIT 1
           ) a ON TRUE
           WHERE p.tenant_id = %s AND p.proposer_subject_id = %s
             AND p.proposer_agent_id = 'curator' AND p.status = 'proposed'
             AND p.generation_sha256 = %s
           ORDER BY p.proposal_id
           LIMIT %s""",
        (
            principal.tenant_id,
            principal.subject_id,
            authorized.generation_sha256,
            MAX_UNRESOLVED_PROPOSALS_PER_SUBJECT + 1,
        ),
    ).fetchall()
    if len(rows) > MAX_UNRESOLVED_PROPOSALS_PER_SUBJECT:
        raise ValueError("coordinator proposal capacity invariant differs")
    selected = rows
    parsed: list[tuple[tuple[ProposalCitation, ...], object]] = []
    concept_ids: set[str] = set()
    for row in selected:
        citations = _stored_proposal_citations(row[4])
        parsed.append((citations, row))
        concept_ids.update(item.concept_id for item in citations)
    concept_rows = ()
    if concept_ids:
        concept_rows = connection.execute(
            """SELECT c.concept_id, b.source_revision, c.content_sha256,
                      c.body, p.policy
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
            (
                principal.tenant_id,
                authorized.generation_sha256,
                sorted(concept_ids),
            ),
        ).fetchall()
    by_concept = {str(row[0]): row for row in concept_rows}
    current_propose_authorization = _authorization_hash(
        authorized.permission_hash,
        "knowledge.propose",
    )
    candidates = []
    for citations, raw_row in parsed:
        row = tuple(raw_row)  # type: ignore[arg-type]
        if (
            not {citation.concept_id for citation in citations}
            <= authorized.visible_concept_ids
        ):
            # A caller must not be able to distinguish a hidden proposal from an
            # absent one.  Omit the whole candidate before validating or ranking
            # any of its source material.
            continue
        items = []
        policies: list[dict[str, object]] = []
        for citation in citations:
            concept = by_concept.get(citation.concept_id)
            if concept is None:
                raise ValueError("coordinator proposal citation does not exist")
            body = str(concept[3])
            if (
                citation.source_revision != concept[1]
                or citation.content_sha256 != concept[2]
                or citation.char_start < 0
                or citation.char_end <= citation.char_start
                or citation.char_end > len(body)
                or not isinstance(concept[4], dict)
            ):
                raise ValueError("coordinator proposal citation is stale or invalid")
            policies.append(dict(concept[4]))
            items.append(
                LibrarianEvidenceItem(
                    concept_id=citation.concept_id,
                    source_revision=citation.source_revision,
                    content_sha256=citation.content_sha256,
                    char_start=citation.char_start,
                    char_end=citation.char_end,
                    text=body[citation.char_start : citation.char_end],
                )
            )
        inherited_policy = row[5]
        if (
            not isinstance(inherited_policy, dict)
            or _strictest_policy(tuple(policies)) != inherited_policy
            or _sha256(inherited_policy) != row[6]
        ):
            raise ValueError("coordinator proposal permission inheritance differs")
        citation_wire = [item.model_dump(mode="json") for item in citations]
        proposal_identity = {
            "tenantId": principal.tenant_id,
            "generationSha256": authorized.generation_sha256,
            "proposerSubjectId": principal.subject_id,
            "proposerAgentId": "curator",
            "proposalType": row[2],
            "proposedContent": row[3],
            "sourceCitations": citation_wire,
            "inheritedPermissionSha256": row[6],
        }
        if (
            row[1] != authorized.generation_sha256
            or row[4] != citation_wire
            or row[0] != _sha256(proposal_identity)
            or row[2] not in {"summary", "relationship"}
            or not isinstance(row[3], str)
            or not _valid_curator_lineage(
                row[7:],
                permission_hash=authorized.permission_hash,
                authorization_hash=authorized.authorization_hash,
                proposal_authorization_hash=current_propose_authorization,
            )
        ):
            raise ValueError("coordinator Curator proposal lineage differs")
        candidates.append(
            CoordinatorProposalCandidate.create(
                proposal_id=str(row[0]),
                curator_request_id=str(row[7]),
                curator_submission_id=str(row[8]),
                curator_request_sha256=str(row[9]),
                curator_work_sha256=str(row[10]),
                curator_evidence_sha256=str(row[11]),
                generation_sha256=authorized.generation_sha256,
                proposal_type=str(row[2]),
                proposed_content=row[3],
                inherited_permission_sha256=str(row[6]),
                proposal_permission_hash=str(row[14]),
                proposal_authorization_hash=str(row[15]),
                citations=tuple(items),
            )
        )
    objective_tokens = _lexical_tokens(request.objective)
    ranked = sorted(
        candidates,
        key=lambda item: (
            -len(
                objective_tokens
                & _lexical_tokens(
                    " ".join(
                        [item.proposed_content]
                        + [citation.text for citation in item.citations]
                    )
                )
            ),
            item.proposal_id,
        ),
    )[:COORDINATOR_MAXIMUM_CANDIDATES]
    accepted = []
    for candidate in ranked:
        try:
            CoordinatorEvidencePack.create(
                generation_sha256=authorized.generation_sha256,
                permission_hash=authorized.permission_hash,
                authorization_hash=authorized.authorization_hash,
                candidates=tuple([*accepted, candidate]),
                output_budget_exhausted=False,
            )
        except ValueError:
            return CoordinatorEvidencePack.create(
                generation_sha256=authorized.generation_sha256,
                permission_hash=authorized.permission_hash,
                authorization_hash=authorized.authorization_hash,
                candidates=tuple(accepted),
                output_budget_exhausted=True,
            )
        accepted.append(candidate)
    return CoordinatorEvidencePack.create(
        generation_sha256=authorized.generation_sha256,
        permission_hash=authorized.permission_hash,
        authorization_hash=authorized.authorization_hash,
        candidates=tuple(accepted),
        output_budget_exhausted=False,
    )


def _lexical_tokens(value: str) -> frozenset[str]:
    return frozenset(token.casefold() for token in _LEXICAL_TOKEN.findall(value))


def _record_coordinator_evidence_failure(
    connection_factory: PrivatePostgresConnectionFactory,
    principal: AuthenticatedPrincipal,
    outcome: str,
    started: float,
) -> None:
    with connection_factory() as connection:
        with connection.transaction():
            record_knowledge_tool_audit(
                connection,
                principal=principal.key,
                agent_id="coordinator",
                operation="open-proposal-evidence",
                outcome=outcome,
                result_count=0,
                generation_sha256=None,
                permission_hash=None,
                authorization_hash=None,
                duration_milliseconds=_duration(started),
            )


def _stored_proposal_citations(value: object) -> tuple[ProposalCitation, ...]:
    if not isinstance(value, list) or not value or len(value) > MAX_PROPOSAL_CITATIONS:
        raise ValueError("coordinator proposal citations are invalid")
    try:
        citations = tuple(
            ProposalCitation.model_validate(item, strict=True) for item in value
        )
    except ValueError as error:
        raise ValueError("coordinator proposal citations are invalid") from error
    identities = {
        (
            item.concept_id,
            item.source_revision,
            item.content_sha256,
            item.char_start,
            item.char_end,
        )
        for item in citations
    }
    if len(identities) != len(citations):
        raise ValueError("coordinator proposal citation is duplicated")
    return citations


def _authorization_hash(permission_hash: str, required_capability: str) -> str:
    return _sha256(
        {
            "permissionHash": permission_hash,
            "requiredCapability": required_capability,
        }
    )


def _valid_curator_lineage(
    value: tuple[object, ...],
    *,
    permission_hash: str,
    authorization_hash: str,
    proposal_authorization_hash: str,
) -> bool:
    return (
        len(value) == 16
        and isinstance(value[0], str)
        and _IDENTITY.fullmatch(value[0]) is not None
        and isinstance(value[1], str)
        and _IDENTITY.fullmatch(value[1]) is not None
        and all(
            isinstance(item, str) and _SHA256.fullmatch(item) for item in value[2:9]
        )
        and value[5] == permission_hash
        and value[6] == authorization_hash
        and value[7] == permission_hash
        and value[8] == proposal_authorization_hash
        and isinstance(value[9], int)
        and not isinstance(value[9], bool)
        and value[9] > 0
        and _bounded_ascii(value[10], 128)
        and _bounded_ascii(value[11], 512)
        and isinstance(value[12], str)
        and re.fullmatch(r"[0-9a-f]{40}", value[12]) is not None
        and _bounded_ascii(value[13], 128)
        and isinstance(value[14], str)
        and _SHA256.fullmatch(value[14]) is not None
        and isinstance(value[15], str)
        and _SHA256.fullmatch(value[15]) is not None
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
    validate_bounded_text(
        proposed_content,
        field="knowledge proposal content",
        maximum=MAX_PROPOSAL_CHARACTERS,
    )
    if (
        not isinstance(citations, tuple)
        or not citations
        or len(citations) > MAX_PROPOSAL_CITATIONS
    ):
        raise ValueError("knowledge proposal citations are invalid")
    for citation in citations:
        if not isinstance(citation, ProposalCitation):
            raise ValueError("knowledge proposal citation differs from the contract")
        try:
            ProposalCitation.model_validate(citation, strict=True)
        except ValueError as error:
            raise ValueError(
                "knowledge proposal citation differs from the contract"
            ) from error
    if len(
        {(item.concept_id, item.char_start, item.char_end) for item in citations}
    ) != len(citations):
        raise ValueError("knowledge proposal citation is duplicated")


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _bounded_ascii(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value.strip() == value
        and value.isascii()
        and value.isprintable()
    )


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = [
    "CoordinatorEvidenceChanged",
    "KnowledgeProposal",
    "KnowledgeProposalCapacityExceeded",
    "KnowledgeProposalDisposition",
    "MAX_UNRESOLVED_PROPOSALS_PER_SUBJECT",
    "PostgresCoordinatorEvidenceReader",
    "discard_knowledge_proposal",
    "install_knowledge_proposal_schema",
    "read_coordinator_evidence_in_transaction",
    "store_knowledge_proposal",
    "store_knowledge_proposal_in_transaction",
]
