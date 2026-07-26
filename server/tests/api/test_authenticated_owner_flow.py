from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from yap_server.api.app import create_server
from yap_server.auth import (
    AuthenticatedPrincipal,
    EntraAccessTokenAuthenticator,
    RepositoryBackedRequestAuthenticator,
)
from yap_server.auth.identity_repository import SqliteIdentityRepository
from yap_server.config import ServerAuthenticationSettings, ServerSettings
from yap_server.jobs import RecordingJobService

from tests.api.api_fixtures import ControlledJobProcessor
from tests.recording_job_fixtures import batch_api_recording_job_request


TENANT_ID = "11111111-1111-4111-8111-111111111111"
ALICE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BOB_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ADMIN_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"
AUDIENCE = "44444444-4444-4444-8444-444444444444"
ISSUER = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
KEY_ID = "synthetic-owner-flow-key"


class _FixedSigningKeys:
    def __init__(self, public_key: object) -> None:
        self._public_key = public_key

    def key_for(self, key_id: str) -> object:
        if key_id != KEY_ID:
            raise KeyError(key_id)
        return self._public_key


class AuthenticatedOwnerFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.settings = ServerSettings(
            host="127.0.0.1",
            port=0,
            authentication=ServerAuthenticationSettings(
                mode="entra",
                tenant_id=TENANT_ID,
                audience=AUDIENCE,
                required_scope="access_as_user",
                allowed_client_ids=(CLIENT_ID,),
                identity_storage_dir=self.root / "identity",
            ),
        )
        self._start()

    def tearDown(self) -> None:
        self._stop()
        self.temporary.cleanup()

    def _start(self) -> None:
        (self.root / "identity").mkdir(exist_ok=True)
        self.repository = SqliteIdentityRepository(
            self.root / "identity" / "identity.sqlite3"
        )
        token_authenticator = EntraAccessTokenAuthenticator(
            self.settings.authentication,
            _FixedSigningKeys(self.private_key.public_key()),
        )
        self.authenticator = RepositoryBackedRequestAuthenticator(
            token_authenticator,
            self.repository,
        )
        self.jobs = RecordingJobService(
            self.root / "jobs",
            processor=ControlledJobProcessor(),
            supported_languages=("en",),
            now=lambda: "2026-07-25T21:00:00Z",
            development_principal=None,
        )
        self.server = create_server(
            self.settings,
            request_authenticator=self.authenticator,
            job_service=self.jobs,
        )
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()

    def _stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.repository.close()

    def _token(self, subject_id: str, *, tenant_id: str = TENANT_ID) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "aud": AUDIENCE,
            "ver": "2.0",
            "exp": now + timedelta(minutes=5),
            "nbf": now - timedelta(minutes=1),
            "iat": now - timedelta(seconds=1),
            "tid": tenant_id,
            "oid": subject_id,
            "azp": CLIENT_ID,
            "scp": "access_as_user",
        }
        return jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": KEY_ID},
        )

    def _request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        headers = {"Authorization": f"Bearer {token}"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    def test_signed_tokens_bind_jobs_to_the_owner_across_restart_and_revocation(
        self,
    ) -> None:
        alice_token = self._token(ALICE_ID)
        bob_token = self._token(BOB_ID)
        create_request = batch_api_recording_job_request()

        alice_status, alice_job = self._request(
            "/v1/jobs",
            token=alice_token,
            method="POST",
            payload=create_request,
            idempotency_key="shared-client-key",
        )
        bob_status, bob_job = self._request(
            "/v1/jobs",
            token=bob_token,
            method="POST",
            payload=create_request,
            idempotency_key="shared-client-key",
        )

        self.assertEqual(alice_status, HTTPStatus.ACCEPTED)
        self.assertEqual(bob_status, HTTPStatus.ACCEPTED)
        self.assertNotEqual(alice_job["jobId"], bob_job["jobId"])

        denied_status, denied = self._request(
            f"/v1/jobs/{alice_job['jobId']}",
            token=bob_token,
        )
        absent_status, absent = self._request(
            f"/v1/jobs/job-{'f' * 32}",
            token=bob_token,
        )
        self.assertEqual(
            (denied_status, denied["code"]),
            (HTTPStatus.NOT_FOUND, "JOB_NOT_FOUND"),
        )
        self.assertEqual(
            (absent_status, absent["code"]),
            (HTTPStatus.NOT_FOUND, "JOB_NOT_FOUND"),
        )

        self._stop()
        self._start()

        resumed_status, resumed = self._request(
            f"/v1/jobs/{alice_job['jobId']}",
            token=alice_token,
        )
        self.assertEqual(resumed_status, HTTPStatus.OK)
        self.assertEqual(resumed["jobId"], alice_job["jobId"])

        admin = AuthenticatedPrincipal(
            tenant_id=TENANT_ID,
            subject_id=ADMIN_ID,
            client_id=CLIENT_ID,
            scopes=frozenset({"access_as_user"}),
            issued_at_unix=int(datetime.now(UTC).timestamp()),
            roles=frozenset({"Yap.IdentityAdministrator"}),
        )
        self.repository.upsert_principal(admin)
        self.repository.revoke_access(
            admin,
            AuthenticatedPrincipal(
                tenant_id=TENANT_ID,
                subject_id=ALICE_ID,
                client_id=CLIENT_ID,
                scopes=frozenset({"access_as_user"}),
            ).key,
            administrator_roles=frozenset({"Yap.IdentityAdministrator"}),
        )
        revoked_status, revoked = self._request(
            f"/v1/jobs/{alice_job['jobId']}",
            token=alice_token,
        )
        self.assertEqual(revoked_status, HTTPStatus.FORBIDDEN)
        self.assertEqual(revoked["code"], "PRINCIPAL_ACCESS_REVOKED")

    def test_another_tenants_signed_token_is_rejected_before_job_dispatch(
        self,
    ) -> None:
        other_tenant = "99999999-9999-4999-8999-999999999999"
        status, error = self._request(
            "/v1/jobs",
            token=self._token(ALICE_ID, tenant_id=other_tenant),
            method="POST",
            payload=batch_api_recording_job_request(),
            idempotency_key="wrong-tenant",
        )

        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(error["code"], "INVALID_ACCESS_TOKEN")


if __name__ == "__main__":
    unittest.main()
