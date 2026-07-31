from __future__ import annotations

from yap_server.auth.entra_access_tokens import (
    EntraAccessTokenAuthenticator,
    entra_access_token_policy,
)
from yap_server.auth.oidc_metadata import OidcDiscoveryJwksProvider
from yap_server.auth.request_authentication import (
    AuthenticationDisabledAuthenticator,
    DevelopmentLoopbackAuthenticator,
    RequestAuthenticator,
)
from yap_server.config import ServerAuthenticationSettings


def build_request_authenticator(
    settings: ServerAuthenticationSettings,
) -> RequestAuthenticator:
    if settings.development_enabled:
        return DevelopmentLoopbackAuthenticator()
    if not settings.required:
        return AuthenticationDisabledAuthenticator()
    policy = entra_access_token_policy(settings)
    signing_keys = OidcDiscoveryJwksProvider(
        policy.issuer,
        allowed_algorithms=policy.allowed_algorithms,
    )
    signing_keys.refresh()
    return EntraAccessTokenAuthenticator(settings, signing_keys)
