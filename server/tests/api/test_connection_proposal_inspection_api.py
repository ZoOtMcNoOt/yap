import json
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

from yap_server.knowledge.knowledge_connections_service import (
    KnowledgeConnectionsService,
)
from tests.agents.curator_connections_fixtures import (
    CuratorConnectionFixture,
    DSN,
    connect,
)
from tests.api.api_fixtures import HealthServerTestCase
from tests.api import test_terminology_api as terminology_fixtures
from tests.contract import contract_schema_support


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class ConnectionProposalInspectionApiTests(
    CuratorConnectionFixture, HealthServerTestCase
):
    server_settings = terminology_fixtures.TerminologyApiTests.server_settings

    def setUp(self):
        self.prepare_connection_review()
        self.reference = self.core.propose(
            self.request, principal=self.principal, cancellation=threading.Event()
        ).proposal_id
        self.request_authenticator = terminology_fixtures._Authentication(self.tenant)
        self.knowledge_connections_service = KnowledgeConnectionsService(connect)
        super().setUp()

    def inspect(self, query=None, principal="alice", method="GET"):
        status, headers, body = self._request(
            "/v1/knowledge/connection-proposal?"
            + urlencode(
                query if query is not None else {"proposalId": self.reference},
                doseq=True,
            ),
            method=method,
            headers={}
            if principal is None
            else {"Authorization": f"Bearer {principal}"},
        )
        return status, headers, json.loads(body)

    def test_authenticated_persisted_inspection_schema_and_no_store(self):
        self.assertEqual(self.inspect(principal=None)[0], 401)
        before = self.graph_identity(), self.stored_connection_rows()
        status, headers, result = self.inspect()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(result["proposalId"], self.reference)
        document = contract_schema_support.load_json(
            Path(__file__).parents[2] / "openapi/openapi.json"
        )
        contract_schema_support.assert_schema_subset(
            result,
            document["components"]["schemas"]["KnowledgeConnectionProposal"],
            document_name="openapi.json",
            documents={"openapi.json": document},
        )
        foreign = self.inspect(principal="bob")
        missing = self.inspect({"proposalId": "f" * 64})
        self.assertEqual(foreign[0], 404)
        self.assertEqual(
            {k: v for k, v in foreign[2].items() if k != "requestId"},
            {k: v for k, v in missing[2].items() if k != "requestId"},
        )
        self.assertNotIn("projects/voiceos", json.dumps(foreign[2]))
        self.assertEqual((self.graph_identity(), self.stored_connection_rows()), before)
        self.assertNotIn(self.reference, "\n".join(self.logger.messages))

    def test_unsupported_methods_duplicate_fields_and_authority_claims_are_refused(
        self,
    ):
        self.assertEqual(self.inspect(method="POST")[0], 405)
        for query in [
            {"proposalId": [self.reference, self.reference]},
            {"proposalId": self.reference, "subjectId": "bob"},
            {"proposalId": "invalid"},
            {},
        ]:
            self.assertEqual(self.inspect(query)[0], 400)
