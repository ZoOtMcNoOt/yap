from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from yap_server.agents.curator_service import CuratorJobView
from yap_server.evaluation import curator_qualification as qualification
from yap_server.evaluation.curator_qualification import (
    CuratorExpectedEvidence,
    CuratorExpectedEvidencePack,
    build_curator_qualification_requests,
    evaluate_curator_qualification,
    load_curator_qualification_acceptance,
    load_curator_qualification_corpus,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SERVER_ROOT = REPOSITORY_ROOT / "server"
RUN_ID = "run-12345678"


class _Service:
    def __init__(
        self,
        decisions: dict[str, str],
        evidence_sha256: dict[str, str],
    ) -> None:
        self._decisions = decisions
        self._evidence_sha256 = evidence_sha256
        self.requests = []
        self._lock = threading.Lock()

    def propose(self, request, *, principal, cancellation):
        if cancellation.is_set():
            raise RuntimeError("unexpected cancellation")
        with self._lock:
            self.requests.append((principal.subject_id, request))
        decision = self._decisions[request.reviewed_content]
        evidence_sha256 = self._evidence_sha256[request.reviewed_content]
        if decision == "propose":
            return CuratorJobView(
                f"curator-observed-{principal.subject_id}",
                request.submission_id,
                "proposed",
                request.expected_generation_sha256,
                evidence_sha256,
                "f" * 64,
            )
        return CuratorJobView(
            f"curator-observed-{principal.subject_id}",
            request.submission_id,
            "rejected",
            request.expected_generation_sha256,
            evidence_sha256,
            reason="model-rejected",
        )


class CuratorQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.acceptance = load_curator_qualification_acceptance(
            SERVER_ROOT / "curator-acceptance.json"
        )
        self.corpus = load_curator_qualification_corpus(
            SERVER_ROOT / "curator-workload-fixtures.json"
        )
        self.generation_sha256 = "d" * 64
        self.expected_evidence = {
            case.case_id: (
                CuratorExpectedEvidence(
                    concept_id=case.concept_id,
                    source_revision="a" * 64,
                    content_sha256="b" * 64,
                    char_start=17,
                    char_end=17 + len(case.body),
                    text=case.body,
                ),
            )
            for case in self.corpus.cases
        }
        self.expected_packs = {
            case.case_id: CuratorExpectedEvidencePack(
                generation_sha256=self.generation_sha256,
                permission_hash=(f"{index + 1:064x}"),
                authorization_hash=(f"{index + 101:064x}"),
                items=self.expected_evidence[case.case_id],
            )
            for index, case in enumerate(self.corpus.cases)
        }
        self.expected_evidence_sha256 = {
            case_id: pack.evidence.evidence_sha256
            for case_id, pack in self.expected_packs.items()
        }

    def test_loaders_and_request_builder_freeze_both_trigger_contracts(self) -> None:
        self.assertEqual(len(self.corpus.cases), 8)
        self.assertEqual(len({case.owner_id for case in self.corpus.cases}), 8)
        self.assertEqual(self.acceptance.concurrent_request_count, 8)
        self.assertEqual(self.acceptance.maximum_output_tokens, 512)
        self.assertEqual(self.acceptance.maximum_input_tokens, 7_680)
        self.assertEqual(self.acceptance.broker_active_capacity, 8)

        requests = build_curator_qualification_requests(
            self.corpus,
            qualification_run_id=RUN_ID,
            generation_sha256=self.generation_sha256,
            expected_evidence=self.expected_evidence,
        )
        for case in self.corpus.cases:
            request = requests[case.case_id]
            expected = self.expected_evidence[case.case_id][0]
            self.assertEqual(request.source_citations, (expected.citation,))
            self.assertEqual(request.reviewed_content, case.reviewed_content)
            if case.trigger == "reviewed-student-answer":
                self.assertIsNotNone(request.student_question)
                question = request.student_question
                assert question is not None
                self.assertEqual(
                    question.source_citation,
                    expected.citation,
                )
                self.assertEqual(question.support_quote, case.source_subject)
                self.assertEqual(
                    question.to_wire()["sourceSupports"][0]["sourceCitation"],
                    {
                        "conceptId": expected.concept_id,
                        "sourceRevision": expected.source_revision,
                        "contentSha256": expected.content_sha256,
                        "charStart": expected.char_start,
                        "charEnd": expected.char_end,
                    },
                )
            else:
                self.assertIsNone(request.student_question)

    def test_acceptance_cannot_reduce_input_output_or_broker_capacity(self) -> None:
        original = json.loads(
            (SERVER_ROOT / "curator-acceptance.json").read_text(encoding="utf-8")
        )
        for field, value in (
            ("maximumInputTokens", 7_679),
            ("maximumOutputTokens", 511),
            ("brokerActiveCapacity", 7),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                changed = {**original, field: value}
                path = Path(temporary) / "acceptance.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "values conflict"):
                    load_curator_qualification_acceptance(path)

    def test_exact_eight_owner_synchronized_wave_qualifies_without_public_content(
        self,
    ) -> None:
        service = _Service(
            {
                case.reviewed_content: case.expected_decision
                for case in self.corpus.cases
            },
            {
                case.reviewed_content: self.expected_evidence_sha256[case.case_id]
                for case in self.corpus.cases
            },
        )
        result = evaluate_curator_qualification(
            service=service,
            corpus=self.corpus,
            acceptance=self.acceptance,
            tenant_id="curator-qualification",
            qualification_run_id=RUN_ID,
            generation_sha256=self.generation_sha256,
            expected_evidence=self.expected_packs,
            observe_warm_state=_warm_state,
            observe_admission_state=_admission_state,
        )

        public = result.public_evidence
        self.assertEqual(
            public["outcome"],
            "curator-knowledge-proposals-qualified",
        )
        self.assertEqual(public["counts"]["caseCount"], 8)
        self.assertEqual(public["counts"]["synchronizedOwnerWaveCount"], 8)
        self.assertEqual(public["counts"]["proposedCaseCount"], 4)
        self.assertEqual(public["counts"]["rejectedCaseCount"], 4)
        self.assertEqual(public["route"]["maximumOutputTokens"], 512)
        self.assertEqual(public["route"]["maximumInputTokens"], 7_680)
        self.assertNotIn("brokerActiveCapacity", public["route"])
        self.assertNotIn(RUN_ID, str(public))
        self.assertNotIn("cases", public)
        serialized = str(public)
        for case in self.corpus.cases:
            self.assertNotIn(case.body, serialized)
            self.assertNotIn(case.reviewed_content, serialized)

    def test_wrong_decision_and_misbuilt_evidence_fail_closed(self) -> None:
        decisions = {
            case.reviewed_content: case.expected_decision
            for case in self.corpus.cases
        }
        decisions[self.corpus.cases[0].reviewed_content] = "reject"
        result = evaluate_curator_qualification(
            service=_Service(
                decisions,
                {
                    case.reviewed_content: self.expected_evidence_sha256[
                        case.case_id
                    ]
                    for case in self.corpus.cases
                },
            ),
            corpus=self.corpus,
            acceptance=self.acceptance,
            tenant_id="curator-qualification",
            qualification_run_id=RUN_ID,
            generation_sha256=self.generation_sha256,
            expected_evidence=self.expected_packs,
            observe_warm_state=_warm_state,
            observe_admission_state=_admission_state,
        )
        self.assertEqual(result.public_evidence["outcome"], "deterministic-no-curator")
        self.assertFalse(
            result.public_evidence["acceptance"]["expectedDecisionsExact"]
        )

        replayed_hash = evaluate_curator_qualification(
            service=_Service(
                {
                    case.reviewed_content: case.expected_decision
                    for case in self.corpus.cases
                },
                {
                    case.reviewed_content: "e" * 64
                    for case in self.corpus.cases
                },
            ),
            corpus=self.corpus,
            acceptance=self.acceptance,
            tenant_id="curator-qualification",
            qualification_run_id=RUN_ID,
            generation_sha256=self.generation_sha256,
            expected_evidence=self.expected_packs,
            observe_warm_state=_warm_state,
            observe_admission_state=_admission_state,
        )
        self.assertFalse(
            replayed_hash.public_evidence["acceptance"][
                "expectedDecisionsExact"
            ]
        )

        missing = dict(self.expected_evidence)
        missing.pop(self.corpus.cases[0].case_id)
        with self.assertRaisesRegex(ValueError, "expected evidence differs"):
            build_curator_qualification_requests(
                self.corpus,
                qualification_run_id=RUN_ID,
                generation_sha256=self.generation_sha256,
                expected_evidence=missing,
            )

        changed = dict(self.expected_evidence)
        first = self.corpus.cases[0]
        expected = changed[first.case_id][0]
        changed[first.case_id] = (
            CuratorExpectedEvidence(
                concept_id=expected.concept_id,
                source_revision=expected.source_revision,
                content_sha256=expected.content_sha256,
                char_start=expected.char_start,
                char_end=expected.char_end,
                text="X" * len(expected.text),
            ),
        )
        with self.assertRaisesRegex(ValueError, "expected evidence is invalid"):
            build_curator_qualification_requests(
                self.corpus,
                qualification_run_id=RUN_ID,
                generation_sha256=self.generation_sha256,
                expected_evidence=changed,
            )

        second_run = build_curator_qualification_requests(
            self.corpus,
            qualification_run_id="run-87654321",
            generation_sha256=self.generation_sha256,
            expected_evidence=self.expected_evidence,
        )
        first_run = build_curator_qualification_requests(
            self.corpus,
            qualification_run_id=RUN_ID,
            generation_sha256=self.generation_sha256,
            expected_evidence=self.expected_evidence,
        )
        self.assertTrue(
            all(
                first_run[case.case_id].submission_id
                != second_run[case.case_id].submission_id
                for case in self.corpus.cases
            )
        )

    def test_wave_timeout_cancels_and_contains_workers_without_blocking_exit(
        self,
    ) -> None:
        class CancellableService:
            def propose(self, request, *, principal, cancellation):
                del request, principal
                if not cancellation.wait(1.0):
                    raise RuntimeError("qualification cancellation was not delivered")
                raise RuntimeError("qualification case cancelled")

        with (
            mock.patch.object(qualification, "_CASE_TIMEOUT_SECONDS", 0.01),
            self.assertRaisesRegex(TimeoutError, "wave exceeded"),
        ):
            evaluate_curator_qualification(
                service=CancellableService(),
                corpus=self.corpus,
                acceptance=self.acceptance,
                tenant_id="curator-qualification",
                qualification_run_id=RUN_ID,
                generation_sha256=self.generation_sha256,
                expected_evidence=self.expected_packs,
                observe_warm_state=_warm_state,
                observe_admission_state=_admission_state,
            )
        self.assertFalse(
            any(
                thread.name.startswith("curator-qualification")
                for thread in threading.enumerate()
            )
        )


def _warm_state():
    return {
        "state": "ready",
        "profileId": "complex-orchestration",
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
