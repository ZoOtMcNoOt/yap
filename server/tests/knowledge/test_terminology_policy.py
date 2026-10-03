from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.terminology_policy import (
    TERMINOLOGY_POLICY_FILE,
    TerminologyPolicy,
    build_terminology_policy,
)


def policy_payload(tenant="tenant-a"):
    return {
        "tenants": [
            {
                "tenantId": tenant,
                "label": "Example organization",
                "administratorRoles": ["terminology.manager"],
                "teams": [
                    {
                        "teamId": "clinical",
                        "label": "Clinical team",
                        "members": ["alice", "bob"],
                        "managers": ["alice"],
                    },
                    {
                        "teamId": "research",
                        "label": "Research team",
                        "members": ["carol"],
                        "managers": ["carol"],
                    },
                ],
            }
        ]
    }


def principal(subject="alice", tenant="tenant-a", roles=()):
    return AuthenticatedPrincipal(
        tenant, subject, "desktop", frozenset(), roles=frozenset(roles)
    )


class TerminologyPolicyTests(unittest.TestCase):
    def test_absent_policy_exposes_only_personal_even_with_admin_claim(self):
        policy = build_terminology_policy({}, authenticated_team_mode=True)
        self.assertEqual(
            [
                s.scope_id
                for s in policy.scopes(principal(roles=["knowledge.terminology.admin"]))
            ],
            ["personal"],
        )
        self.assertFalse(policy.authorization(principal()).may_manage_organization)

    def test_visibility_management_and_role_policy_are_distinct_and_tenant_bound(self):
        policy = TerminologyPolicy.from_payload(policy_payload())
        scopes = {s.scope_id: s for s in policy.scopes(principal("bob"))}
        self.assertEqual(set(scopes), {"personal", "organization", "team:clinical"})
        self.assertFalse(scopes["team:clinical"].can_manage)
        self.assertFalse(scopes["organization"].can_manage)
        self.assertEqual(scopes["team:clinical"].label, "Clinical team")
        self.assertTrue(policy.authorization(principal()).managed_team_ids)
        self.assertFalse(
            policy.authorization(
                principal(roles=["knowledge.terminology.admin"])
            ).may_manage_organization
        )
        self.assertTrue(
            policy.authorization(
                principal(roles=["terminology.manager"])
            ).may_manage_organization
        )
        self.assertEqual(
            [s.scope_id for s in policy.scopes(principal(tenant="other"))], ["personal"]
        )
        self.assertNotIn("ownerId", scopes["team:clinical"].wire())

    def test_invalid_or_excessive_grants_and_unknown_fields_fail_closed(self):
        mutations = [
            lambda p: p["tenants"][0]["teams"][0].update(managers=["stranger"]),
            lambda p: p["tenants"][0]["teams"][0].update(members=["alice", "alice"]),
            lambda p: p["tenants"][0]["teams"][0].update(teamId="../other"),
            lambda p: p["tenants"][0]["teams"][0].update(label="hidden\nlabel"),
            lambda p: p["tenants"][0].update(administratorRoles=[]),
            lambda p: p["tenants"][0].update(administratorRoles=["bad role"]),
            lambda p: p["tenants"][0].update(teams=p["tenants"][0]["teams"] * 17),
            lambda p: p["tenants"].append(deepcopy(p["tenants"][0])),
            lambda p: p.update(owner="forged"),
        ]
        for mutation in mutations:
            value = policy_payload()
            mutation(value)
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                TerminologyPolicy.from_payload(value)

    def test_loaded_policy_is_immutable_and_not_request_owned(self):
        value = policy_payload()
        policy = TerminologyPolicy.from_payload(value)
        value["tenants"][0]["teams"][0]["managers"].append("bob")
        self.assertEqual(policy.managed_team_ids_for(principal("bob").key), ())

    def test_runtime_requires_authentication_private_regular_bounded_configuration(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "policy.json"
            path.write_text(json.dumps(policy_payload()))
            path.chmod(0o600)
            env = {TERMINOLOGY_POLICY_FILE: str(path)}
            self.assertEqual(
                build_terminology_policy(
                    env, authenticated_team_mode=True
                ).team_ids_for(principal().key),
                ("clinical",),
            )
            with self.assertRaisesRegex(ValueError, "authentication"):
                build_terminology_policy(env, authenticated_team_mode=False)
            for content in ("not-json", "x" * 65_537, '{"tenants":[],"tenants":[]}'):
                path.write_text(content)
                with self.assertRaisesRegex(
                    ValueError, "unavailable or invalid"
                ) as failure:
                    build_terminology_policy(env, authenticated_team_mode=True)
                self.assertTrue(failure.exception.__suppress_context__)
            if os.name == "posix":
                path.write_text(json.dumps(policy_payload()))
                path.chmod(0o644)
                with self.assertRaises(ValueError):
                    build_terminology_policy(env, authenticated_team_mode=True)
                path.chmod(0o600)
                link = Path(temporary) / "link.json"
                link.symlink_to(path)
                with self.assertRaises(ValueError):
                    build_terminology_policy(
                        {TERMINOLOGY_POLICY_FILE: str(link)},
                        authenticated_team_mode=True,
                    )
                fifo = Path(temporary) / "fifo"
                os.mkfifo(fifo)
                with self.assertRaises(ValueError):
                    build_terminology_policy(
                        {TERMINOLOGY_POLICY_FILE: str(fifo)},
                        authenticated_team_mode=True,
                    )
