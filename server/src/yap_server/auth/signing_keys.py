from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import threading
import time
from typing import Protocol
from urllib.request import Request, urlopen

import jwt


_MAX_JWKS_BYTES = 256 * 1024
_MAX_SIGNING_KEYS = 64
_MAX_KEY_ID_CHARS = 128
_FETCH_TIMEOUT_SECONDS = 2.0
_REFRESH_INTERVAL_SECONDS = 60 * 60
_UNKNOWN_KEY_REFRESH_INTERVAL_SECONDS = 5 * 60
_KEY_RETENTION_SECONDS = 24 * 60 * 60


class SigningKeyUnavailable(RuntimeError):
    """The trusted key source cannot currently establish token validity."""


class SigningKeyProvider(Protocol):
    def key_for(self, key_id: str) -> object:
        """Return the trusted public key for one validated key identifier."""


SigningKeyFetcher = Callable[..., bytes]


@dataclass(frozen=True, slots=True)
class _CachedSigningKey:
    key: object
    observed_at: float


def _fetch_signing_keys(
    url: str,
    *,
    maximum_bytes: int,
    timeout_seconds: float,
) -> bytes:
    request = Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > maximum_bytes:
            raise ValueError("signing-key response is too large")
        body = response.read(maximum_bytes + 1)
    if len(body) > maximum_bytes:
        raise ValueError("signing-key response is too large")
    return body


class JwksSigningKeyProvider:
    def __init__(
        self,
        tenant_id: str,
        *,
        fetcher: SigningKeyFetcher = _fetch_signing_keys,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        self._fetcher = fetcher
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._keys: dict[str, _CachedSigningKey] = {}
        self._last_refresh: float | None = None
        self._last_unknown_refresh: float | None = None

    def refresh(self) -> None:
        with self._lock:
            self._refresh_locked(self._monotonic())

    def key_for(self, key_id: str) -> object:
        self._validate_key_id(key_id)
        with self._lock:
            now = self._monotonic()
            cached = self._keys.get(key_id)
            refresh_attempted = False
            if (
                self._last_refresh is None
                or now - self._last_refresh >= _REFRESH_INTERVAL_SECONDS
            ):
                refresh_attempted = True
                try:
                    self._refresh_locked(now)
                except SigningKeyUnavailable:
                    if (
                        cached is not None
                        and now - cached.observed_at <= _KEY_RETENTION_SECONDS
                    ):
                        return cached.key
                    raise
                cached = self._keys.get(key_id)
            if cached is not None:
                return cached.key
            if refresh_attempted:
                self._last_unknown_refresh = now
                raise KeyError(key_id)
            if (
                self._last_unknown_refresh is not None
                and now - self._last_unknown_refresh
                < _UNKNOWN_KEY_REFRESH_INTERVAL_SECONDS
            ):
                raise KeyError(key_id)
            self._last_unknown_refresh = now
            self._refresh_locked(now)
            cached = self._keys.get(key_id)
            if cached is None:
                raise KeyError(key_id)
            return cached.key

    @staticmethod
    def _validate_key_id(key_id: str) -> None:
        if (
            not isinstance(key_id, str)
            or not key_id
            or len(key_id) > _MAX_KEY_ID_CHARS
            or not key_id.isascii()
            or not key_id.isprintable()
        ):
            raise KeyError("invalid signing key identifier")

    def _refresh_locked(self, now: float) -> None:
        try:
            body = self._fetcher(
                self._url,
                maximum_bytes=_MAX_JWKS_BYTES,
                timeout_seconds=_FETCH_TIMEOUT_SECONDS,
            )
            keys = self._decode_keys(body)
        except SigningKeyUnavailable:
            raise
        except (
            OSError,
            TimeoutError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            jwt.PyJWTError,
        ) as error:
            raise SigningKeyUnavailable(
                "trusted signing keys are unavailable"
            ) from error
        retained = {
            key_id: cached
            for key_id, cached in self._keys.items()
            if now - cached.observed_at <= _KEY_RETENTION_SECONDS
        }
        retained.update(
            {
                key_id: _CachedSigningKey(key=key, observed_at=now)
                for key_id, key in keys.items()
            }
        )
        self._keys = retained
        self._last_refresh = now

    @staticmethod
    def _decode_keys(body: bytes) -> dict[str, object]:
        if not isinstance(body, bytes) or len(body) > _MAX_JWKS_BYTES:
            raise ValueError("signing-key response is invalid")
        document = json.loads(body)
        if not isinstance(document, Mapping) or set(document) != {"keys"}:
            raise ValueError("signing-key document is invalid")
        raw_keys = document["keys"]
        if (
            not isinstance(raw_keys, list)
            or not raw_keys
            or len(raw_keys) > _MAX_SIGNING_KEYS
        ):
            raise ValueError("signing-key set is invalid")
        keys: dict[str, object] = {}
        for raw_key in raw_keys:
            if not isinstance(raw_key, Mapping):
                raise ValueError("signing key is invalid")
            key_id = raw_key.get("kid")
            JwksSigningKeyProvider._validate_key_id(key_id)
            if key_id in keys:
                raise ValueError("signing-key identifier is duplicated")
            if (
                raw_key.get("kty") != "RSA"
                or raw_key.get("use") != "sig"
                or raw_key.get("alg") != "RS256"
            ):
                raise ValueError("signing key is not an allowed RSA key")
            keys[key_id] = jwt.PyJWK.from_dict(
                dict(raw_key),
                algorithm="RS256",
            ).key
        return keys
