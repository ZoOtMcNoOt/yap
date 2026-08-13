from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from contextlib import ExitStack
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

from yap_server.agents.librarian import LibrarianEvidenceItem, LibrarianEvidencePack
from yap_server.evaluation import librarian_product_qualification_gate as gate
from yap_server.evaluation.librarian_qualification import (
    build_librarian_qualification_invocations,
    compile_librarian_expected_evidence,
    load_librarian_qualification_corpus,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _pack() -> LibrarianEvidencePack:
    text = "The reviewed Atlas handoff requires two reviewers."
    return LibrarianEvidencePack.create(
        generation_sha256="a" * 64,
        permission_hash="b" * 64,
        authorization_hash="c" * 64,
        items=(
            LibrarianEvidenceItem(
                concept_id="meetings/atlas",
                source_revision="revision-1",
                content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                char_start=0,
                char_end=len(text),
                text=text,
            ),
        ),
        output_budget_exhausted=False,
    )


class LibrarianProductQualificationGateTests(unittest.TestCase):
    def test_acceptance_is_exact_and_candidate_inputs_cover_the_product(self) -> None:
        acceptance = gate.load_librarian_product_acceptance(
            REPOSITORY_ROOT / "server/librarian-product-acceptance.json"
        )

        self.assertEqual(acceptance.case_count, 8)
        self.assertEqual(acceptance.query_count, 10)
        self.assertEqual(acceptance.exact_terminal_count, 10)
        self.assertEqual(acceptance.maximum_normal_p95_milliseconds, 16_000)

        relative = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in gate._candidate_input_paths(REPOSITORY_ROOT)
        }
        required = {
            "server/librarian-product-acceptance.json",
            "server/src/yap_server/agents/librarian_query_service.py",
            "server/src/yap_server/agents/librarian_runtime.py",
            "server/src/yap_server/api/librarian_query_requests.py",
            "server/src/yap_server/evaluation/librarian_product_qualification_gate.py",
            "server/tests/evaluation/test_librarian_product_qualification_gate.py",
            "desktop/src/librarian.ts",
            "desktop/src/components/panels/librarian-panel.tsx",
            "desktop/src-tauri/src/librarian_query.rs",
            "desktop/src-tauri/src/server_connector/librarian.rs",
            "desktop/tests/unit/librarian-product.test.tsx",
            "desktop/tests/wdio/smoke.spec.js",
            ".github/workflows/ci.yml",
        }
        self.assertTrue(required <= relative)
        self.assertEqual(
            len(relative), len(gate._candidate_input_paths(REPOSITORY_ROOT))
        )

    def test_product_view_parser_requires_the_exact_hash_bound_wire(self) -> None:
        pack = _pack()
        request_id = "librarian-query-" + "1" * 32
        complete = {
            "schemaVersion": 1,
            "requestId": request_id,
            "status": "complete",
            "evidencePack": pack.to_wire(),
        }

        parsed = gate._parse_product_view(complete)

        self.assertEqual(parsed.request_id, request_id)
        self.assertEqual(parsed.evidence, pack)
        self.assertIsNone(parsed.reason)

        forged = json.loads(json.dumps(complete))
        forged["evidencePack"]["evidenceSha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "evidence digest"):
            gate._parse_product_view(forged)

        broader = json.loads(json.dumps(complete))
        broader["rawScore"] = 0.99
        with self.assertRaisesRegex(ValueError, "view fields"):
            gate._parse_product_view(broader)

        missing_pack = {
            "schemaVersion": 1,
            "requestId": request_id,
            "status": "complete",
        }
        with self.assertRaisesRegex(ValueError, "view fields"):
            gate._parse_product_view(missing_pack)

    def test_unavailable_and_active_views_cannot_carry_evidence(self) -> None:
        request_id = "librarian-query-" + "2" * 32
        unavailable = gate._parse_product_view(
            {
                "schemaVersion": 1,
                "requestId": request_id,
                "status": "evidence-unavailable",
                "reason": "empty-result",
            }
        )
        self.assertEqual(
            unavailable.terminal_shape(), ("evidence-unavailable", "empty-result")
        )

        with self.assertRaisesRegex(ValueError, "view fields"):
            gate._parse_product_view(
                {
                    "schemaVersion": 1,
                    "requestId": request_id,
                    "status": "running",
                    "evidencePack": _pack().to_wire(),
                }
            )

    def test_http_authentication_covers_post_get_and_delete(self) -> None:
        def response(
            _base_url: str,
            path: str,
            *,
            method: str,
            token: str | None,
            body=None,
        ):
            del body
            if path == "/v1/health":
                return 200, {
                    "auth": "required",
                    "capabilities": {"librarianQueries": True},
                }
            self.assertIn(method, {"POST", "GET", "DELETE"})
            if token is None:
                return 401, {"code": "AUTHENTICATION_REQUIRED"}
            return 401, {"code": "INVALID_ACCESS_TOKEN"}

        with mock.patch.object(gate, "_http_json", side_effect=response) as request:
            checks = gate._probe_http_authentication("http://127.0.0.1:1234")

        self.assertEqual(request.call_count, 7)
        self.assertTrue(all(checks.values()))
        self.assertEqual(
            set(checks),
            {
                "healthCapabilityExact",
                "missingPostBearerRejected",
                "invalidPostBearerRejected",
                "missingGetBearerRejected",
                "invalidGetBearerRejected",
                "missingDeleteBearerRejected",
                "invalidDeleteBearerRejected",
            },
        )

    def test_foreign_owner_cannot_read_or_cancel_a_product_query(self) -> None:
        with mock.patch.object(
            gate,
            "_http_json",
            side_effect=(
                (404, {"code": "LIBRARIAN_QUERY_NOT_FOUND"}),
                (404, {"code": "LIBRARIAN_QUERY_NOT_FOUND"}),
            ),
        ) as request:
            exact = gate._foreign_owner_isolation_exact(
                "http://127.0.0.1:1234",
                "librarian-query-" + "1" * 32,
                foreign_token="foreign-token",
            )

        self.assertTrue(exact)
        self.assertEqual(
            [call.kwargs["method"] for call in request.call_args_list],
            ["GET", "DELETE"],
        )

    def test_private_destination_is_create_once_and_outside_the_repository(
        self,
    ) -> None:
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

        with self.assertRaisesRegex(ValueError, "new and outside"):
            gate._new_private_evidence_destination(
                REPOSITORY_ROOT / "private-product-receipt.json",
                repository_root=REPOSITORY_ROOT,
            )

    def test_public_result_derives_from_all_observed_http_terminals(self) -> None:
        acceptance = gate.load_librarian_product_acceptance(
            REPOSITORY_ROOT / "server/librarian-product-acceptance.json"
        )
        corpus = load_librarian_qualification_corpus(
            REPOSITORY_ROOT / "server/librarian-workload-fixtures.json"
        )
        expected = compile_librarian_expected_evidence(corpus)
        invocations = build_librarian_qualification_invocations(corpus)
        observations = []
        for index, invocation in enumerate(invocations):
            product_request_id = f"librarian-query-{index:032x}"
            view = gate._expected_product_view(
                expected[invocation.invocation_id],
                request_id=product_request_id,
            )
            observations.append(
                gate.LibrarianProductObservation(
                    invocation=invocation,
                    product_request_id=product_request_id,
                    internal_request_id=f"agent-{index:032x}",
                    expected=expected[invocation.invocation_id],
                    observed=view,
                    duration_milliseconds=10,
                    exact_match=True,
                    authentication_header_exact=True,
                    owner_isolation_exact=True,
                    failure_kind=None,
                )
            )

        result = gate._evaluate_product_observations(
            observations,
            acceptance=acceptance,
            authentication_probe={
                "healthCapabilityExact": True,
                "missingPostBearerRejected": True,
                "invalidPostBearerRejected": True,
                "missingGetBearerRejected": True,
                "invalidGetBearerRejected": True,
                "missingDeleteBearerRejected": True,
                "invalidDeleteBearerRejected": True,
            },
            worker_containment_met=True,
        )

        self.assertTrue(result["qualified"])
        self.assertEqual(result["exactTerminalCount"], 10)
        self.assertEqual(result["uniqueProductRequestIdCount"], 10)

        observations[0] = replace(
            observations[0],
            exact_match=False,
            failure_kind="RuntimeError",
        )
        failed = gate._evaluate_product_observations(
            observations,
            acceptance=acceptance,
            authentication_probe={
                "healthCapabilityExact": True,
                "missingPostBearerRejected": True,
                "invalidPostBearerRejected": True,
                "missingGetBearerRejected": True,
                "invalidGetBearerRejected": True,
                "missingDeleteBearerRejected": True,
                "invalidDeleteBearerRejected": True,
            },
            worker_containment_met=True,
        )
        self.assertFalse(failed["qualified"])
        self.assertEqual(failed["exactTerminalCount"], 9)

    def test_gate_owns_two_restarts_http_runtime_teardown_and_private_receipt(
        self,
    ) -> None:
        acceptance = gate.load_librarian_product_acceptance(
            REPOSITORY_ROOT / "server/librarian-product-acceptance.json"
        )
        corpus = load_librarian_qualification_corpus(
            REPOSITORY_ROOT / "server/librarian-workload-fixtures.json"
        )
        candidate = mock.Mock()
        database = mock.Mock()
        started = SimpleNamespace(dsn="postgresql://private", process_id=10)
        first_restart = SimpleNamespace(dsn="postgresql://private", process_id=11)
        second_restart = SimpleNamespace(dsn="postgresql://private", process_id=12)
        database.start.return_value = started
        database.stop.return_value = {"contained": True}
        runtime = mock.Mock()
        runtime.service = object()
        initialized = SimpleNamespace(bound=SimpleNamespace(corpus=corpus))
        product_observations = (object(),)
        authentication_probe = {
            "healthCapabilityExact": True,
            "missingPostBearerRejected": True,
            "invalidPostBearerRejected": True,
            "missingGetBearerRejected": True,
            "invalidGetBearerRejected": True,
            "missingDeleteBearerRejected": True,
            "invalidDeleteBearerRejected": True,
        }
        capacity = {
            "admittedOwnerCount": 1,
            "expectedCapacityObserved": True,
            "overflowOwnerQueued": True,
            "contained": True,
            "brokerIdentityUnchanged": True,
        }
        public = acceptance.expected_public_evidence()
        public["qualified"] = True
        written = mock.Mock()

        with tempfile.TemporaryDirectory() as value:
            destination = Path(value).resolve() / "receipt.json"
            private_root = Path(value).resolve()
            with ExitStack() as stack:
                patches = {
                    "_candidate_input_paths": {"return_value": ()},
                    "admit_checked_candidate": {"return_value": candidate},
                    "_require_private_arm64_host": {},
                    "load_librarian_product_acceptance": {"return_value": acceptance},
                    "load_librarian_qualification_corpus": {"return_value": corpus},
                    "load_rapid_agent_vllm_service_profile": {
                        "return_value": SimpleNamespace(
                            candidate_lock_sha256="a" * 64,
                            profile_sha256="b" * 64,
                        )
                    },
                    "load_complex_agent_vllm_service_profile": {
                        "return_value": SimpleNamespace(
                            candidate_lock_sha256="a" * 64,
                            profile_sha256="c" * 64,
                        )
                    },
                    "build_checked_admission_broker": {"return_value": "d" * 64},
                    "_probe_server_io_capacity": {"return_value": capacity},
                    "load_knowledge_database_runtime_lock": {
                        "return_value": SimpleNamespace(lock_sha256="e" * 64)
                    },
                    "OwnedPostgresKnowledgeRuntime": {"return_value": database},
                    "_initialize_librarian_knowledge": {"return_value": initialized},
                    "_restart_database": {
                        "side_effect": (first_restart, second_restart)
                    },
                    "build_librarian_runtime": {"return_value": runtime},
                    "_start_http_server": {
                        "return_value": (
                            object(),
                            mock.Mock(),
                            "http://127.0.0.1:1234",
                        )
                    },
                    "_stop_http_server": {},
                    "_run_product_workload": {
                        "return_value": (
                            product_observations,
                            authentication_probe,
                        )
                    },
                    "_bind_internal_request_ids": {
                        "return_value": (product_observations, object())
                    },
                    "_verify_product_database_state": {
                        "return_value": {"librarianResultAuditExact": True}
                    },
                    "_require_exact_teardown": {},
                    "_evaluate_product_observations": {"return_value": public},
                    "bind_checked_candidate_evidence": {
                        "side_effect": lambda evidence, _candidate: {
                            **evidence,
                            "candidate": {"checkedHead": "f" * 40},
                            "evidenceSha256": "0" * 64,
                        }
                    },
                    "_private_observations": {"return_value": [{"exactMatch": True}]},
                    "write_new_private_json_evidence": {"new": written},
                }
                active = {
                    name: stack.enter_context(mock.patch.object(gate, name, **options))
                    for name, options in patches.items()
                }
                receipt = gate.run_librarian_product_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="f" * 40,
                    evidence_destination=destination,
                    admission_socket_path=private_root / "admission.sock",
                    rapid_state_path=private_root / "rapid.json",
                    complex_state_path=private_root / "complex.json",
                )

        self.assertEqual(
            receipt["outcome"],
            "librarian-authenticated-product-server-boundary-qualified",
        )
        self.assertEqual(active["_restart_database"].call_count, 2)
        database.stop.assert_called_once_with(timeout_seconds=15)
        active["_stop_http_server"].assert_called_once()
        runtime.close.assert_called_once()
        candidate.verify_unchanged.assert_called_once()
        written.assert_called_once()
        private_payload = written.call_args.args[1]
        self.assertEqual(
            private_payload["privacyScope"],
            "private-librarian-product-qualification",
        )
        serialized_private = json.dumps(private_payload)
        self.assertNotIn("postgresql://private", serialized_private)
        self.assertNotIn("Bearer ", serialized_private)


if __name__ == "__main__":
    unittest.main()
