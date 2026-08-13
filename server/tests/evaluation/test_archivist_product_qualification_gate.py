from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import yaml

from yap_server.evaluation import archivist_product_qualification_gate as gate


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _staged_view(index: int = 1) -> gate.ArchivistProductView:
    return gate._parse_product_view(
        {
            "schemaVersion": 1,
            "requestId": f"archivist-ingestion-{index:032x}",
            "status": "staged",
            "jobId": f"job-{index}",
            "resultSha256": "a" * 64,
            "captureSha256": "b" * 64,
            "sourceAdmissionSha256": "c" * 64,
            "generationSha256": "d" * 64,
            "conceptCount": 1,
            "permissionCount": 1,
        }
    )


class ArchivistProductQualificationGateTests(unittest.TestCase):
    def test_acceptance_is_exact_and_candidate_inputs_cover_the_vertical(self) -> None:
        acceptance = gate.load_archivist_product_acceptance(
            REPOSITORY_ROOT / "server/archivist-product-acceptance.json"
        )

        self.assertEqual(acceptance.case_count, 9)
        self.assertEqual(acceptance.request_count, 10)
        self.assertEqual(acceptance.staged_generation_count, 8)
        self.assertEqual(acceptance.active_generation_count, 0)
        self.assertEqual(acceptance.maximum_normal_p95_milliseconds, 60_000)

        relative = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in gate._candidate_input_paths(REPOSITORY_ROOT)
        }
        required = {
            "server/archivist-product-acceptance.json",
            "server/src/yap_server/agents/archivist_ingestion_runner.py",
            "server/src/yap_server/agents/archivist_ingestion_service.py",
            "server/src/yap_server/agents/archivist_runtime.py",
            "server/src/yap_server/api/archivist_ingestion_requests.py",
            "server/src/yap_server/evaluation/archivist_product_qualification_gate.py",
            "server/tests/evaluation/test_archivist_product_qualification_gate.py",
            "desktop/src/archivist.ts",
            "desktop/src/components/archivist/use-archivist-ingestion.ts",
            "desktop/src-tauri/src/archivist_ingestion.rs",
            "desktop/src-tauri/src/server_connector/archivist.rs",
            "desktop/tests/e2e/archivist-ingestion.spec.ts",
            ".github/workflows/ci.yml",
        }
        self.assertTrue(required <= relative)
        self.assertEqual(
            len(relative), len(gate._candidate_input_paths(REPOSITORY_ROOT))
        )
        self.assertTrue(
            all(
                0 < path.stat().st_size <= 16 * 1024 * 1024
                for path in gate._candidate_input_paths(REPOSITORY_ROOT)
            )
        )

    def test_product_view_parser_requires_exact_hash_bound_shapes(self) -> None:
        staged = _staged_view()

        self.assertEqual(staged.status, "staged")
        self.assertEqual(staged.concept_count, 1)
        self.assertIsNone(staged.reason)

        broader = staged.to_wire()
        broader["transcript"] = "private"
        with self.assertRaisesRegex(ValueError, "view fields"):
            gate._parse_product_view(broader)

        forged = staged.to_wire()
        forged["generationSha256"] = "not-a-hash"
        with self.assertRaisesRegex(ValueError, "generation identity"):
            gate._parse_product_view(forged)

        active = {
            "schemaVersion": 1,
            "requestId": "archivist-ingestion-" + "2" * 32,
            "status": "running",
            "jobId": "job-2",
            "resultSha256": "a" * 64,
        }
        self.assertEqual(gate._parse_product_view(active).status, "running")
        active["captureSha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "view fields"):
            gate._parse_product_view(active)

    def test_cancelled_view_cannot_claim_a_capture_or_generation(self) -> None:
        value = {
            "schemaVersion": 1,
            "requestId": "archivist-ingestion-" + "3" * 32,
            "status": "cancelled",
            "jobId": "job-3",
            "resultSha256": "a" * 64,
            "reason": "client-cancelled",
        }
        view = gate._parse_product_view(value)
        self.assertEqual(view.terminal_shape(), ("cancelled", "client-cancelled"))

        value["captureSha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "view fields"):
            gate._parse_product_view(value)

    def test_reviewed_source_contract_is_exact_and_rejects_extra_content(self) -> None:
        reviewed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result = {
            "sessionId": "session-1",
            "createdAtUtc": reviewed_at,
            "transcript": "Reviewed decision.",
        }
        result_sha256 = gate.result_revision_sha256(result)
        seed = SimpleNamespace(
            owner_id="owner-1",
            job_id="job-1",
            result_sha256=result_sha256,
            title="Reviewed meeting",
            transcript="Reviewed decision.",
        )
        review_sha256 = gate._canonical_json_sha256(
            {
                "schemaVersion": 2,
                "reviewer": {"tenantId": "tenant-1", "subjectId": "owner-1"},
                "reviewedAtUtc": reviewed_at,
                "jobId": "job-1",
                "title": "Reviewed meeting",
                "resultRevisionSha256": result_sha256,
                "decision": "accepted",
            }
        )
        frontmatter = {
            "type": "Meeting",
            "title": "Reviewed meeting",
            "resource": "yap://tenant/tenant-1/meeting/job-1",
            "timestamp": reviewed_at,
            "yap_schema": 1,
            "provenance": {
                "source": "server-authoritative-meeting-result",
                "source_revision": result_sha256,
                "result_sha256": result_sha256,
                "review_sha256": review_sha256,
                "job_id": "job-1",
                "session_id": "session-1",
                "owner": {"tenant_id": "tenant-1", "subject_id": "owner-1"},
                "reviewer": {
                    "tenant_id": "tenant-1",
                    "subject_id": "owner-1",
                },
            },
        }
        normalized = (
            "---\n"
            + yaml.safe_dump(
                frontmatter,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ).strip()
            + "\n---\n# Transcript\n\nReviewed decision.\n"
        )
        normalized_sha256 = hashlib.sha256(normalized.encode()).hexdigest()
        capture_sha256 = hashlib.sha256(
            "\0".join(
                (
                    "tenant-1",
                    "owner-1",
                    "job-1",
                    result_sha256,
                    review_sha256,
                    normalized_sha256,
                )
            ).encode()
        ).hexdigest()
        arguments = {
            "tenant_id": "tenant-1",
            "seed": seed,
            "capture_sha256": capture_sha256,
            "review_sha256": review_sha256,
            "normalized_okf_sha256": normalized_sha256,
            "normalized_okf": normalized,
            "result_payload": result,
        }

        self.assertTrue(gate._reviewed_source_contract_exact(**arguments))
        changed = normalized.replace(
            "Reviewed decision.\n", "Reviewed decision.\nInjected content.\n"
        )
        self.assertFalse(
            gate._reviewed_source_contract_exact(
                **{
                    **arguments,
                    "normalized_okf": changed,
                    "normalized_okf_sha256": hashlib.sha256(
                        changed.encode()
                    ).hexdigest(),
                }
            )
        )

    def test_public_result_requires_every_terminal_and_one_lease_each(self) -> None:
        acceptance = gate.load_archivist_product_acceptance(
            REPOSITORY_ROOT / "server/archivist-product-acceptance.json"
        )
        observations = []
        normal = []
        for index in range(8):
            view = _staged_view(index + 1)
            observation = gate.ArchivistProductObservation(
                label=f"normal-{index}",
                owner_id=f"owner-{index}",
                job_id=view.job_id,
                product_request_id=view.request_id,
                observed=view,
                expected_status="staged",
                duration_milliseconds=10,
                exact_match=True,
                failure_kind=None,
            )
            observations.append(observation)
            normal.append(observation)
        replay = replace(
            observations[0],
            label="replay",
            product_request_id="archivist-ingestion-" + "9" * 32,
        )
        cancelled = gate.ArchivistProductObservation(
            label="cancelled",
            owner_id="owner-0",
            job_id="job-9",
            product_request_id="archivist-ingestion-" + "a" * 32,
            observed=gate._parse_product_view(
                {
                    "schemaVersion": 1,
                    "requestId": "archivist-ingestion-" + "a" * 32,
                    "status": "cancelled",
                    "jobId": "job-9",
                    "resultSha256": "a" * 64,
                    "reason": "client-cancelled",
                }
            ),
            expected_status="cancelled",
            duration_milliseconds=10,
            exact_match=True,
            failure_kind=None,
        )
        observations.extend((replay, cancelled))
        admission = {
            "newTicketCount": 10,
            "submitCount": 10,
            "completeCount": 9,
            "cancelCount": 1,
            "acknowledgeCount": 1,
            "allWorkIdentityExact": True,
            "allTerminalExact": True,
        }
        probes = {
            "authenticatedHttpExact": True,
            "ownerIsolationExact": True,
            "sourceDriftFailedClosed": True,
            "brokerIdentityUnchanged": True,
        }

        result = gate._evaluate_product_observations(
            observations,
            normal_observations=normal,
            acceptance=acceptance,
            probes=probes,
            admission=admission,
            database_state={
                "reviewedCaptureCount": 9,
                "sourceAdmissionCount": 8,
                "stagedGenerationCount": 8,
                "activeGenerationCount": 0,
                "serverDerivedReviewExact": True,
                "noActivationExact": True,
                "exactReplayReused": True,
                "cancelledGenerationAbsent": True,
                "admissionSourceBindingExact": True,
            },
            worker_containment_met=True,
        )

        self.assertTrue(result["qualified"])
        self.assertEqual(result["exactTerminalCount"], 10)
        self.assertTrue(result["singleLeasePerRequestExact"])

        bad_admission = dict(admission)
        bad_admission["newTicketCount"] = 11
        failed = gate._evaluate_product_observations(
            observations,
            normal_observations=normal,
            acceptance=acceptance,
            probes=probes,
            admission=bad_admission,
            database_state={
                "reviewedCaptureCount": 9,
                "sourceAdmissionCount": 8,
                "stagedGenerationCount": 8,
                "activeGenerationCount": 0,
                "serverDerivedReviewExact": True,
                "noActivationExact": True,
                "exactReplayReused": True,
                "cancelledGenerationAbsent": True,
                "admissionSourceBindingExact": True,
            },
            worker_containment_met=True,
        )
        self.assertFalse(failed["qualified"])

        unbound_database = {
            "reviewedCaptureCount": 9,
            "sourceAdmissionCount": 8,
            "stagedGenerationCount": 8,
            "activeGenerationCount": 0,
            "serverDerivedReviewExact": True,
            "noActivationExact": True,
            "exactReplayReused": True,
            "cancelledGenerationAbsent": True,
            "admissionSourceBindingExact": False,
        }
        failed = gate._evaluate_product_observations(
            observations,
            normal_observations=normal,
            acceptance=acceptance,
            probes=probes,
            admission=admission,
            database_state=unbound_database,
            worker_containment_met=True,
        )
        self.assertFalse(failed["qualified"])

        changed_broker = dict(probes)
        changed_broker["brokerIdentityUnchanged"] = False
        failed = gate._evaluate_product_observations(
            observations,
            normal_observations=normal,
            acceptance=acceptance,
            probes=changed_broker,
            admission=admission,
            database_state={**unbound_database, "admissionSourceBindingExact": True},
            worker_containment_met=True,
        )
        self.assertFalse(failed["qualified"])

    def test_private_destination_is_create_once_and_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            destination = Path(value).resolve() / "receipt.json"
            self.assertEqual(
                gate._new_private_evidence_destination(
                    destination,
                    repository_root=REPOSITORY_ROOT,
                ),
                destination,
            )
            destination.write_text("reserved", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "new and outside"):
                gate._new_private_evidence_destination(
                    destination,
                    repository_root=REPOSITORY_ROOT,
                )

        with self.assertRaisesRegex(ValueError, "new and outside"):
            gate._new_private_evidence_destination(
                REPOSITORY_ROOT / "private-archivist-product.json",
                repository_root=REPOSITORY_ROOT,
            )

    def test_recording_seed_uses_real_owner_scoped_restart_safe_results(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            seeded = gate._seed_recording_jobs(
                Path(value) / "jobs",
                tenant_id="archivist-portable-tenant",
            )
            try:
                self.assertEqual(len(seeded.seeds), 9)
                self.assertEqual(
                    len({seed.owner_id for seed in seeded.seeds}),
                    8,
                )
                for seed in seeded.seeds:
                    result = seeded.jobs.for_principal(seed.principal).get_result(
                        seed.job_id
                    )
                    self.assertEqual(
                        gate.result_revision_sha256(result),
                        seed.result_sha256,
                    )
            finally:
                seeded.jobs.begin_runtime_shutdown()

    def test_gate_owns_restarts_http_teardown_and_private_receipt(self) -> None:
        acceptance = gate.load_archivist_product_acceptance(
            REPOSITORY_ROOT / "server/archivist-product-acceptance.json"
        )
        candidate = mock.Mock()
        database = mock.Mock()
        started = SimpleNamespace(dsn="postgresql://private", process_id=10)
        first_restart = SimpleNamespace(dsn="postgresql://private", process_id=11)
        second_restart = SimpleNamespace(dsn="postgresql://private", process_id=12)
        database.start.return_value = started
        database.stop.return_value = {"contained": True}
        runtime = mock.Mock()
        seeded = SimpleNamespace(
            jobs=object(),
            seeds=tuple(range(9)),
            tokens_by_owner={"owner-0": "secret"},
        )
        observations = (object(),)
        normal = (object(),)
        probes = {
            "authenticatedHttpExact": True,
            "ownerIsolationExact": True,
            "sourceDriftFailedClosed": True,
            "brokerIdentityUnchanged": True,
        }
        admission = {
            "newTicketCount": 10,
            "submitCount": 10,
            "completeCount": 9,
            "cancelCount": 1,
            "acknowledgeCount": 1,
            "allWorkIdentityExact": True,
            "allTerminalExact": True,
        }
        runtime.admission.snapshot.return_value = admission
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
                    "load_archivist_product_acceptance": {"return_value": acceptance},
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
                    "observe_admission_broker": {
                        "return_value": {"processId": 10, "startedAt": "fixed"}
                    },
                    "_probe_server_io_capacity": {
                        "return_value": {
                            "admittedOwnerCount": 1,
                            "expectedCapacityObserved": True,
                            "overflowOwnerQueued": True,
                            "contained": True,
                            "brokerIdentityUnchanged": True,
                        }
                    },
                    "load_knowledge_database_runtime_lock": {
                        "return_value": SimpleNamespace(lock_sha256="e" * 64)
                    },
                    "OwnedPostgresKnowledgeRuntime": {"return_value": database},
                    "_install_and_preflight_database": {},
                    "_restart_database": {
                        "side_effect": (first_restart, second_restart)
                    },
                    "_seed_recording_jobs": {"return_value": seeded},
                    "_build_product_runtime": {"return_value": runtime},
                    "_start_http_server": {
                        "return_value": (
                            object(),
                            mock.Mock(),
                            "http://127.0.0.1:1234",
                        )
                    },
                    "_run_product_workload": {
                        "return_value": (observations, normal, probes)
                    },
                    "_stop_http_server": {},
                    "_verify_database_state": {
                        "return_value": {
                            "reviewedCaptureCount": 9,
                            "sourceAdmissionCount": 8,
                            "stagedGenerationCount": 8,
                            "activeGenerationCount": 0,
                            "serverDerivedReviewExact": True,
                            "noActivationExact": True,
                            "exactReplayReused": True,
                            "cancelledGenerationAbsent": True,
                            "admissionSourceBindingExact": True,
                        }
                    },
                    "_verify_recording_restart": {"return_value": True},
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
                receipt = gate.run_archivist_product_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="f" * 40,
                    evidence_destination=destination,
                    admission_socket_path=private_root / "admission.sock",
                    rapid_state_path=private_root / "rapid.json",
                    complex_state_path=private_root / "complex.json",
                )

        self.assertEqual(
            receipt["outcome"],
            "archivist-authenticated-product-vertical-qualified",
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
            "private-archivist-product-qualification",
        )
        serialized = json.dumps(private_payload)
        self.assertNotIn("postgresql://private", serialized)
        self.assertNotIn("Bearer ", serialized)


if __name__ == "__main__":
    unittest.main()
