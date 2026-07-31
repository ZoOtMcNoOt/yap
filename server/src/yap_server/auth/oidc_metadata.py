from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from ipaddress import ip_address
import json
import threading
import time
from typing import Protocol
from urllib.parse import SplitResult, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jwt


_MAX_URL_CHARS = 2_048
_MAX_DISCOVERY_BYTES = 64 * 1024
_MAX_JWKS_BYTES = 256 * 1024
_MAX_SIGNING_KEYS = 64
_MAX_CACHED_SIGNING_KEYS = 2 * _MAX_SIGNING_KEYS
_MAX_KEY_ID_CHARS = 128
_MIN_RSA_KEY_BITS = 2_048
_MAX_RSA_KEY_BITS = 8_192
_FETCH_TIMEOUT_SECONDS = 2.0
_REFRESH_INTERVAL_SECONDS = 60 * 60
_UNKNOWN_KEY_REFRESH_INTERVAL_SECONDS = 5 * 60
_KEY_RETENTION_SECONDS = 24 * 60 * 60
_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"
_SUPPORTED_SIGNING_ALGORITHMS = frozenset({"RS256"})


class SigningKeyUnavailable(RuntimeError):
    """A trusted signing-key source cannot currently establish validity."""


class OidcMetadataUnavailable(SigningKeyUnavailable):
    """OIDC metadata needed for validation is unavailable or untrusted."""


class OidcDiscoveryUnavailable(OidcMetadataUnavailable):
    """OIDC discovery metadata is unavailable or untrusted."""


class OidcJwksUnavailable(OidcMetadataUnavailable):
    """The discovered OIDC signing-key set is unavailable or untrusted."""


class SigningKeyProvider(Protocol):
    def key_for(self, key_id: str) -> object:
        """Return the trusted public key for one validated key identifier."""


MetadataFetcher = Callable[..., bytes]


@dataclass(frozen=True, slots=True)
class _CachedSigningKey:
    key: object
    observed_at: float


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


def _fetch_metadata(
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
    opener = build_opener(_NoRedirectHandler())
    with opener.open(request, timeout=timeout_seconds) as response:
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > maximum_bytes:
            raise ValueError("metadata response is too large")
        body = response.read(maximum_bytes + 1)
    if len(body) > maximum_bytes:
        raise ValueError("metadata response is too large")
    return body


def _loopback_host(host: str) -> bool:
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _validated_url(
    value: str,
    *,
    allow_insecure_loopback: bool,
    issuer: bool,
) -> tuple[str, SplitResult]:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_URL_CHARS
        or not value.isascii()
        or not value.isprintable()
        or value.strip() != value
    ):
        raise ValueError("OIDC metadata URL is invalid")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        parsed.port
    except ValueError as error:
        raise ValueError("OIDC metadata URL is invalid") from error
    if (
        host is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (issuer and (parsed.query or value.endswith("/")))
    ):
        raise ValueError("OIDC metadata URL is invalid")
    if parsed.scheme == "https":
        return value, parsed
    if parsed.scheme == "http" and allow_insecure_loopback and _loopback_host(host):
        return value, parsed
    raise ValueError("OIDC metadata URL must use trusted transport")


def _same_origin(first: SplitResult, second: SplitResult) -> bool:
    try:
        first_port = first.port or (443 if first.scheme == "https" else 80)
        second_port = second.port or (443 if second.scheme == "https" else 80)
    except ValueError:
        return False
    return (
        first.scheme == second.scheme
        and first.hostname == second.hostname
        and first_port == second_port
    )


class OidcDiscoveryJwksProvider:
    """Owns bounded OIDC discovery, JWKS caching, and rotation refresh."""

    def __init__(
        self,
        issuer: str,
        *,
        allowed_algorithms: frozenset[str] = _SUPPORTED_SIGNING_ALGORITHMS,
        allow_insecure_loopback: bool = False,
        fetcher: MetadataFetcher = _fetch_metadata,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._issuer, self._issuer_url = _validated_url(
            issuer,
            allow_insecure_loopback=allow_insecure_loopback,
            issuer=True,
        )
        if (
            not isinstance(allowed_algorithms, frozenset)
            or not allowed_algorithms
            or not allowed_algorithms <= _SUPPORTED_SIGNING_ALGORITHMS
        ):
            raise ValueError("OIDC signing algorithms are not supported")
        self._allowed_algorithms = allowed_algorithms
        self._allow_insecure_loopback = allow_insecure_loopback
        self._discovery_url = f"{self._issuer}{_DISCOVERY_SUFFIX}"
        self._fetcher = fetcher
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._jwks_uri: str | None = None
        self._keys: dict[str, _CachedSigningKey] = {}
        self._last_discovery_refresh: float | None = None
        self._last_key_refresh: float | None = None
        self._last_unknown_refresh: float | None = None
        self._last_unknown_refresh_failure: type[OidcMetadataUnavailable] | None = None

    def refresh(self) -> None:
        with self._lock:
            self._refresh_keys_locked(self._monotonic())

    def key_for(self, key_id: str) -> object:
        self._validate_key_id(key_id)
        with self._lock:
            now = self._monotonic()
            cached = self._keys.get(key_id)
            if (
                cached is None
                and self._last_unknown_refresh is not None
                and now - self._last_unknown_refresh
                < _UNKNOWN_KEY_REFRESH_INTERVAL_SECONDS
            ):
                failure_type = self._last_unknown_refresh_failure
                if failure_type is not None:
                    raise failure_type("recent trusted OIDC signing-key refresh failed")
                raise KeyError(key_id)
            refresh_attempted = False
            if (
                self._last_key_refresh is None
                or now - self._last_key_refresh >= _REFRESH_INTERVAL_SECONDS
            ):
                refresh_attempted = True
                try:
                    self._refresh_keys_locked(now)
                except OidcMetadataUnavailable as error:
                    if (
                        cached is not None
                        and now - cached.observed_at <= _KEY_RETENTION_SECONDS
                    ):
                        return cached.key
                    self._last_unknown_refresh = now
                    self._last_unknown_refresh_failure = type(error)
                    raise
                cached = self._keys.get(key_id)
            if cached is not None:
                return cached.key
            if refresh_attempted:
                self._last_unknown_refresh = now
                self._last_unknown_refresh_failure = None
                raise KeyError(key_id)
            self._last_unknown_refresh = now
            try:
                self._refresh_keys_locked(now)
            except OidcMetadataUnavailable as error:
                self._last_unknown_refresh_failure = type(error)
                raise
            self._last_unknown_refresh_failure = None
            cached = self._keys.get(key_id)
            if cached is None:
                raise KeyError(key_id)
            return cached.key

    @staticmethod
    def _validate_key_id(key_id: object) -> None:
        if (
            not isinstance(key_id, str)
            or not key_id
            or len(key_id) > _MAX_KEY_ID_CHARS
            or not key_id.isascii()
            or not key_id.isprintable()
            or key_id.strip() != key_id
        ):
            raise KeyError("invalid signing key identifier")

    def _refresh_keys_locked(self, now: float) -> None:
        jwks_uri = self._jwks_uri
        if (
            jwks_uri is None
            or self._last_discovery_refresh is None
            or now - self._last_discovery_refresh >= _REFRESH_INTERVAL_SECONDS
        ):
            jwks_uri = self._refresh_discovery_locked(now)
        try:
            body = self._fetcher(
                jwks_uri,
                maximum_bytes=_MAX_JWKS_BYTES,
                timeout_seconds=_FETCH_TIMEOUT_SECONDS,
            )
            keys = self._decode_keys(body)
        except OidcJwksUnavailable:
            raise
        except (
            OSError,
            TimeoutError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            jwt.PyJWTError,
        ) as error:
            raise OidcJwksUnavailable(
                "trusted OIDC signing keys are unavailable"
            ) from error
        retained_candidates = sorted(
            (
                (key_id, cached)
                for key_id, cached in self._keys.items()
                if key_id not in keys
                and now - cached.observed_at <= _KEY_RETENTION_SECONDS
            ),
            key=lambda item: (-item[1].observed_at, item[0]),
        )
        retained = dict(retained_candidates[: _MAX_CACHED_SIGNING_KEYS - len(keys)])
        retained.update(
            {
                key_id: _CachedSigningKey(key=key, observed_at=now)
                for key_id, key in keys.items()
            }
        )
        self._keys = retained
        self._last_key_refresh = now
        self._last_unknown_refresh_failure = None

    def _refresh_discovery_locked(self, now: float) -> str:
        try:
            body = self._fetcher(
                self._discovery_url,
                maximum_bytes=_MAX_DISCOVERY_BYTES,
                timeout_seconds=_FETCH_TIMEOUT_SECONDS,
            )
            jwks_uri = self._decode_discovery(body)
        except OidcDiscoveryUnavailable:
            raise
        except (
            OSError,
            TimeoutError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise OidcDiscoveryUnavailable(
                "trusted OIDC discovery metadata is unavailable"
            ) from error
        self._jwks_uri = jwks_uri
        self._last_discovery_refresh = now
        return jwks_uri

    def _decode_discovery(self, body: bytes) -> str:
        if not isinstance(body, bytes) or len(body) > _MAX_DISCOVERY_BYTES:
            raise ValueError("OIDC discovery response is invalid")
        document = json.loads(body)
        if not isinstance(document, Mapping):
            raise ValueError("OIDC discovery document is invalid")
        if document.get("issuer") != self._issuer:
            raise ValueError("OIDC discovery issuer does not match")
        raw_jwks_uri = document.get("jwks_uri")
        jwks_uri, parsed = _validated_url(
            raw_jwks_uri,
            allow_insecure_loopback=self._allow_insecure_loopback,
            issuer=False,
        )
        if not _same_origin(self._issuer_url, parsed):
            raise ValueError("OIDC JWKS endpoint origin does not match issuer")
        return jwks_uri

    def _decode_keys(self, body: bytes) -> dict[str, object]:
        if not isinstance(body, bytes) or len(body) > _MAX_JWKS_BYTES:
            raise ValueError("OIDC signing-key response is invalid")
        document = json.loads(body)
        if not isinstance(document, Mapping) or "keys" not in document:
            raise ValueError("OIDC signing-key document is invalid")
        raw_keys = document["keys"]
        if (
            not isinstance(raw_keys, list)
            or not raw_keys
            or len(raw_keys) > _MAX_SIGNING_KEYS
        ):
            raise ValueError("OIDC signing-key set is invalid")
        keys: dict[str, object] = {}
        for raw_key in raw_keys:
            if not isinstance(raw_key, Mapping):
                raise ValueError("OIDC signing key is invalid")
            key_id = raw_key.get("kid")
            try:
                self._validate_key_id(key_id)
            except KeyError as error:
                raise ValueError("OIDC signing key identifier is invalid") from error
            assert isinstance(key_id, str)
            if key_id in keys:
                raise ValueError("OIDC signing-key identifier is duplicated")
            key_algorithm = raw_key.get("alg")
            key_use = raw_key.get("use")
            key_operations = raw_key.get("key_ops")
            if (
                raw_key.get("kty") != "RSA"
                or key_algorithm not in {None, *self._allowed_algorithms}
                or key_use not in {None, "sig"}
                or (
                    key_operations is not None
                    and (
                        not isinstance(key_operations, list)
                        or "verify" not in key_operations
                    )
                )
            ):
                raise ValueError("OIDC signing key is not allowed")
            key = jwt.PyJWK.from_dict(
                dict(raw_key),
                algorithm=(
                    key_algorithm
                    if isinstance(key_algorithm, str)
                    else next(iter(self._allowed_algorithms))
                ),
            ).key
            key_size = getattr(key, "key_size", None)
            if (
                isinstance(key_size, bool)
                or not isinstance(key_size, int)
                or not _MIN_RSA_KEY_BITS <= key_size <= _MAX_RSA_KEY_BITS
            ):
                raise ValueError("OIDC signing key strength is not allowed")
            keys[key_id] = key
        return keys


__all__ = [
    "OidcDiscoveryJwksProvider",
    "OidcDiscoveryUnavailable",
    "OidcJwksUnavailable",
    "OidcMetadataUnavailable",
    "SigningKeyProvider",
    "SigningKeyUnavailable",
]
