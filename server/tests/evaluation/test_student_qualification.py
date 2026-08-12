from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from yap_server.agents.student import StudentEvidenceItem
from yap_server.agents.student_model import StudentQuestion
from yap_server.agents.student_service import StudentJobView
from yap_server.evaluation.student_qualification import (
    evaluate_student_qualification,
    load_student_qualification_acceptance,
    load_student_qualification_corpus,
)


SERVER_ROOT = Path(__file__).resolve().parents[2]


class _Service:
    def __init__(self, *, wrong_term: bool = False, wrong_citation: bool = False):
        self.wrong_term = wrong_term
        self.wrong_citation = wrong_citation

    def create_questions(self, request, *, principal, cancellation):
        del cancellation
        case_id = request.conversation_concept_id.removeprefix("meetings/")
        question = {
            "restart-safety": "What does the active pointer protect after a restart?",
            "terminology-dose": (
                "Which Evolut FX procedure detail and medication dose were reviewed?"
            ),
            "spanish-review": "Que decision sobre TAVI se reviso el 12 de agosto?",
            "negation-boundary": "Why was the release decision not approved?",
            "date-owner-count": (
                "When is the audit scheduled, and how many owners must review?"
            ),
            "instruction-is-data": "What does the reviewed evidence policy require?",
            "raw-authority": "Why must raw ASR remain authoritative?",
            "librarian-boundary": "How does Librarian protect hidden nodes and links?",
        }[case_id]
        if self.wrong_term:
            question = "What should we learn about an unrelated subject?"
        text = "Visible evidence"
        citation = StudentEvidenceItem(
            concept_id=(
                "meetings/other" if self.wrong_citation else request.conversation_concept_id
            ),
            source_revision="a" * 64,
            content_sha256="b" * 64,
            char_start=0,
            char_end=len(text),
            text=text,
        )
        return StudentJobView(
            request_id=f"request-{principal.subject_id}",
            status="complete",
            conversation_concept_id=request.conversation_concept_id,
            generation_sha256=request.expected_generation_sha256,
            evidence_sha256="c" * 64,
            questions=(StudentQuestion(question, (citation,)),),
        )


class StudentQualificationTests(unittest.TestCase):
    def test_checked_acceptance_and_fixture_load(self) -> None:
        acceptance = load_student_qualification_acceptance(
            SERVER_ROOT / "student-acceptance.json"
        )
        corpus = load_student_qualification_corpus(
            SERVER_ROOT / "student-workload-fixtures.json"
        )
        self.assertEqual(acceptance.concurrent_request_count, 8)
        self.assertEqual(len(corpus.cases), 8)
        self.assertEqual(len({case.owner_id for case in corpus.cases}), 8)

    def test_multi_owner_result_qualifies_without_public_question_content(self) -> None:
        corpus = load_student_qualification_corpus(
            SERVER_ROOT / "student-workload-fixtures.json"
        )
        result = evaluate_student_qualification(
            service=_Service(),
            corpus=corpus,
            acceptance=load_student_qualification_acceptance(
                SERVER_ROOT / "student-acceptance.json"
            ),
            tenant_id="student-qualification",
            generation_sha256="d" * 64,
            observe_warm_state=_warm_state,
            observe_admission_state=_admission_state,
        )
        self.assertEqual(
            result.public_evidence["outcome"],
            "student-learning-questions-qualified",
        )
        self.assertEqual(
            result.public_evidence["counts"]["maximumConcurrentOwnerCount"], 8
        )
        public = json.dumps(result.public_evidence, sort_keys=True)
        private = json.dumps(result.private_evidence, sort_keys=True)
        self.assertNotIn("active pointer", public)
        self.assertNotIn("What should we learn", public)
        self.assertIn("What does the active pointer", private)

    def test_wrong_term_or_citation_rejects_qualification(self) -> None:
        corpus = load_student_qualification_corpus(
            SERVER_ROOT / "student-workload-fixtures.json"
        )
        acceptance = load_student_qualification_acceptance(
            SERVER_ROOT / "student-acceptance.json"
        )
        for service, failed_check in (
            (_Service(wrong_term=True), "requiredTermCoverageMet"),
            (_Service(wrong_citation=True), "sourceCitationsExact"),
        ):
            with self.subTest(check=failed_check):
                result = evaluate_student_qualification(
                    service=service,
                    corpus=corpus,
                    acceptance=acceptance,
                    tenant_id="student-qualification",
                    generation_sha256="d" * 64,
                    observe_warm_state=_warm_state,
                    observe_admission_state=_admission_state,
                )
                self.assertEqual(
                    result.public_evidence["outcome"], "deterministic-no-student"
                )
                self.assertFalse(result.public_evidence["acceptance"][failed_check])

    def test_fixture_rejects_duplicate_owner_and_unsourced_required_term(self) -> None:
        source = json.loads(
            (SERVER_ROOT / "student-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        mutations = []
        duplicate = json.loads(json.dumps(source))
        duplicate["cases"][1]["ownerId"] = duplicate["cases"][0]["ownerId"]
        mutations.append(duplicate)
        unsourced = json.loads(json.dumps(source))
        unsourced["cases"][0]["requiredQuestionTerms"] = ["not in the source"]
        mutations.append(unsourced)
        unfrozen = json.loads(json.dumps(source))
        unfrozen["cases"][0]["expectedQuestion"] = "What was invented?"
        mutations.append(unfrozen)
        for value in mutations:
            with self.subTest(value=value["cases"][0]["requiredQuestionTerms"]):
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "fixtures.json"
                    path.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_student_qualification_corpus(path)

    def test_warm_or_broker_change_rejects_qualification(self) -> None:
        corpus = load_student_qualification_corpus(
            SERVER_ROOT / "student-workload-fixtures.json"
        )
        acceptance = load_student_qualification_acceptance(
            SERVER_ROOT / "student-acceptance.json"
        )
        warm_states = iter((_warm_state(), {**_warm_state(), "processGeneration": 8}))
        broker_states = iter((_admission_state(), {**_admission_state(), "processId": 42}))
        result = evaluate_student_qualification(
            service=_Service(),
            corpus=corpus,
            acceptance=acceptance,
            tenant_id="student-qualification",
            generation_sha256="d" * 64,
            observe_warm_state=lambda: next(warm_states),
            observe_admission_state=lambda: next(broker_states),
        )
        self.assertEqual(result.public_evidence["outcome"], "deterministic-no-student")
        self.assertFalse(
            result.public_evidence["acceptance"]["alreadyWarmGenerationUnchanged"]
        )
        self.assertFalse(
            result.public_evidence["acceptance"]["admissionBrokerProcessUnchanged"]
        )


def _warm_state():
    return {
        "state": "ready",
        "profileId": "rapid-automation",
        "profileSha256": "e" * 64,
        "candidateLockSha256": "f" * 64,
        "processGeneration": 7,
        "startCount": 1,
        "restartCount": 0,
    }


def _admission_state():
    return {
        "processId": 41,
        "processStartTicks": 9,
        "binarySha256": "a" * 64,
        "socketDevice": 1,
        "socketInode": 2,
    }


if __name__ == "__main__":
    unittest.main()
