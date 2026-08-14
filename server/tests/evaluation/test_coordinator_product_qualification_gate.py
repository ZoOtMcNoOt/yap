from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from yap_server.agents.coordinator import (
    CoordinatorProposalCandidate,
    CoordinatorProposalBundle,
    CoordinatorRequest,
)
from yap_server.agents.librarian import LibrarianEvidenceItem
from yap_server.evaluation import coordinator_product_qualification_gate as gate
from yap_server.evaluation.coordinator_qualification import CoordinatorExpectedView
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _bundle() -> CoordinatorProposalBundle:
    citation = LibrarianEvidenceItem(
        concept_id="coordinator-product-test",
        source_revision="source-revision",
        content_sha256="a" * 64,
        char_start=0,
        char_end=4,
        text="fact",
    )
    candidate = CoordinatorProposalCandidate.create(
        proposal_id="1" * 64,
        curator_request_id="curator-request",
        curator_submission_id="curator-submission",
        curator_request_sha256="2" * 64,
        curator_work_sha256="3" * 64,
        curator_evidence_sha256="4" * 64,
        generation_sha256="c" * 64,
        proposal_type="summary",
        proposed_content="A reviewed proposal.",
        inherited_permission_sha256="5" * 64,
        proposal_permission_hash="6" * 64,
        proposal_authorization_hash="7" * 64,
        citations=(citation,),
    )
    return CoordinatorProposalBundle.create(
        generation_sha256="c" * 64,
        evidence_sha256="b" * 64,
        items=(candidate,),
    )


def _request(index: int = 0) -> CoordinatorRequest:
    return CoordinatorRequest(
        objective=f"What is product fact {index}?",
        maximum_items=3,
        expected_generation_sha256="c" * 64,
    )


class CoordinatorProductQualificationGateTests(unittest.TestCase):
    def test_acceptance_and_candidate_inputs_cover_the_product_boundary(self) -> None:
        acceptance = gate.load_coordinator_product_acceptance(
            REPOSITORY_ROOT / "server/coordinator-product-acceptance.json"
        )

        self.assertEqual(acceptance.case_count, 8)
        self.assertEqual(acceptance.query_count, 10)
        self.assertEqual(acceptance.complete_count, 5)
        self.assertEqual(acceptance.unavailable_count, 4)
        self.assertEqual(acceptance.cancelled_count, 1)
        self.assertEqual(acceptance.maximum_normal_p95_milliseconds, 85_000)

        paths = gate._candidate_input_paths(REPOSITORY_ROOT)
        relative = {path.relative_to(REPOSITORY_ROOT).as_posix() for path in paths}
        required = {
            "server/coordinator-product-acceptance.json",
            "server/src/yap_server/agents/coordinator_bundle_service.py",
            "server/src/yap_server/agents/coordinator_product_runtime.py",
            "server/src/yap_server/api/coordinator_bundle_requests.py",
            "server/src/yap_server/evaluation/coordinator_product_qualification_gate.py",
            "server/tests/evaluation/test_coordinator_product_qualification_gate.py",
            "desktop/src/coordinator.ts",
            "desktop/src/components/coordinator/coordinator-bundle-composer.tsx",
            "desktop/src/components/coordinator/coordinator-bundle-result.tsx",
            "desktop/src/components/coordinator/use-coordinator-bundle.ts",
            "desktop/src-tauri/src/coordinator_bundle.rs",
            "desktop/src-tauri/src/server_connector/coordinator.rs",
            "desktop/tests/unit/coordinator-product.test.tsx",
            "desktop/tests/wdio/smoke.spec.js",
            ".github/workflows/ci.yml",
        }
        self.assertTrue(required <= relative)
        self.assertEqual(len(relative), len(paths))
        self.assertTrue(
            all(0 < path.stat().st_size <= 16 * 1024 * 1024 for path in paths)
        )

    def test_product_view_parser_is_strict_and_hash_bound(self) -> None:
        bundle = _bundle()
        request_id = "coordinator-bundle-" + "1" * 32
        complete = {
            "schemaVersion": 1,
            "requestId": request_id,
            "status": "complete",
            "proposalBundle": bundle.to_wire(),
        }

        parsed = gate._parse_product_view(complete)

        self.assertEqual(parsed.request_id, request_id)
        self.assertEqual(parsed.bundle, gate._parse_bundle(bundle.to_wire()))
        with self.assertRaisesRegex(ValueError, "fields"):
            gate._parse_product_view(dict(complete, canonical=False))
        forged = bundle.to_wire()
        forged["bundleSha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "bundle hash"):
            gate._parse_product_view(dict(complete, proposalBundle=forged))

    def test_active_and_unavailable_views_carry_no_bundle(self) -> None:
        request_id = "coordinator-bundle-" + "2" * 32
        active = gate._parse_product_view(
            {
                "schemaVersion": 1,
                "requestId": request_id,
                "status": "running",
            }
        )
        unavailable = gate._parse_product_view(
            {
                "schemaVersion": 1,
                "requestId": request_id,
                "status": "evidence-unavailable",
                "reason": "empty-result",
            }
        )

        self.assertIsNone(active.bundle)
        self.assertIsNone(unavailable.bundle)
        with self.assertRaisesRegex(ValueError, "fields"):
            gate._parse_product_view(
                {
                    "schemaVersion": 1,
                    "requestId": request_id,
                    "status": "cancelled",
                    "reason": "client-cancelled",
                    "proposalBundle": _bundle().to_wire(),
                }
            )

    def test_http_authentication_covers_post_get_and_delete(self) -> None:
        def response(_base_url, path, *, method, token, body=None):
            del body
            if path == "/v1/health":
                return 200, {
                    "auth": "required",
                    "capabilities": {"coordinatorBundles": True},
                }
            self.assertIn(method, {"POST", "GET", "DELETE"})
            if token is None:
                return 401, {"code": "AUTHENTICATION_REQUIRED"}
            return 401, {"code": "INVALID_ACCESS_TOKEN"}

        with mock.patch.object(gate, "_http_json", side_effect=response) as call:
            checks = gate._probe_http_authentication(
                "http://127.0.0.1:1234",
                request=_request(),
            )

        self.assertEqual(call.call_count, 7)
        self.assertTrue(all(checks.values()))

    def test_foreign_owner_cannot_read_or_cancel(self) -> None:
        with mock.patch.object(
            gate,
            "_http_json",
            side_effect=(
                (404, {"code": "COORDINATOR_BUNDLE_NOT_FOUND"}),
                (404, {"code": "COORDINATOR_BUNDLE_NOT_FOUND"}),
            ),
        ) as call:
            exact = gate._foreign_owner_isolation_exact(
                "http://127.0.0.1:1234",
                "coordinator-bundle-" + "3" * 32,
                foreign_token="foreign-token",
            )

        self.assertTrue(exact)
        self.assertEqual(
            [item.kwargs["method"] for item in call.call_args_list],
            ["GET", "DELETE"],
        )

    def test_product_evidence_counts_and_hidden_shape_fail_closed(self) -> None:
        acceptance = gate.load_coordinator_product_acceptance(
            REPOSITORY_ROOT / "server/coordinator-product-acceptance.json"
        )
        bundle = _bundle()
        product_bundle = gate._parse_bundle(bundle.to_wire())
        observations: list[gate.CoordinatorProductObservation] = []
        labels = (
            "exact-single-selection",
            "ordered-multi-selection",
            "instruction-as-data-selection",
            "release-summary-selection",
            "relationship-review-selection",
            "unsupported-objective-unavailable",
            "hidden-only-unavailable",
            "absent-unavailable",
        )
        for index, label in enumerate(labels):
            expected = (
                CoordinatorExpectedView("complete", None, bundle)
                if index < 5
                else CoordinatorExpectedView(
                    "evidence-unavailable",
                    "empty-result"
                    if label in {"hidden-only-unavailable", "absent-unavailable"}
                    else "model-evidence-unavailable",
                    None,
                )
            )
            view = gate.CoordinatorProductView(
                "coordinator-bundle-" + f"{index:032x}",
                expected.status,
                product_bundle if expected.bundle is not None else None,
                expected.reason,
            )
            observations.append(
                gate.CoordinatorProductObservation(
                    label,
                    f"owner-{index}",
                    _request(index),
                    expected,
                    view.request_id,
                    f"internal-{index}",
                    view,
                    10,
                    True,
                    True,
                    True,
                    True,
                    None,
                )
            )
        empty = CoordinatorExpectedView("evidence-unavailable", "empty-result", None)
        hidden_view = gate.CoordinatorProductView(
            "coordinator-bundle-" + "a" * 32,
            empty.status,
            None,
            empty.reason,
        )
        observations.append(
            gate.CoordinatorProductObservation(
                "cross-owner-hidden",
                "cross-owner",
                _request(8),
                empty,
                hidden_view.request_id,
                "internal-hidden",
                hidden_view,
                10,
                True,
                True,
                True,
                False,
                None,
            )
        )
        cancelled = CoordinatorExpectedView("cancelled", "client-cancelled", None)
        cancelled_view = gate.CoordinatorProductView(
            "coordinator-bundle-" + "b" * 32,
            cancelled.status,
            None,
            cancelled.reason,
        )
        observations.append(
            gate.CoordinatorProductObservation(
                "http-cancelled",
                "owner-0",
                _request(),
                cancelled,
                cancelled_view.request_id,
                "internal-cancelled",
                cancelled_view,
                10,
                True,
                True,
                True,
                False,
                None,
            )
        )

        public = gate._evaluate_product_observations(
            observations,
            acceptance=acceptance,
            authentication_probe={"exact": True},
            database_state_exact=True,
            worker_containment_met=True,
        )
        self.assertTrue(public["qualified"])
        self.assertEqual(public["exactTerminalCount"], 10)

        forged = list(observations)
        forged[0] = replace(forged[0], exact_match=False)
        self.assertFalse(
            gate._evaluate_product_observations(
                forged,
                acceptance=acceptance,
                authentication_probe={"exact": True},
                database_state_exact=True,
                worker_containment_met=True,
            )["qualified"]
        )

    def test_cancellation_model_requires_the_product_event(self) -> None:
        model = gate._CancellationModel()
        cancellation = threading.Event()
        failure: list[BaseException] = []

        def run() -> None:
            try:
                model.select(
                    mock.sentinel.request,
                    mock.sentinel.evidence,
                    cancellation=cancellation,
                )
            except BaseException as error:
                failure.append(error)

        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(model.started.wait(1.0))
        cancellation.set()
        worker.join(1.0)

        self.assertFalse(worker.is_alive())
        self.assertTrue(model.cancelled.is_set())
        self.assertEqual(len(failure), 1)
        self.assertIsInstance(failure[0], KnowledgeToolCancelled)

    def test_private_destination_is_create_once_and_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            outside = Path(value).resolve() / "receipt.json"
            self.assertEqual(
                gate._new_private_evidence_destination(
                    outside,
                    repository_root=REPOSITORY_ROOT,
                ),
                outside,
            )
            outside.write_text("reserved", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "new and outside"):
                gate._new_private_evidence_destination(
                    outside,
                    repository_root=REPOSITORY_ROOT,
                )

    def test_gate_owns_two_restarts_http_runtimes_and_private_receipt(self) -> None:
        acceptance = gate.load_coordinator_product_acceptance(
            REPOSITORY_ROOT / "server/coordinator-product-acceptance.json"
        )
        candidate = mock.Mock()
        database = mock.Mock()
        database.start.return_value = SimpleNamespace(
            dsn="postgresql://private-initial",
            process_id=10,
        )
        database.stop.return_value = {"contained": True}
        first_restart = SimpleNamespace(
            dsn="postgresql://private-first",
            process_id=11,
        )
        second_restart = SimpleNamespace(
            dsn="postgresql://private-second",
            process_id=12,
        )
        normal_runtime = mock.Mock()
        cancel_runtime = mock.Mock()
        invocations = tuple(
            SimpleNamespace(
                owner_id=f"owner-{index}",
                objective=f"Question {index}?",
                maximum_items=3,
                expected_generation_sha256="a" * 64,
            )
            for index in range(8)
        )
        observations = tuple(object() for _ in range(10))
        authentication = {"exact": True}
        profile = SimpleNamespace(
            maximum_sequences=8,
            batch_invariant=True,
            launch_arguments=(),
            candidate_id="candidate",
            expected_model="model",
            model_revision="b" * 40,
            runtime_id="runtime",
            profile_sha256="c" * 64,
            candidate_lock_sha256="d" * 64,
        )
        semantic_acceptance = SimpleNamespace(
            maximum_normal_p95_milliseconds=85_000,
            plan_sha256="e" * 64,
        )
        corpus = SimpleNamespace(
            cases=tuple(object() for _ in range(8)),
            corpus_sha256="f" * 64,
        )
        compiled = SimpleNamespace()
        initialized = SimpleNamespace(corpus=compiled)
        bound = SimpleNamespace()
        curator_request_ids = {
            f"proposal-{index}": f"curator-{index}" for index in range(8)
        }
        capacity = {
            "admittedOwnerCount": 8,
            "expectedCapacityObserved": True,
            "overflowOwnerQueued": True,
            "contained": True,
            "providerIdentityUnchanged": True,
            "brokerIdentityUnchanged": True,
        }
        public = acceptance.expected_public_evidence()
        public["qualified"] = True
        written = mock.Mock()

        with tempfile.TemporaryDirectory() as value:
            private_root = Path(value).resolve()
            destination = private_root / "receipt.json"
            patches = {
                "_candidate_input_paths": {"return_value": ()},
                "admit_checked_candidate": {"return_value": candidate},
                "_require_private_arm64_host": {},
                "load_coordinator_product_acceptance": {"return_value": acceptance},
                "load_coordinator_qualification_acceptance": {
                    "return_value": semantic_acceptance
                },
                "load_coordinator_qualification_corpus": {"return_value": corpus},
                "load_coordinator_service_profile": {"return_value": profile},
                "_require_full_complex_profile": {},
                "build_checked_admission_broker": {"return_value": "1" * 64},
                "read_service_state": {"return_value": {"processGeneration": 7}},
                "validate_state_identity": {},
                "probe_exact_service": {},
                "observe_admission_broker": {"return_value": {"processId": 8}},
                "probe_agent_admission_broker_capacity": {"return_value": capacity},
                "load_knowledge_database_runtime_lock": {
                    "return_value": SimpleNamespace(lock_sha256="2" * 64)
                },
                "OwnedPostgresKnowledgeRuntime": {"return_value": database},
                "_initialize_coordinator_knowledge": {"return_value": initialized},
                "_restart_database": {"side_effect": (first_restart, second_restart)},
                "_verify_initialized_knowledge": {},
                "_write_new_private_text": {},
                "_publish_curator_proposals": {"return_value": curator_request_ids},
                "bind_coordinator_curator_lineage": {"return_value": bound},
                "_normal_invocations": {"return_value": invocations},
                "_build_product_runtime": {"return_value": normal_runtime},
                "_build_cancellation_runtime": {"return_value": cancel_runtime},
                "_start_http_server": {
                    "side_effect": (
                        (object(), mock.Mock(), "http://127.0.0.1:1"),
                        (object(), mock.Mock(), "http://127.0.0.1:2"),
                    )
                },
                "_stop_http_server": {},
                "_probe_http_authentication": {"return_value": authentication},
                "_run_normal_product_wave": {"return_value": observations[:8]},
                "_run_cross_owner_control": {"return_value": observations[8]},
                "_run_cancellation_control": {"return_value": observations[9]},
                "_provider_generation": {"return_value": 7},
                "_bind_internal_request_ids": {"return_value": observations},
                "_verify_product_database_state": {
                    "return_value": {"coordinatorResultAuditExact": True}
                },
                "_require_exact_teardown": {},
                "_evaluate_product_observations": {"return_value": public},
                "bind_checked_candidate_evidence": {
                    "side_effect": lambda evidence, _candidate: {
                        **evidence,
                        "candidate": {"checkedHead": "3" * 40},
                        "evidenceSha256": "4" * 64,
                    }
                },
                "_private_observations": {"return_value": [{"exactMatch": True}]},
                "write_new_private_json_evidence": {"new": written},
            }
            with ExitStack() as stack:
                active = {
                    name: stack.enter_context(mock.patch.object(gate, name, **options))
                    for name, options in patches.items()
                }
                receipt = gate.run_coordinator_product_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="3" * 40,
                    evidence_destination=destination,
                    admission_socket_path=private_root / "admission.sock",
                    rapid_state_path=private_root / "rapid.json",
                    complex_state_path=private_root / "complex.json",
                )

        self.assertEqual(
            receipt["outcome"],
            "coordinator-authenticated-product-server-boundary-qualified",
        )
        self.assertEqual(active["_restart_database"].call_count, 2)
        self.assertEqual(active["_start_http_server"].call_count, 2)
        self.assertEqual(active["_stop_http_server"].call_count, 2)
        normal_runtime.close.assert_called_once_with()
        cancel_runtime.close.assert_called_once_with()
        database.stop.assert_called_once_with(timeout_seconds=15)
        candidate.verify_unchanged.assert_called_once()
        written.assert_called_once()
        private_payload = written.call_args.args[1]
        self.assertEqual(
            private_payload["privacyScope"],
            "private-coordinator-product-qualification",
        )
        serialized = json.dumps(private_payload)
        self.assertNotIn("postgresql://private", serialized)
        self.assertNotIn("Bearer ", serialized)


if __name__ == "__main__":
    unittest.main()
