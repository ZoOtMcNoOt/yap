from __future__ import annotations

from yap_server.auth.entra_access_tokens import EntraAccessTokenAuthenticator
from yap_server.auth.request_authentication import (
    DevelopmentLoopbackAuthenticator,
    RequestAuthenticator,
)
from yap_server.auth.signing_keys import JwksSigningKeyProvider
from yap_server.config import ServerAuthenticationSettings


def build_request_authenticator(
    settings: ServerAuthenticationSettings,
) -> RequestAuthenticator:
    if not settings.required:
        return DevelopmentLoopbackAuthenticator()
    assert settings.tenant_id is not None
    signing_keys = JwksSigningKeyProvider(settings.tenant_id)
    signing_keys.refresh()
    return EntraAccessTokenAuthenticator(settings, signing_keys)
