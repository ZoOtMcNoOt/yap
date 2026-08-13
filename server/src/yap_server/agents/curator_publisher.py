from __future__ import annotations

import threading
import time

from psycopg.errors import QueryCanceled

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.cancellable_database_operation import (
    run_cancellable_database_operation,
)
from yap_server.knowledge.knowledge_proposals import (
    KnowledgeProposal,
    store_knowledge_proposal_in_transaction,
)
from yap_server.knowledge.knowledge_tool_audit import record_knowledge_tool_audit
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
)
from yap_server.private_postgres_connection import PrivatePostgresConnectionFactory

from .curator import (
    CuratorEvidence,
    CuratorRequest,
    read_curator_evidence_in_transaction,
)
from .curator_result_audit import PostgresCuratorResultAuditor


class PostgresCuratorPublisher:
    """Atomically publish one noncanonical proposal and its success evidence."""

    def __init__(
        self,
        connection_factory: PrivatePostgresConnectionFactory,
        result_auditor: PostgresCuratorResultAuditor,
    ) -> None:
        if result_auditor.connection_factory is not connection_factory:
            raise ValueError("curator publisher connection authority differs")
        self._connection_factory = connection_factory
        self._result_auditor = result_auditor

    def publish(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request: CuratorRequest,
        evidence: CuratorEvidence,
        provider_generation: int,
        started: float,
        deadline: float,
        cancellation: threading.Event,
    ) -> KnowledgeProposal:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("curator principal type is invalid")
        if (
            isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or deadline <= started
        ):
            raise KnowledgeToolTimedOut("curator publication deadline elapsed")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("curator publication cancellation type is invalid")
        with self._connection_factory() as connection:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise KnowledgeToolTimedOut(
                    "curator publication deadline elapsed"
                )
            operation_cancellation = threading.Event()
            if cancellation.is_set():
                operation_cancellation.set()
            forwarding_stopped = threading.Event()
            forwarder = threading.Thread(
                target=_forward_cancellation,
                args=(cancellation, operation_cancellation, forwarding_stopped),
                name="curator-publication-cancellation",
                daemon=False,
            )
            deadline_timer = threading.Timer(
                remaining,
                operation_cancellation.set,
            )
            deadline_timer.name = "curator-publication-deadline"
            deadline_timer.daemon = False
            forwarder.start()
            deadline_timer.start()
            try:
                try:
                    return run_cancellable_database_operation(
                        connection,
                        operation_cancellation,
                        lambda: self._publish_in_transaction(
                            connection=connection,
                            principal=principal,
                            request_id=request_id,
                            request=request,
                            evidence=evidence,
                            provider_generation=provider_generation,
                            started=started,
                        ),
                    )
                except (KnowledgeToolCancelled, QueryCanceled) as error:
                    if time.monotonic() >= deadline and not cancellation.is_set():
                        raise KnowledgeToolTimedOut(
                            "curator publication deadline elapsed"
                        ) from error
                    if operation_cancellation.is_set():
                        raise KnowledgeToolCancelled(
                            "curator publication was cancelled"
                        ) from error
                    raise
            finally:
                forwarding_stopped.set()
                forwarder.join()
                deadline_timer.cancel()
                deadline_timer.join()

    def _publish_in_transaction(
        self,
        *,
        connection,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request: CuratorRequest,
        evidence: CuratorEvidence,
        provider_generation: int,
        started: float,
    ) -> KnowledgeProposal:
        with connection.transaction():
            current = read_curator_evidence_in_transaction(
                connection,
                request,
                principal=principal,
            )
            if current != evidence:
                raise ValueError("curator evidence changed before publication")
            proposal = store_knowledge_proposal_in_transaction(
                connection,
                principal=principal.key,
                purpose="knowledge.read",
                agent_id="curator",
                agent_capabilities=frozenset({"knowledge.propose"}),
                proposal_type="summary",
                proposed_content=request.reviewed_content,
                source_citations=request.source_citations,
                expected_generation_sha256=request.expected_generation_sha256,
            )
            duration = max(0, round((time.monotonic() - started) * 1_000))
            record_knowledge_tool_audit(
                connection,
                principal=principal.key,
                agent_id="curator",
                operation="propose",
                outcome="succeeded",
                result_count=1,
                generation_sha256=proposal.generation_sha256,
                permission_hash=proposal.permission_hash,
                authorization_hash=proposal.authorization_hash,
                duration_milliseconds=duration,
            )
            self._result_auditor.record_in_transaction(
                connection,
                principal=principal,
                request_id=request_id,
                request=request,
                provider_generation=provider_generation,
                status="proposed",
                reason=None,
                evidence=current,
                proposal_id=proposal.proposal_id,
                proposal_permission_hash=proposal.permission_hash,
                proposal_authorization_hash=proposal.authorization_hash,
                duration_milliseconds=duration,
            )
        return proposal


def _forward_cancellation(
    source: threading.Event,
    target: threading.Event,
    stopped: threading.Event,
) -> None:
    while not stopped.wait(0.01):
        if source.is_set():
            target.set()
            return


__all__ = ["PostgresCuratorPublisher"]
