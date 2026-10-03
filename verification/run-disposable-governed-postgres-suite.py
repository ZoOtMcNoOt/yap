from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import psycopg

_IMAGE = "pgvector/pgvector@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d"
_REPOSITORY = Path(__file__).resolve().parent.parent


def main() -> int:
    if sys.argv[1:]:
        raise RuntimeError("the disposable Postgres suite takes no arguments")
    if sys.platform != "linux":
        raise RuntimeError("the disposable Postgres suite requires Linux")
    server = _REPOSITORY / "server"
    subprocess.run(
        [
            sys.executable,
            str(_REPOSITORY / "verification/run-portable-server-suite.py"),
            "--identity-only",
        ],
        cwd=server,
        check=True,
        timeout=15,
    )
    executable = shutil.which("docker")
    if not executable:
        raise RuntimeError("the disposable Postgres suite requires Docker")
    docker = [executable, "--host=unix:///var/run/docker.sock"]
    environment = os.environ.copy()
    for variable in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        environment.pop(variable, None)
    # Explicitly own this runtime; never inherit an operator's database route.
    environment.pop("YAP_TEST_POSTGRES_DSN", None)
    environment["PYTHONPATH"] = "src"
    subprocess.run(docker + ["pull", _IMAGE], env=environment, check=True, timeout=120)
    container = None
    with TemporaryDirectory(prefix="yap-postgres-gate-") as directory:
        password = secrets.token_urlsafe(32)
        secret = Path(directory) / "container.env"
        with secret.open("x") as file:
            secret.chmod(0o600)
            file.write(
                "POSTGRES_USER=yap_test\nPOSTGRES_DB=yap_test\nPOSTGRES_PASSWORD="
                + password
                + "\n"
            )
        try:
            # The unique name also permits cleanup if startup loses its reply.
            container = "yap-postgres-gate-" + secrets.token_hex(12)
            subprocess.run(
                docker
                + [
                    "run",
                    "--detach",
                    "--name",
                    container,
                    "--publish",
                    "127.0.0.1::5432",
                    "--env-file",
                    str(secret),
                    "--cpus",
                    "2",
                    "--memory",
                    "512m",
                    "--tmpfs",
                    "/var/lib/postgresql/data:rw,nosuid,nodev,mode=0700",
                    _IMAGE,
                ],
                env=environment,
                check=True,
                timeout=30,
                stdout=subprocess.DEVNULL,
            )
            port = subprocess.check_output(
                docker + ["port", container, "5432/tcp"],
                env=environment,
                text=True,
                timeout=10,
            ).strip()
            if (
                not port.startswith("127.0.0.1:")
                or not port.removeprefix("127.0.0.1:").isdigit()
            ):
                raise RuntimeError("the disposable Postgres port must be loopback-only")
            dsn = "postgresql://yap_test:" + password + "@" + port + "/yap_test"
            deadline = time.monotonic() + 45
            while True:
                try:
                    with psycopg.connect(
                        dsn,
                        connect_timeout=2,
                        options="-c statement_timeout=5000 -c lock_timeout=1000",
                    ) as connection:
                        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
                        postgres = connection.execute("SHOW server_version").fetchone()[
                            0
                        ]
                        vector = connection.execute(
                            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                        ).fetchone()[0]
                    break
                except psycopg.OperationalError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "disposable Postgres readiness timed out"
                        ) from None
                    time.sleep(0.25)
            if postgres.split()[0] != "17.11" or vector != "0.8.7":
                raise RuntimeError("the pinned Postgres runtime identity differs")
            environment["YAP_TEST_POSTGRES_DSN"] = dsn
            subprocess.run(
                [
                    sys.executable,
                    str(
                        _REPOSITORY
                        / "verification/run-governed-knowledge-postgres-suite.py"
                    ),
                ],
                cwd=server,
                env=environment,
                check=True,
                timeout=150,
            )
            print(
                json.dumps(
                    {
                        "image": _IMAGE,
                        "postgresVersion": postgres,
                        "pgvectorVersion": vector,
                    },
                    sort_keys=True,
                )
            )
        finally:
            if container:
                # Cleanup failure also fails the gate; data lives only in this
                # owned container's tmpfs, with no developer/production mounts.
                subprocess.run(
                    docker + ["rm", "--force", container],
                    env=environment,
                    check=True,
                    timeout=30,
                    stdout=subprocess.DEVNULL,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
