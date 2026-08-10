from __future__ import annotations

import threading
import time

from psycopg import Connection
from psycopg.errors import QueryCanceled

from yap_server.auth.principal import PrincipalKey

from .cancellable_database_operation import run_cancellable_database_operation
from .knowledge_agent_authority import KnowledgeAgentAuthority
from .knowledge_proposals import KnowledgeProposal, store_knowledge_proposal
from .knowledge_tool_audit import record_knowledge_tool_audit
from .knowledge_tool_contract import (
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
    ProposalCitation,
)


class GovernedKnowledgeProposals:
    """Admit model-authored content only as cited, noncanonical proposals."""

    def __init__(self, authority: KnowledgeAgentAuthority) -> None:
        self._authority = authority

    def propose(
        self,
        connection: Connection[object],
        *,
        principal: PrincipalKey,
        agent_id: str,
        purpose: str,
        proposal_type: str,
        proposed_content: str,
        source_citations: tuple[ProposalCitation, ...],
        expected_generation_sha256: str | None,
        cancellation: threading.Event,
    ) -> KnowledgeProposal:
        started = time.monotonic()
        try:
            profile = self._authority.authorize(agent_id=agent_id, purpose=purpose)
            if cancellation.is_set():
                raise KnowledgeToolCancelled("knowledge proposal was cancelled")
            with connection.transaction():
                connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(profile.statement_timeout_milliseconds),),
                )
                proposal = run_cancellable_database_operation(
                    connection,
                    cancellation,
                    lambda: store_knowledge_proposal(
                        connection,
                        principal=principal,
                        purpose=purpose,
                        agent_id=agent_id,
                        agent_capabilities=profile.capabilities,
                        proposal_type=proposal_type,
                        proposed_content=proposed_content,
                        source_citations=source_citations,
                        expected_generation_sha256=expected_generation_sha256,
                    ),
                )
                record_knowledge_tool_audit(
                    connection,
                    principal=principal,
                    agent_id=agent_id,
                    operation="propose",
                    outcome="succeeded",
                    result_count=1,
                    generation_sha256=proposal.generation_sha256,
                    permission_hash=proposal.permission_hash,
                    authorization_hash=proposal.authorization_hash,
                    duration_milliseconds=_duration(started),
                )
            return proposal
        except QueryCanceled as error:
            outcome = "cancelled" if cancellation.is_set() else "timed_out"
            _record_failure(connection, principal, agent_id, outcome, started)
            if cancellation.is_set():
                raise KnowledgeToolCancelled("knowledge proposal was cancelled") from error
            raise KnowledgeToolTimedOut("knowledge proposal timed out") from error
        except KnowledgeToolCancelled:
            _record_failure(connection, principal, agent_id, "cancelled", started)
            raise
        except PermissionError:
            _record_failure(connection, principal, agent_id, "denied", started)
            raise
        except Exception:
            _record_failure(connection, principal, agent_id, "failed", started)
            raise


def _record_failure(
    connection: Connection[object],
    principal: PrincipalKey,
    agent_id: str,
    outcome: str,
    started: float,
) -> None:
    with connection.transaction():
        record_knowledge_tool_audit(
            connection,
            principal=principal,
            agent_id=agent_id,
            operation="propose",
            outcome=outcome,
            result_count=0,
            generation_sha256=None,
            permission_hash=None,
            authorization_hash=None,
            duration_milliseconds=_duration(started),
        )


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = ["GovernedKnowledgeProposals"]
