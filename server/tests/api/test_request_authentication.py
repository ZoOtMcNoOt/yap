from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path

from yap_server.auth import AuthenticatedPrincipal, AuthenticationFailure
from yap_server.api.app import create_server
from yap_server.config import ServerAuthenticationSettings, ServerSettings

from tests.api.api_fixtures import HealthServerTestCase


class _BearerFixture:
    authentication_required = True
    principal_access_enforced = True

    def __init__(self) -> None:
        self.headers: list[str | None] = []

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        self.headers.append(authorization)
        if authorization is None:
            raise AuthenticationFailure.missing()
        if authorization == "Bearer insufficient":
            raise AuthenticationFailure.forbidden(
                code="INSUFFICIENT_SCOPE",
                message="The access token does not grant this operation.",
            )
        if authorization != "Bearer valid-yap-token":
            raise AuthenticationFailure.invalid()
        return AuthenticatedPrincipal(
            tenant_id="11111111-1111-4111-8111-111111111111",
            subject_id="22222222-2222-4222-8222-222222222222",
            client_id="33333333-3333-4333-8333-333333333333",
            scopes=frozenset({"access_as_user"}),
        )


class RequestAuthenticationTests(HealthServerTestCase):
    asr_capabilities = {"schemaVersion": 1, "providers": []}
    server_settings = ServerSettings(
        host="127.0.0.1",
        port=0,
        authentication=ServerAuthenticationSettings(
            mode="entra",
            tenant_id="11111111-1111-4111-8111-111111111111",
            audience="55555555-5555-4555-8555-555555555555",
            required_scope="access_as_user",
            allowed_client_ids=("33333333-3333-4333-8333-333333333333",),
            identity_storage_dir=Path("test-private-identity"),
        ),
    )

    def setUp(self) -> None:
        self.authenticator = _BearerFixture()
        self.request_authenticator = self.authenticator
        super().setUp()

    def test_health_is_the_only_public_route_and_reports_required_auth(self) -> None:
        status, _, body = self._request("/v1/health")

        self.assertEqual(status, HTTPStatus.OK)
        health_view = json.loads(body)
        self.assertEqual(health_view["auth"], "required")
        self.assertEqual(
            health_view["capabilities"],
            {
                "batchJobs": False,
                "liveStreaming": False,
                "jobStatus": False,
                "transcriptCorrection": False,
                "librarianQueries": False,
                "studentQuestions": False,
                "archivistIngestions": False,
                "curatorProposals": False,
                "analystAnswers": False,
                "coordinatorBundles": False,
                "auditorReports": False,
            },
        )
        self.assertEqual(self.authenticator.headers, [])

        status, _, _ = self._request("/v1/health/")
        self.assertEqual(status, HTTPStatus.NOT_FOUND)
        self.assertEqual(self.authenticator.headers, [])

    def test_protected_route_requires_a_bearer_token_before_dispatch(self) -> None:
        status, headers, body = self._request("/v1/asr/capabilities")

        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(headers["WWW-Authenticate"], "Bearer")
        self.assert_error(
            status,
            headers,
            body,
            expected_status=HTTPStatus.UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            message="A Yap API access token is required.",
        )

    def test_valid_principal_reaches_the_protected_route(self) -> None:
        status, _, body = self._request(
            "/v1/asr/capabilities",
            headers={"Authorization": "Bearer valid-yap-token"},
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(json.loads(body), self.asr_capabilities)
        self.assertEqual(self.authenticator.headers, ["Bearer valid-yap-token"])

    def test_valid_but_unauthorized_token_is_forbidden_without_a_challenge(
        self,
    ) -> None:
        status, headers, body = self._request(
            "/v1/asr/capabilities",
            headers={"Authorization": "Bearer insufficient"},
        )

        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertIsNone(headers.get("WWW-Authenticate"))
        self.assert_error(
            status,
            headers,
            body,
            expected_status=HTTPStatus.FORBIDDEN,
            code="INSUFFICIENT_SCOPE",
            message="The access token does not grant this operation.",
        )

    def test_invalid_token_uses_a_uniform_non_retryable_error(self) -> None:
        status, headers, body = self._request(
            "/v1/asr/capabilities",
            headers={"Authorization": "Basic secret"},
        )

        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(headers["WWW-Authenticate"], "Bearer")
        self.assert_error(
            status,
            headers,
            body,
            expected_status=HTTPStatus.UNAUTHORIZED,
            code="INVALID_ACCESS_TOKEN",
            message="The Yap API access token is invalid.",
        )

    def test_team_mode_rejects_token_validation_without_access_policy(self) -> None:
        class _TokenOnlyFixture(_BearerFixture):
            principal_access_enforced = False

        with self.assertRaisesRegex(
            ValueError,
            "principal access enforcement",
        ):
            create_server(
                self.server_settings,
                request_authenticator=_TokenOnlyFixture(),
            )


class DefaultFailClosedAuthenticationTests(HealthServerTestCase):
    server_settings = ServerSettings(host="127.0.0.1", port=0)

    def test_default_server_exposes_health_but_rejects_protected_routes(self) -> None:
        health_status, _, health_body = self._request("/v1/health")
        self.assertEqual(health_status, HTTPStatus.OK)
        self.assertEqual(json.loads(health_body)["auth"], "required")

        status, headers, body = self._request("/v1/asr/capabilities")
        self.assert_error(
            status,
            headers,
            body,
            expected_status=HTTPStatus.SERVICE_UNAVAILABLE,
            code="AUTHENTICATION_UNAVAILABLE",
            message="Yap could not validate the access token.",
            retryable=True,
        )
