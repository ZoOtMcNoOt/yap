from __future__ import annotations

import unittest

from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey
from yap_server.knowledge.terminology_authorization import (
    resolve_terminology_authorization,
)


class _Memberships:
    def __init__(self, team_ids: tuple[str, ...]) -> None:
        self._team_ids = team_ids
        self.seen: PrincipalKey | None = None

    def team_ids_for(self, principal: PrincipalKey) -> tuple[str, ...]:
        self.seen = principal
        return self._team_ids


class TerminologyAuthorizationTests(unittest.TestCase):
    def test_derives_membership_and_admin_from_trusted_identity_inputs(self) -> None:
        memberships = _Memberships(("team-b", "team-a"))
        principal = AuthenticatedPrincipal(
            "tenant-1",
            "person-1",
            "desktop-client",
            frozenset({"knowledge.read"}),
            roles=frozenset({"knowledge.admin"}),
        )

        authorization = resolve_terminology_authorization(
            principal,
            memberships=memberships,
            administrator_roles=frozenset({"knowledge.admin"}),
        )

        self.assertEqual(memberships.seen, principal.key)
        self.assertEqual(authorization.team_ids, ("team-a", "team-b"))
        self.assertTrue(authorization.may_manage_organization)

    def test_untrusted_request_values_are_not_an_authorization_input(self) -> None:
        principal = AuthenticatedPrincipal(
            "tenant-1",
            "person-1",
            "desktop-client",
            frozenset({"knowledge.read"}),
        )
        authorization = resolve_terminology_authorization(
            principal,
            memberships=_Memberships(()),
            administrator_roles=frozenset({"knowledge.admin"}),
        )
        self.assertEqual(authorization.team_ids, ())
        self.assertFalse(authorization.may_manage_organization)

    def test_rejects_duplicated_resolved_membership(self) -> None:
        principal = AuthenticatedPrincipal(
            "tenant-1",
            "person-1",
            "desktop-client",
            frozenset({"knowledge.read"}),
        )
        with self.assertRaisesRegex(ValueError, "duplicated"):
            resolve_terminology_authorization(
                principal,
                memberships=_Memberships(("team-a", "team-a")),
                administrator_roles=frozenset({"knowledge.admin"}),
            )


if __name__ == "__main__":
    unittest.main()
