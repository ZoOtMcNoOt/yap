from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from yap_server.auth import (
    AuthenticatedPrincipal,
    AuthenticationFailure,
    RepositoryBackedRequestAuthenticator,
)
from yap_server.auth.identity_repository import SqliteIdentityRepository
from yap_server.auth.principal_admission import PrincipalAdmissionUnavailable


TENANT_ID = "11111111-1111-4111-8111-111111111111"
SUBJECT_ID = "22222222-2222-4222-8222-222222222222"
ADMIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"


class _TokenAuthenticator:
    authentication_required = True
    principal_access_enforced = False

    def __init__(self, principal: AuthenticatedPrincipal) -> None:
        self.principal = principal

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        if authorization != "Bearer synthetic":
            raise AuthenticationFailure.invalid()
        return self.principal


def _principal(subject_id: str, issued_at_unix: int) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=TENANT_ID,
        subject_id=subject_id,
        client_id=CLIENT_ID,
        scopes=frozenset({"access_as_user"}),
        issued_at_unix=issued_at_unix,
    )


class RepositoryBackedRequestAuthenticatorTests(unittest.TestCase):
    def test_request_upserts_principal_and_local_revocation_blocks_all_tokens(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
            repository = SqliteIdentityRepository(
                Path(temporary) / "identity.sqlite3",
                clock=lambda: now,
            )
            try:
                old_token_principal = _principal(
                    SUBJECT_ID,
                    int((now - timedelta(seconds=1)).timestamp()),
                )
                authenticator = RepositoryBackedRequestAuthenticator(
                    _TokenAuthenticator(old_token_principal),
                    repository,
                )

                admitted = authenticator.authenticate("Bearer synthetic")
                self.assertEqual(admitted, old_token_principal)
                self.assertIsNotNone(repository.principal(admitted.key))

                admin = _principal(ADMIN_ID, int(now.timestamp()))
                repository.upsert_principal(admin)
                repository.revoke_access(admin.key, admitted.key)

                with self.assertRaises(AuthenticationFailure) as denied:
                    authenticator.authenticate("Bearer synthetic")
                self.assertEqual(denied.exception.status, 403)
                self.assertEqual(
                    denied.exception.code,
                    "PRINCIPAL_ACCESS_REVOKED",
                )

                newer = _principal(
                    SUBJECT_ID,
                    int((now + timedelta(seconds=1)).timestamp()),
                )
                refreshed = RepositoryBackedRequestAuthenticator(
                    _TokenAuthenticator(newer),
                    repository,
                )
                with self.assertRaises(AuthenticationFailure) as still_denied:
                    refreshed.authenticate("Bearer synthetic")
                self.assertEqual(
                    still_denied.exception.code,
                    "PRINCIPAL_ACCESS_REVOKED",
                )
            finally:
                repository.close()

    def test_repository_unavailability_is_a_stable_fail_closed_response(self) -> None:
        class _UnavailableRepository:
            def admit_principal(self, principal: AuthenticatedPrincipal) -> bool:
                del principal
                raise PrincipalAdmissionUnavailable("synthetic outage")

        authenticator = RepositoryBackedRequestAuthenticator(
            _TokenAuthenticator(_principal(SUBJECT_ID, 1)),
            _UnavailableRepository(),
        )

        with self.assertRaises(AuthenticationFailure) as unavailable:
            authenticator.authenticate("Bearer synthetic")
        self.assertEqual(unavailable.exception.status, 503)
        self.assertEqual(
            unavailable.exception.code,
            "AUTHENTICATION_UNAVAILABLE",
        )
        self.assertTrue(unavailable.exception.retryable)

    def test_repository_authorization_rejects_disabled_token_authentication(
        self,
    ) -> None:
        class _DisabledAuthenticator:
            authentication_required = False
            principal_access_enforced = False

            def authenticate(
                self,
                authorization: str | None,
            ) -> AuthenticatedPrincipal:
                del authorization
                return _principal(SUBJECT_ID, 0)

        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteIdentityRepository(Path(temporary) / "identity.sqlite3")
            try:
                with self.assertRaisesRegex(
                    ValueError,
                    "requires token authentication",
                ):
                    RepositoryBackedRequestAuthenticator(
                        _DisabledAuthenticator(),
                        repository,
                    )
            finally:
                repository.close()


if __name__ == "__main__":
    unittest.main()
