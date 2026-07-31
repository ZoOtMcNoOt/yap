from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from yap_server.auth import (
    AuthenticatedPrincipal,
    AuthenticationFailure,
    IdentityAuthorizationService,
    RepositoryBackedRequestAuthenticator,
    build_request_authorization_runtime,
)
from yap_server.auth.identity_repository import SqliteIdentityRepository
from yap_server.auth.principal_admission import PrincipalAdmissionUnavailable
from yap_server.config import ServerAuthenticationSettings


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


def _principal(
    subject_id: str,
    issued_at_unix: int,
    *,
    roles: frozenset[str] = frozenset(),
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=TENANT_ID,
        subject_id=subject_id,
        client_id=CLIENT_ID,
        scopes=frozenset({"access_as_user"}),
        issued_at_unix=issued_at_unix,
        roles=roles,
    )


class RepositoryBackedRequestAuthenticatorTests(unittest.TestCase):
    def test_entra_runtime_exposes_the_purpose_authorization_seam(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = ServerAuthenticationSettings(
                mode="entra",
                tenant_id=TENANT_ID,
                audience="44444444-4444-4444-8444-444444444444",
                required_scope="access_as_user",
                allowed_client_ids=(CLIENT_ID,),
                allowed_roles=("Yap.IdentityAdministrator",),
                identity_storage_dir=Path(temporary),
            )
            principal = _principal(SUBJECT_ID, 1)
            runtime = build_request_authorization_runtime(
                settings,
                _TokenAuthenticator(principal),
            )
            try:
                self.assertIsInstance(
                    runtime.purpose_authorization,
                    IdentityAuthorizationService,
                )
                self.assertIs(
                    runtime.authenticator._identity_repository,
                    runtime.identity_repository,
                )
            finally:
                runtime.close()

    def test_failed_first_principal_commits_never_admit_visible_uncommitted_state(
        self,
    ) -> None:
        class _FailingCommitConnection(sqlite3.Connection):
            remaining_commit_failures = 0

            def commit(self) -> None:
                if self.remaining_commit_failures > 0:
                    self.remaining_commit_failures -= 1
                    raise sqlite3.OperationalError("synthetic commit failure")
                super().commit()

        sqlite_connect = sqlite3.connect

        def connect(*args: object, **kwargs: object) -> sqlite3.Connection:
            return sqlite_connect(*args, **kwargs, factory=_FailingCommitConnection)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "identity.sqlite3"
            with patch(
                "yap_server.auth.identity_repository.sqlite3.connect",
                side_effect=connect,
            ):
                repository = SqliteIdentityRepository(path)
            try:
                connection = repository._active_connection()
                self.assertIsInstance(connection, _FailingCommitConnection)
                connection.remaining_commit_failures = 2
                principal = _principal(SUBJECT_ID, 1)
                authenticator = RepositoryBackedRequestAuthenticator(
                    _TokenAuthenticator(principal),
                    repository,
                )

                for _ in range(2):
                    with self.assertRaises(AuthenticationFailure) as unavailable:
                        authenticator.authenticate("Bearer synthetic")
                    self.assertEqual(unavailable.exception.status, 503)
                    self.assertEqual(
                        unavailable.exception.code,
                        "AUTHENTICATION_UNAVAILABLE",
                    )
                    self.assertFalse(connection.in_transaction)
                    self.assertIsNone(repository.principal(principal.key))

                self.assertEqual(
                    authenticator.authenticate("Bearer synthetic"),
                    principal,
                )
                self.assertFalse(connection.in_transaction)
            finally:
                repository.close()

            reopened = SqliteIdentityRepository(path)
            try:
                self.assertIsNotNone(reopened.principal(principal.key))
                reopened.verify_audit_chain()
            finally:
                reopened.close()

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
                self.assertTrue(authenticator.principal_is_admitted(admitted))

                administrator_roles = frozenset({"Yap.IdentityAdministrator"})
                admin = _principal(
                    ADMIN_ID,
                    int(now.timestamp()),
                    roles=administrator_roles,
                )
                repository.upsert_principal(admin)
                repository.revoke_access(
                    admin,
                    admitted.key,
                    administrator_roles=administrator_roles,
                )

                with self.assertRaises(AuthenticationFailure) as denied:
                    authenticator.authenticate("Bearer synthetic")
                self.assertEqual(denied.exception.status, 403)
                self.assertEqual(
                    denied.exception.code,
                    "PRINCIPAL_ACCESS_REVOKED",
                )
                self.assertFalse(authenticator.principal_is_admitted(admitted))

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
