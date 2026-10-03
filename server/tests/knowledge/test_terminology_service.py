from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import threading
import unittest
from uuid import uuid4

import psycopg

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.terminology_service import (
    TerminologyService,
    TerminologyServiceError,
)
from yap_server.knowledge.terminology_authorization import TerminologyAuthorization
from yap_server.knowledge.terminology_policy import TerminologyPolicy
from yap_server.agents.transcript_correction_terminology import (
    PostgresTranscriptCorrectionTerminologyResolver,
)
from .test_terminology_policy import policy_payload
from yap_server.knowledge.terminology_ledger import (
    bind_job_terminology_snapshot,
    read_job_terminology_snapshot,
)

DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class PersonalTerminologyTests(unittest.TestCase):
    def setUp(self):
        self.tenant = f"tenant-{uuid4().hex}"
        self.alice = AuthenticatedPrincipal(
            self.tenant, "alice", "desktop", frozenset({"knowledge.read"})
        )
        self.bob = AuthenticatedPrincipal(
            self.tenant, "bob", "desktop", frozenset({"knowledge.read"})
        )
        self.other_tenant = AuthenticatedPrincipal(
            f"other-{uuid4().hex}", "alice", "desktop", frozenset({"knowledge.read"})
        )
        self.service = TerminologyService(connection_factory=self.connect)

    @contextmanager
    def connect(self):
        with psycopg.connect(
            DSN,
            connect_timeout=3,
            options="-c statement_timeout=3000 -c lock_timeout=3000",
        ) as connection:
            yield connection

    def tearDown(self):
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM yap_terminology_job_bindings WHERE tenant_id IN (%s, %s)",
                (self.tenant, self.other_tenant.tenant_id),
            )
            connection.execute(
                "DELETE FROM yap_terminology_snapshots WHERE tenant_id IN (%s, %s)",
                (self.tenant, self.other_tenant.tenant_id),
            )
            connection.execute(
                "DELETE FROM yap_terminology_records WHERE tenant_id IN (%s, %s)",
                (self.tenant, self.other_tenant.tenant_id),
            )

    def test_creation_retry_is_owner_scoped_and_preserves_the_original_receipt(self):
        body = _body()
        created = self.service.create(body, principal=self.alice)
        self.assertEqual(self.service.create(body, principal=self.alice), created)
        self.assertNotEqual(
            self.service.create(body, principal=self.bob)["recordId"],
            created["recordId"],
        )
        self.assertNotEqual(
            self.service.create(body, principal=self.other_tenant)["recordId"],
            created["recordId"],
        )
        with self.assertRaises(TerminologyServiceError) as error:
            self.service.create(
                {**body, "canonicalForm": "Changed"}, principal=self.alice
            )
        self.assertEqual(error.exception.status, 409)
        self.service.update(created["recordId"], _edit(1, "YAP"), principal=self.alice)
        self.assertEqual(self.service.create(body, principal=self.alice), created)
        self.assertEqual(
            self.service.get(created["recordId"], principal=self.alice)["version"], 2
        )
        with self.connect() as connection:
            count = connection.execute(
                "SELECT count(*) FROM yap_terminology_records WHERE tenant_id = %s AND owner_id = %s",
                (self.tenant, self.alice.subject_id),
            ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_create_read_edit_delete_preserves_history_and_reconnect_identity(self):
        created = self.service.create(_body(), principal=self.alice)
        self.assertEqual(created["version"], 1)
        self.assertNotIn("ownerId", created)
        restored = TerminologyService(connection_factory=self.connect)
        self.assertEqual(
            restored.get(created["recordId"], principal=self.alice)["canonicalForm"],
            "Yap",
        )
        self.assertEqual(
            restored.list(principal=self.alice, locale="en-US")["records"][0][
                "recordId"
            ],
            created["recordId"],
        )
        updated = restored.update(
            created["recordId"], _edit(1, "YAP"), principal=self.alice
        )
        self.assertEqual(updated["version"], 2)
        deleted = restored.delete(
            created["recordId"], {"expectedVersion": 2}, principal=self.alice
        )
        self.assertEqual(
            deleted,
            {
                "scopeId": "personal",
                "recordId": created["recordId"],
                "version": 3,
                "deleted": True,
            },
        )
        self.assertEqual(
            restored.list(principal=self.alice, locale="en-US")["records"], []
        )
        with self.assertRaises(TerminologyServiceError) as error:
            restored.get(created["recordId"], principal=self.alice)
        self.assertEqual(error.exception.status, 404)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT version, canonical_form, deleted FROM yap_terminology_records WHERE tenant_id = %s AND record_id = %s ORDER BY version",
                (self.tenant, created["recordId"]),
            ).fetchall()
        self.assertEqual(rows, [(1, "Yap", False), (2, "YAP", False), (3, "YAP", True)])

    def test_other_owners_and_tenants_cannot_read_edit_delete_or_list_terms(self):
        created = self.service.create(_body(), principal=self.alice)
        for principal in (self.bob, self.other_tenant):
            with self.subTest(principal=principal.key):
                self.assertEqual(
                    self.service.list(principal=principal, locale="en-US")["records"],
                    [],
                )
                operations = (
                    lambda: self.service.get(created["recordId"], principal=principal),
                    lambda: self.service.update(
                        created["recordId"], _edit(1, "Other"), principal=principal
                    ),
                    lambda: self.service.delete(
                        created["recordId"], {"expectedVersion": 1}, principal=principal
                    ),
                )
                for operation in operations:
                    with self.assertRaises(TerminologyServiceError) as error:
                        operation()
                    self.assertEqual(error.exception.status, 404)
        self.assertEqual(
            self.service.get(created["recordId"], principal=self.alice)["version"], 1
        )

    def test_concurrent_expected_version_has_one_winner_and_keeps_the_original(self):
        created = self.service.create(_body(), principal=self.alice)
        barrier = threading.Barrier(2)

        def update(text):
            barrier.wait(timeout=5)
            try:
                return self.service.update(
                    created["recordId"], _edit(1, text), principal=self.alice
                )["version"]
            except TerminologyServiceError as error:
                return error.status

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(update, ("First", "Second")))
        self.assertCountEqual(results, [2, 409])
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT version, canonical_form FROM yap_terminology_records WHERE tenant_id = %s AND record_id = %s ORDER BY version",
                (self.tenant, created["recordId"]),
            ).fetchall()
        self.assertEqual(rows[0], (1, "Yap"))
        self.assertEqual(len(rows), 2)

    def test_old_job_snapshot_stays_frozen_and_new_job_observes_the_edit(self):
        created = self.service.create(_body(), principal=self.alice)
        authority = TerminologyAuthorization(self.alice.key, (), (), False)
        with self.connect() as connection:
            original = bind_job_terminology_snapshot(
                connection, job_id="job-before", authorization=authority, locale="en-US"
            )
        self.service.update(created["recordId"], _edit(1, "YAP"), principal=self.alice)
        with self.connect() as connection:
            old = read_job_terminology_snapshot(
                connection, principal=self.alice.key, job_id="job-before"
            )
            new = bind_job_terminology_snapshot(
                connection, job_id="job-after", authorization=authority, locale="en-US"
            )
        self.assertEqual(old, original)
        self.assertEqual(old.entries[0].canonical_form, "Yap")
        self.assertEqual(new.entries[0].canonical_form, "YAP")
        self.assertNotEqual(new.snapshot_sha256, old.snapshot_sha256)

    def test_listing_is_bounded_owner_filtered_and_includes_language_independent_terms(
        self,
    ):
        expected = []
        for index in range(12):
            body = _body()
            body["canonicalForm"] = f"Term{index}"
            body["variants"] = [f"term{index}"]
            if index == 0:
                body["locale"] = "und"
            expected.append(self.service.create(body, principal=self.alice)["recordId"])
        self.service.create({**_body(), "locale": "fr-FR"}, principal=self.alice)
        self.service.create(_body(), principal=self.bob)
        first = self.service.list(principal=self.alice, locale="en-US")
        self.assertEqual(len(first["records"]), 10)
        second = self.service.list(
            principal=self.alice, locale="en-US", after=first["nextCursor"]
        )
        self.assertIsNone(second["nextCursor"])
        self.assertCountEqual(
            [row["recordId"] for row in first["records"] + second["records"]], expected
        )

    def test_forged_identity_extra_fields_invalid_versions_and_variants_do_not_write(
        self,
    ):
        for extra in ("ownerId", "tenantId", "scope", "managedTeamIds"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.service.create({**_body(), extra: "forged"}, principal=self.alice)
        for variants in ([], ["yap", "YAP"], ["x"] * 65, "yap"):
            with (
                self.subTest(variants=variants),
                self.assertRaises((ValueError, TypeError)),
            ):
                self.service.create(
                    {**_body(), "variants": variants}, principal=self.alice
                )
        created = self.service.create(_body(), principal=self.alice)
        for version in (True, 0, 1.0, -1):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.service.update(
                    created["recordId"], _edit(version, "Other"), principal=self.alice
                )
        self.assertEqual(
            self.service.get(created["recordId"], principal=self.alice)["version"], 1
        )

    def shared(self):
        self.policy = TerminologyPolicy.from_payload(policy_payload(self.tenant))
        self.service = TerminologyService(
            connection_factory=self.connect, policy=self.policy
        )
        return self.service

    def test_shared_visibility_does_not_grant_mutation_or_creation_replay(self):
        service = self.shared()
        body = _body()
        term = service.create(body, principal=self.alice, scope_id="team:clinical")
        self.assertEqual(
            service.get(term["recordId"], principal=self.bob, scope_id="team:clinical"),
            term,
        )
        for operation in (
            lambda: service.create(body, principal=self.bob, scope_id="team:clinical"),
            lambda: service.update(
                term["recordId"],
                _edit(1, "Other"),
                principal=self.bob,
                scope_id="team:clinical",
            ),
            lambda: service.delete(
                term["recordId"],
                {"expectedVersion": 1},
                principal=self.bob,
                scope_id="team:clinical",
            ),
        ):
            with self.assertRaises(TerminologyServiceError) as failure:
                operation()
            self.assertEqual(failure.exception.status, 403)
        # Even the creator loses replay authority after an operator revokes management.
        payload = policy_payload(self.tenant)
        payload["tenants"][0]["teams"][0]["managers"] = []
        revoked = TerminologyService(
            connection_factory=self.connect,
            policy=TerminologyPolicy.from_payload(payload),
        )
        with self.assertRaises(TerminologyServiceError) as failure:
            revoked.create(body, principal=self.alice, scope_id="team:clinical")
        self.assertEqual(failure.exception.status, 403)
        self.assertEqual(
            service.get(
                term["recordId"], principal=self.alice, scope_id="team:clinical"
            )["version"],
            1,
        )

    def test_shared_reads_and_writes_cannot_cross_scope_or_tenant(self):
        service = self.shared()
        term = service.create(_body(), principal=self.alice, scope_id="team:clinical")
        for principal, scope in (
            (self.alice, "personal"),
            (self.alice, "organization"),
            (self.alice, "team:research"),
            (self.other_tenant, "team:clinical"),
        ):
            with self.subTest(principal=principal.key, scope=scope):
                with self.assertRaises(TerminologyServiceError) as failure:
                    service.get(term["recordId"], principal=principal, scope_id=scope)
                self.assertEqual(failure.exception.status, 404)
        self.assertEqual(
            [
                s["scopeId"]
                for s in service.scopes(principal=self.other_tenant)["scopes"]
            ],
            ["personal"],
        )
        self.assertEqual(
            service.list(principal=self.bob, scope_id="organization", locale="en-US")[
                "records"
            ],
            [],
        )

    def test_organization_management_uses_only_the_configured_authenticated_role(self):
        service = self.shared()
        for roles in ((), ("knowledge.terminology.admin",)):
            actor = AuthenticatedPrincipal(
                self.tenant, "alice", "desktop", frozenset(), roles=frozenset(roles)
            )
            with self.assertRaises(TerminologyServiceError) as failure:
                service.create(_body(), principal=actor, scope_id="organization")
            self.assertEqual(failure.exception.status, 403)
        administrator = AuthenticatedPrincipal(
            self.tenant,
            "alice",
            "desktop",
            frozenset(),
            roles=frozenset({"terminology.manager"}),
        )
        term = service.create(_body(), principal=administrator, scope_id="organization")
        self.assertEqual(
            service.get(term["recordId"], principal=self.bob, scope_id="organization"),
            term,
        )
        with self.assertRaises(ValueError):
            service.create(
                {**_body(), "roles": ["terminology.manager"]},
                principal=administrator,
                scope_id="organization",
            )
        service.delete(
            term["recordId"],
            {"expectedVersion": 1},
            principal=administrator,
            scope_id="organization",
        )
        self.assertEqual(
            service.list(principal=self.alice, scope_id="organization", locale="en-US")[
                "records"
            ],
            [],
        )

    def test_shared_replay_tombstone_and_snapshot_keep_existing_personal_data(self):
        body = _body()
        personal = self.service.create(body, principal=self.alice)
        service = self.shared()
        self.assertEqual(service.create(body, principal=self.alice), personal)
        shared = service.create(body, principal=self.alice, scope_id="team:clinical")
        self.assertNotEqual(shared["recordId"], personal["recordId"])
        with self.connect() as connection:
            frozen = bind_job_terminology_snapshot(
                connection,
                job_id="shared-before",
                authorization=self.policy.authorization(self.bob),
                locale="en-US",
            )
        service.update(
            shared["recordId"],
            _edit(1, "Shared Yap"),
            principal=self.alice,
            scope_id="team:clinical",
        )
        with self.assertRaises(TerminologyServiceError) as failure:
            service.update(
                shared["recordId"],
                _edit(1, "Lost write"),
                principal=self.alice,
                scope_id="team:clinical",
            )
        self.assertEqual(failure.exception.status, 409)
        resolver = PostgresTranscriptCorrectionTerminologyResolver(
            connection_factory=self.connect, policy=self.policy
        )
        projected = resolver.resolve(principal=self.bob, locale="en-US")
        self.assertIn("Shared Yap", projected.exact_forms)
        service.delete(
            shared["recordId"],
            {"expectedVersion": 2},
            principal=self.alice,
            scope_id="team:clinical",
        )
        self.assertEqual(
            service.create(body, principal=self.alice, scope_id="team:clinical"), shared
        )
        with self.connect() as connection:
            original = read_job_terminology_snapshot(
                connection, principal=self.bob.key, job_id="shared-before"
            )
            current = bind_job_terminology_snapshot(
                connection,
                job_id="shared-after",
                authorization=self.policy.authorization(self.bob),
                locale="en-US",
            )
        self.assertEqual(original, frozen)
        self.assertEqual(original.entries[0].canonical_form, "Yap")
        self.assertEqual(current.entries, ())
        self.assertEqual(
            service.get(personal["recordId"], principal=self.alice), personal
        )

    def test_shared_pagination_and_locale_never_include_neighbor_scopes(self):
        service = self.shared()
        expected = []
        for index in range(12):
            body = {
                **_body(),
                "canonicalForm": f"Shared {index}",
                "variants": [f"shared-{index}"],
                "locale": "und" if index == 0 else "en-US",
            }
            expected.append(
                service.create(body, principal=self.alice, scope_id="team:clinical")[
                    "recordId"
                ]
            )
        service.create(_body(), principal=self.alice)
        service.create(
            {**_body(), "locale": "fr-FR"},
            principal=self.alice,
            scope_id="team:clinical",
        )
        page = service.list(
            principal=self.bob, scope_id="team:clinical", locale="en-US"
        )
        self.assertEqual(len(page["records"]), 10)
        next_page = service.list(
            principal=self.bob,
            scope_id="team:clinical",
            locale="en-US",
            after=page["nextCursor"],
        )
        self.assertIsNone(next_page["nextCursor"])
        self.assertCountEqual(
            [row["recordId"] for row in page["records"] + next_page["records"]],
            expected,
        )
        self.assertTrue(
            all(
                row["scopeId"] == "team:clinical"
                for row in page["records"] + next_page["records"]
            )
        )


def _body():
    return {
        "mutationId": str(uuid4()),
        "locale": "en-US",
        "canonicalForm": "Yap",
        "variants": ["yap"],
        "sensitivity": "internal",
    }


def _edit(version, canonical):
    return {
        "expectedVersion": version,
        "canonicalForm": canonical,
        "variants": ["yap"],
        "sensitivity": "internal",
    }
