from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import psycopg

from yap_server.auth import AuthenticatedPrincipal, AuthenticationFailure
from yap_server.config import ServerAuthenticationSettings, ServerSettings
from yap_server.knowledge.terminology_service import (
    TerminologyServiceError,
)
from yap_server.knowledge.terminology_runtime import (
    build_terminology_service,
)
from yap_server.knowledge.terminology_policy import TerminologyPolicy
from tests.knowledge.test_terminology_policy import policy_payload
from .api_fixtures import HealthServerTestCase

DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")
_TENANT = "11111111-1111-4111-8111-111111111111"
_CLIENT = "33333333-3333-4333-8333-333333333333"


class _Authentication:
    authentication_required = True
    principal_access_enforced = True

    def __init__(self, tenant):
        self.tenant = tenant

    def authenticate(self, authorization):
        if authorization is None:
            raise AuthenticationFailure.missing()
        if authorization not in ("Bearer alice", "Bearer bob", "Bearer admin"):
            raise AuthenticationFailure.invalid()
        return AuthenticatedPrincipal(
            self.tenant,
            authorization.split()[1],
            _CLIENT,
            frozenset({"access_as_user"}),
            roles=frozenset({"terminology.manager"})
            if authorization == "Bearer admin"
            else frozenset(),
        )


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class TerminologyApiTests(HealthServerTestCase):
    server_settings = ServerSettings(
        host="127.0.0.1",
        port=0,
        authentication=ServerAuthenticationSettings(
            mode="entra",
            tenant_id=_TENANT,
            audience="55555555-5555-4555-8555-555555555555",
            required_scope="access_as_user",
            allowed_client_ids=(_CLIENT,),
            identity_storage_dir=Path("test-private-identity"),
        ),
    )

    def setUp(self):
        self.tenant = f"tenant-{uuid4().hex}"
        self.request_authenticator = _Authentication(self.tenant)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        credential = Path(temporary.name) / "knowledge.dsn"
        credential.write_text(DSN)
        credential.chmod(0o600)
        self.terminology_service = build_terminology_service(
            {
                "YAP_TERMINOLOGY_RUNTIME": "postgres",
                "YAP_TERMINOLOGY_DSN_FILE": str(credential),
            },
            authenticated_team_mode=True,
            policy=TerminologyPolicy.from_payload(policy_payload(self.tenant)),
        )
        super().setUp()

    @contextmanager
    def connect(self):
        with psycopg.connect(DSN, connect_timeout=3) as connection:
            yield connection

    def tearDown(self):
        super().tearDown()
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM yap_terminology_records WHERE tenant_id = %s",
                (self.tenant,),
            )

    def send(
        self, path, *, method="GET", value=None, owner="alice", scope_id="personal"
    ):
        if (
            path.startswith("/v1/terminology")
            and path != "/v1/terminology/scopes"
            and "scopeId=" not in path
        ):
            path += ("&" if "?" in path else "?") + "scopeId=" + scope_id
        headers = {"Authorization": f"Bearer {owner}"}
        if value is not None:
            headers["Content-Type"] = "application/json"
        status, response_headers, body = self._request(
            path,
            method=method,
            headers=headers,
            data=json.dumps(value).encode() if value is not None else None,
        )
        self.assert_json_headers(response_headers, body)
        return status, json.loads(body)

    def test_authenticated_create_replay_read_list_edit_and_delete(self):
        _, health = self.send("/v1/health")
        self.assertTrue(health["capabilities"]["personalTerminology"])
        self.assertFalse(health["capabilities"]["transcriptCorrection"])
        value = _body()
        status, created = self.send("/v1/terminology", method="POST", value=value)
        self.assertEqual(status, 201)
        status, replay = self.send("/v1/terminology", method="POST", value=value)
        self.assertEqual((status, replay), (201, created))
        path = f"/v1/terminology/{created['recordId']}"
        self.assertEqual(self.send(path), (200, created))
        status, page = self.send("/v1/terminology?locale=en-US")
        self.assertEqual(status, 200)
        self.assertEqual(len(page["records"]), 1)
        status, changed = self.send(
            path,
            method="PUT",
            value={
                "expectedVersion": 1,
                "canonicalForm": "YAP",
                "variants": ["yap"],
                "sensitivity": "internal",
            },
        )
        self.assertEqual((status, changed["version"]), (200, 2))
        status, deleted = self.send(path, method="DELETE", value={"expectedVersion": 2})
        self.assertEqual((status, deleted["deleted"]), (200, True))
        self.assertEqual(self.send(path)[0], 404)
        self.assertEqual(self.send("/v1/terminology?locale=en-US")[1]["records"], [])

    def test_authenticated_discovery_and_shared_mutation_keep_visibility_separate(self):
        self.assertEqual(self._request("/v1/terminology/scopes")[0], 401)
        status, discovery = self.send("/v1/terminology/scopes", owner="bob")
        self.assertEqual(status, 200)
        scopes = {scope["scopeId"]: scope for scope in discovery["scopes"]}
        self.assertEqual(set(scopes), {"personal", "organization", "team:clinical"})
        self.assertFalse(scopes["team:clinical"]["canManage"])
        self.assertFalse(scopes["organization"]["canManage"])
        value = _body()
        status, created = self.send(
            "/v1/terminology", method="POST", value=value, scope_id="team:clinical"
        )
        self.assertEqual((status, created["scopeId"]), (201, "team:clinical"))
        path = f"/v1/terminology/{created['recordId']}"
        self.assertEqual(
            self.send(path, owner="bob", scope_id="team:clinical"), (200, created)
        )
        self.assertEqual(self.send(path, scope_id="personal")[0], 404)
        self.assertEqual(self.send(path, scope_id="team:research")[0], 404)
        for method, body in (
            (
                "PUT",
                {
                    "expectedVersion": 1,
                    "canonicalForm": "Forged",
                    "variants": ["forged"],
                    "sensitivity": "internal",
                },
            ),
            ("DELETE", {"expectedVersion": 1}),
        ):
            self.assertEqual(
                self.send(
                    path,
                    method=method,
                    value=body,
                    owner="bob",
                    scope_id="team:clinical",
                )[0],
                403,
            )
        self.assertEqual(
            self.send(
                "/v1/terminology",
                method="POST",
                value=value,
                owner="bob",
                scope_id="team:clinical",
            )[0],
            403,
        )
        self.assertEqual(
            self.send(
                "/v1/terminology?locale=en-US", owner="bob", scope_id="team:clinical"
            )[1]["records"],
            [created],
        )
        self.assertEqual(self.send("/v1/terminology/scopes?scopeId=personal")[0], 400)
        self.assertEqual(
            self.send("/v1/terminology/scopes", method="POST", value={})[0], 405
        )

    def test_organization_role_and_explicit_scope_are_enforced_over_http(self):
        self.assertEqual(
            self._request(
                "/v1/terminology?locale=en-US",
                headers={"Authorization": "Bearer alice"},
            )[0],
            400,
        )
        self.assertEqual(
            self.send(
                "/v1/terminology", method="POST", value=_body(), scope_id="organization"
            )[0],
            403,
        )
        status, created = self.send(
            "/v1/terminology",
            method="POST",
            value=_body(),
            scope_id="organization",
            owner="admin",
        )
        self.assertEqual(status, 201)
        path = f"/v1/terminology/{created['recordId']}"
        self.assertEqual(
            self.send(path, owner="bob", scope_id="organization"), (200, created)
        )
        self.assertEqual(
            self.send(
                path,
                method="DELETE",
                value={"expectedVersion": 1},
                owner="admin",
                scope_id="organization",
            )[0],
            200,
        )
        self.assertEqual(self.send(path, scope_id="organization")[0], 404)

    def test_missing_auth_and_another_owner_share_no_term_content(self):
        _, created = self.send("/v1/terminology", method="POST", value=_body())
        path = f"/v1/terminology/{created['recordId']}"
        self.assertEqual(self._request(path)[0], 401)
        self.assertEqual(self.send(path, owner="bob")[0], 404)
        self.assertEqual(
            self.send(path, method="DELETE", value={"expectedVersion": 1}, owner="bob")[
                0
            ],
            404,
        )
        self.assertEqual(
            self.send("/v1/terminology?locale=en-US", owner="bob")[1]["records"], []
        )
        self.assertEqual(self.send(path)[1]["version"], 1)

    def test_forged_authority_and_invalid_queries_return_redacted_errors(self):
        status, response = self.send(
            "/v1/terminology",
            method="POST",
            value={**_body(), "ownerId": "private-secret-owner"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(
            self.send("/v1/terminology?ownerId=alice", method="POST", value=_body())[0],
            400,
        )
        for query in (
            "",
            "?locale=en-US&locale=fr-FR",
            "?locale=en-US&ownerId=bob",
            "?locale=private-secret-term",
        ):
            status, response = self.send(f"/v1/terminology{query}")
            self.assertEqual(status, 400)
            self.assertNotIn("private-secret", json.dumps(response))
        self.assertNotIn("PreferredSecretName", "\n".join(self.logger.messages))
        self.assertNotIn("private-secret", "\n".join(self.logger.messages))

    def test_version_conflict_is_explicit_and_persistence_failure_is_retryable(self):
        _, created = self.send("/v1/terminology", method="POST", value=_body())
        path = f"/v1/terminology/{created['recordId']}"
        status, response = self.send(
            path, method="DELETE", value={"expectedVersion": 2}
        )
        self.assertEqual((status, response["code"]), (409, "TERMINOLOGY_CONFLICT"))
        original = self.terminology_service.list

        def unavailable(**kwargs):
            raise TerminologyServiceError(
                503,
                "TERMINOLOGY_UNAVAILABLE",
                "Personal terminology is temporarily unavailable.",
                retryable=True,
            )

        self.terminology_service.list = unavailable
        try:
            status, response = self.send("/v1/terminology?locale=en-US")
            self.assertEqual((status, response["retryable"]), (503, True))
        finally:
            self.terminology_service.list = original


def _body():
    return {
        "mutationId": str(uuid4()),
        "locale": "en-US",
        "canonicalForm": "PreferredSecretName",
        "variants": ["preferred-secret-name"],
        "sensitivity": "internal",
    }
