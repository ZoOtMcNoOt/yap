from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from yap_server.auth.signing_keys import (
    JwksSigningKeyProvider,
    SigningKeyUnavailable,
)


TENANT_ID = "11111111-1111-4111-8111-111111111111"
EXPECTED_URL = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"


def _jwk(key_id: str) -> dict[str, object]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    value = jwt.algorithms.RSAAlgorithm.to_jwk(
        key.public_key(),
        as_dict=True,
    )
    value.update({"kid": key_id, "use": "sig", "alg": "RS256"})
    return value


def _body(*keys: dict[str, object]) -> bytes:
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
                raise AssertionError("unexpected signing-key fetch")
            response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value


class JwksSigningKeyProviderTests(unittest.TestCase):
    def test_startup_fetches_only_the_tenant_derived_bounded_endpoint(self) -> None:
        fetcher = _Fetcher(_body(_jwk("current")))
        provider = JwksSigningKeyProvider(
            TENANT_ID,
            fetcher=fetcher,
        )

        provider.refresh()
        self.assertIsNotNone(provider.key_for("current"))

        self.assertEqual(len(fetcher.calls), 1)
        url, maximum_bytes, timeout_seconds = fetcher.calls[0]
        self.assertEqual(url, EXPECTED_URL)
        self.assertEqual(maximum_bytes, 256 * 1024)
        self.assertEqual(timeout_seconds, 2.0)

    def test_concurrent_unknown_key_causes_one_single_flight_refresh(self) -> None:
        fetcher = _Fetcher(
            _body(_jwk("old")),
            _body(_jwk("old"), _jwk("rotated")),
        )
        provider = JwksSigningKeyProvider(TENANT_ID, fetcher=fetcher)
        provider.refresh()

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(provider.key_for, ["rotated"] * 8))

        self.assertTrue(all(result is not None for result in results))
        self.assertEqual(len(fetcher.calls), 2)

    def test_unknown_key_refresh_is_rate_limited_when_key_remains_absent(self) -> None:
        fetcher = _Fetcher(_body(_jwk("current")), _body(_jwk("current")))
        provider = JwksSigningKeyProvider(TENANT_ID, fetcher=fetcher)
        provider.refresh()

        with self.assertRaises(KeyError):
            provider.key_for("missing")
        with self.assertRaises(KeyError):
            provider.key_for("missing")

        self.assertEqual(len(fetcher.calls), 2)

    def test_last_known_key_survives_a_bounded_refresh_outage(self) -> None:
        clock = _Clock()
        fetcher = _Fetcher(
            _body(_jwk("current")),
            OSError("offline"),
        )
        provider = JwksSigningKeyProvider(
            TENANT_ID,
            fetcher=fetcher,
            monotonic=clock,
        )
        provider.refresh()
        clock.value += 3_601

        self.assertIsNotNone(provider.key_for("current"))
        self.assertEqual(len(fetcher.calls), 2)

    def test_unknown_key_fails_unavailable_when_refresh_is_offline(self) -> None:
        fetcher = _Fetcher(
            _body(_jwk("current")),
            OSError("offline"),
        )
        provider = JwksSigningKeyProvider(TENANT_ID, fetcher=fetcher)
        provider.refresh()

        with self.assertRaises(SigningKeyUnavailable):
            provider.key_for("new")

    def test_malformed_or_untrusted_key_sets_fail_closed(self) -> None:
        invalid_sets = (
            b"{not-json",
            _body(),
            _body({"kid": "symmetric", "kty": "oct", "k": "c2VjcmV0"}),
            _body(_jwk("duplicate"), _jwk("duplicate")),
            b"x" * (256 * 1024 + 1),
        )
        for body in invalid_sets:
            with self.subTest(size=len(body)):
                provider = JwksSigningKeyProvider(
                    TENANT_ID,
                    fetcher=_Fetcher(body),
                )
                with self.assertRaises(SigningKeyUnavailable):
                    provider.refresh()
