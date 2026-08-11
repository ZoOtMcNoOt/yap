from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit


def parse_numeric_loopback_http_endpoint(
    endpoint: str,
    *,
    component: str,
) -> tuple[str, int]:
    """Parse one canonical numeric-loopback HTTP authority."""

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


__all__ = ["parse_numeric_loopback_http_endpoint"]
