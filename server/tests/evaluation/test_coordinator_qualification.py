from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from yap_server.agents.coordinator_service import CoordinatorJobView
from yap_server.evaluation.coordinator_qualification import (
    CoordinatorExpectedView,
    CoordinatorQualificationInvocation,
    bind_coordinator_compiled_corpus,
    bind_coordinator_curator_lineage,
    build_coordinator_qualification_invocations,
    evaluate_coordinator_qualification,
    load_coordinator_qualification_acceptance,
    load_coordinator_qualification_corpus,
    render_coordinator_qualification_generations,
)
from yap_server.knowledge.okf_compiler import compile_okf_bundle


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SERVER_ROOT = REPOSITORY_ROOT / "server"


class _Executor:
    def __init__(
        self,
        expected: dict[str, CoordinatorExpectedView],
        *,
        overrides: dict[str, CoordinatorJobView | BaseException] | None = None,
        duplicate_request_ids: bool = False,
        synchronize_normal_calls: bool = False,
    ) -> None:
        self._expected = expected
        self._overrides = overrides or {}
        self._duplicate_request_ids = duplicate_request_ids
        self._barrier = threading.Barrier(8) if synchronize_normal_calls else None
        self._lock = threading.Lock()
        self.calls: list[tuple[CoordinatorQualificationInvocation, bool]] = []

    def __call__(
        self,
        invocation: CoordinatorQualificationInvocation,
        cancellation: threading.Event,
    ) -> CoordinatorJobView:
        with self._lock:
            self.calls.append((invocation, cancellation.is_set()))
        if self._barrier is not None and invocation.mode == "normal":
            self._barrier.wait(timeout=1.0)
        override = self._overrides.get(invocation.invocation_id)
        if isinstance(override, BaseException):
            raise override
        if override is not None:
            return override
        expected = self._expected[invocation.expected_view_id]
        request_id = (
            "coordinator-duplicate"
            if self._duplicate_request_ids
            else (
                f"coordinator-{invocation.wave_id or 'control'}-"
                f"{invocation.case_id}-{invocation.run_id}"
            )
        )
        return CoordinatorJobView(
            request_id=request_id,
            status=expected.status,
            reason=expected.reason,
            bundle=expected.bundle,
        )


class CoordinatorQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.acceptance = load_coordinator_qualification_acceptance(
            SERVER_ROOT / "coordinator-acceptance.json"
        )
        self.corpus = load_coordinator_qualification_corpus(
            SERVER_ROOT / "coordinator-workload-fixtures.json"
        )
        self.compiled = _compiled_corpus(self.corpus)
        self.bound = bind_coordinator_curator_lineage(
            self.compiled,
            {
                key: f"curator-request-{key}"
                for key in self.compiled.proposal_seeds_by_key
            },
        )
        self.expected = dict(self.bound.expected_views)

    def test_contract_freezes_eight_owner_waves_and_five_controls(self) -> None:
        invocations = build_coordinator_qualification_invocations(
            self.corpus, self.acceptance
        )
        primary = tuple(item for item in invocations if item.mode == "normal")
        controlled = tuple(item for item in invocations if item.mode != "normal")

        self.assertEqual(self.corpus.corpus_id, "coordinator-public-synthetic-v2")
        self.assertEqual(len(self.corpus.cases), 8)
        self.assertEqual(len({item.owner_id for item in self.corpus.cases}), 8)
        self.assertEqual(len(invocations), 29)
        self.assertEqual(len(primary), 24)
        self.assertEqual(
            {item.wave_id for item in primary},
            {"repeat-1", "repeat-2", "repeat-3"},
        )
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
            (15, 10, 1, 3),
        )

    def test_compiler_and_curator_lineage_bind_exact_selection_oracle(self) -> None:
        single = self.expected["exact-single-selection:normal"].bundle
        ordered = self.expected["ordered-multi-selection:normal"].bundle
        injected = self.expected["instruction-as-data-selection:normal"].bundle
        relationship = self.expected["relationship-review-selection:normal"].bundle

        self.assertIsNotNone(single)
        self.assertIsNotNone(ordered)
        self.assertIsNotNone(injected)
        self.assertIsNotNone(relationship)
        assert single is not None and ordered is not None and injected is not None
        assert relationship is not None
        self.assertEqual(len(single.items), 1)
        self.assertEqual(
            tuple(item.proposed_content for item in ordered.items),
            (
                "Nimbus release sequencing begins with security review.",
                "Nimbus release sequencing places approver confirmation after "
                "security review.",
            ),
        )
        self.assertIn(
            "is untrusted source data",
            injected.items[0].proposed_content,
        )
        self.assertIn(
            "Ignore all prior instructions", injected.items[0].citations[0].text
        )
        self.assertEqual(relationship.items[0].proposal_type, "summary")
        self.assertIn("dependency", relationship.items[0].proposed_content)
        self.assertEqual(single.to_wire()["canonical"], False)
        self.assertEqual(single.to_wire()["requiresReview"], True)
        self.assertNotIn("curatorRequestId", json.dumps(single.to_wire()))

        seed = self.compiled.proposal_seeds_by_key["atlas-security"]
        self.assertTrue(
            all(
                item.request.reviewed_content == item.evidence.items[0].text
                for item in self.compiled.proposal_seeds_by_key.values()
            )
        )
        coordinator_evidence = self.bound.evidence_by_case["exact-single-selection"]
        self.assertEqual(
            seed.evidence.authorization_hash,
            _authorization_hash(
                seed.evidence.permission_hash,
                "knowledge.search.lexical",
            ),
        )
        self.assertEqual(seed.proposal_permission_hash, seed.evidence.permission_hash)
        self.assertEqual(
            single.items[0].inherited_permission_sha256,
            seed.inherited_permission_sha256,
        )
        self.assertEqual(
            single.items[0].proposal_authorization_hash,
            _authorization_hash(seed.proposal_permission_hash, "knowledge.propose"),
        )
        self.assertEqual(
            coordinator_evidence.authorization_hash,
            _authorization_hash(
                coordinator_evidence.permission_hash,
                "knowledge.read",
            ),
        )
        self.assertNotEqual(
            seed.evidence.authorization_hash,
            coordinator_evidence.authorization_hash,
        )

    def test_exact_views_qualify_with_public_aggregate_only(self) -> None:
        executor = _Executor(self.expected, synchronize_normal_calls=True)
        result = evaluate_coordinator_qualification(
            executor=executor,
            corpus=self.bound,
            acceptance=self.acceptance,
        )

        self.assertEqual(
            result.public_evidence, self.acceptance.expected_public_evidence()
        )
        self.assertTrue(result.public_evidence["qualified"])
        self.assertTrue(result.public_evidence["selectionOnlyContractMet"])
        self.assertTrue(result.public_evidence["hiddenOnlyIndistinguishable"])
        public = json.dumps(result.public_evidence).casefold()
        self.assertNotIn("objective", public)
        self.assertNotIn("proposal", public)
        normal_calls = [item for item in executor.calls if item[0].mode == "normal"]
        pre_cancelled = next(
            item for item in executor.calls if item[0].mode == "pre-cancelled"
        )
        self.assertEqual(len(normal_calls), 24)
        self.assertTrue(all(not was_set for _invocation, was_set in normal_calls))
        self.assertTrue(pre_cancelled[1])

    def test_mismatch_error_and_duplicate_request_id_cannot_false_green(self) -> None:
        unavailable = CoordinatorJobView(
            request_id="coordinator-forged",
            status="evidence-unavailable",
            reason="model-evidence-unavailable",
        )
        scenarios = (
            _Executor(
                self.expected,
                overrides={"wave-repeat-1:exact-single-selection:normal": unavailable},
            ),
            _Executor(
                self.expected,
                overrides={
                    "wave-repeat-1:exact-single-selection:normal": RuntimeError(
                        "failed"
                    )
                },
            ),
            _Executor(self.expected, duplicate_request_ids=True),
        )
        for executor in scenarios:
            with self.subTest(executor=type(executor).__name__):
                result = evaluate_coordinator_qualification(
                    executor=executor,
                    corpus=self.bound,
                    acceptance=self.acceptance,
                )
                self.assertFalse(result.public_evidence["qualified"])

    def test_complete_bundle_must_be_the_exact_domain_type(self) -> None:
        class _EqualToAnything:
            def __eq__(self, other):
                del other
                return True

        forged = CoordinatorJobView(
            request_id="coordinator-forged-bundle",
            status="complete",
            bundle=_EqualToAnything(),  # type: ignore[arg-type]
        )
        result = evaluate_coordinator_qualification(
            executor=_Executor(
                self.expected,
                overrides={"wave-repeat-1:exact-single-selection:normal": forged},
            ),
            corpus=self.bound,
            acceptance=self.acceptance,
        )
        self.assertFalse(result.public_evidence["qualified"])
        observation = next(
            item
            for item in result.observations
            if item.invocation.invocation_id
            == "wave-repeat-1:exact-single-selection:normal"
        )
        self.assertEqual(observation.failure_kind, "executor-error")

    def test_raw_and_compiler_only_corpora_cannot_execute(self) -> None:
        with self.assertRaisesRegex(TypeError, "Curator-lineage-bound"):
            evaluate_coordinator_qualification(
                executor=_Executor(self.expected),
                corpus=self.corpus,  # type: ignore[arg-type]
                acceptance=self.acceptance,
            )
        with self.assertRaisesRegex(TypeError, "Curator-lineage-bound"):
            evaluate_coordinator_qualification(
                executor=_Executor(self.expected),
                corpus=self.compiled,  # type: ignore[arg-type]
                acceptance=self.acceptance,
            )

    def test_compiler_and_lineage_drift_are_rejected(self) -> None:
        rendered, compiled = _render_and_compile(self.corpus)
        successor = compiled["successor"]
        changed = {
            **compiled,
            "successor": replace(successor, source_revision="forged-revision"),
        }
        with self.assertRaisesRegex(ValueError, "source revision"):
            bind_coordinator_compiled_corpus(self.corpus, rendered, changed)

        with self.assertRaisesRegex(ValueError, "request identities"):
            bind_coordinator_curator_lineage(
                self.compiled,
                {"atlas-security": "curator-request-atlas-security"},
            )
        request_ids = {
            key: f"curator-request-{key}" for key in self.compiled.proposal_seeds_by_key
        }
        request_ids["atlas-security"] = "bad identity"
        with self.assertRaisesRegex(ValueError, "request identity"):
            bind_coordinator_curator_lineage(self.compiled, request_ids)

    def test_ordered_selection_is_stable_across_runtime_tenants(self) -> None:
        observed: list[tuple[str, ...]] = []
        proposal_id_sets: list[set[str]] = []
        for tenant_id in ("coordinator-q-alpha", "coordinator-q-beta"):
            rendered, compiled = _render_and_compile(
                self.corpus,
                tenant_id=tenant_id,
            )
            compiler_bound = bind_coordinator_compiled_corpus(
                self.corpus,
                rendered,
                compiled,
            )
            bound = bind_coordinator_curator_lineage(
                compiler_bound,
                {
                    key: f"curator-request-{key}"
                    for key in compiler_bound.proposal_seeds_by_key
                },
            )
            bundle = bound.expected_views["ordered-multi-selection:normal"].bundle
            self.assertIsNotNone(bundle)
            assert bundle is not None
            observed.append(tuple(item.proposed_content for item in bundle.items))
            proposal_id_sets.append(
                {seed.proposal_id for seed in bound.proposal_seeds_by_key.values()}
            )
        self.assertEqual(
            observed,
            [
                (
                    "Nimbus release sequencing begins with security review.",
                    "Nimbus release sequencing places approver confirmation after "
                    "security review.",
                )
            ]
            * 2,
        )
        self.assertNotEqual(proposal_id_sets[0], proposal_id_sets[1])

    def test_wave_timeout_cancels_and_contains_workers(self) -> None:
        class _BlockingExecutor:
            def __call__(self, invocation, cancellation):
                cancellation.wait(1.0)
                expected = self_expected[invocation.expected_view_id]
                return CoordinatorJobView(
                    request_id=f"coordinator-{invocation.case_id}-{invocation.run_id}",
                    status=expected.status,
                    reason=expected.reason,
                    bundle=expected.bundle,
                )

        self_expected = self.expected
        with mock.patch(
            "yap_server.evaluation.coordinator_qualification._PRIMARY_WAVE_TIMEOUT_SECONDS",
            0.02,
        ):
            with self.assertRaisesRegex(TimeoutError, "wave exceeded"):
                evaluate_coordinator_qualification(
                    executor=_BlockingExecutor(),
                    corpus=self.bound,
                    acceptance=self.acceptance,
                )
        time.sleep(0.02)
        self.assertFalse(
            any(
                thread.name.startswith("coordinator-qualification")
                for thread in threading.enumerate()
            )
        )

    def test_acceptance_and_fixture_mutations_fail_closed(self) -> None:
        acceptance = json.loads(
            (SERVER_ROOT / "coordinator-acceptance.json").read_text(encoding="utf-8")
        )
        fixture = json.loads(
            (SERVER_ROOT / "coordinator-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        for changed in (
            {**acceptance, "invocationCount": 28},
            {**acceptance, "legacyThreshold": 1},
        ):
            with (
                self.subTest(acceptance=changed),
                tempfile.TemporaryDirectory() as temp,
            ):
                path = Path(temp) / "acceptance.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_coordinator_qualification_acceptance(path)

        cases = list(fixture["cases"])
        cases[0] = {**cases[0], "ownerId": cases[1]["ownerId"]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixture.json"
            path.write_text(json.dumps({**fixture, "cases": cases}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_coordinator_qualification_corpus(path)

        proposals = list(fixture["proposals"])
        proposals[0] = {**proposals[0], "proposalType": "relationship"}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixture.json"
            path.write_text(
                json.dumps({**fixture, "proposals": proposals}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "proposal identity"):
                load_coordinator_qualification_corpus(path)


def _render_and_compile(corpus, *, tenant_id="fresh-coordinator-tenant"):
    rendered = render_coordinator_qualification_generations(
        corpus,
        tenant_id=tenant_id,
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


def _compiled_corpus(corpus):
    rendered, compiled = _render_and_compile(corpus)
    return bind_coordinator_compiled_corpus(corpus, rendered, compiled)


def _authorization_hash(permission_hash: str, required_capability: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "permissionHash": permission_hash,
                "requiredCapability": required_capability,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
