from __future__ import annotations

import argparse
import json
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from http.client import HTTPConnection
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from tests.recording_job_fixtures import (
    ControlledJobProcessor,
    batch_api_recording_job_request,
)
from yap_server.api.app import create_server
from yap_server.auth import (
    OidcAccessTokenAuthenticator,
    OidcAccessTokenPolicy,
    OidcDiscoveryJwksProvider,
    RepositoryBackedRequestAuthenticator,
)
from yap_server.auth.identity_repository import SqliteIdentityRepository
from yap_server.config import ServerAuthenticationSettings, ServerSettings
from yap_server.jobs import RecordingJobService

# Reserved exclusively for synthetic Yap Phase 7 verification identities.
TENANT_ID = "00000000-0000-4000-8000-000000000071"
ALICE_ID = "00000000-0000-4000-8000-000000000072"
BOB_ID = "00000000-0000-4000-8000-000000000073"
CLIENT_ID = "00000000-0000-4000-8000-000000000074"
AUDIENCE = "00000000-0000-4000-8000-000000000075"
ADMIN_ROLE = "Yap.IdentityAdministrator"
ISSUER_ID = "yap-phase7"
REDIRECT_URI = "http://127.0.0.1/yap-phase7-synthetic-callback"
_MAX_RESPONSE_BYTES = 64 * 1024
_FLOW_STAGE = "bootstrap"


def _set_flow_stage(stage: str) -> None:
    global _FLOW_STAGE
    _FLOW_STAGE = stage


def _failure_category(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, HTTPError):
        return "http"
    if isinstance(error, AssertionError):
        return "assertion"
    if isinstance(error, (ConnectionError, OSError)):
        return "transport"
    if isinstance(error, (TypeError, ValueError, json.JSONDecodeError)):
        return "invalid-data"
    if isinstance(error, RuntimeError):
        return "runtime"
    return "internal"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-base-url", required=True)
    parser.add_argument("--state-root", required=True, type=Path)
    return parser.parse_args()


def _bounded_json(response: object) -> dict[str, object]:
    body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise RuntimeError("Synthetic OIDC response exceeded its bound.")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise TypeError("Synthetic OIDC response was not an object.")
    return value


def _authorization_code(provider_base_url: str) -> str:
    endpoint = urlsplit(f"{provider_base_url}/{ISSUER_ID}/authorize")
    if (
        endpoint.scheme != "http"
        or endpoint.hostname != "127.0.0.1"
        or endpoint.port is None
    ):
        raise RuntimeError("Synthetic OIDC provider must be loopback HTTP.")
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": "openid access_as_user",
            "state": "synthetic-state",
            "nonce": "synthetic-nonce",
        }
    )
    connection = HTTPConnection(endpoint.hostname, endpoint.port, timeout=2)
    try:
        connection.request("GET", f"{endpoint.path}?{query}")
        response = connection.getresponse()
        response.read(_MAX_RESPONSE_BYTES + 1)
        if response.status != HTTPStatus.FOUND:
            raise RuntimeError("Synthetic authorization request did not redirect.")
        location = response.getheader("Location")
    finally:
        connection.close()
    if not isinstance(location, str):
        raise TypeError("Synthetic authorization code was unavailable.")
    codes = parse_qs(urlsplit(location).query).get("code", [])
    if len(codes) != 1 or not codes[0] or len(codes[0]) > 2_048:
        raise RuntimeError("Synthetic authorization code was invalid.")
    return codes[0]


def _token(provider_base_url: str, fixture: str) -> str:
    code = _authorization_code(provider_base_url)
    request = Request(
        f"{provider_base_url}/{ISSUER_ID}/token",
        data=urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": "synthetic-client-secret",
                "redirect_uri": REDIRECT_URI,
                "code": code,
                "fixture": fixture,
            }
        ).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        payload = _bounded_json(response)
    token = payload.get("access_token")
    if not isinstance(token, str) or not token or len(token) > 16 * 1024:
        raise RuntimeError("Synthetic access token was unavailable.")
    return token


def _api_request(
    base_url: str,
    path: str,
    token: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, object]]:
    headers = {"Authorization": f"Bearer {token}"}
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        response = urlopen(request, timeout=2)
    except HTTPError as error:
        response = error
    with response:
        return response.status, _bounded_json(response)


def _assert_status(
    actual: tuple[int, dict[str, object]],
    status: HTTPStatus,
    *,
    code: str | None = None,
) -> dict[str, object]:
    actual_status, payload = actual
    if actual_status != status:
        raise AssertionError(f"Expected HTTP {status}, received {actual_status}.")
    if code is not None and payload.get("code") != code:
        raise AssertionError(f"Expected error code {code}.")
    return payload


def main() -> None:
    _set_flow_stage("arguments")
    arguments = _arguments()
    _set_flow_stage("authority-validation")
    provider_base_url = arguments.provider_base_url.rstrip("/")
    parsed_provider = urlsplit(provider_base_url)
    if (
        parsed_provider.scheme != "http"
        or parsed_provider.hostname != "127.0.0.1"
        or parsed_provider.port is None
        or parsed_provider.path
        or parsed_provider.query
        or parsed_provider.fragment
    ):
        raise RuntimeError("Synthetic OIDC provider must be a loopback origin.")
    state_root = arguments.state_root.resolve(strict=True)
    if not state_root.is_dir() or state_root.is_symlink():
        raise RuntimeError("Synthetic verification state root is invalid.")

    issuer = f"{provider_base_url}/{ISSUER_ID}"
    _set_flow_stage("discovery")
    policy = OidcAccessTokenPolicy(
        issuer=issuer,
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
    )
    signing_keys = OidcDiscoveryJwksProvider(
        issuer,
        allowed_algorithms=policy.allowed_algorithms,
        allow_insecure_loopback=True,
    )
    signing_keys.refresh()
    token_authenticator = OidcAccessTokenAuthenticator(policy, signing_keys)

    _set_flow_stage("token-issuance")
    alice_token = _token(provider_base_url, "alice")
    bob_token = _token(provider_base_url, "bob")
    wrong_audience_token = _token(provider_base_url, "wrong-audience")
    insufficient_scope_token = _token(provider_base_url, "insufficient-scope")

    _set_flow_stage("principal-validation")
    alice_principal = token_authenticator.authenticate(f"Bearer {alice_token}")
    if (
        alice_principal.key.tenant_id != TENANT_ID
        or alice_principal.key.subject_id != ALICE_ID
        or alice_principal.expires_at_unix is None
        or alice_principal.roles != frozenset({ADMIN_ROLE})
    ):
        raise AssertionError("Synthetic validated principal authority was incorrect.")

    _set_flow_stage("service-startup")
    identity_root = state_root / "identity"
    identity_root.mkdir(mode=0o700)
    repository = SqliteIdentityRepository(identity_root / "identity.sqlite3")
    authenticator = RepositoryBackedRequestAuthenticator(
        token_authenticator,
        repository,
    )
    jobs = RecordingJobService(
        state_root / "jobs",
        processor=ControlledJobProcessor(),
        supported_languages=("en",),
        now=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        development_principal=None,
    )
    settings = ServerSettings(
        host="127.0.0.1",
        port=0,
        authentication=ServerAuthenticationSettings(
            mode="entra",
            tenant_id=TENANT_ID,
            audience=AUDIENCE,
            required_scope="access_as_user",
            allowed_client_ids=(CLIENT_ID,),
            allowed_roles=(ADMIN_ROLE,),
            identity_storage_dir=identity_root,
        ),
    )
    server = create_server(
        settings,
        request_authenticator=authenticator,
        job_service=jobs,
    )
    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        daemon=True,
    )
    thread.start()
    try:
        _set_flow_stage("owner-create")
        created = _assert_status(
            _api_request(
                base_url,
                "/v1/jobs",
                alice_token,
                method="POST",
                payload=batch_api_recording_job_request(),
                idempotency_key="synthetic-owner-flow",
            ),
            HTTPStatus.ACCEPTED,
        )
        job_id = created.get("jobId")
        if not isinstance(job_id, str):
            raise TypeError("Synthetic owner flow did not create a job.")
        _set_flow_stage("owner-read")
        _assert_status(
            _api_request(base_url, f"/v1/jobs/{job_id}", alice_token),
            HTTPStatus.OK,
        )
        _set_flow_stage("owner-isolation")
        _assert_status(
            _api_request(base_url, f"/v1/jobs/{job_id}", bob_token),
            HTTPStatus.NOT_FOUND,
            code="JOB_NOT_FOUND",
        )
        _set_flow_stage("wrong-audience")
        _assert_status(
            _api_request(
                base_url,
                "/v1/jobs",
                wrong_audience_token,
                method="POST",
                payload=batch_api_recording_job_request(),
                idempotency_key="synthetic-wrong-audience",
            ),
            HTTPStatus.UNAUTHORIZED,
            code="INVALID_ACCESS_TOKEN",
        )
        _set_flow_stage("insufficient-scope")
        _assert_status(
            _api_request(
                base_url,
                "/v1/jobs",
                insufficient_scope_token,
                method="POST",
                payload=batch_api_recording_job_request(),
                idempotency_key="synthetic-insufficient-scope",
            ),
            HTTPStatus.FORBIDDEN,
            code="INSUFFICIENT_SCOPE",
        )
    finally:
        active_stage = _FLOW_STAGE
        _set_flow_stage("service-shutdown")
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        repository.close()
        if thread.is_alive():
            raise RuntimeError("Synthetic REST server did not stop.")
        _set_flow_stage(active_stage)
    _set_flow_stage("complete")
    print("MOCK_OIDC_OWNER_FLOW=PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"MOCK_OIDC_OWNER_FLOW=FAIL:{_FLOW_STAGE}:{_failure_category(error)}",
            flush=True,
        )
        raise
