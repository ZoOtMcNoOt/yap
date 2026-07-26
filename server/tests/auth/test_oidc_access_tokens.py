from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from yap_server.auth import AuthenticationFailure
from yap_server.auth.oidc_access_tokens import (
    OidcAccessTokenAuthenticator,
    OidcAccessTokenPolicy,
)
from yap_server.auth.oidc_metadata import SigningKeyUnavailable


TENANT_ID = "00000000-0000-4000-8000-000000000071"
OTHER_TENANT_ID = "00000000-0000-4000-8000-000000000072"
SUBJECT_ID = "00000000-0000-4000-8000-000000000073"
CLIENT_ID = "00000000-0000-4000-8000-000000000074"
AUDIENCE = "00000000-0000-4000-8000-000000000075"
ISSUER = "https://issuer.example.test/yap"
KID = "synthetic-test-signing-key"
ADMIN_ROLE = "Yap.IdentityAdministrator"


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


class OidcAccessTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.public_key = cls.private_key.public_key()

    def setUp(self) -> None:
        self.keys = _SigningKeys(self.public_key)
        self.policy = OidcAccessTokenPolicy(
            issuer=ISSUER,
            audience=AUDIENCE,
            tenant_id_claim="tid",
            subject_id_claim="oid",
            client_id_claim="azp",
            scope_claim="scp",
            roles_claim="roles",
            identity_format="uuid",
            allowed_tenant_ids=frozenset({TENANT_ID}),
            allowed_client_ids=frozenset({CLIENT_ID}),
            required_scopes=frozenset({"access_as_user"}),
            allowed_roles=frozenset({ADMIN_ROLE}),
            required_claim_values=(("ver", "2.0"),),
            optional_claim_values=(("token_use", frozenset({"access_token"})),),
            rejected_claim_values=(("idtyp", frozenset({"app"})),),
        )
        self.authenticator = OidcAccessTokenAuthenticator(self.policy, self.keys)

    def _claims(self) -> dict[str, object]:
        now = datetime.now(UTC)
        return {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "ver": "2.0",
            "exp": now + timedelta(minutes=5),
            "nbf": now - timedelta(minutes=1),
            "iat": now - timedelta(seconds=1),
            "tid": TENANT_ID,
            "oid": SUBJECT_ID,
            "azp": CLIENT_ID,
            "scp": "access_as_user",
            "roles": [ADMIN_ROLE, "Unconfigured.Role"],
        }

    def _token(
        self,
        claims: dict[str, object] | None = None,
        *,
        private_key: object | None = None,
        algorithm: str = "RS256",
        kid: str | None = KID,
        token_type: str | None = "at+jwt",
    ) -> str:
        headers: dict[str, object] = {}
        if kid is not None:
            headers["kid"] = kid
        if token_type is not None:
            headers["typ"] = token_type
        return jwt.encode(
            self._claims() if claims is None else claims,
            self.private_key if private_key is None else private_key,
            algorithm=algorithm,
            headers=headers,
        )

    def _failure(
        self,
        token: str,
        authenticator: OidcAccessTokenAuthenticator | None = None,
    ) -> AuthenticationFailure:
        active = self.authenticator if authenticator is None else authenticator
        with self.assertRaises(AuthenticationFailure) as raised:
            active.authenticate(f"Bearer {token}")
        return raised.exception

    def test_valid_access_token_returns_bounded_immutable_authority(self) -> None:
        principal = self.authenticator.authenticate(f"Bearer {self._token()}")

        self.assertEqual(principal.tenant_id, TENANT_ID)
        self.assertEqual(principal.subject_id, SUBJECT_ID)
        self.assertEqual(principal.client_id, CLIENT_ID)
        self.assertEqual(principal.scopes, frozenset({"access_as_user"}))
        self.assertEqual(principal.roles, frozenset({ADMIN_ROLE}))
        self.assertIsInstance(principal.issued_at_unix, int)
        self.assertIsInstance(principal.expires_at_unix, int)
        assert principal.issued_at_unix is not None
        assert principal.expires_at_unix is not None
        self.assertGreater(principal.expires_at_unix, principal.issued_at_unix)
        self.assertEqual(self.keys.requested, [KID])

    def test_provider_neutral_claim_mapping_is_policy_owned(self) -> None:
        policy = OidcAccessTokenPolicy(
            issuer=ISSUER,
            audience="yap-api",
            tenant_id_claim="realm",
            subject_id_claim="sub",
            client_id_claim="client_id",
            scope_claim="scope",
            roles_claim="permissions",
            identity_format="bounded_text",
            allowed_tenant_ids=frozenset({"clinical-research"}),
            allowed_client_ids=frozenset({"desktop-client"}),
            required_scopes=frozenset({"transcribe"}),
            allowed_roles=frozenset({"reviewer"}),
            required_claim_values=(("token_kind", "access"),),
            optional_claim_values=(("actor_kind", frozenset({"human", "service"})),),
            rejected_claim_values=(("grant_kind", frozenset({"application"})),),
        )
        authenticator = OidcAccessTokenAuthenticator(policy, self.keys)
        now = datetime.now(UTC)
        token = self._token(
            {
                "iss": ISSUER,
                "aud": "yap-api",
                "exp": now + timedelta(minutes=5),
                "nbf": now - timedelta(seconds=1),
                "iat": now - timedelta(seconds=1),
                "realm": "clinical-research",
                "sub": "person-42",
                "client_id": "desktop-client",
                "scope": "transcribe",
                "permissions": ["reviewer"],
                "token_kind": "access",
                "actor_kind": "human",
            }
        )

        principal = authenticator.authenticate(f"Bearer {token}")

        self.assertEqual(principal.tenant_id, "clinical-research")
        self.assertEqual(principal.subject_id, "person-42")
        self.assertEqual(principal.client_id, "desktop-client")
        self.assertEqual(principal.scopes, frozenset({"transcribe"}))
        self.assertEqual(principal.roles, frozenset({"reviewer"}))

        invalid_claims = (
            ("token_kind", "id"),
            ("actor_kind", "robot"),
            ("grant_kind", "application"),
        )
        for claim_name, claim_value in invalid_claims:
            with self.subTest(claim_name=claim_name):
                claims = jwt.decode(
                    token,
                    options={"verify_signature": False},
                )
                claims[claim_name] = claim_value
                failure = self._failure(
                    self._token(claims),
                    authenticator,
                )
                self.assertEqual(failure.code, "INVALID_ACCESS_TOKEN")

    def test_authorization_header_shape_fails_uniformly(self) -> None:
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

    def test_resource_issuer_tenant_client_and_identity_fail_closed(self) -> None:
        mutations = (
            ("iss", "https://wrong.example.test/yap"),
            ("iss", "not-an-issuer"),
            ("aud", "00000003-0000-0000-c000-000000000000"),
            ("aud", "https://unrelated.example.test/api"),
            ("tid", OTHER_TENANT_ID),
            ("tid", "not-a-guid"),
            ("oid", "not-a-guid"),
            ("azp", "00000000-0000-4000-8000-000000000099"),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                claims = self._claims()
                claims[field] = value
                self.assertEqual(
                    self._failure(self._token(claims)).code,
                    "INVALID_ACCESS_TOKEN",
                )

        claims = self._claims()
        claims["aud"] = [
            AUDIENCE,
            "00000003-0000-0000-c000-000000000000",
        ]
        self.assertEqual(
            self._failure(self._token(claims)).code,
            "INVALID_ACCESS_TOKEN",
        )

    def test_all_authority_and_time_claims_are_required(self) -> None:
        for field in (
            "iss",
            "aud",
            "exp",
            "nbf",
            "iat",
            "ver",
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

    def test_scope_and_configured_role_policy_is_explicit(self) -> None:
        claims = self._claims()
        claims["scp"] = "User.Read"
        failure = self._failure(self._token(claims))
        self.assertEqual((failure.status, failure.code), (403, "INSUFFICIENT_SCOPE"))

        required_role_policy = OidcAccessTokenPolicy(
            issuer=ISSUER,
            audience=AUDIENCE,
            tenant_id_claim="tid",
            subject_id_claim="oid",
            client_id_claim="azp",
            scope_claim="scp",
            roles_claim="roles",
            identity_format="uuid",
            allowed_tenant_ids=frozenset({TENANT_ID}),
            allowed_client_ids=frozenset({CLIENT_ID}),
            required_scopes=frozenset({"access_as_user"}),
            allowed_roles=frozenset({ADMIN_ROLE}),
            required_roles=frozenset({ADMIN_ROLE}),
            required_claim_values=(("ver", "2.0"),),
            optional_claim_values=(("token_use", frozenset({"access_token"})),),
            rejected_claim_values=(("idtyp", frozenset({"app"})),),
        )
        required_role_authenticator = OidcAccessTokenAuthenticator(
            required_role_policy,
            self.keys,
        )
        claims = self._claims()
        claims.pop("roles")
        failure = self._failure(
            self._token(claims),
            required_role_authenticator,
        )
        self.assertEqual((failure.status, failure.code), (403, "INSUFFICIENT_ROLE"))

        claims["roles"] = ["Yap.TranscriptReviewer"]
        failure = self._failure(
            self._token(claims),
            required_role_authenticator,
        )
        self.assertEqual((failure.status, failure.code), (403, "INSUFFICIENT_ROLE"))

        claims = self._claims()
        claims["roles"] = ADMIN_ROLE
        self.assertEqual(
            self._failure(self._token(claims)).code,
            "INVALID_ACCESS_TOKEN",
        )

    def test_expiry_not_before_issued_at_and_skew_are_enforced(self) -> None:
        now = datetime.now(UTC)
        mutations = (
            ("exp", now - timedelta(seconds=61)),
            ("nbf", now + timedelta(seconds=61)),
            ("iat", now + timedelta(seconds=61)),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                claims = self._claims()
                claims[field] = value
                self.assertEqual(
                    self._failure(self._token(claims)).code,
                    "INVALID_ACCESS_TOKEN",
                )

        within_skew = self._claims()
        within_skew["nbf"] = now + timedelta(seconds=30)
        principal = self.authenticator.authenticate(
            f"Bearer {self._token(within_skew)}"
        )
        self.assertEqual(principal.key.tenant_id, TENANT_ID)

    def test_id_app_and_non_access_token_types_are_rejected(self) -> None:
        self.assertEqual(
            self._failure(self._token(token_type="id+jwt")).code,
            "INVALID_ACCESS_TOKEN",
        )

        for claim, value in (("idtyp", "app"), ("token_use", "id_token")):
            with self.subTest(claim=claim):
                claims = self._claims()
                claims[claim] = value
                self.assertEqual(
                    self._failure(self._token(claims)).code,
                    "INVALID_ACCESS_TOKEN",
                )

    def test_signature_algorithm_and_key_identity_fail_closed(self) -> None:
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        signed = self._token()
        parts = signed.split(".")
        signature = parts[2]
        replacement = "A" if signature[0] != "A" else "B"
        tampered = ".".join((parts[0], parts[1], f"{replacement}{signature[1:]}"))
        cases = (
            self._token(private_key=other_key),
            tampered,
            self._token(kid=f"unknown-{uuid4().hex}"),
            self._token(kid=None),
            jwt.encode(
                self._claims(),
                key="",
                algorithm="none",
                headers={"kid": KID, "typ": "at+jwt"},
            ),
            jwt.encode(
                self._claims(),
                key="synthetic-secret-that-is-at-least-32-bytes",
                algorithm="HS256",
                headers={"kid": KID, "typ": "at+jwt"},
            ),
        )
        for token in cases:
            with self.subTest(header=jwt.get_unverified_header(token)):
                self.assertEqual(
                    self._failure(token).code,
                    "INVALID_ACCESS_TOKEN",
                )

    def test_same_subject_in_different_tenants_has_a_distinct_principal_key(
        self,
    ) -> None:
        policy = OidcAccessTokenPolicy(
            issuer=ISSUER,
            audience=AUDIENCE,
            tenant_id_claim="tid",
            subject_id_claim="oid",
            client_id_claim="azp",
            scope_claim="scp",
            identity_format="uuid",
            allowed_tenant_ids=frozenset({TENANT_ID, OTHER_TENANT_ID}),
            allowed_client_ids=frozenset({CLIENT_ID}),
            required_scopes=frozenset({"access_as_user"}),
            required_claim_values=(("ver", "2.0"),),
        )
        authenticator = OidcAccessTokenAuthenticator(policy, self.keys)
        first = authenticator.authenticate(f"Bearer {self._token()}")
        claims = self._claims()
        claims["tid"] = OTHER_TENANT_ID
        second = authenticator.authenticate(f"Bearer {self._token(claims)}")

        self.assertEqual(first.subject_id, second.subject_id)
        self.assertNotEqual(first.key, second.key)

    def test_key_service_unavailability_is_typed_and_retryable(self) -> None:
        self.keys.failure = SigningKeyUnavailable("offline")

        failure = self._failure(self._token())

        self.assertEqual(failure.status, 503)
        self.assertEqual(failure.code, "AUTHENTICATION_UNAVAILABLE")
        self.assertTrue(failure.retryable)


if __name__ == "__main__":
    unittest.main()
