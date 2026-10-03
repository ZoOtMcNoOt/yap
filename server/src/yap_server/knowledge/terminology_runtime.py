from __future__ import annotations

from pathlib import Path
from typing import Mapping

import psycopg

from yap_server.private_postgres_connection import private_postgres_connection_factory
from .terminology_service import TerminologyService
from .terminology_policy import TerminologyPolicy, build_terminology_policy


TERMINOLOGY_RUNTIME = "YAP_TERMINOLOGY_RUNTIME"
TERMINOLOGY_DSN_FILE = "YAP_TERMINOLOGY_DSN_FILE"


def build_terminology_service(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
    policy: TerminologyPolicy | None = None,
) -> TerminologyService | None:
    mode = environ.get(TERMINOLOGY_RUNTIME)
    has_credential = TERMINOLOGY_DSN_FILE in environ
    if mode is None:
        if has_credential:
            raise ValueError("terminology requires an explicit runtime mode")
        return None
    if mode not in {"disabled", "postgres"}:
        raise ValueError("terminology runtime mode is invalid")
    if mode == "disabled":
        if has_credential:
            raise ValueError("disabled terminology cannot include credentials")
        return None
    if not authenticated_team_mode:
        raise ValueError("terminology requires organization authentication")
    value = environ.get(TERMINOLOGY_DSN_FILE)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("terminology requires a database credential file")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("terminology credential path must be absolute")
    try:
        return TerminologyService(
            connection_factory=private_postgres_connection_factory(path),
            policy=policy
            if policy is not None
            else build_terminology_policy(
                environ, authenticated_team_mode=authenticated_team_mode
            ),
        )
    except (ValueError, psycopg.Error):
        raise ValueError("terminology database configuration is unavailable") from None
