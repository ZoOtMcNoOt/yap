from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from yap_server.api.app import create_server
from yap_server.auth import (
    EntraAccessTokenAuthenticator,
    RepositoryBackedRequestAuthenticator,
)
from yap_server.auth.identity_repository import SqliteIdentityRepository
from yap_server.config import ServerAuthenticationSettings, ServerSettings


TENANT_ID = "11111111-1111-4111-8111-111111111111"
SUBJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"
AUDIENCE = "44444444-4444-4444-8444-444444444444"
KEY_ID = "authenticated-connector-key"


class _FixedSigningKeys:
    def __init__(self, public_key: object) -> None:
        self._public_key = public_key

    def key_for(self, key_id: str) -> object:
        if key_id != KEY_ID:
            raise KeyError(key_id)
        return self._public_key


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    return parser.parse_args()


def _signed_token(private_key: object) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
            "aud": AUDIENCE,
            "exp": now + timedelta(minutes=5),
            "nbf": now - timedelta(minutes=1),
            "iat": now - timedelta(seconds=1),
            "tid": TENANT_ID,
            "oid": SUBJECT_ID,
            "azp": CLIENT_ID,
            "scp": "access_as_user",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )


def main() -> None:
    arguments = _arguments()
    state_root = arguments.state_root.resolve(strict=True)
    token_file = arguments.token_file.resolve(strict=False)
    if token_file.parent != state_root or token_file.exists() or token_file.is_symlink():
        raise RuntimeError("Token destination must be a new file under the state root.")

    identity_root = state_root / "identity"
    identity_root.mkdir(mode=0o700)
    settings = ServerSettings(
        host="127.0.0.1",
        port=arguments.port,
        authentication=ServerAuthenticationSettings(
            mode="entra",
            tenant_id=TENANT_ID,
            audience=AUDIENCE,
            required_scope="access_as_user",
            allowed_client_ids=(CLIENT_ID,),
            identity_storage_dir=identity_root,
        ),
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    repository = SqliteIdentityRepository(identity_root / "identity.sqlite3")
    authenticator = RepositoryBackedRequestAuthenticator(
        EntraAccessTokenAuthenticator(
            settings.authentication,
            _FixedSigningKeys(private_key.public_key()),
        ),
        repository,
    )
    server = create_server(
        settings,
        request_authenticator=authenticator,
    )
    try:
        descriptor = os.open(
            token_file,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
            stream.write(_signed_token(private_key))
            stream.write("\n")
        server.serve_forever(poll_interval=0.01)
    finally:
        server.server_close()
        repository.close()


if __name__ == "__main__":
    main()
