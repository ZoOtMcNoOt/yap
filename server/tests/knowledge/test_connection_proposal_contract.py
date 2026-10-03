import json
import unittest

from yap_server.knowledge.knowledge_tool_contract import (
    MAX_CONNECTION_PROPOSAL_CHARACTERS,
    ProposalCitation,
    canonical_connection_proposal,
    validate_governed_agent_tool_arguments,
)


def candidate(**changes):
    return {
        "schema_version": 1,
        "source_concept_id": "projects/yap",
        "target_concept_id": "decisions/interface",
        "relationship_type": "supports",
        "rationale": "The reviewed sources describe the interface decision.",
        **changes,
    }


def citations():
    return tuple(
        ProposalCitation(
            concept_id=concept,
            source_revision="reviewed-1",
            content_sha256="f" * 64,
            char_start=0,
            char_end=4,
        )
        for concept in ("projects/yap", "decisions/interface")
    )


class ConnectionProposalContractTests(unittest.TestCase):
    def parse(self, value=None, source_citations=None, generation="a" * 64):
        return canonical_connection_proposal(
            json.dumps(candidate() if value is None else value, ensure_ascii=False),
            citations() if source_citations is None else source_citations,
            generation,
        )

    def test_only_a_typed_candidate_can_enter_the_relationship_contract(self):
        invalid = (
            "A connection might exist.",
            [],
            {**candidate(), "authority": "human_confirmed"},
            {**candidate(), "canonical": True},
            candidate(schema_version=True),
            candidate(schema_version="1"),
            candidate(schema_version=2),
            candidate(source_concept_id=3),
            candidate(source_concept_id=" projects/yap"),
            candidate(source_concept_id="projects/\nyap"),
            candidate(target_concept_id="projects/yap"),
            candidate(relationship_type="related to"),
            candidate(relationship_type="supports\x00"),
            candidate(relationship_type="関連"),
            candidate(relationship_type="x" * 129),
            candidate(rationale=""),
            candidate(rationale="x" * 2001),
            candidate(rationale="Private\x00text"),
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse(value)

    def test_duplicate_fields_deep_json_and_excess_input_are_refused(self):
        for value in (
            '{"schema_version":1,"schema_version":1}',
            "[" * 2000 + "0" + "]" * 2000,
            "x" * (MAX_CONNECTION_PROPOSAL_CHARACTERS + 1),
        ):
            with self.subTest(value=value[:40]), self.assertRaises(ValueError):
                canonical_connection_proposal(value, citations(), "a" * 64)

    def test_both_distinct_endpoints_and_the_generation_need_exact_evidence(self):
        for proof in (
            (),
            citations()[:1],
            citations() + citations()[:1],
            (
                citations()[0],
                citations()[1].model_copy(update={"concept_id": "secret/other"}),
            ),
            (citations()[0], citations()[0]),
        ):
            with self.subTest(proof=proof), self.assertRaises(ValueError):
                self.parse(source_citations=proof)
        for generation in (None, "stale", True):
            with self.subTest(generation=generation), self.assertRaises(ValueError):
                self.parse(generation=generation)

    def test_equivalent_json_and_citation_order_have_one_replay_identity(self):
        original = self.parse()
        reordered = dict(reversed(list(candidate().items())))
        self.assertEqual(
            original,
            self.parse(reordered, tuple(reversed(citations()))),
        )
        self.assertEqual(json.loads(original[0]), candidate())

    def test_unicode_rationale_fits_the_actual_escaped_storage_bound(self):
        text = "🙂" * 2000
        with self.assertRaisesRegex(ValueError, "stored bound"):
            self.parse(candidate(rationale=text))
        encoded, _ = self.parse(candidate(rationale="界" * 2000))
        self.assertLessEqual(len(encoded), MAX_CONNECTION_PROPOSAL_CHARACTERS)
        self.assertEqual(json.loads(encoded)["rationale"], "界" * 2000)

    def test_model_argument_validation_uses_the_same_relationship_contract(self):
        arguments = {
            "purpose": "knowledge.read",
            "proposal_type": "relationship",
            "proposed_content": json.dumps(candidate()),
            "source_citations": [item.model_dump(mode="json") for item in citations()],
            "expected_generation_sha256": "a" * 64,
        }
        validate_governed_agent_tool_arguments("propose_knowledge", arguments)
        for changes in (
            {"proposed_content": "Unstructured connection text"},
            {"source_citations": arguments["source_citations"][:1]},
            {"expected_generation_sha256": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_governed_agent_tool_arguments(
                    "propose_knowledge", {**arguments, **changes}
                )
