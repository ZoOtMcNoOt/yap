from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import unittest
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from yap_server.auth import AuthenticationFailure
from yap_server.auth.entra_access_tokens import EntraAccessTokenAuthenticator
from yap_server.auth.signing_keys import SigningKeyUnavailable
from yap_server.config import ServerAuthenticationSettings


TENANT_ID = "11111111-1111-4111-8111-111111111111"
SUBJECT_ID = "22222222-2222-4222-8222-222222222222"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"
AUDIENCE = "44444444-4444-4444-8444-444444444444"
ISSUER = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
KID = "test-signing-key"


class _SigningKeys:
    def __init__(self, key: object) -> None:
        self.key = key
        self.requested: list[str] = []
        self.failure: Exception | None = None

    def key_for(self, key_id: str) -> object:
        self.requested.append(key_id)
        if self.failure is not None:
            raise self.failure
        if key_id != KID:
            raise KeyError(key_id)
        return self.key


class EntraAccessTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.public_key = cls.private_key.public_key()

    def setUp(self) -> None:
        self.keys = _SigningKeys(self.public_key)
        self.authenticator = EntraAccessTokenAuthenticator(
            ServerAuthenticationSettings(
                mode="entra",
                tenant_id=TENANT_ID,
                audience=AUDIENCE,
                required_scope="access_as_user",
                allowed_client_ids=(CLIENT_ID,),
                identity_storage_dir=Path("test-private-identity"),
            ),
            self.keys,
        )

    def _claims(self) -> dict[str, object]:
        now = datetime.now(UTC)
        return {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": now + timedelta(minutes=5),
            "nbf": now - timedelta(minutes=1),
            "iat": now - timedelta(minutes=1),
            "tid": TENANT_ID,
            "oid": SUBJECT_ID,
            "azp": CLIENT_ID,
            "scp": "access_as_user",
        }

    def _token(
        self,
        claims: dict[str, object] | None = None,
        *,
        private_key: object | None = None,
        algorithm: str = "RS256",
        kid: str = KID,
    ) -> str:
        return jwt.encode(
            self._claims() if claims is None else claims,
            self.private_key if private_key is None else private_key,
            algorithm=algorithm,
            headers={"kid": kid},
        )

    def _failure(self, token: str) -> AuthenticationFailure:
        with self.assertRaises(AuthenticationFailure) as raised:
            self.authenticator.authenticate(f"Bearer {token}")
        return raised.exception

    def test_valid_yap_api_token_returns_the_tenant_scoped_principal(self) -> None:
        principal = self.authenticator.authenticate(f"Bearer {self._token()}")

        self.assertEqual(principal.tenant_id, TENANT_ID)
        self.assertEqual(principal.subject_id, SUBJECT_ID)
        self.assertEqual(principal.client_id, CLIENT_ID)
        self.assertEqual(principal.scopes, frozenset({"access_as_user"}))
        self.assertIsInstance(principal.issued_at_unix, int)
        self.assertEqual(self.keys.requested, [KID])

    def test_header_and_token_shape_fail_uniformly(self) -> None:
        for authorization in (
            None,
            "",
            "Basic secret",
            "Bearer",
            "Bearer one two",
            f"Bearer {'x' * 16_385}",
        ):
            with self.subTest(authorization=authorization):
                with self.assertRaises(AuthenticationFailure) as raised:
                    self.authenticator.authenticate(authorization)
                self.assertEqual(
                    raised.exception.code,
                    (
                        "AUTHENTICATION_REQUIRED"
                        if authorization is None
                        else "INVALID_ACCESS_TOKEN"
                    ),
                )

    def test_claim_validation_rejects_wrong_resource_or_identity(self) -> None:
        mutations = {
            "iss": "https://login.microsoftonline.com/common/v2.0",
            "aud": "00000003-0000-0000-c000-000000000000",
            "tid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "oid": "not-a-guid",
            "azp": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "scp": "User.Read",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                claims = self._claims()
                claims[field] = value
                self.assertEqual(
                    self._failure(self._token(claims)).code,
                    "INVALID_ACCESS_TOKEN",
                )

    def test_missing_required_claims_and_app_only_tokens_are_rejected(self) -> None:
        for field in (
            "iss",
            "aud",
            "exp",
            "nbf",
            "iat",
            "tid",
            "oid",
            "azp",
            "scp",
        ):
            with self.subTest(field=field):
                claims = self._claims()
                claims.pop(field)
                self.assertEqual(
                    self._failure(self._token(claims)).code,
                    "INVALID_ACCESS_TOKEN",
                )

        claims = self._claims()
        claims.pop("scp")
        claims["roles"] = ["Yap.Access"]
        claims["idtyp"] = "app"
        self.assertEqual(
            self._failure(self._token(claims)).code,
            "INVALID_ACCESS_TOKEN",
        )

    def test_expired_future_and_bad_signature_tokens_are_rejected(self) -> None:
        now = datetime.now(UTC)
        expired = self._claims()
        expired["exp"] = now - timedelta(minutes=5)
        self.assertEqual(
            self._failure(self._token(expired)).code,
            "INVALID_ACCESS_TOKEN",
        )

        future = self._claims()
        future["nbf"] = now + timedelta(minutes=5)
        self.assertEqual(
            self._failure(self._token(future)).code,
            "INVALID_ACCESS_TOKEN",
        )

        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.assertEqual(
            self._failure(self._token(private_key=other_key)).code,
            "INVALID_ACCESS_TOKEN",
        )

    def test_algorithm_and_unknown_key_fail_closed(self) -> None:
        unsigned = jwt.encode(
            self._claims(),
            key="",
            algorithm="none",
            headers={"kid": KID},
        )
        self.assertEqual(
            self._failure(unsigned).code,
            "INVALID_ACCESS_TOKEN",
        )
        self.assertEqual(
            self._failure(self._token(kid=f"unknown-{uuid4().hex}")).code,
            "INVALID_ACCESS_TOKEN",
        )

    def test_key_service_unavailability_is_typed_and_retryable(self) -> None:
        self.keys.failure = SigningKeyUnavailable("offline")

        failure = self._failure(self._token())

        self.assertEqual(failure.status, 503)
        self.assertEqual(failure.code, "AUTHENTICATION_UNAVAILABLE")
        self.assertTrue(failure.retryable)
