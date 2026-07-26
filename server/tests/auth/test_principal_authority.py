from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from yap_server.auth import AuthenticatedPrincipal


class AuthenticatedPrincipalAuthorityTests(unittest.TestCase):
    def test_expiry_and_roles_are_bounded_immutable_authority(self) -> None:
        principal = AuthenticatedPrincipal(
            tenant_id="00000000-0000-4000-8000-000000000071",
            subject_id="00000000-0000-4000-8000-000000000073",
            client_id="00000000-0000-4000-8000-000000000074",
            scopes=frozenset({"access_as_user"}),
            issued_at_unix=1_700_000_000,
            expires_at_unix=1_700_000_300,
            roles=frozenset({"Yap.IdentityAdministrator"}),
        )

        self.assertEqual(principal.expires_at_unix, 1_700_000_300)
        self.assertEqual(
            principal.roles,
            frozenset({"Yap.IdentityAdministrator"}),
        )
        with self.assertRaises(FrozenInstanceError):
            principal.expires_at_unix = 1  # type: ignore[misc]

    def test_development_principal_may_have_no_token_expiry(self) -> None:
        principal = AuthenticatedPrincipal(
            tenant_id="development-loopback",
            subject_id="local-server",
            client_id="yap-development-client",
            scopes=frozenset({"access_as_user"}),
        )

        self.assertIsNone(principal.expires_at_unix)
        self.assertEqual(principal.roles, frozenset())

    def test_invalid_expiry_and_role_shapes_are_rejected(self) -> None:
        common = {
            "tenant_id": "00000000-0000-4000-8000-000000000071",
            "subject_id": "00000000-0000-4000-8000-000000000073",
            "client_id": "00000000-0000-4000-8000-000000000074",
            "scopes": frozenset({"access_as_user"}),
            "issued_at_unix": 100,
        }
        for expiry in (-1, True, 99, 253_402_300_800):
            with self.subTest(expiry=expiry):
                with self.assertRaises(ValueError):
                    AuthenticatedPrincipal(
                        **common,
                        expires_at_unix=expiry,
                    )

        with self.assertRaises(TypeError):
            AuthenticatedPrincipal(
                **common,
                expires_at_unix=101,
                roles={"Yap.IdentityAdministrator"},  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
