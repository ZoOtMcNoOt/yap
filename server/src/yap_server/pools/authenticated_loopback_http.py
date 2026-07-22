from __future__ import annotations

from ipaddress import ip_address
import json
from typing import Protocol
from urllib.parse import urlsplit

from yap_server.pools.batch_contract import WorkerExecutionError


MAX_PRIVATE_API_KEY_BYTES = 512


class HttpResponse(Protocol):
    status: int

    def getheader(self, name: str) -> str | None: ...

    def read(self, amount: int = -1) -> bytes: ...


class HttpConnection(Protocol):
    def putrequest(self, method: str, path: str) -> None: ...

    def putheader(self, name: str, value: str) -> None: ...

    def endheaders(self) -> None: ...

    def send(self, value: object) -> None: ...

    def getresponse(self) -> HttpResponse: ...

    def close(self) -> None: ...


def parse_numeric_loopback_http_endpoint(
    endpoint: str,
    *,
    component: str,
) -> tuple[str, int]:
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except (AttributeError, ValueError) as error:
        raise ValueError(f"{component} endpoint is invalid") from error
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("",)
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
        or port is None
        or port == 0
    ):
        raise ValueError(
            f"{component} endpoint must be one numeric loopback HTTP authority"
        )
    try:
        address = ip_address(parsed.hostname)
    except ValueError as error:
        raise ValueError(
            f"{component} endpoint host must be a numeric IP address"
        ) from error
    if not address.is_loopback:
        raise ValueError(f"{component} endpoint must use a loopback address")
    return str(address), port


def validate_private_api_key(api_key: str, *, component: str) -> None:
    try:
        encoded = api_key.encode("ascii")
    except (AttributeError, UnicodeEncodeError) as error:
        raise ValueError(f"{component} API key must be printable ASCII") from error
    if not 1 <= len(encoded) <= MAX_PRIVATE_API_KEY_BYTES or any(
        byte <= 0x20 or byte >= 0x7F for byte in encoded
    ):
        raise ValueError(f"{component} API key is invalid")


def decode_bounded_json_response(
    response: HttpResponse,
    *,
    component: str,
    maximum_bytes: int,
    accepted_statuses: frozenset[int] = frozenset({200}),
) -> tuple[int, object]:
    if maximum_bytes <= 0 or not accepted_statuses:
        raise ValueError("HTTP response bounds are invalid")
    content_type = response.getheader("Content-Type")
    if not isinstance(content_type, str) or not content_type.lower().startswith(
        "application/json"
    ):
        raise WorkerExecutionError(f"{component} response content type is invalid")
    content_length = response.getheader("Content-Length")
    declared_length: int | None = None
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise WorkerExecutionError(
                f"{component} response content length is invalid"
            ) from error
        if not 0 <= declared_length <= maximum_bytes:
            raise WorkerExecutionError(f"{component} response exceeds the byte bound")
    encoded = response.read(maximum_bytes + 1)
    if len(encoded) > maximum_bytes:
        raise WorkerExecutionError(f"{component} response exceeds the byte bound")
    if declared_length is not None and len(encoded) != declared_length:
        raise WorkerExecutionError(
            f"{component} response length differs from its header"
        )
    if response.status not in accepted_statuses:
        raise WorkerExecutionError(f"{component} request returned an unexpected status")
    try:
        payload = json.loads(encoded, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise WorkerExecutionError(f"{component} response is not valid JSON") from error
    return response.status, payload


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
