import unittest

from yap_server.auth.oidc_metadata import OidcDiscoveryJwksProvider
from yap_server.auth.signing_keys import JwksSigningKeyProvider


class SigningKeyCompatibilityTests(unittest.TestCase):
    def test_legacy_import_names_the_provider_neutral_metadata_owner(self) -> None:
        self.assertIs(JwksSigningKeyProvider, OidcDiscoveryJwksProvider)


if __name__ == "__main__":
    unittest.main()
