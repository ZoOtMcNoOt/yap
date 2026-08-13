from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import json
import threading
import unittest
from unittest.mock import patch

from psycopg.pq import TransactionStatus

from yap_server.agents.coordinator import CoordinatorRequest
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.knowledge_proposals import (
    CoordinatorEvidenceChanged,
    PostgresCoordinatorEvidenceReader,
    read_coordinator_evidence_in_transaction,
)
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancelled,
    ProposalCitation,
)
from yap_server.knowledge.postgres_permission_view import AuthorizedKnowledgeQuery


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


class _Cursor:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self._rows = rows or []

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _Info:
    transaction_status = TransactionStatus.INTRANS


class _Transaction(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(self, *unused: object) -> None:
        return None


class _Connection(AbstractContextManager["_Connection"]):
    def __init__(
        self,
        proposal_rows: list[tuple[object, ...]],
        concept_rows: list[tuple[object, ...]],
    ) -> None:
        self.info = _Info()
        self.proposal_rows = proposal_rows
        self.concept_rows = concept_rows
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.tool_audits: list[tuple[object, ...]] = []

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *unused: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction()

    def cancel_safe(self, *, timeout: float) -> None:
        del timeout

    def close(self) -> None:
        return None

    def execute(
        self,
        statement: str,
        values: tuple[object, ...] = (),
    ) -> _Cursor:
        normalized = " ".join(statement.split())
        self.executions.append((normalized, values))
        if "FROM yap_knowledge_proposals p" in normalized:
            return _Cursor(self.proposal_rows)
        if "FROM yap_knowledge_concepts c" in normalized:
            return _Cursor(self.concept_rows)
        if normalized.startswith("INSERT INTO yap_knowledge_tool_audit"):
            self.tool_audits.append(values)
            return _Cursor()
        raise AssertionError(f"unexpected SQL: {normalized}")


def _principal(subject_id: str = "owner-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-1",
        subject_id=subject_id,
        client_id="coordinator-tests",
        scopes=frozenset({"knowledge.read"}),
    )


def _request() -> CoordinatorRequest:
    return CoordinatorRequest(
        objective="Coordinate the reviewed release records.",
        maximum_items=3,
        expected_generation_sha256="a" * 64,
    )


def _authorization(permission_hash: str, capability: str) -> str:
    return _sha256(
        {"permissionHash": permission_hash, "requiredCapability": capability}
    )


def _authorized() -> AuthorizedKnowledgeQuery:
    permission_hash = "b" * 64
    return AuthorizedKnowledgeQuery(
        tenant_id="tenant-1",
        subject_id="owner-1",
        purpose="knowledge.read",
        generation_sha256="a" * 64,
        permission_hash=permission_hash,
        authorization_hash=_authorization(permission_hash, "knowledge.read"),
        required_capability="knowledge.read",
        visible_concept_ids=frozenset({"conversations/1"}),
    )


def _fixture(
    index: int = 1,
    *,
    content: str | None = None,
) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    text = "Reviewed source supports the exact proposal."
    citation = ProposalCitation(
        concept_id="conversations/1",
        source_revision="revision-1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        char_start=0,
        char_end=len(text),
    )
    citations = [citation.model_dump(mode="json")]
    policy = {
        "audience": [{"tenantId": "tenant-1", "subjectId": "owner-1"}],
        "denials": [],
        "purposes": ["knowledge.read"],
        "classification": "internal",
        "canonical": False,
    }
    inherited_hash = _sha256(policy)
    canonical = {
        "tenantId": "tenant-1",
        "generationSha256": "a" * 64,
        "proposerSubjectId": "owner-1",
        "proposerAgentId": "curator",
        "proposalType": "summary",
        "proposedContent": content
        or f"Coordinate the reviewed release proposal {index}.",
        "sourceCitations": citations,
        "inheritedPermissionSha256": inherited_hash,
    }
    permission_hash = "b" * 64
    proposal = (
        _sha256(canonical),
        "a" * 64,
        "summary",
        canonical["proposedContent"],
        citations,
        policy,
        inherited_hash,
        f"curator-request-{index}",
        f"curator-submission-{index}",
        "1" * 64,
        "2" * 64,
        "3" * 64,
        permission_hash,
        _authorization(permission_hash, "knowledge.search.lexical"),
        permission_hash,
        _authorization(permission_hash, "knowledge.propose"),
        11,
        "gemma-4-31b-it-nvfp4",
        "nvidia/Gemma-4-31B-IT-NVFP4",
        "4" * 40,
        "gemma-vllm-26.06",
        "5" * 64,
        "6" * 64,
    )
    concept = (
        citation.concept_id,
        citation.source_revision,
        citation.content_sha256,
        text,
        policy,
    )
    return [proposal], [concept]


class CoordinatorKnowledgeProposalTests(unittest.TestCase):
    def test_reader_rebinds_owner_current_generation_citations_and_lineage(
        self,
    ) -> None:
        proposals, concepts = _fixture()
        connection = _Connection(proposals, concepts)
        with patch(
            "yap_server.knowledge.knowledge_proposals._authorize_knowledge_query",
            return_value=_authorized(),
        ) as authorize:
            evidence = read_coordinator_evidence_in_transaction(
                connection,  # type: ignore[arg-type]
                _request(),
                principal=_principal(),
            )

        self.assertEqual(len(evidence.candidates), 1)
        candidate = evidence.candidates[0]
        self.assertEqual(candidate.curator_request_id, "curator-request-1")
        self.assertEqual(candidate.curator_submission_id, "curator-submission-1")
        self.assertEqual(candidate.citations[0].text, concepts[0][3])
        self.assertNotEqual(
            proposals[0][13],
            evidence.authorization_hash,
        )
        self.assertFalse(evidence.output_budget_exhausted)
        authorize.assert_called_once_with(
            connection,
            principal=_principal().key,
            purpose="knowledge.read",
            agent_capabilities=frozenset({"knowledge.read"}),
            required_capability="knowledge.read",
            expected_generation_sha256="a" * 64,
        )
        proposal_query = connection.executions[0]
        self.assertIn("p.proposer_subject_id = %s", proposal_query[0])
        self.assertIn("p.proposer_agent_id = 'curator'", proposal_query[0])
        self.assertIn("p.status = 'proposed'", proposal_query[0])
        self.assertEqual(proposal_query[1][0:3], ("tenant-1", "owner-1", "a" * 64))

    def test_reader_fails_closed_on_forged_proposal_or_curator_lineage(self) -> None:
        proposals, concepts = _fixture()
        for index, replacement in (
            (0, "f" * 64),
            (12, "f" * 64),
            (15, "f" * 64),
            (20, ""),
        ):
            changed = list(proposals[0])
            changed[index] = replacement
            connection = _Connection([tuple(changed)], concepts)
            with (
                self.subTest(index=index),
                patch(
                    "yap_server.knowledge.knowledge_proposals._authorize_knowledge_query",
                    return_value=_authorized(),
                ),
                self.assertRaisesRegex(ValueError, "lineage differs"),
            ):
                read_coordinator_evidence_in_transaction(
                    connection,  # type: ignore[arg-type]
                    _request(),
                    principal=_principal(),
                )

    def test_empty_and_many_results_are_bounded_after_deterministic_ranking(
        self,
    ) -> None:
        proposals, concepts = _fixture()
        all_proposals = [_fixture(index)[0][0] for index in range(1, 10)]
        with patch(
            "yap_server.knowledge.knowledge_proposals._authorize_knowledge_query",
            return_value=_authorized(),
        ):
            empty = read_coordinator_evidence_in_transaction(
                _Connection([], []),  # type: ignore[arg-type]
                _request(),
                principal=_principal(),
            )
            bounded = read_coordinator_evidence_in_transaction(
                _Connection(all_proposals, concepts),  # type: ignore[arg-type]
                _request(),
                principal=_principal(),
            )
        self.assertEqual(empty.candidates, ())
        self.assertFalse(empty.output_budget_exhausted)
        self.assertEqual(len(bounded.candidates), 8)
        self.assertFalse(bounded.output_budget_exhausted)
        self.assertEqual(
            [candidate.proposal_id for candidate in bounded.candidates],
            sorted(candidate.proposal_id for candidate in bounded.candidates),
        )

    def test_hidden_only_proposal_has_the_same_empty_shape_as_absence(self) -> None:
        proposals, concepts = _fixture()
        hidden = _authorized()
        hidden = AuthorizedKnowledgeQuery(
            tenant_id=hidden.tenant_id,
            subject_id=hidden.subject_id,
            purpose=hidden.purpose,
            generation_sha256=hidden.generation_sha256,
            permission_hash=hidden.permission_hash,
            authorization_hash=hidden.authorization_hash,
            required_capability=hidden.required_capability,
            visible_concept_ids=frozenset(),
        )
        with patch(
            "yap_server.knowledge.knowledge_proposals._authorize_knowledge_query",
            return_value=hidden,
        ):
            hidden_connection = _Connection(proposals, concepts)
            hidden_only = read_coordinator_evidence_in_transaction(
                hidden_connection,  # type: ignore[arg-type]
                _request(),
                principal=_principal(),
            )
            absent = read_coordinator_evidence_in_transaction(
                _Connection([], []),  # type: ignore[arg-type]
                _request(),
                principal=_principal(),
            )

        self.assertEqual(hidden_only.to_wire(), absent.to_wire())
        self.assertFalse(
            any(
                "FROM yap_knowledge_concepts c" in statement
                for statement, _values in hidden_connection.executions
            )
        )

    def test_reader_ranks_all_owner_proposals_before_applying_the_eight_item_cap(
        self,
    ) -> None:
        irrelevant = [
            _fixture(index, content=f"Routine unrelated record {index}.")[0][0]
            for index in range(1, 9)
        ]
        relevant = _fixture(9, content="Urgent zebra release decision.")[0][0]
        request = CoordinatorRequest(
            objective="Coordinate the urgent zebra decision.",
            maximum_items=1,
            expected_generation_sha256="a" * 64,
        )
        with patch(
            "yap_server.knowledge.knowledge_proposals._authorize_knowledge_query",
            return_value=_authorized(),
        ):
            evidence = read_coordinator_evidence_in_transaction(
                _Connection([*irrelevant, relevant], _fixture()[1]),  # type: ignore[arg-type]
                request,
                principal=_principal(),
            )

        self.assertEqual(len(evidence.candidates), 8)
        self.assertEqual(
            evidence.candidates[0].proposed_content,
            "Urgent zebra release decision.",
        )

    def test_reader_cancellation_and_typed_reauthorization_drift(self) -> None:
        proposals, concepts = _fixture()
        connection = _Connection(proposals, concepts)
        reader = PostgresCoordinatorEvidenceReader(connection.__enter__)
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(KnowledgeToolCancelled):
            reader.read(_request(), principal=_principal(), cancellation=cancelled)

        with patch(
            "yap_server.knowledge.knowledge_proposals._authorize_knowledge_query",
            return_value=_authorized(),
        ):
            evidence = reader.read(
                _request(), principal=_principal(), cancellation=threading.Event()
            )
        self.assertEqual(len(connection.tool_audits), 2)
        self.assertEqual(
            connection.tool_audits[0][2:6],
            ("coordinator", "open-proposal-evidence", "cancelled", 0),
        )
        self.assertEqual(
            connection.tool_audits[1][2:6],
            ("coordinator", "open-proposal-evidence", "succeeded", 1),
        )
        connection.proposal_rows = []
        with (
            patch(
                "yap_server.knowledge.knowledge_proposals._authorize_knowledge_query",
                return_value=_authorized(),
            ),
            self.assertRaises(CoordinatorEvidenceChanged),
        ):
            reader.verify(
                _request(),
                evidence,
                principal=_principal(),
                cancellation=threading.Event(),
            )


if __name__ == "__main__":
    unittest.main()
