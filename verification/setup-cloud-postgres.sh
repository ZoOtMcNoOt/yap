#!/usr/bin/env bash
set -euo pipefail
umask 077
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
postgres_root="$repo_root/.tools/postgres"
postgres_bin="$postgres_root/native/usr/lib/postgresql/17/bin"
source "$repo_root/verification/cloud-env.sh"
if [[ ! -f "$repo_root/.tools/apt/sources.list" ]]; then
  echo 'Run verification/setup-cloud-dev.sh first.' >&2
  exit 1
fi
mkdir -p "$postgres_root/archives/partial" "$postgres_root/socket"
if [[ ! -x "$postgres_bin/postgres" ]]; then
  apt_options=(
    -o "Dir::Etc::sourcelist=$repo_root/.tools/apt/sources.list"
    -o Dir::Etc::sourceparts=-
    -o "Dir::State::lists=$repo_root/.tools/apt/lists"
    -o "Dir::Cache::archives=$postgres_root/archives"
    -o Debug::NoLocking=1
  )
  if [[ -n "${HTTPS_PROXY:-}" ]]; then
    apt_options+=(-o "Acquire::https::Proxy=$HTTPS_PROXY")
  fi
  apt-get "${apt_options[@]}" --download-only -y --no-install-recommends install \
    postgresql-17=17.11-0+deb13u1 postgresql-client-17=17.11-0+deb13u1 postgresql-17-pgvector=0.8.0-1
  python3 - "$postgres_root" <<'PY'
from pathlib import Path
import subprocess
import sys
root = Path(sys.argv[1])
for package in sorted((root / "archives").glob("*.deb")):
    subprocess.run(["dpkg-deb", "-x", str(package), str(root / "native")], check=True)
PY
fi
export LD_LIBRARY_PATH="$postgres_root/native/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [[ ! -f "$postgres_root/data/PG_VERSION" ]]; then
  python3 - "$postgres_root" <<'PY'
import secrets
from pathlib import Path
import sys
root = Path(sys.argv[1])
if not (root / "password").exists():
    with (root / "password").open("x") as file:
        file.write(secrets.token_urlsafe(32))
PY
  "$postgres_bin/initdb" -D "$postgres_root/data" --username=yap_dev \
    --auth-local=trust --auth-host=scram-sha-256 --encoding=UTF8 --locale=C.UTF-8 \
    --pwfile="$postgres_root/password" --no-instructions
fi
if ! "$postgres_bin/pg_ctl" -D "$postgres_root/data" status >/dev/null; then
  python3 - "$postgres_root/port" <<'PY'
from pathlib import Path
import socket
import sys
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    Path(sys.argv[1]).write_text(str(listener.getsockname()[1]))
PY
  postgres_port="$(cat "$postgres_root/port")"
  "$postgres_bin/pg_ctl" -D "$postgres_root/data" -l "$postgres_root/server.log" -w start \
    -o "-h 127.0.0.1 -p $postgres_port -k $postgres_root/socket -c max_connections=20 -c shared_buffers=32MB"
fi
"$repo_root/server/.venv/bin/python" - "$postgres_root" <<'PY'
from pathlib import Path
import shlex
import sys
from urllib.parse import quote
import psycopg
root = Path(sys.argv[1])
password = root.joinpath("password").read_text().strip()
port = int(root.joinpath("port").read_text())
dsn = f"postgresql://yap_dev:{quote(password, safe='')}@127.0.0.1:{port}/postgres"
with psycopg.connect(dsn, connect_timeout=5) as connection:
    connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
    version = connection.execute("SHOW server_version").fetchone()[0]
    vector = connection.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
root.joinpath("env").write_text(f"export YAP_TEST_POSTGRES_DSN={shlex.quote(dsn)}\n")
print(f"Development Postgres {version}; pgvector {vector}; loopback-only, user-owned data.")
print(f"Load test access: source {root / 'env'}")
PY
