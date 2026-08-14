from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from yap_server.agents.curator import CuratorRequest
from yap_server.evaluation import curator_product_qualification_gate as gate
from yap_server.evaluation.curator_qualification import (
    build_curator_qualification_requests,
    load_curator_qualification_corpus,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _request() -> CuratorRequest:
    corpus = load_curator_qualification_corpus(
        REPOSITORY_ROOT / "server/curator-workload-fixtures.json"
    )
    case = corpus.cases[0]
    from yap_server.evaluation.curator_qualification import CuratorExpectedEvidence

    evidence = CuratorExpectedEvidence(
        concept_id=case.concept_id,
        source_revision="a" * 64,
        content_sha256=hashlib.sha256(case.body.encode()).hexdigest(),
        char_start=0,
        char_end=len(case.body),
        text=case.body,
    )
    return build_curator_qualification_requests(
        corpus,
        qualification_run_id="run-12345678",
        generation_sha256="b" * 64,
        expected_evidence={
            item.case_id: (
                replace(
                    evidence,
                    concept_id=item.concept_id,
                    content_sha256=hashlib.sha256(item.body.encode()).hexdigest(),
                    char_end=len(item.body),
                    text=item.body,
                ),
            )
            for item in corpus.cases
        },
    )[case.case_id]


class CuratorProductQualificationGateTests(unittest.TestCase):
    def test_acceptance_and_candidate_inputs_are_exact(self) -> None:
        acceptance = gate.load_curator_product_acceptance(
            REPOSITORY_ROOT / "server/curator-product-acceptance.json"
        )

        self.assertEqual(acceptance.case_count, 8)
        self.assertEqual(acceptance.query_count, 10)
        self.assertEqual(acceptance.proposed_count, 4)
        self.assertEqual(acceptance.rejected_count, 4)
        self.assertEqual(acceptance.maximum_normal_p95_milliseconds, 60_000)

        paths = gate._candidate_input_paths(REPOSITORY_ROOT)
        relative = {path.relative_to(REPOSITORY_ROOT).as_posix() for path in paths}
        required = {
            "server/curator-product-acceptance.json",
            "server/src/yap_server/agents/curator_proposal_service.py",
            "server/src/yap_server/agents/curator_product_runtime.py",
            "server/src/yap_server/api/curator_proposal_requests.py",
            "server/src/yap_server/evaluation/curator_product_qualification_gate.py",
            "server/tests/evaluation/test_curator_product_qualification_gate.py",
            "desktop/src/curator.ts",
            "desktop/src/components/curator/curator-proposal-composer.tsx",
            "desktop/src-tauri/src/curator_proposal.rs",
            "desktop/src-tauri/src/server_connector/curator.rs",
            "desktop/tests/unit/curator-product.test.tsx",
            "desktop/tests/wdio/smoke.spec.js",
            ".github/workflows/ci.yml",
        }
        self.assertTrue(required <= relative)
        self.assertEqual(len(relative), len(paths))
        self.assertTrue(
            all(0 < path.stat().st_size <= 16 * 1024 * 1024 for path in paths)
        )

    def test_product_view_parser_is_strict_and_hash_bound(self) -> None:
        request = _request()
        request_id = "curator-proposal-" + "1" * 32
        proposed = {
            "schemaVersion": 1,
            "requestId": request_id,
            "submissionId": request.submission_id,
            "status": "proposed",
            "generationSha256": request.expected_generation_sha256,
            "evidenceSha256": "c" * 64,
            "proposalId": "d" * 64,
        }

        parsed = gate._parse_product_view(
            proposed,
            expected_request=request,
            expected_evidence_sha256="c" * 64,
        )

        self.assertEqual(parsed.request_id, request_id)
        self.assertEqual(parsed.status, "proposed")
        self.assertEqual(parsed.proposal_id, "d" * 64)
        broader = dict(proposed, canonical=False)
        with self.assertRaisesRegex(ValueError, "fields"):
            gate._parse_product_view(broader, expected_request=request)
        forged = dict(proposed, evidenceSha256="e" * 64)
        with self.assertRaisesRegex(ValueError, "evidence identity"):
            gate._parse_product_view(
                forged,
                expected_request=request,
                expected_evidence_sha256="c" * 64,
            )

    def test_active_and_non_proposed_terminal_views_carry_no_proposal(self) -> None:
        request = _request()
        request_id = "curator-proposal-" + "2" * 32
        active = gate._parse_product_view(
            {
                "schemaVersion": 1,
                "requestId": request_id,
                "submissionId": request.submission_id,
                "status": "running",
                "generationSha256": request.expected_generation_sha256,
            },
            expected_request=request,
        )
        self.assertEqual(active.status, "running")

        rejected = gate._parse_product_view(
            {
                "schemaVersion": 1,
                "requestId": request_id,
                "submissionId": request.submission_id,
                "status": "rejected",
                "generationSha256": request.expected_generation_sha256,
                "evidenceSha256": "c" * 64,
                "reason": "model-rejected",
            },
            expected_request=request,
        )
        self.assertEqual(rejected.status, "rejected")
        self.assertIsNone(rejected.proposal_id)

        with self.assertRaisesRegex(ValueError, "fields"):
            gate._parse_product_view(
                {
                    "schemaVersion": 1,
                    "requestId": request_id,
                    "submissionId": request.submission_id,
                    "status": "cancelled",
                    "generationSha256": request.expected_generation_sha256,
                    "proposalId": "d" * 64,
                    "reason": "client-cancelled",
                },
                expected_request=request,
            )

    def test_http_authentication_covers_post_get_and_delete(self) -> None:
        request = _request()

        def response(_base_url, path, *, method, token, body=None):
            del body
            if path == "/v1/health":
                return 200, {
                    "auth": "required",
                    "capabilities": {"curatorProposals": True},
                }
            self.assertIn(method, {"POST", "GET", "DELETE"})
            if token is None:
                return 401, {"code": "AUTHENTICATION_REQUIRED"}
            return 401, {"code": "INVALID_ACCESS_TOKEN"}

        with mock.patch.object(gate, "_http_json", side_effect=response) as call:
            checks = gate._probe_http_authentication(
                "http://127.0.0.1:1234", request=request
            )

        self.assertEqual(call.call_count, 7)
        self.assertTrue(all(checks.values()))

    def test_foreign_owner_cannot_read_or_cancel(self) -> None:
        with mock.patch.object(
            gate,
            "_http_json",
            side_effect=(
                (404, {"code": "CURATOR_PROPOSAL_NOT_FOUND"}),
                (404, {"code": "CURATOR_PROPOSAL_NOT_FOUND"}),
            ),
        ) as call:
            exact = gate._foreign_owner_isolation_exact(
                "http://127.0.0.1:1234",
                "curator-proposal-" + "3" * 32,
                foreign_token="foreign-token",
            )

        self.assertTrue(exact)
        self.assertEqual(
            [item.kwargs["method"] for item in call.call_args_list],
            ["GET", "DELETE"],
        )

    def test_product_evidence_counts_fail_closed(self) -> None:
        acceptance = gate.load_curator_product_acceptance(
            REPOSITORY_ROOT / "server/curator-product-acceptance.json"
        )
        request = _request()
        normal = []
        for index, status in enumerate(("proposed",) * 4 + ("rejected",) * 4):
            normal.append(
                gate.CuratorProductObservation(
                    label=f"case-{index}",
                    owner_id=f"owner-{index}",
                    request=replace(request, submission_id=f"submission-{index}"),
                    product_request_id=f"curator-proposal-{index:032x}",
                    internal_request_id=f"internal-{index}",
                    observed=gate.CuratorProductView(
                        request_id=f"curator-proposal-{index:032x}",
                        submission_id=f"submission-{index}",
                        status=status,
                        generation_sha256=request.expected_generation_sha256,
                        evidence_sha256="c" * 64,
                        proposal_id="d" * 64 if status == "proposed" else None,
                        reason=None if status == "proposed" else "model-rejected",
                    ),
                    duration_milliseconds=10,
                    exact_match=True,
                    authentication_header_exact=True,
                    owner_isolation_exact=True,
                    normal=True,
                    failure_kind=None,
                )
            )
        controls = (
            gate.CuratorProductObservation(
                label="hidden",
                owner_id="hidden-owner",
                request=replace(request, submission_id="hidden-submission"),
                product_request_id="curator-proposal-" + "a" * 32,
                internal_request_id="internal-hidden",
                observed=gate.CuratorProductView(
                    request_id="curator-proposal-" + "a" * 32,
                    submission_id="hidden-submission",
                    status="failed",
                    generation_sha256=request.expected_generation_sha256,
                    reason="evidence-unavailable",
                ),
                duration_milliseconds=10,
                exact_match=True,
                authentication_header_exact=True,
                owner_isolation_exact=True,
                normal=False,
                failure_kind=None,
            ),
            gate.CuratorProductObservation(
                label="cancelled",
                owner_id="owner-0",
                request=replace(request, submission_id="cancel-submission"),
                product_request_id="curator-proposal-" + "b" * 32,
                internal_request_id="internal-cancel",
                observed=gate.CuratorProductView(
                    request_id="curator-proposal-" + "b" * 32,
                    submission_id="cancel-submission",
                    status="cancelled",
                    generation_sha256=request.expected_generation_sha256,
                    reason="client-cancelled",
                ),
                duration_milliseconds=10,
                exact_match=True,
                authentication_header_exact=True,
                owner_isolation_exact=True,
                normal=False,
                failure_kind=None,
            ),
        )
        public = gate._evaluate_product_observations(
            (*normal, *controls),
            acceptance=acceptance,
            authentication_probe={"exact": True},
            semantic_qualification_exact=True,
            database_state_exact=True,
            replay_conflict_exact=True,
            worker_containment_met=True,
        )
        self.assertTrue(public["qualified"])
        self.assertEqual(public["exactTerminalCount"], 10)

        forged = list((*normal, *controls))
        forged[0] = replace(forged[0], exact_match=False)
        self.assertFalse(
            gate._evaluate_product_observations(
                forged,
                acceptance=acceptance,
                authentication_probe={"exact": True},
                semantic_qualification_exact=True,
                database_state_exact=True,
                replay_conflict_exact=True,
                worker_containment_met=True,
            )["qualified"]
        )

    def test_private_destination_is_create_once_and_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            outside = Path(value).resolve() / "receipt.json"
            self.assertEqual(
                gate._new_private_evidence_destination(
                    outside, repository_root=REPOSITORY_ROOT
                ),
                outside,
            )
            outside.write_text("reserved", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "new and outside"):
                gate._new_private_evidence_destination(
                    outside, repository_root=REPOSITORY_ROOT
                )


if __name__ == "__main__":
    unittest.main()
