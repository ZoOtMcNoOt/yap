#!/usr/bin/env python3
"""Run the demo identity provider and mint tokens for the demo users.

Phase 7 built tenant-scoped identity and nobody has used it, because signing in
needs an Entra app registration that IT owns. The verification suite already
works around that with a synthetic OIDC provider and two fixed users, but it is
wired as a one-shot assertion: it proves the flow and exits.

This runs the same provider, from the same digest-pinned image and the same
claims, and leaves it up so the real server and the real client can be pointed
at it. Nothing here is a stub or a bypass. The tokens are genuine JWTs and the
server validates them through its ordinary Entra code path, so what gets
exercised is the shipping authentication boundary, not a demo of one.

    ./demo/run-demo-identity-provider.py serve
    ./demo/run-demo-identity-provider.py token --identity alice

Loopback only, and the container is removed on exit.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROVIDER_LOCK = REPO_ROOT / "verification" / "mock-oidc-provider.lock.json"

ISSUER_ID = "yap-phase7"
CONTAINER_NAME = "yap-demo-identity-provider"
DEFAULT_PORT = 18790

# The same identities the verification flow uses. Keeping them identical means a
# demo session and a gate run exercise one set of claims, so a demo cannot drift
# into proving something the gate does not.
TENANT_ID = "00000000-0000-4000-8000-000000000071"
ALICE_ID = "00000000-0000-4000-8000-000000000072"
BOB_ID = "00000000-0000-4000-8000-000000000073"
CLIENT_ID = "00000000-0000-4000-8000-000000000074"
AUDIENCE = "00000000-0000-4000-8000-000000000075"
ADMIN_ROLE = "Yap.IdentityAdministrator"
CLIENT_SECRET = "synthetic-client-secret"
REDIRECT_URI = "http://127.0.0.1/yap-demo-callback"

# Alice administers, Bob does not. Two users in one tenant is the point: it is
# what makes owner-scoped isolation visible rather than theoretical.
IDENTITIES = {
    "alice": {"oid": ALICE_ID, "roles": [ADMIN_ROLE]},
    "bob": {"oid": BOB_ID, "roles": []},
}


def provider_reference() -> str:
    lock = json.loads(PROVIDER_LOCK.read_text(encoding="utf-8"))
    reference = lock.get("reference")
    if not isinstance(reference, str) or "@sha256:" not in reference:
        raise SystemExit("Provider lock does not carry a digest-pinned reference.")
    return reference


def provider_configuration() -> str:
    mappings = [
        {
            "requestParam": "fixture",
            "match": name,
            "typeHeader": "at+jwt",
            "claims": {
                "sub": identity["oid"],
                "aud": [AUDIENCE],
                "tid": TENANT_ID,
                "oid": identity["oid"],
                "azp": CLIENT_ID,
                "scp": "access_as_user",
                "roles": identity["roles"],
            },
        }
        for name, identity in IDENTITIES.items()
    ]
    return json.dumps(
        {
            "interactiveLogin": False,
            "httpServer": "NettyWrapper",
            "tokenCallbacks": [
                {"issuerId": ISSUER_ID, "tokenExpiry": 3600, "requestMappings": mappings}
            ],
        },
        separators=(",", ":"),
    )


def remove_existing_container() -> None:
    subprocess.run(
        ["docker", "rm", "--force", CONTAINER_NAME],
        check=False,
        capture_output=True,
    )


def start(port: int) -> None:
    remove_existing_container()
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            CONTAINER_NAME,
            # Loopback only. A demo identity provider that answers on a routable
            # interface is a token oracle for anyone who can reach it.
            "--publish",
            f"127.0.0.1:{port}:8080",
            "--env",
            f"JSON_CONFIG={provider_configuration()}",
            provider_reference(),
        ],
        check=True,
        capture_output=True,
    )


def wait_until_ready(base_url: str, timeout_seconds: float = 60.0) -> None:
    discovery = f"{base_url}/{ISSUER_ID}/.well-known/openid-configuration"
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(discovery, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as error:  # noqa: BLE001 - any failure means not ready yet
            last_error = error
        time.sleep(0.5)
    raise SystemExit(f"Demo identity provider never became ready: {last_error}")


def authorization_code(base_url: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": "openid access_as_user",
            "state": "yap-demo",
        }
    )
    request = urllib.request.Request(
        f"{base_url}/{ISSUER_ID}/authorize?{query}", method="GET"
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=5) as response:
            location = response.headers.get("Location", "")
    except urllib.error.HTTPError as error:
        location = error.headers.get("Location", "")
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query).get("code", [""])[0]
    if not code:
        raise SystemExit("Demo identity provider did not return an authorization code.")
    return code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """The authorization code arrives in a redirect that must not be followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, ANN001
        return None


def mint_token(base_url: str, identity: str) -> str:
    if identity not in IDENTITIES:
        raise SystemExit(f"Unknown demo identity {identity!r}; choose from {sorted(IDENTITIES)}.")
    payload = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "code": authorization_code(base_url),
            "fixture": identity,
        }
    ).encode("ascii")
    request = urllib.request.Request(
        f"{base_url}/{ISSUER_ID}/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = json.loads(response.read(64 * 1024).decode("utf-8"))
    token = body.get("access_token")
    if not isinstance(token, str) or not token:
        raise SystemExit("Demo identity provider returned no access token.")
    return token


def server_environment(port: int) -> str:
    issuer = f"http://127.0.0.1:{port}/{ISSUER_ID}"
    return "\n".join(
        [
            "YAP_AUTH_MODE=entra",
            f"YAP_OIDC_ISSUER={issuer}",
            f"YAP_OIDC_AUDIENCE={AUDIENCE}",
            f"YAP_OIDC_ALLOWED_TENANT_IDS={TENANT_ID}",
            f"YAP_OIDC_ALLOWED_CLIENT_IDS={CLIENT_ID}",
            "YAP_OIDC_REQUIRED_SCOPES=access_as_user",
            "YAP_OIDC_ALLOW_INSECURE_LOOPBACK=1",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["serve", "token", "stop", "env"])
    parser.add_argument("--identity", default="alice", help="alice (admin) or bob (plain user)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    arguments = parser.parse_args()
    base_url = f"http://127.0.0.1:{arguments.port}"

    if arguments.command == "stop":
        remove_existing_container()
        print("Demo identity provider stopped.")
        return

    if arguments.command == "env":
        print(server_environment(arguments.port))
        return

    if arguments.command == "serve":
        start(arguments.port)
        wait_until_ready(base_url)
        print(f"Demo identity provider ready at {base_url}/{ISSUER_ID}")
        print(f"  alice  {ALICE_ID}  roles: {ADMIN_ROLE}")
        print(f"  bob    {BOB_ID}  roles: none")
        print()
        print("Point the server at it with:")
        print(server_environment(arguments.port))
        print()
        print(f"Mint a token:  {Path(__file__).name} token --identity alice")
        print(f"Stop:          {Path(__file__).name} stop")
        return

    # token
    wait_until_ready(base_url, timeout_seconds=5)
    print(mint_token(base_url, arguments.identity))


if __name__ == "__main__":
    sys.exit(main())
