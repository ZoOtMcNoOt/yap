from __future__ import annotations

from yap_server.auth.oidc_access_tokens import (
    OidcAccessTokenAuthenticator,
    OidcAccessTokenPolicy,
)
from yap_server.auth.oidc_metadata import SigningKeyProvider
from yap_server.config import ServerAuthenticationSettings


def entra_access_token_policy(
    settings: ServerAuthenticationSettings,
) -> OidcAccessTokenPolicy:
    """Translate Entra deployment configuration into provider-neutral policy."""
    if not settings.required:
        raise ValueError("Entra authentication requires Entra settings")
    assert settings.tenant_id is not None
    assert settings.audience is not None
    assert settings.required_scope is not None
    return OidcAccessTokenPolicy(
        issuer=f"https://login.microsoftonline.com/{settings.tenant_id}/v2.0",
        audience=settings.audience,
        tenant_id_claim="tid",
        subject_id_claim="oid",
        client_id_claim="azp",
        scope_claim="scp",
        roles_claim="roles",
        identity_format="uuid",
        allowed_tenant_ids=frozenset({settings.tenant_id}),
        allowed_client_ids=frozenset(settings.allowed_client_ids),
        required_scopes=frozenset({settings.required_scope}),
        allowed_roles=frozenset(settings.allowed_roles),
        required_claim_values=(("ver", "2.0"),),
        optional_claim_values=(("token_use", frozenset({"access_token"})),),
        rejected_claim_values=(("idtyp", frozenset({"app"})),),
    )


class EntraAccessTokenAuthenticator(OidcAccessTokenAuthenticator):
    """Compatibility factory over the provider-neutral token validator."""

    def __init__(
        self,
        settings: ServerAuthenticationSettings,
        signing_keys: SigningKeyProvider,
    ) -> None:
        super().__init__(entra_access_token_policy(settings), signing_keys)


__all__ = [
    "EntraAccessTokenAuthenticator",
    "entra_access_token_policy",
]
