from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import threading
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from yap_server.auth.oidc_access_tokens import (
    OidcAccessTokenAuthenticator,
    OidcAccessTokenPolicy,
)
from yap_server.auth.oidc_metadata import (
    OidcDiscoveryJwksProvider,
    OidcDiscoveryUnavailable,
    OidcJwksUnavailable,
)


ISSUER = "https://issuer.example.test/yap"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
JWKS_URL = "https://issuer.example.test/yap/jwks"
TENANT_ID = "00000000-0000-4000-8000-000000000071"
SUBJECT_ID = "00000000-0000-4000-8000-000000000073"
CLIENT_ID = "00000000-0000-4000-8000-000000000074"
AUDIENCE = "00000000-0000-4000-8000-000000000075"


def _public_jwk(
    key: rsa.RSAPrivateKey,
    key_id: str,
) -> dict[str, object]:
    value = jwt.algorithms.RSAAlgorithm.to_jwk(
        key.public_key(),
        as_dict=True,
    )
    value.update({"kid": key_id, "use": "sig", "alg": "RS256"})
    return value


def _jwk(key_id: str) -> dict[str, object]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _public_jwk(key, key_id)


def _discovery(
    *,
    issuer: str = ISSUER,
    jwks_uri: str = JWKS_URL,
) -> bytes:
    return json.dumps(
        {
            "issuer": issuer,
            "jwks_uri": jwks_uri,
            "token_endpoint": f"{ISSUER}/token",
        },
        separators=(",", ":"),
    ).encode()


def _jwks(*keys: dict[str, object]) -> bytes:
    return json.dumps({"keys": list(keys)}, separators=(",", ":")).encode()


class _Fetcher:
    def __init__(self, *responses: bytes | Exception) -> None:
        self._responses = list(responses)
        self._lock = threading.Lock()
        self.calls: list[tuple[str, int, float]] = []

    def __call__(
        self,
        url: str,
        *,
        maximum_bytes: int,
        timeout_seconds: float,
    ) -> bytes:
        with self._lock:
            self.calls.append((url, maximum_bytes, timeout_seconds))
            if not self._responses:
                raise AssertionError("unexpected metadata fetch")
            response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value


class OidcMetadataTests(unittest.TestCase):
    def test_startup_uses_discovery_then_the_declared_bounded_jwks_endpoint(
        self,
    ) -> None:
        fetcher = _Fetcher(_discovery(), _jwks(_jwk("current")))
        provider = OidcDiscoveryJwksProvider(ISSUER, fetcher=fetcher)

        provider.refresh()
        self.assertIsNotNone(provider.key_for("current"))

        self.assertEqual(
            fetcher.calls,
            [
                (DISCOVERY_URL, 64 * 1024, 2.0),
                (JWKS_URL, 256 * 1024, 2.0),
            ],
        )

    def test_discovery_is_exact_and_insecure_transport_is_test_only(self) -> None:
        with self.assertRaises(ValueError):
            OidcDiscoveryJwksProvider("http://issuer.example.test/yap")
        with self.assertRaises(ValueError):
            OidcDiscoveryJwksProvider(
                "http://issuer.example.test/yap",
                allow_insecure_loopback=True,
            )
        with self.assertRaises(ValueError):
            OidcDiscoveryJwksProvider(
                "http://localhost:18767/yap",
                allow_insecure_loopback=True,
            )

        provider = OidcDiscoveryJwksProvider(
            "http://127.0.0.1:18767/yap",
            allow_insecure_loopback=True,
            fetcher=_Fetcher(
                json.dumps(
                    {
                        "issuer": "http://127.0.0.1:18767/yap",
                        "jwks_uri": "http://127.0.0.1:18767/yap/jwks",
                    }
                ).encode(),
                _jwks(_jwk("loopback")),
            ),
        )
        provider.refresh()
        self.assertIsNotNone(provider.key_for("loopback"))

    def test_discovery_failures_are_explicit_and_fail_closed(self) -> None:
        invalid_documents = (
            TimeoutError("timed out"),
            b"{not-json",
            _discovery(issuer="https://wrong.example.test/yap"),
            _discovery(jwks_uri="http://issuer.example.test/yap/jwks"),
            b"x" * (64 * 1024 + 1),
        )
        for response in invalid_documents:
            with self.subTest(response_type=type(response).__name__):
                provider = OidcDiscoveryJwksProvider(
                    ISSUER,
                    fetcher=_Fetcher(response),
                )
                with self.assertRaises(OidcDiscoveryUnavailable):
                    provider.refresh()

    def test_jwks_failures_are_explicit_and_fail_closed(self) -> None:
        invalid_sets = (
            TimeoutError("timed out"),
            b"{not-json",
            _jwks(),
            _jwks({"kid": "symmetric", "kty": "oct", "k": "c2VjcmV0"}),
            _jwks(
                _public_jwk(
                    rsa.generate_private_key(public_exponent=65537, key_size=1024),
                    "weak-rsa",
                )
            ),
            _jwks(_jwk("duplicate"), _jwk("duplicate")),
            b"x" * (256 * 1024 + 1),
        )
        for response in invalid_sets:
            with self.subTest(response_type=type(response).__name__):
                provider = OidcDiscoveryJwksProvider(
                    ISSUER,
                    fetcher=_Fetcher(_discovery(), response),
                )
                with self.assertRaises(OidcJwksUnavailable):
                    provider.refresh()

    def test_jwks_ignores_provider_extension_members(self) -> None:
        document = json.loads(_jwks(_jwk("current")))
        document["provider_metadata"] = {"rotation": "enabled"}
        provider = OidcDiscoveryJwksProvider(
            ISSUER,
            fetcher=_Fetcher(
                _discovery(),
                json.dumps(document, separators=(",", ":")).encode(),
            ),
        )

        provider.refresh()

        self.assertIsNotNone(provider.key_for("current"))

    def test_concurrent_unknown_key_has_one_single_flight_rotation_refresh(
        self,
    ) -> None:
        fetcher = _Fetcher(
            _discovery(),
            _jwks(_jwk("old")),
            _jwks(_jwk("old"), _jwk("rotated")),
        )
        provider = OidcDiscoveryJwksProvider(ISSUER, fetcher=fetcher)
        provider.refresh()

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(provider.key_for, ["rotated"] * 8))

        self.assertTrue(all(result is not None for result in results))
        self.assertEqual(
            [call[0] for call in fetcher.calls],
            [DISCOVERY_URL, JWKS_URL, JWKS_URL],
        )

    def test_concurrent_token_validation_uses_the_single_rotation_refresh(
        self,
    ) -> None:
        old_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rotated_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        fetcher = _Fetcher(
            _discovery(),
            _jwks(_public_jwk(old_key, "old")),
            _jwks(
                _public_jwk(old_key, "old"),
                _public_jwk(rotated_key, "rotated"),
            ),
        )
        provider = OidcDiscoveryJwksProvider(ISSUER, fetcher=fetcher)
        provider.refresh()
        authenticator = OidcAccessTokenAuthenticator(
            OidcAccessTokenPolicy(
                issuer=ISSUER,
                audience=AUDIENCE,
                tenant_id_claim="tid",
                subject_id_claim="oid",
                client_id_claim="azp",
                scope_claim="scp",
                identity_format="uuid",
                allowed_tenant_ids=frozenset({TENANT_ID}),
                allowed_client_ids=frozenset({CLIENT_ID}),
                required_scopes=frozenset({"access_as_user"}),
            ),
            provider,
        )
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "iss": ISSUER,
                "aud": AUDIENCE,
                "exp": now + timedelta(minutes=5),
                "nbf": now - timedelta(seconds=1),
                "iat": now - timedelta(seconds=1),
                "tid": TENANT_ID,
                "oid": SUBJECT_ID,
                "azp": CLIENT_ID,
                "scp": "access_as_user",
            },
            rotated_key,
            algorithm="RS256",
            headers={"kid": "rotated", "typ": "at+jwt"},
        )

        with ThreadPoolExecutor(max_workers=8) as pool:
            principals = list(
                pool.map(
                    authenticator.authenticate,
                    [f"Bearer {token}"] * 8,
                )
            )

        self.assertTrue(
            all(principal.subject_id == SUBJECT_ID for principal in principals)
        )
        self.assertEqual(
            [call[0] for call in fetcher.calls],
            [DISCOVERY_URL, JWKS_URL, JWKS_URL],
        )

    def test_unknown_key_refresh_and_discovery_cache_are_rate_limited(self) -> None:
        fetcher = _Fetcher(
            _discovery(),
            _jwks(_jwk("current")),
            _jwks(_jwk("current")),
        )
        provider = OidcDiscoveryJwksProvider(ISSUER, fetcher=fetcher)
        provider.refresh()

        with self.assertRaises(KeyError):
            provider.key_for("missing")
        with self.assertRaises(KeyError):
            provider.key_for("missing")

        self.assertEqual(
            [call[0] for call in fetcher.calls],
            [DISCOVERY_URL, JWKS_URL, JWKS_URL],
        )

    def test_retained_rotation_keys_have_a_total_cache_bound(self) -> None:
        base_key = _jwk("base")

        def key_set(prefix: str) -> bytes:
            return _jwks(
                *({**base_key, "kid": f"{prefix}-{index:02d}"} for index in range(64))
            )

        clock = _Clock()
        fetcher = _Fetcher(
            _discovery(),
            key_set("old"),
            key_set("middle"),
            key_set("current"),
            key_set("current"),
        )
        provider = OidcDiscoveryJwksProvider(
            ISSUER,
            fetcher=fetcher,
            monotonic=clock,
        )
        provider.refresh()
        clock.value += 1
        provider.refresh()
        clock.value += 1
        provider.refresh()

        self.assertIsNotNone(provider.key_for("current-00"))
        self.assertIsNotNone(provider.key_for("middle-00"))
        with self.assertRaises(KeyError):
            provider.key_for("old-00")

    def test_last_known_key_survives_one_bounded_metadata_outage(self) -> None:
        clock = _Clock()
        fetcher = _Fetcher(
            _discovery(),
            _jwks(_jwk("current")),
            TimeoutError("offline"),
        )
        provider = OidcDiscoveryJwksProvider(
            ISSUER,
            fetcher=fetcher,
            monotonic=clock,
        )
        provider.refresh()
        clock.value += 3_601

        self.assertIsNotNone(provider.key_for("current"))
        self.assertEqual(
            [call[0] for call in fetcher.calls],
            [DISCOVERY_URL, JWKS_URL, DISCOVERY_URL],
        )

    def test_unknown_key_reports_jwks_unavailable_when_rotation_fetch_fails(
        self,
    ) -> None:
        provider = OidcDiscoveryJwksProvider(
            ISSUER,
            fetcher=_Fetcher(
                _discovery(),
                _jwks(_jwk("current")),
                OSError("offline"),
            ),
        )
        provider.refresh()

        with self.assertRaises(OidcJwksUnavailable):
            provider.key_for("rotated")

    def test_failed_unknown_key_refresh_remains_typed_during_backoff(self) -> None:
        clock = _Clock()
        fetcher = _Fetcher(
            _discovery(),
            _jwks(_jwk("current")),
            OSError("offline"),
            _jwks(_jwk("current"), _jwk("rotated")),
        )
        provider = OidcDiscoveryJwksProvider(
            ISSUER,
            fetcher=fetcher,
            monotonic=clock,
        )
        provider.refresh()

        with self.assertRaises(OidcJwksUnavailable):
            provider.key_for("rotated")
        with self.assertRaises(OidcJwksUnavailable):
            provider.key_for("rotated")
        clock.value += 301
        self.assertIsNotNone(provider.key_for("rotated"))

        self.assertEqual(
            [call[0] for call in fetcher.calls],
            [DISCOVERY_URL, JWKS_URL, JWKS_URL, JWKS_URL],
        )


if __name__ == "__main__":
    unittest.main()
