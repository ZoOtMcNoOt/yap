from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from yap_server.agents.student import StudentEvidenceItem
from yap_server.agents.student_model import StudentQuestion, StudentQuestionSupport
from yap_server.evaluation import student_product_qualification_gate as gate


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _question() -> StudentQuestion:
    text = "The reviewed Atlas lesson is crash containment."
    evidence = StudentEvidenceItem(
        concept_id="meetings/atlas",
        source_revision="a" * 64,
        content_sha256="b" * 64,
        char_start=0,
        char_end=len(text),
        text=text,
    )
    return StudentQuestion(
        source_subject="crash containment",
        question="What should you remember about crash containment?",
        supports=(
            StudentQuestionSupport(evidence=evidence, quote="crash containment"),
        ),
    )


def _complete_wire(request_id: str) -> dict[str, object]:
    question = _question()
    return {
        "schemaVersion": 1,
        "requestId": request_id,
        "status": "complete",
        "conversationConceptId": "meetings/atlas",
        "generationSha256": "c" * 64,
        "evidenceSha256": "d" * 64,
        "questions": [question.to_wire()],
        "outputBudgetExhausted": False,
    }


class StudentProductQualificationGateTests(unittest.TestCase):
    def test_acceptance_and_candidate_inputs_are_exact(self) -> None:
        acceptance = gate.load_student_product_acceptance(
            REPOSITORY_ROOT / "server/student-product-acceptance.json"
        )

        self.assertEqual(acceptance.case_count, 8)
        self.assertEqual(acceptance.query_count, 11)
        self.assertEqual(acceptance.complete_count, 8)
        self.assertEqual(acceptance.unavailable_count, 2)
        self.assertEqual(acceptance.cancelled_count, 1)
        self.assertEqual(acceptance.maximum_normal_p95_milliseconds, 31_000)

        paths = gate._candidate_input_paths(REPOSITORY_ROOT)
        relative = {path.relative_to(REPOSITORY_ROOT).as_posix() for path in paths}
        required = {
            "server/student-product-acceptance.json",
            "server/src/yap_server/agents/student_question_service.py",
            "server/src/yap_server/agents/student_product_runtime.py",
            "server/src/yap_server/api/student_question_requests.py",
            "server/src/yap_server/evaluation/student_product_qualification_gate.py",
            "server/tests/evaluation/test_student_product_qualification_gate.py",
            "server/tests/jobs/test_runtime.py",
            "desktop/src/student.ts",
            "desktop/src/components/student/use-student-question.ts",
            "desktop/src-tauri/src/student_question.rs",
            "desktop/src-tauri/src/server_connector/student.rs",
            "desktop/tests/unit/student-product.test.tsx",
            ".github/workflows/ci.yml",
        }
        self.assertTrue(required <= relative)
        self.assertEqual(len(paths), len(relative))
        self.assertTrue(
            all(0 < path.stat().st_size <= 16 * 1024 * 1024 for path in paths)
        )

    def test_product_view_parser_reconstructs_and_validates_exact_questions(
        self,
    ) -> None:
        request_id = "student-question-" + "1" * 32
        expected_evidence = (_question().supports[0].evidence,)
        parsed = gate._parse_product_view(
            _complete_wire(request_id),
            expected_evidence=tuple(
                gate.StudentExpectedEvidence(
                    item.concept_id,
                    item.source_revision,
                    item.content_sha256,
                    item.char_start,
                    item.char_end,
                    item.text,
                )
                for item in expected_evidence
            ),
            expected_evidence_sha256="d" * 64,
        )

        self.assertEqual(parsed.request_id, request_id)
        self.assertEqual(parsed.questions, (_question(),))
        self.assertEqual(parsed.status, "complete")

        broader = _complete_wire(request_id)
        broader["score"] = 1.0
        with self.assertRaisesRegex(ValueError, "fields"):
            gate._parse_product_view(
                broader,
                expected_evidence=tuple(
                    gate.StudentExpectedEvidence(
                        item.concept_id,
                        item.source_revision,
                        item.content_sha256,
                        item.char_start,
                        item.char_end,
                        item.text,
                    )
                    for item in expected_evidence
                ),
                expected_evidence_sha256="d" * 64,
            )

        forged = json.loads(json.dumps(_complete_wire(request_id)))
        forged["questions"][0]["sourceSupports"][0]["supportCharEnd"] += 1
        with self.assertRaisesRegex(ValueError, "support"):
            gate._parse_product_view(
                forged,
                expected_evidence=tuple(
                    gate.StudentExpectedEvidence(
                        item.concept_id,
                        item.source_revision,
                        item.content_sha256,
                        item.char_start,
                        item.char_end,
                        item.text,
                    )
                    for item in expected_evidence
                ),
                expected_evidence_sha256="d" * 64,
            )

        forged_evidence = _complete_wire(request_id)
        forged_evidence["evidenceSha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "evidence identity"):
            gate._parse_product_view(
                forged_evidence,
                expected_evidence=tuple(
                    gate.StudentExpectedEvidence(
                        item.concept_id,
                        item.source_revision,
                        item.content_sha256,
                        item.char_start,
                        item.char_end,
                        item.text,
                    )
                    for item in expected_evidence
                ),
                expected_evidence_sha256="d" * 64,
            )

    def test_unavailable_and_active_views_cannot_carry_questions(self) -> None:
        request_id = "student-question-" + "2" * 32
        unavailable = gate._parse_product_view(
            {
                "schemaVersion": 1,
                "requestId": request_id,
                "status": "evidence-unavailable",
                "conversationConceptId": "meetings/hidden",
                "generationSha256": "c" * 64,
                "evidenceSha256": "d" * 64,
                "questions": [],
                "outputBudgetExhausted": False,
                "reason": "evidence-unavailable",
            }
        )
        self.assertEqual(
            unavailable.public_terminal_shape(),
            ("evidence-unavailable", "evidence-unavailable", 0, False),
        )

        running = {
            "schemaVersion": 1,
            "requestId": request_id,
            "status": "running",
            "conversationConceptId": "meetings/hidden",
            "generationSha256": "c" * 64,
            "questions": [_question().to_wire()],
            "outputBudgetExhausted": False,
        }
        with self.assertRaisesRegex(ValueError, "active"):
            gate._parse_product_view(
                running,
                expected_evidence=(
                    gate.StudentExpectedEvidence(
                        _question().supports[0].evidence.concept_id,
                        _question().supports[0].evidence.source_revision,
                        _question().supports[0].evidence.content_sha256,
                        _question().supports[0].evidence.char_start,
                        _question().supports[0].evidence.char_end,
                        _question().supports[0].evidence.text,
                    ),
                ),
            )

    def test_terminal_wait_defers_expected_evidence_binding_until_terminal(
        self,
    ) -> None:
        request_id = "student-question-" + "3" * 32
        active = {
            "schemaVersion": 1,
            "requestId": request_id,
            "status": "running",
            "conversationConceptId": "meetings/atlas",
            "generationSha256": "c" * 64,
            "questions": [],
            "outputBudgetExhausted": False,
        }
        expected_evidence = tuple(
            gate.StudentExpectedEvidence(
                item.concept_id,
                item.source_revision,
                item.content_sha256,
                item.char_start,
                item.char_end,
                item.text,
            )
            for item in (_question().supports[0].evidence,)
        )
        with mock.patch.object(
            gate,
            "_http_json",
            side_effect=[
                (200, active),
                (200, _complete_wire(request_id)),
            ],
        ):
            observed = gate._wait_for_terminal(
                "http://127.0.0.1:1",
                request_id,
                token="token",
                deadline=gate.time.monotonic() + 1.0,
                expected_evidence=expected_evidence,
                expected_evidence_sha256="d" * 64,
            )

        self.assertEqual(observed.status, "complete")
        self.assertEqual(observed.evidence_sha256, "d" * 64)

    def test_expected_product_evidence_binds_compiled_permission_authority(
        self,
    ) -> None:
        tenant_id = "student-product-tenant"
        cases = (
            SimpleNamespace(
                case_id="atlas",
                concept_id="meetings/atlas",
                owner_id="owner-atlas",
                body="Atlas lesson.",
            ),
            SimpleNamespace(
                case_id="cedar",
                concept_id="meetings/cedar",
                owner_id="owner-cedar",
                body="Cedar lesson.",
            ),
        )
        generation = SimpleNamespace(
            tenant_id=tenant_id,
            generation_sha256="a" * 64,
            source_revision="b" * 64,
            concepts=(
                SimpleNamespace(
                    concept_id="meetings/atlas",
                    permission_path_prefix="meetings/atlas/",
                    content_sha256="c" * 64,
                ),
                SimpleNamespace(
                    concept_id="meetings/cedar",
                    permission_path_prefix="meetings/cedar/",
                    content_sha256="d" * 64,
                ),
            ),
            chunks=(
                SimpleNamespace(
                    chunk_id="1" * 64,
                    concept_id="meetings/atlas",
                    content_sha256="c" * 64,
                    char_start=0,
                    char_end=len("Atlas lesson."),
                    text="Atlas lesson.",
                ),
                SimpleNamespace(
                    chunk_id="2" * 64,
                    concept_id="meetings/cedar",
                    content_sha256="d" * 64,
                    char_start=0,
                    char_end=len("Cedar lesson."),
                    text="Cedar lesson.",
                ),
            ),
            permissions=(
                SimpleNamespace(
                    path_prefix="meetings/atlas/",
                    audience=(
                        SimpleNamespace(tenant_id=tenant_id, subject_id="owner-atlas"),
                    ),
                    denials=(),
                    purposes=("knowledge.read",),
                    permission_sha256="e" * 64,
                ),
                SimpleNamespace(
                    path_prefix="meetings/cedar/",
                    audience=(
                        SimpleNamespace(tenant_id=tenant_id, subject_id="owner-cedar"),
                    ),
                    denials=(),
                    purposes=("knowledge.read",),
                    permission_sha256="f" * 64,
                ),
            ),
        )

        expected = gate._expected_product_evidence(
            generation,
            SimpleNamespace(cases=cases),
            tenant_id=tenant_id,
        )

        self.assertEqual(
            len(expected[("owner-atlas", "meetings/atlas")].items),
            1,
        )
        self.assertEqual(
            expected[(gate._CROSS_OWNER, "meetings/atlas")].items,
            (),
        )
        self.assertEqual(
            expected[(gate._CROSS_OWNER, "meetings/absent-probe")].items,
            (),
        )
        self.assertNotEqual(
            expected[("owner-atlas", "meetings/atlas")].permission_hash,
            expected[(gate._CROSS_OWNER, "meetings/atlas")].permission_hash,
        )

    def test_http_authentication_covers_health_post_get_and_delete(self) -> None:
        def response(_base_url, path, *, method, token, body=None):
            del body
            if path == "/v1/health":
                return 200, {
                    "auth": "required",
                    "capabilities": {"studentQuestions": True},
                }
            self.assertIn(method, {"POST", "GET", "DELETE"})
            if token is None:
                return 401, {"code": "AUTHENTICATION_REQUIRED"}
            return 401, {"code": "INVALID_ACCESS_TOKEN"}

        with mock.patch.object(gate, "_http_json", side_effect=response) as request:
            checks = gate._probe_http_authentication("http://127.0.0.1:1234")

        self.assertEqual(request.call_count, 7)
        self.assertTrue(all(checks.values()))

    def test_foreign_owner_cannot_read_or_cancel_product_request(self) -> None:
        with mock.patch.object(
            gate,
            "_http_json",
            side_effect=(
                (404, {"code": "STUDENT_QUESTION_NOT_FOUND"}),
                (404, {"code": "STUDENT_QUESTION_NOT_FOUND"}),
            ),
        ) as request:
            exact = gate._foreign_owner_isolation_exact(
                "http://127.0.0.1:1234",
                "student-question-" + "1" * 32,
                foreign_token="foreign-token",
            )

        self.assertTrue(exact)
        self.assertEqual(
            [call.kwargs["method"] for call in request.call_args_list],
            ["GET", "DELETE"],
        )

    def test_public_result_requires_every_exact_http_terminal(self) -> None:
        acceptance = gate.load_student_product_acceptance(
            REPOSITORY_ROOT / "server/student-product-acceptance.json"
        )
        observations = []
        statuses = ["complete"] * 8 + ["evidence-unavailable"] * 2 + ["cancelled"]
        for index, status in enumerate(statuses):
            reason = (
                None
                if status == "complete"
                else (
                    "client-cancelled"
                    if status == "cancelled"
                    else "evidence-unavailable"
                )
            )
            observations.append(
                gate.StudentProductObservation(
                    label=f"case-{index}",
                    owner_id=f"owner-{index % 8}",
                    request=mock.Mock(),
                    product_request_id=f"student-question-{index:032x}",
                    internal_request_id=f"agent-{index:032x}",
                    observed=mock.Mock(
                        status=status,
                        reason=reason,
                        questions=(_question(),) if status == "complete" else (),
                        output_budget_exhausted=False,
                    ),
                    duration_milliseconds=10,
                    exact_match=True,
                    authentication_header_exact=True,
                    owner_isolation_exact=True,
                    normal=index < 8,
                    failure_kind=None,
                )
            )
        authentication = {
            "healthCapabilityExact": True,
            "missingPostBearerRejected": True,
            "invalidPostBearerRejected": True,
            "missingGetBearerRejected": True,
            "invalidGetBearerRejected": True,
            "missingDeleteBearerRejected": True,
            "invalidDeleteBearerRejected": True,
        }

        result = gate._evaluate_product_observations(
            observations,
            acceptance=acceptance,
            authentication_probe=authentication,
            semantic_qualification_exact=True,
            hidden_only_indistinguishable=True,
            worker_containment_met=True,
        )
        self.assertTrue(result["qualified"])
        self.assertEqual(result["exactTerminalCount"], 11)

        observations[0] = replace(observations[0], exact_match=False)
        failed = gate._evaluate_product_observations(
            observations,
            acceptance=acceptance,
            authentication_probe=authentication,
            semantic_qualification_exact=True,
            hidden_only_indistinguishable=True,
            worker_containment_met=True,
        )
        self.assertFalse(failed["qualified"])

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

        with self.assertRaisesRegex(ValueError, "new and outside"):
            gate._new_private_evidence_destination(
                REPOSITORY_ROOT / "student-private-receipt.json",
                repository_root=REPOSITORY_ROOT,
            )

    def test_gate_owns_fresh_state_restarts_http_teardown_and_private_receipt(
        self,
    ) -> None:
        acceptance = gate.load_student_product_acceptance(
            REPOSITORY_ROOT / "server/student-product-acceptance.json"
        )
        candidate = mock.Mock()
        database = mock.Mock()
        started = SimpleNamespace(dsn="postgresql://private", process_id=10)
        first_restart = SimpleNamespace(dsn="postgresql://private", process_id=11)
        second_restart = SimpleNamespace(dsn="postgresql://private", process_id=12)
        database.start.return_value = started
        database.stop.return_value = {
            "containerAbsent": True,
            "listenerAbsent": True,
            "networkAbsent": True,
            "ownedProcessAbsent": True,
            "sameLabelOwnersAbsent": True,
            "volumeAbsent": True,
        }
        runtime = mock.Mock()
        corpus = SimpleNamespace(
            corpus_id="student-product-synthetic",
            corpus_sha256="1" * 64,
            cases=tuple(
                SimpleNamespace(owner_id=f"owner-{index}") for index in range(8)
            ),
        )
        generation = SimpleNamespace(generation_sha256="2" * 64)
        semantic_acceptance = SimpleNamespace(plan_sha256="3" * 64)
        semantic_result = SimpleNamespace(
            public_evidence={
                "outcome": "student-learning-questions-qualified",
                "evidenceSha256": "4" * 64,
            },
            private_evidence={"exact": True},
        )
        observations = (object(),)
        authentication = {"healthCapabilityExact": True}
        rapid_profile = SimpleNamespace(
            candidate_lock_sha256="5" * 64,
            profile_sha256="6" * 64,
            maximum_sequences=4,
            launch_arguments=("--max-num-seqs", "4"),
            expected_model="Qwen/Qwen3-4B-Instruct-2507-NVFP4",
            candidate_id="warm-qwen",
            model_revision="7" * 40,
            runtime_id="vllm-0.22.1",
        )
        complex_profile = SimpleNamespace(
            candidate_lock_sha256="5" * 64,
            profile_sha256="8" * 64,
        )
        capacity = {
            "admittedOwnerCount": 4,
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
            destination = Path(value).resolve() / "receipt.json"
            private_root = Path(value).resolve()
            with ExitStack() as stack:
                patches = {
                    "_candidate_input_paths": {"return_value": ()},
                    "admit_checked_candidate": {"return_value": candidate},
                    "_require_private_arm64_host": {},
                    "load_student_product_acceptance": {"return_value": acceptance},
                    "load_student_qualification_acceptance": {
                        "return_value": semantic_acceptance
                    },
                    "load_student_qualification_corpus": {"return_value": corpus},
                    "load_student_service_profile": {"return_value": rapid_profile},
                    "load_complex_agent_vllm_service_profile": {
                        "return_value": complex_profile
                    },
                    "_require_full_rapid_profile": {},
                    "build_checked_admission_broker": {"return_value": "9" * 64},
                    "probe_agent_admission_broker_capacity": {"return_value": capacity},
                    "load_knowledge_database_runtime_lock": {
                        "return_value": SimpleNamespace(lock_sha256="a" * 64)
                    },
                    "OwnedPostgresKnowledgeRuntime": {"return_value": database},
                    "_install_and_preflight_database": {},
                    "_initialize_student_knowledge": {"return_value": generation},
                    "_restart_database": {
                        "side_effect": (first_restart, second_restart)
                    },
                    "_write_new_private_text": {},
                    "_expected_student_evidence": {"return_value": {}},
                    "_expected_product_evidence": {"return_value": {}},
                    "build_student_product_runtime": {"return_value": runtime},
                    "_start_http_server": {
                        "return_value": (
                            object(),
                            mock.Mock(),
                            "http://127.0.0.1:1234",
                        )
                    },
                    "_run_product_workload": {
                        "return_value": (
                            observations,
                            semantic_result,
                            authentication,
                            True,
                        )
                    },
                    "_stop_http_server": {},
                    "_bind_internal_request_ids": {"return_value": observations},
                    "_verify_product_database_state": {
                        "return_value": {"studentResultAuditExact": True}
                    },
                    "_evaluate_product_observations": {"return_value": public},
                    "bind_checked_candidate_evidence": {
                        "side_effect": lambda evidence, _candidate: {
                            **evidence,
                            "candidate": {"checkedHead": "b" * 40},
                            "evidenceSha256": "c" * 64,
                        }
                    },
                    "_private_observations": {"return_value": [{"exactMatch": True}]},
                    "write_new_private_json_evidence": {"new": written},
                }
                active = {
                    name: stack.enter_context(mock.patch.object(gate, name, **options))
                    for name, options in patches.items()
                }
                receipt = gate.run_student_product_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="b" * 40,
                    evidence_destination=destination,
                    admission_socket_path=private_root / "admission.sock",
                    rapid_state_path=private_root / "rapid.json",
                    complex_state_path=private_root / "complex.json",
                )

        self.assertEqual(
            receipt["outcome"],
            "student-authenticated-product-server-boundary-qualified",
        )
        active["_install_and_preflight_database"].assert_called_once()
        initialize = active["_initialize_student_knowledge"].call_args
        self.assertTrue(initialize.kwargs["tenant_id"].startswith("student-product-q-"))
        self.assertEqual(active["_restart_database"].call_count, 2)
        database.stop.assert_called_once_with(timeout_seconds=15)
        active["_stop_http_server"].assert_called_once()
        runtime.close.assert_called_once()
        candidate.verify_unchanged.assert_called_once()
        written.assert_called_once()
        private_payload = written.call_args.args[1]
        self.assertEqual(
            private_payload["privacyScope"],
            "private-student-product-qualification",
        )
        serialized = json.dumps(private_payload)
        self.assertNotIn("postgresql://private", serialized)
        self.assertNotIn("Bearer ", serialized)


if __name__ == "__main__":
    unittest.main()
