import json
import os
import threading
from dataclasses import replace
from uuid import uuid4

import psycopg

from yap_server.agents.curator import CuratorRequest, PostgresCuratorEvidenceReader
from yap_server.agents.curator_model import CuratorProposalModel
from yap_server.agents.curator_publisher import PostgresCuratorPublisher
from yap_server.agents.curator_result_audit import (
    PostgresCuratorResultAuditor,
    install_curator_result_audit_schema,
)
from yap_server.agents.curator_service import CuratorService
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.generation_ledger import install_knowledge_schema
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)
from yap_server.knowledge.knowledge_tool_contract import ProposalCitation
from tests.agents.test_curator import _Admission, _Transport, _tool_response
from tests.agents.test_curator_postgres import _cleanup, _runtime_identity
from tests.knowledge.knowledge_connections_fixtures import activate_connection_fixture

DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


def connect():
    return psycopg.connect(DSN)


class CuratorConnectionFixture:
    def prepare_connection_review(self):
        self.tenant = f"curator-connection-{uuid4().hex}"
        self.principal = AuthenticatedPrincipal(
            self.tenant, "alice", "desktop", frozenset({"access_as_user"})
        )
        with connect() as connection:
            install_knowledge_schema(connection)
            install_knowledge_tool_audit_schema(connection)
            install_curator_result_audit_schema(connection)
            self.generation = activate_connection_fixture(connection, self.tenant)
        self.addCleanup(self.clean_connection_review)
        self.candidate = {
            "schema_version": 1,
            "source_concept_id": "projects/voiceos",
            "target_concept_id": "decisions/public",
            "relationship_type": "references",
            "rationale": "The reviewed project references the public decision.",
        }
        self.request = CuratorRequest(
            submission_id=f"connection-{uuid4().hex}",
            trigger="reviewed-connection",
            expected_generation_sha256=self.generation.generation_sha256,
            reviewed_content=json.dumps(self.candidate),
            source_citations=tuple(
                self.citation(item) for item in ("projects/voiceos", "decisions/public")
            ),
        )
        self.reader = PostgresCuratorEvidenceReader(connect)
        self.auditor = PostgresCuratorResultAuditor(connect, _runtime_identity())
        self.publisher = PostgresCuratorPublisher(connect, self.auditor)
        self.transport = _Transport(_tool_response())
        self.core = CuratorService(
            admission=_Admission(),
            evidence_reader=self.reader,
            reviewer=CuratorProposalModel(
                transport=self.transport,
                model="deterministic-review-fixture",
                maximum_output_tokens=128,
            ),
            publisher=self.publisher,
            result_auditor=self.auditor,
        )

    def clean_connection_review(self):
        with connect() as connection:
            _cleanup(connection, self.tenant)

    def citation(self, concept_id):
        concept = next(
            item for item in self.generation.concepts if item.concept_id == concept_id
        )
        chunks = [
            item for item in self.generation.chunks if item.concept_id == concept_id
        ]
        reference = (
            "decisions/public.md"
            if concept_id == "projects/voiceos"
            else "projects/voiceos.md"
        )
        chunk = next((item for item in chunks if reference in item.text), chunks[0])
        text = chunk.text.strip()
        start = chunk.char_start + chunk.text.index(text)
        return ProposalCitation(
            concept_id=concept_id,
            source_revision=self.generation.source_revision,
            content_sha256=concept.content_sha256,
            char_start=start,
            char_end=start + len(text),
        )

    def frozen_evidence(self):
        return self.reader.read(
            self.request, principal=self.principal, cancellation=threading.Event()
        )

    def stored_connection_rows(self):
        with connect() as connection:
            return connection.execute(
                "SELECT proposal_type, proposed_content, source_citations, status FROM yap_knowledge_proposals WHERE tenant_id = %s",
                (self.tenant,),
            ).fetchall()

    def graph_identity(self):
        with connect() as connection:
            active = connection.execute(
                "SELECT generation_sha256 FROM yap_knowledge_active_builds WHERE tenant_id = %s",
                (self.tenant,),
            ).fetchone()
            edges = connection.execute(
                "SELECT relationship_id FROM yap_knowledge_relationships WHERE tenant_id = %s ORDER BY relationship_id",
                (self.tenant,),
            ).fetchall()
            return active, edges

    def hidden_request(self):
        hidden = next(
            item.concept_id
            for item in self.generation.concepts
            if item.concept_id.startswith("secret/")
        )
        candidate = {**self.candidate, "target_concept_id": hidden}
        source = next(
            item
            for item in self.request.source_citations
            if item.concept_id == self.candidate["source_concept_id"]
        )
        return replace(
            self.request,
            reviewed_content=json.dumps(candidate),
            source_citations=(source, self.citation(hidden)),
        )
