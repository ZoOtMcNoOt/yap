"""Compatibility exports for the provider-neutral OIDC metadata owner."""

from yap_server.auth.oidc_metadata import (
    OidcDiscoveryJwksProvider,
    OidcDiscoveryUnavailable,
    OidcJwksUnavailable,
    OidcMetadataUnavailable,
    SigningKeyProvider,
    SigningKeyUnavailable,
)


JwksSigningKeyProvider = OidcDiscoveryJwksProvider


__all__ = [
    "JwksSigningKeyProvider",
    "OidcDiscoveryJwksProvider",
    "OidcDiscoveryUnavailable",
    "OidcJwksUnavailable",
    "OidcMetadataUnavailable",
    "SigningKeyProvider",
    "SigningKeyUnavailable",
]
