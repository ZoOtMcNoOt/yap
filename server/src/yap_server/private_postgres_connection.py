from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
import os
from pathlib import Path
import stat
from typing import Callable, Iterator

import psycopg
from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict


_MAXIMUM_DSN_BYTES = 4_096
_CONNECT_TIMEOUT_SECONDS = 3
_STATEMENT_TIMEOUT_MILLISECONDS = 3_000

PrivatePostgresConnectionFactory = Callable[
    [], AbstractContextManager[Connection[object]]
]


def private_postgres_connection_factory(
    path: Path,
) -> PrivatePostgresConnectionFactory:
    """Create bounded Postgres connections from one owner-private DSN file."""

    dsn = read_private_postgres_dsn(path)
    conninfo_to_dict(dsn)

    @contextmanager
    def connect() -> Iterator[Connection[object]]:
        with psycopg.connect(
            dsn,
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            options=(
                f"-c statement_timeout={_STATEMENT_TIMEOUT_MILLISECONDS} "
                f"-c lock_timeout={_STATEMENT_TIMEOUT_MILLISECONDS}"
            ),
        ) as connection:
            yield connection

    return connect


def read_private_postgres_dsn(path: Path) -> str:
    requested = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(requested, flags)
    except OSError as error:
        raise ValueError("database credential file is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("database credential must be a regular file")
        if metadata.st_size > _MAXIMUM_DSN_BYTES:
            raise ValueError("database credential is too large")
        if os.name == "posix" and (
            stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.geteuid()
        ):
            raise ValueError("database credential is not owner-private")
        chunks: list[bytes] = []
        remaining = _MAXIMUM_DSN_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > _MAXIMUM_DSN_BYTES:
            raise ValueError("database credential is too large")
    finally:
        os.close(descriptor)
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("database credential is invalid") from error
    dsn = value.removesuffix("\n")
    if (
        not dsn
        or dsn.strip() != dsn
        or "\0" in dsn
        or "\r" in dsn
        or "\n" in dsn
    ):
        raise ValueError("database credential is invalid")
    return dsn


__all__ = [
    "PrivatePostgresConnectionFactory",
    "private_postgres_connection_factory",
    "read_private_postgres_dsn",
]
