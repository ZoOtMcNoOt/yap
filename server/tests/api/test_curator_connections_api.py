import json
import threading
import time
import unittest
from pathlib import Path

from yap_server.agents.curator_proposal_service import CuratorProposalService
from tests.agents.curator_connections_fixtures import CuratorConnectionFixture, DSN
from tests.agents.test_curator_connections import connection_wire
from tests.api.api_fixtures import HealthServerTestCase
from tests.api import test_terminology_api as terminology_fixtures
from tests.contract import contract_schema_support


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class CuratorConnectionsApiTests(CuratorConnectionFixture, HealthServerTestCase):
    server_settings = terminology_fixtures.TerminologyApiTests.server_settings

    def setUp(self):
        self.prepare_connection_review()
        self.request_authenticator = terminology_fixtures._Authentication(self.tenant)
        self.curator_proposal_service = CuratorProposalService(curator=self.core)
        self.addCleanup(self.curator_proposal_service.close)
        super().setUp()

    def send(
        self,
        value=None,
        *,
        path="/v1/curator-proposals",
        principal="alice",
        method=None,
    ):
        headers = {} if principal is None else {"Authorization": f"Bearer {principal}"}
        if value is not None:
            headers["Content-Type"] = "application/json"
        status, response_headers, body = self._request(
            path,
            method=method or ("POST" if value is not None else "GET"),
            headers=headers,
            data=json.dumps(value).encode() if value is not None else None,
        )
        return status, response_headers, json.loads(body)

    def terminal(self, request_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, _, result = self.send(path=f"/v1/curator-proposals/{request_id}")
            self.assertEqual(status, 200)
            if result["status"] not in {"queued", "running", "cancellation-requested"}:
                return result
            threading.Event().wait(0.01)
        self.fail("The deterministic connection review did not terminate")

    def test_authenticated_http_review_persists_typed_intent_and_owner_scoped_reference(
        self,
    ):
        wire = connection_wire(self.request)
        before = self.graph_identity()
        status, _, _ = self.send(wire, principal=None)
        self.assertEqual(status, 401)
        status, _, accepted = self.send(wire)
        self.assertEqual(status, 202)
        result = self.terminal(accepted["requestId"])
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(self.stored_connection_rows()[0][0], "relationship")
        self.assertEqual(self.graph_identity(), before)
        document = contract_schema_support.load_json(
            Path(__file__).parents[2] / "openapi" / "openapi.json"
        )
        for value, schema in [
            (wire, "CuratorReviewedConnectionRequest"),
            (result, "CuratorProposalJobView"),
        ]:
            contract_schema_support.assert_schema_subset(
                value,
                document["components"]["schemas"][schema],
                document_name="openapi.json",
                documents={"openapi.json": document},
            )
        status, _, hidden = self.send(
            path=f"/v1/curator-proposals/{accepted['requestId']}", principal="bob"
        )
        self.assertEqual(status, 404)
        self.assertNotIn("proposalId", hidden)
        status, _, replay = self.send(wire)
        self.assertEqual(status, 202)
        self.assertEqual(
            self.terminal(replay["requestId"])["proposalId"], result["proposalId"]
        )
        self.assertEqual(len(self.transport.payloads), 1)
        logged = " ".join(self.logger.messages)
        self.assertNotIn(self.candidate["rationale"], logged)
        self.assertNotIn("Bearer alice", logged)

    def test_claims_untyped_edges_and_hidden_sources_cannot_publish_a_connection(self):
        wire = connection_wire(self.request)
        malformed = json.loads(self.request.reviewed_content)
        malformed["authority"] = "human_confirmed"
        for bad in [
            {**wire, "tenantId": "forged"},
            {**wire, "reviewedContent": json.dumps(malformed)},
            {**wire, "reviewedContent": "Untyped relationship"},
            {**wire, "sourceCitations": wire["sourceCitations"][:1]},
        ]:
            with self.subTest(request=bad):
                status, _, _ = self.send(bad)
                self.assertEqual(status, 400)
        self.assertEqual(self.transport.payloads, [])
        self.assertEqual(self.stored_connection_rows(), [])
        before = self.graph_identity()
        status, _, accepted = self.send(connection_wire(self.hidden_request()))
        self.assertEqual(status, 202)
        result = self.terminal(accepted["requestId"])
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("proposalId", result)
        self.assertNotIn("secret/", json.dumps(result))
        self.assertEqual(self.transport.payloads, [])
        self.assertEqual(self.stored_connection_rows(), [])
        self.assertEqual(self.graph_identity(), before)
