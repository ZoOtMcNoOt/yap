from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from yap_server.auth import PrincipalKey
from yap_server.jobs import JobServiceError, RecordingJobService

from .service_fixtures import _Processor, _create_request


ALICE = PrincipalKey(
    tenant_id="11111111-1111-4111-8111-111111111111",
    subject_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
)
BOB = PrincipalKey(
    tenant_id="11111111-1111-4111-8111-111111111111",
    subject_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
)


class JobOwnerAuthorizationTests(unittest.TestCase):
    def _service(self, root: Path) -> RecordingJobService:
        return RecordingJobService(
            root,
            processor=_Processor(),
            supported_languages=("en",),
            now=lambda: "2026-07-25T21:00:00Z",
            development_principal=None,
        )

    def test_same_idempotency_key_is_scoped_per_principal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            alice = service.for_principal(ALICE)
            bob = service.for_principal(BOB)

            alice_job = alice.create(
                _create_request(),
                idempotency_key="same-client-key",
            )
            bob_job = bob.create(
                _create_request(),
                idempotency_key="same-client-key",
            )

            self.assertNotEqual(alice_job["jobId"], bob_job["jobId"])
            self.assertEqual(
                alice.create(
                    _create_request(),
                    idempotency_key="same-client-key",
                )["jobId"],
                alice_job["jobId"],
            )

    def test_cross_owner_lookup_is_indistinguishable_from_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            alice_job = service.for_principal(ALICE).create(_create_request())

            with self.assertRaises(JobServiceError) as denied:
                service.for_principal(BOB).get(alice_job["jobId"])
            with self.assertRaises(JobServiceError) as absent:
                service.for_principal(BOB).get("job-" + "f" * 32)

            self.assertEqual(
                (denied.exception.status, denied.exception.code),
                (404, "JOB_NOT_FOUND"),
            )
            self.assertEqual(
                (absent.exception.status, absent.exception.code),
                (404, "JOB_NOT_FOUND"),
            )

    def test_owner_binding_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._service(root)
            job = first.for_principal(ALICE).create(_create_request())

            restarted = self._service(root)
            self.assertEqual(
                restarted.for_principal(ALICE).get(job["jobId"])["jobId"],
                job["jobId"],
            )
            with self.assertRaises(JobServiceError):
                restarted.for_principal(BOB).get(job["jobId"])

    def test_team_service_cannot_use_implicit_development_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            with self.assertRaisesRegex(
                RuntimeError,
                "principal-bound",
            ):
                service.create(_create_request())
