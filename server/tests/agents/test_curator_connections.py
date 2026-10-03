import json
import threading
import unittest
from dataclasses import replace

from yap_server.agents.curator import (
    CuratorEvidence,
    CuratorEvidenceItem,
    CuratorRequest,
    curator_request_sha256,
)
from yap_server.agents.curator_model import CuratorProposalModel
from yap_server.knowledge.knowledge_tool_contract import ProposalCitation
from tests.agents.test_curator import _Transport, _tool_response


def connection_request(**changes):
    candidate = {
        "schema_version": 1,
        "source_concept_id": "projects/yap",
        "target_concept_id": "decisions/interface",
        "relationship_type": "references",
        "rationale": "The reviewed project text references the interface decision.",
    }
    citations = tuple(
        ProposalCitation(
            concept_id=concept,
            source_revision="reviewed-1",
            content_sha256="b" * 64,
            char_start=0,
            char_end=12,
        )
        for concept in ("projects/yap", "decisions/interface")
    )
    return CuratorRequest(
        **{
            "submission_id": "connection-1",
            "trigger": "reviewed-connection",
            "expected_generation_sha256": "a" * 64,
            "reviewed_content": json.dumps(candidate),
            "source_citations": citations,
            **changes,
        }
    )


def connection_wire(request):
    return {
        "schemaVersion": 1,
        "submissionId": request.submission_id,
        "trigger": request.trigger,
        "expectedGenerationSha256": request.expected_generation_sha256,
        "reviewedContent": request.reviewed_content,
        "sourceCitations": [
            {
                "conceptId": item.concept_id,
                "sourceRevision": item.source_revision,
                "contentSha256": item.content_sha256,
                "charStart": item.char_start,
                "charEnd": item.char_end,
            }
            for item in request.source_citations
        ],
    }


class CuratorConnectionContractTests(unittest.TestCase):
    def test_wire_normalizes_semantic_replay_and_keeps_direction_in_request_identity(
        self,
    ):
        request = connection_request()
        self.assertEqual(request.proposal_type, "relationship")
        wire = connection_wire(request)
        wire["sourceCitations"].reverse()
        wire["reviewedContent"] = json.dumps(
            json.loads(request.reviewed_content), indent=2
        )
        replay = CuratorRequest.from_wire(wire)
        self.assertEqual(replay, request)
        self.assertEqual(
            curator_request_sha256(replay), curator_request_sha256(request)
        )
        candidate = json.loads(request.reviewed_content)
        candidate["source_concept_id"], candidate["target_concept_id"] = (
            candidate["target_concept_id"],
            candidate["source_concept_id"],
        )
        reversed_edge = replace(request, reviewed_content=json.dumps(candidate))
        self.assertNotEqual(
            curator_request_sha256(reversed_edge), curator_request_sha256(request)
        )

    def test_both_endpoint_proofs_and_the_connection_trigger_are_required(self):
        request = connection_request()
        for citations in [
            request.source_citations[:1],
            (request.source_citations[0],) * 2,
        ]:
            with self.subTest(citations=citations), self.assertRaises(ValueError):
                replace(request, source_citations=citations)
        wire = connection_wire(request)
        wire["studentQuestion"] = {}
        with self.assertRaises(ValueError):
            CuratorRequest.from_wire(wire)
        candidate = json.loads(request.reviewed_content)
        candidate["authority"] = "human_confirmed"
        with self.assertRaises(ValueError):
            replace(request, reviewed_content=json.dumps(candidate))
        with self.assertRaises(ValueError):
            replace(request, reviewed_content='{"schema_version":1,"schema_version":1}')
        with self.assertRaises(ValueError):
            replace(request, reviewed_content="An untyped connection statement")
        self.assertEqual(
            replace(request, trigger="explicit-proposal").proposal_type, "summary"
        )

    def test_encoded_connection_bound_is_separate_from_summary_statement_bound(self):
        request = connection_request()
        candidate = json.loads(request.reviewed_content)
        candidate["rationale"] = "é" * 1000
        long_edge = replace(
            request, reviewed_content=json.dumps(candidate, ensure_ascii=False)
        )
        self.assertGreater(len(long_edge.reviewed_content), 2048)
        with self.assertRaises(ValueError):
            replace(long_edge, trigger="explicit-proposal")
        candidate["rationale"] = "𒁉" * 2000
        with self.assertRaises(ValueError):
            replace(request, reviewed_content=json.dumps(candidate, ensure_ascii=False))

    def test_model_receives_frozen_typed_direction_and_both_identified_excerpts(self):
        request = connection_request()
        evidence = CuratorEvidence.create(
            generation_sha256=request.expected_generation_sha256,
            permission_hash="c" * 64,
            authorization_hash="d" * 64,
            items=tuple(
                CuratorEvidenceItem(citation, "Exact source")
                for citation in request.source_citations
            ),
        )
        transport = _Transport(_tool_response())
        result = CuratorProposalModel(
            transport=transport, model="test-model", maximum_output_tokens=128
        ).review(request, evidence, cancellation=threading.Event())
        self.assertEqual(result.decision, "propose")
        payload = transport.payloads[0]
        data = json.loads(payload["messages"][1]["content"])
        self.assertEqual(
            data["connectionCandidate"], json.loads(request.reviewed_content)
        )
        self.assertNotIn("reviewedContent", data)
        self.assertEqual(
            data["visibleEvidence"],
            [
                {"conceptId": item.citation.concept_id, "text": item.text}
                for item in evidence.items
            ],
        )
        self.assertIn("direction", payload["messages"][0]["content"])
        self.assertIn("similarity", payload["messages"][0]["content"])
        self.assertEqual(
            payload["tool_choice"]["function"]["name"], "return_curator_decision"
        )
        self.assertFalse(payload["parallel_tool_calls"])
