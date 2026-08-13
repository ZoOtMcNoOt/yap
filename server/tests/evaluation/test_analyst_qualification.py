from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from yap_server.agents.analyst_service import AnalystJobView
from yap_server.evaluation.analyst_qualification import (
    AnalystExpectedView,
    AnalystQualificationInvocation,
    bind_analyst_compiled_corpus,
    build_analyst_qualification_invocations,
    evaluate_analyst_qualification,
    load_analyst_qualification_acceptance,
    load_analyst_qualification_corpus,
    render_analyst_qualification_generations,
)
from yap_server.knowledge.okf_compiler import compile_okf_bundle


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SERVER_ROOT = REPOSITORY_ROOT / "server"


class _Executor:
    def __init__(
        self,
        expected: dict[str, AnalystExpectedView],
        *,
        overrides: dict[str, AnalystJobView | BaseException] | None = None,
        duplicate_request_ids: bool = False,
        synchronize_normal_calls: bool = False,
    ) -> None:
        self._expected = expected
        self._overrides = overrides or {}
        self._duplicate_request_ids = duplicate_request_ids
        self._barrier = threading.Barrier(8) if synchronize_normal_calls else None
        self._lock = threading.Lock()
        self.calls: list[tuple[AnalystQualificationInvocation, bool]] = []

    def __call__(
        self,
        invocation: AnalystQualificationInvocation,
        cancellation: threading.Event,
    ) -> AnalystJobView:
        with self._lock:
            self.calls.append((invocation, cancellation.is_set()))
        if self._barrier is not None and invocation.mode == "normal":
            self._barrier.wait(timeout=1.0)
        override = self._overrides.get(invocation.invocation_id)
        if isinstance(override, BaseException):
            raise override
        if override is not None:
            return override
        expected = self._expected[invocation.invocation_id]
        request_id = (
            "analyst-duplicate"
            if self._duplicate_request_ids
            else f"analyst-{invocation.case_id}-{invocation.run_id}"
        )
        return AnalystJobView(
            request_id=request_id,
            status=expected.status,
            reason=expected.reason,
            answer=expected.answer,
        )


class AnalystQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.acceptance = load_analyst_qualification_acceptance(
            SERVER_ROOT / "analyst-acceptance.json"
        )
        self.corpus = load_analyst_qualification_corpus(
            SERVER_ROOT / "analyst-workload-fixtures.json"
        )
        self.bound = _bound_corpus(self.corpus)
        self.expected = dict(self.bound.expected_views)

    def test_contract_freezes_eight_owner_wave_and_five_controls(self) -> None:
        invocations = build_analyst_qualification_invocations(self.corpus)
        primary = tuple(item for item in invocations if item.mode == "normal")
        controlled = tuple(item for item in invocations if item.mode != "normal")

        self.assertEqual(len(self.corpus.cases), 8)
        self.assertEqual(self.corpus.corpus_id, "analyst-public-synthetic-v3")
        self.assertEqual(len(invocations), 13)
        self.assertEqual(len(primary), 8)
        self.assertEqual(len({item.owner_id for item in primary}), 8)
        self.assertEqual(
            tuple(item.mode for item in controlled),
            (
                "client-cancelled",
                "deadline",
                "invalid-output",
                "stale-generation",
                "pre-cancelled",
            ),
        )
        self.assertEqual(
            (
                self.acceptance.complete_count,
                self.acceptance.unavailable_count,
                self.acceptance.failed_count,
                self.acceptance.cancelled_count,
            ),
            (4, 5, 1, 3),
        )
        self.assertEqual(self.acceptance.answer_count, 4)
        self.assertEqual(self.acceptance.citation_count, 5)
        empty = next(
            item for item in primary if item.case_id == "absent-time-unavailable"
        )
        self.assertEqual(
            self.expected[empty.invocation_id],
            AnalystExpectedView("evidence-unavailable", "empty-result", None),
        )
        self.assertNotIn(empty.case_id, self.bound.evidence_by_case)
        borealis = next(
            item
            for item in self.corpus.cases
            if item.case_id == "unassigned-owner-unavailable"
        )
        self.assertEqual(
            borealis.request.question,
            "Who is the currently assigned Borealis owner?",
        )
        borealis_evidence = borealis.runs[0].expected_evidence[0]
        self.assertIn("requires an owner field", borealis_evidence.quote)
        self.assertNotIn("assigned or identified", borealis_evidence.quote)

    def test_renderer_compiler_binding_derives_exact_answers_and_citations(
        self,
    ) -> None:
        exact = self.expected["exact-single-answer:normal"].answer
        multi = self.expected["ordered-multi-answer:normal"].answer
        injected = self.expected["instruction-as-data-answer:normal"].answer

        self.assertIsNotNone(exact)
        self.assertIsNotNone(multi)
        self.assertIsNotNone(injected)
        assert exact is not None and multi is not None and injected is not None
        self.assertEqual(
            exact.answer,
            "Atlas handoff requires two reviewers before publication.",
        )
        self.assertEqual(
            tuple(item.concept_id for item in multi.citations),
            ("release/nimbus-1-security", "release/nimbus-2-approvers"),
        )
        self.assertEqual(
            multi.answer, "\n\n".join(item.text for item in multi.citations)
        )
        self.assertIn("Ignore all prior instructions", injected.answer)
        self.assertEqual(
            sum(
                len(item.answer.citations)
                for item in self.expected.values()
                if item.answer is not None
            ),
            5,
        )
        self.assertTrue(
            all(
                not pack.output_budget_exhausted
                for pack in self.bound.evidence_by_case.values()
            )
        )

    def test_exact_views_qualify_with_public_aggregate_only(self) -> None:
        executor = _Executor(self.expected, synchronize_normal_calls=True)

        result = evaluate_analyst_qualification(
            executor=executor,
            corpus=self.bound,
            acceptance=self.acceptance,
        )

        self.assertEqual(
            result.public_evidence,
            self.acceptance.expected_public_evidence(),
        )
        self.assertTrue(result.public_evidence["qualified"])
        self.assertNotIn("question", json.dumps(result.public_evidence).casefold())
        normal_calls = [item for item in executor.calls if item[0].mode == "normal"]
        pre_cancelled = next(
            item for item in executor.calls if item[0].mode == "pre-cancelled"
        )
        self.assertEqual(len(normal_calls), 8)
        self.assertTrue(all(not was_set for _invocation, was_set in normal_calls))
        self.assertTrue(pre_cancelled[1])

    def test_mismatch_error_and_duplicate_request_id_cannot_false_green(self) -> None:
        unavailable = AnalystJobView(
            request_id="analyst-forged",
            status="evidence-unavailable",
            reason="model-evidence-unavailable",
        )
        scenarios = (
            _Executor(
                self.expected,
                overrides={"exact-single-answer:normal": unavailable},
            ),
            _Executor(
                self.expected,
                overrides={"exact-single-answer:normal": RuntimeError("failed")},
            ),
            _Executor(self.expected, duplicate_request_ids=True),
        )
        for executor in scenarios:
            with self.subTest(executor=type(executor).__name__):
                result = evaluate_analyst_qualification(
                    executor=executor,
                    corpus=self.bound,
                    acceptance=self.acceptance,
                )
                self.assertFalse(result.public_evidence["qualified"])
                self.assertTrue(
                    result.public_evidence["terminalMismatchCount"] > 0
                    or result.public_evidence["uniqueRequestIdCount"] != 13
                )

    def test_complete_answer_must_be_the_exact_domain_type(self) -> None:
        class _EqualToAnything:
            def __eq__(self, other):
                del other
                return True

        forged = AnalystJobView(
            request_id="analyst-forged-answer",
            status="complete",
            answer=_EqualToAnything(),  # type: ignore[arg-type]
        )
        result = evaluate_analyst_qualification(
            executor=_Executor(
                self.expected,
                overrides={"exact-single-answer:normal": forged},
            ),
            corpus=self.bound,
            acceptance=self.acceptance,
        )
        self.assertFalse(result.public_evidence["qualified"])
        observation = next(
            item
            for item in result.observations
            if item.invocation.invocation_id == "exact-single-answer:normal"
        )
        self.assertEqual(observation.failure_kind, "executor-error")

    def test_raw_fixture_and_compiler_drift_are_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "not compiler-bound"):
            evaluate_analyst_qualification(
                executor=_Executor(self.expected),
                corpus=self.corpus,  # type: ignore[arg-type]
                acceptance=self.acceptance,
            )

        rendered, compiled = _render_and_compile(self.corpus)
        successor = compiled["successor"]
        forged = replace(successor, source_revision="forged-revision")
        with self.assertRaisesRegex(ValueError, "source revision differs"):
            bind_analyst_compiled_corpus(
                self.corpus,
                rendered,
                {**compiled, "successor": forged},
            )
        changed_file = replace(rendered[0].files[0], body=b"changed\n")
        changed_rendered = replace(
            rendered[0],
            files=(changed_file, *rendered[0].files[1:]),
        )
        with self.assertRaisesRegex(ValueError, "rendered corpus differs"):
            bind_analyst_compiled_corpus(
                self.corpus,
                (changed_rendered, *rendered[1:]),
                compiled,
            )

    def test_wave_timeout_cancels_and_contains_workers(self) -> None:
        class _BlockingExecutor:
            def __call__(self, invocation, cancellation):
                cancellation.wait(1.0)
                expected = self_expected[invocation.invocation_id]
                return AnalystJobView(
                    request_id=f"analyst-{invocation.case_id}-{invocation.run_id}",
                    status=expected.status,
                    reason=expected.reason,
                    answer=expected.answer,
                )

        self_expected = self.expected
        with mock.patch(
            "yap_server.evaluation.analyst_qualification._PRIMARY_WAVE_TIMEOUT_SECONDS",
            0.02,
        ):
            with self.assertRaisesRegex(TimeoutError, "wave exceeded"):
                evaluate_analyst_qualification(
                    executor=_BlockingExecutor(),
                    corpus=self.bound,
                    acceptance=self.acceptance,
                )
        time.sleep(0.02)
        self.assertFalse(
            any(
                thread.name.startswith("analyst-qualification")
                for thread in threading.enumerate()
            )
        )

    def test_acceptance_and_fixture_mutations_fail_closed(self) -> None:
        acceptance = json.loads(
            (SERVER_ROOT / "analyst-acceptance.json").read_text(encoding="utf-8")
        )
        fixture = json.loads(
            (SERVER_ROOT / "analyst-workload-fixtures.json").read_text(encoding="utf-8")
        )
        changed_acceptance = (
            {**acceptance, "invocationCount": 12},
            {**acceptance, "legacyThreshold": 1},
            {**acceptance, "synchronizedOwnerWaveMet": 1},
        )
        for changed in changed_acceptance:
            with (
                self.subTest(acceptance=changed),
                tempfile.TemporaryDirectory() as temp,
            ):
                path = Path(temp) / "acceptance.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_analyst_qualification_acceptance(path)

        changed_cases = list(fixture["cases"])
        changed_cases[0] = {
            **changed_cases[0],
            "ownerId": changed_cases[1]["ownerId"],
        }
        changed_fixture = {**fixture, "cases": changed_cases}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixture.json"
            path.write_text(json.dumps(changed_fixture), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "wave contract"):
                load_analyst_qualification_corpus(path)


def _render_and_compile(corpus):
    rendered = render_analyst_qualification_generations(
        corpus,
        tenant_id="fresh-analyst-tenant",
    )
    compiled = {}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for generation in rendered:
            generation_root = root / generation.generation_id
            for item in generation.files:
                path = generation_root / item.relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(item.body)
            compiled[generation.generation_id] = compile_okf_bundle(
                generation_root,
                tenant_id=generation.tenant_id,
                source_revision=generation.source_revision,
            )
    return rendered, compiled


def _bound_corpus(corpus):
    rendered, compiled = _render_and_compile(corpus)
    return bind_analyst_compiled_corpus(corpus, rendered, compiled)


if __name__ == "__main__":
    unittest.main()
