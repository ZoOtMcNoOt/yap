"""Own the pinned Postgres/pgvector lifecycle used by the knowledge gate."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets
import socket
import subprocess
import time
from typing import Callable, Sequence
from urllib.parse import quote

from yap_server.private_artifact import read_json_object_with_identity


Runner = Callable[..., subprocess.CompletedProcess[str]]
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_NAME = "yap-governed-knowledge-postgres"
_NETWORK_NAME = "yap-governed-knowledge-postgres"
_VOLUME_NAME = "yap-governed-knowledge-postgres-data"
_OWNER_LABEL = "governed-knowledge-qualification"
_DATABASE_USER = "yap_gate"
_DATABASE_NAME = "yap_gate"
_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
_NANO_CPUS = 2_000_000_000
_PIDS_LIMIT = 256


@dataclass(frozen=True, slots=True)
class KnowledgeDatabaseRuntimeLock:
    image: str
    platform: str
    manifest_digest: str
    image_id: str
    postgres_version: str
    pgvector_version: str
    lock_sha256: str


@dataclass(frozen=True, slots=True)
class StartedKnowledgeDatabase:
    container_id: str
    image_id: str
    host_port: int
    process_id: int
    dsn: str


class OwnedPostgresKnowledgeRuntime:
    """Own one exact, isolated Postgres/pgvector qualification lifecycle."""

    def __init__(
        self,
        *,
        checked_head: str,
        runtime_lock: KnowledgeDatabaseRuntimeLock,
        runner: Runner = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        listener_absent: Callable[[int], bool] | None = None,
        process_absent: Callable[[int], bool] | None = None,
    ) -> None:
        if _SHA40.fullmatch(checked_head) is None:
            raise ValueError("knowledge database checked head is invalid")
        self._checked_head = checked_head
        self._runtime_lock = runtime_lock
        self._runner = runner
        self._sleep = sleep
        self._listener_absent = listener_absent or _listener_is_absent
        self._process_absent = process_absent or _process_is_absent
        self._network_created = False
        self._volume_created = False
        self._password: str | None = None
        self._started: StartedKnowledgeDatabase | None = None
        self._container_created = False
        self._created_container_id: str | None = None

    def start(self, *, timeout_seconds: int) -> StartedKnowledgeDatabase:
        if self._started is not None or self._network_created or self._volume_created:
            raise RuntimeError("knowledge database runtime is already started")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("knowledge database startup timeout is invalid")
        if self._container_exists() or self._network_exists() or self._volume_exists():
            raise RuntimeError("knowledge database qualification owner already exists")
        image_id = self._verified_image_id()
        password = secrets.token_urlsafe(32)
        self._password = password
        try:
            self._create_volume()
            self._create_network()
            completed = self._run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    _CONTAINER_NAME,
                    "--pull",
                    "never",
                    "--label",
                    f"io.yap.owner={_OWNER_LABEL}",
                    "--label",
                    f"io.yap.revision={self._checked_head}",
                    "--network",
                    _NETWORK_NAME,
                    "--publish",
                    "127.0.0.1::5432",
                    "--memory",
                    "2g",
                    "--cpus",
                    "2",
                    "--pids-limit",
                    str(_PIDS_LIMIT),
                    "--mount",
                    f"type=volume,source={_VOLUME_NAME},target=/var/lib/postgresql/data",
                    "--env",
                    f"POSTGRES_USER={_DATABASE_USER}",
                    "--env",
                    f"POSTGRES_DB={_DATABASE_NAME}",
                    "--env",
                    f"POSTGRES_PASSWORD={password}",
                    image_id,
                ],
                sensitive=True,
            )
            returned_container_id = completed.stdout.strip()
            self._container_created = True
            if re.fullmatch(r"[0-9a-f]{64}", returned_container_id):
                self._created_container_id = returned_container_id
            started, inspected = self._inspect_started_container(
                inspect_target=self._created_container_id or _CONTAINER_NAME,
                container_id=self._created_container_id,
                image_id=image_id,
                password=password,
            )
            self._started = started
            if returned_container_id != started.container_id:
                raise ValueError("knowledge database container identity is invalid")
            self._verify_container_policy(inspected, started=started, password=password)
            self._wait_ready(timeout_seconds)
            self._verify_postgres_package_version()
            return started
        except BaseException as error:
            try:
                self.contain_failed_run()
            except BaseException as containment_error:
                raise containment_error from error
            raise

    def restart(self, *, timeout_seconds: int) -> dict[str, bool]:
        previous = self._started
        password = self._password
        if previous is None or password is None:
            raise RuntimeError("knowledge database runtime was not started")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("knowledge database restart timeout is invalid")
        self._run(
            ["docker", "restart", "--time", "15", _CONTAINER_NAME],
            timeout=timeout_seconds + 15,
        )
        restarted, inspected = self._inspect_started_container(
            inspect_target=previous.container_id,
            container_id=previous.container_id,
            image_id=previous.image_id,
            password=password,
        )
        self._started = restarted
        self._verify_container_policy(inspected, started=restarted, password=password)
        if (
            restarted.process_id == previous.process_id
            or restarted.host_port != previous.host_port
            or not self._process_absent(previous.process_id)
        ):
            raise RuntimeError("knowledge database restart identity differs")
        self._wait_ready(timeout_seconds)
        self._verify_postgres_package_version()
        return {
            "newProcessObserved": True,
            "sameContainerObserved": True,
            "sameLoopbackPortObserved": True,
        }

    def stop(self, *, timeout_seconds: int) -> dict[str, bool]:
        started = self._started
        if started is None:
            raise RuntimeError("knowledge database runtime was not started")
        if not 1 <= timeout_seconds <= 60:
            raise ValueError("knowledge database teardown timeout is invalid")
        self._run(
            ["docker", "stop", "--time", str(timeout_seconds), _CONTAINER_NAME],
            timeout=timeout_seconds + 10,
        )
        self._run(["docker", "rm", _CONTAINER_NAME])
        self._run(["docker", "network", "rm", _NETWORK_NAME])
        self._run(["docker", "volume", "rm", _VOLUME_NAME])
        teardown = self._teardown_state(started)
        if not all(teardown.values()):
            raise RuntimeError("knowledge database teardown did not complete")
        self._clear_identity()
        return teardown

    def contain_failed_run(self) -> dict[str, bool]:
        started = self._started
        observation_error: BaseException | None = None
        if started is None and self._container_created:
            try:
                password = self._password
                if password is None:
                    raise RuntimeError(
                        "knowledge database launch secret is unavailable"
                    )
                started, _inspected = self._inspect_started_container(
                    inspect_target=self._created_container_id or _CONTAINER_NAME,
                    container_id=self._created_container_id,
                    image_id=self._runtime_lock.image_id,
                    password=password,
                )
                self._started = started
            except BaseException as error:
                observation_error = error
        self._force_cleanup()
        identity_unobserved = started is None and self._container_created
        if started is None:
            teardown = {
                "containerAbsent": not self._container_exists(),
                "listenerAbsent": True,
                "networkAbsent": not self._network_exists(),
                "ownedProcessAbsent": True,
                "sameLabelOwnersAbsent": self._same_label_owners_absent(),
                "volumeAbsent": not self._volume_exists(),
            }
        else:
            teardown = self._teardown_state(started)
        if not all(teardown.values()):
            raise RuntimeError(
                "knowledge database failure containment did not complete"
            )
        if identity_unobserved:
            raise RuntimeError(
                "created knowledge database identity could not be observed for containment"
            ) from observation_error
        self._clear_identity()
        return teardown

    def _create_volume(self) -> None:
        self._run(
            [
                "docker",
                "volume",
                "create",
                "--label",
                f"io.yap.owner={_OWNER_LABEL}",
                "--label",
                f"io.yap.revision={self._checked_head}",
                _VOLUME_NAME,
            ]
        )
        self._volume_created = True
        inspected = _single_inspection(
            self._run(["docker", "volume", "inspect", _VOLUME_NAME])
        )
        labels = inspected.get("Labels")
        if (
            inspected.get("Name") != _VOLUME_NAME
            or inspected.get("Driver") != "local"
            or not isinstance(labels, dict)
            or labels.get("io.yap.owner") != _OWNER_LABEL
            or labels.get("io.yap.revision") != self._checked_head
        ):
            raise ValueError("knowledge database volume ownership differs")

    def _create_network(self) -> None:
        self._run(
            [
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--label",
                f"io.yap.owner={_OWNER_LABEL}",
                "--label",
                f"io.yap.revision={self._checked_head}",
                _NETWORK_NAME,
            ]
        )
        self._network_created = True
        inspected = _single_inspection(
            self._run(["docker", "network", "inspect", _NETWORK_NAME])
        )
        labels = inspected.get("Labels")
        if (
            inspected.get("Name") != _NETWORK_NAME
            or inspected.get("Driver") != "bridge"
            or inspected.get("Internal") is not False
            or not isinstance(labels, dict)
            or labels.get("io.yap.owner") != _OWNER_LABEL
            or labels.get("io.yap.revision") != self._checked_head
        ):
            raise ValueError("knowledge database network ownership differs")

    def _verified_image_id(self) -> str:
        inspected = _single_inspection(
            self._run(["docker", "image", "inspect", self._runtime_lock.image])
        )
        repo_digests = inspected.get("RepoDigests")
        if (
            inspected.get("Os") != "linux"
            or inspected.get("Architecture") != "arm64"
            or inspected.get("Id") != self._runtime_lock.image_id
            or not isinstance(repo_digests, list)
            or not any(
                str(value).endswith(f"@{self._runtime_lock.manifest_digest}")
                for value in repo_digests
            )
        ):
            raise ValueError("knowledge database image differs from its lock")
        return self._runtime_lock.image_id

    def _inspect_started_container(
        self,
        *,
        inspect_target: str,
        container_id: str | None,
        image_id: str,
        password: str,
    ) -> tuple[StartedKnowledgeDatabase, dict[str, object]]:
        inspected = _single_inspection(
            self._run(["docker", "container", "inspect", inspect_target])
        )
        state = inspected.get("State")
        network_settings = inspected.get("NetworkSettings")
        published_ports = (
            network_settings.get("Ports")
            if isinstance(network_settings, dict)
            else None
        )
        process_id = state.get("Pid") if isinstance(state, dict) else None
        binding = _one_published_binding(published_ports)
        if (
            not isinstance(inspected.get("Id"), str)
            or re.fullmatch(r"[0-9a-f]{64}", inspected["Id"]) is None
            or (container_id is not None and inspected.get("Id") != container_id)
            or inspected.get("Name") != f"/{_CONTAINER_NAME}"
            or inspected.get("Image") != image_id
            or not isinstance(state, dict)
            or state.get("Running") is not True
            or isinstance(process_id, bool)
            or not isinstance(process_id, int)
            or process_id < 2
            or binding is None
        ):
            raise ValueError("knowledge database container identity differs")
        host_port = int(binding["HostPort"])
        started = StartedKnowledgeDatabase(
            container_id=str(inspected["Id"]),
            image_id=image_id,
            host_port=host_port,
            process_id=process_id,
            dsn=(
                f"postgresql://{_DATABASE_USER}:{quote(password, safe='')}"
                f"@127.0.0.1:{host_port}/{_DATABASE_NAME}"
            ),
        )
        return started, inspected

    def _verify_container_policy(
        self,
        inspected: dict[str, object],
        *,
        started: StartedKnowledgeDatabase,
        password: str,
    ) -> None:
        config = inspected.get("Config")
        host_config = inspected.get("HostConfig")
        network_settings = inspected.get("NetworkSettings")
        labels = config.get("Labels") if isinstance(config, dict) else None
        environment = config.get("Env") if isinstance(config, dict) else None
        port_bindings = (
            host_config.get("PortBindings") if isinstance(host_config, dict) else None
        )
        published_ports = (
            network_settings.get("Ports")
            if isinstance(network_settings, dict)
            else None
        )
        attached_networks = (
            network_settings.get("Networks")
            if isinstance(network_settings, dict)
            else None
        )
        mounts = inspected.get("Mounts")
        expected_environment = {
            f"POSTGRES_USER={_DATABASE_USER}",
            f"POSTGRES_DB={_DATABASE_NAME}",
            f"POSTGRES_PASSWORD={password}",
        }
        if (
            inspected.get("Id") != started.container_id
            or inspected.get("Name") != f"/{_CONTAINER_NAME}"
            or inspected.get("Image") != started.image_id
            or not isinstance(config, dict)
            or not isinstance(labels, dict)
            or labels.get("io.yap.owner") != _OWNER_LABEL
            or labels.get("io.yap.revision") != self._checked_head
            or not isinstance(environment, list)
            or not expected_environment.issubset(set(environment))
            or not isinstance(host_config, dict)
            or host_config.get("NetworkMode") != _NETWORK_NAME
            or host_config.get("Memory") != _MEMORY_BYTES
            or host_config.get("NanoCpus") != _NANO_CPUS
            or host_config.get("PidsLimit") != _PIDS_LIMIT
            or not _one_loopback_binding(port_bindings, assigned=False)
            or not _one_loopback_binding(published_ports, assigned=True)
            or not isinstance(attached_networks, dict)
            or set(attached_networks) != {_NETWORK_NAME}
            or not _exact_owned_volume_mount(mounts)
        ):
            raise ValueError("knowledge database container policy differs")

    def _wait_ready(self, timeout_seconds: int) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            ready = self._run(
                [
                    "docker",
                    "exec",
                    _CONTAINER_NAME,
                    "pg_isready",
                    "--username",
                    _DATABASE_USER,
                    "--dbname",
                    _DATABASE_NAME,
                ],
                check=False,
                timeout=5,
            )
            if ready.returncode == 0:
                return
            if not self._container_exists():
                raise RuntimeError("knowledge database exited before readiness")
            self._sleep(0.25)
        raise TimeoutError("knowledge database readiness timed out")

    def _verify_postgres_package_version(self) -> None:
        completed = self._run(
            [
                "docker",
                "exec",
                _CONTAINER_NAME,
                "dpkg-query",
                "--show",
                "--showformat=${Version}",
                "postgresql-17",
            ]
        )
        if completed.stdout.strip() != self._runtime_lock.postgres_version:
            raise ValueError(
                "knowledge database Postgres version differs from its lock"
            )

    def _teardown_state(
        self,
        started: StartedKnowledgeDatabase,
    ) -> dict[str, bool]:
        return {
            "containerAbsent": not self._container_exists(),
            "listenerAbsent": self._listener_absent(started.host_port),
            "networkAbsent": not self._network_exists(),
            "ownedProcessAbsent": self._process_absent(started.process_id),
            "sameLabelOwnersAbsent": self._same_label_owners_absent(),
            "volumeAbsent": not self._volume_exists(),
        }

    def _same_label_owners_absent(self) -> bool:
        commands = (
            ["docker", "ps", "--all", "--quiet"],
            ["docker", "network", "ls", "--quiet"],
            ["docker", "volume", "ls", "--quiet"],
        )
        filters = [
            "--filter",
            f"label=io.yap.owner={_OWNER_LABEL}",
            "--filter",
            f"label=io.yap.revision={self._checked_head}",
        ]
        for command in commands:
            completed = self._run([*command, *filters], check=False)
            if completed.returncode != 0 or completed.stdout.strip():
                return False
        return True

    def _container_exists(self) -> bool:
        return (
            self._run(
                ["docker", "container", "inspect", _CONTAINER_NAME],
                check=False,
            ).returncode
            == 0
        )

    def _network_exists(self) -> bool:
        return (
            self._run(
                ["docker", "network", "inspect", _NETWORK_NAME],
                check=False,
            ).returncode
            == 0
        )

    def _volume_exists(self) -> bool:
        return (
            self._run(
                ["docker", "volume", "inspect", _VOLUME_NAME],
                check=False,
            ).returncode
            == 0
        )

    def _force_cleanup(self) -> None:
        self._run(
            ["docker", "rm", "--force", _CONTAINER_NAME],
            check=False,
        )
        self._run(
            ["docker", "network", "rm", _NETWORK_NAME],
            check=False,
        )
        self._run(
            ["docker", "volume", "rm", _VOLUME_NAME],
            check=False,
        )

    def _clear_identity(self) -> None:
        self._started = None
        self._password = None
        self._network_created = False
        self._volume_created = False
        self._container_created = False
        self._created_container_id = None

    def _run(
        self,
        command: Sequence[str],
        *,
        check: bool = True,
        timeout: int = 30,
        sensitive: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = self._runner(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError, UnicodeError) as error:
            if sensitive:
                raise RuntimeError(
                    "sensitive knowledge database launch could not execute"
                ) from None
            raise RuntimeError(
                "knowledge database command could not execute"
            ) from error
        if check and completed.returncode != 0:
            message = "knowledge database command failed"
            if sensitive:
                message = "sensitive knowledge database launch failed"
            raise RuntimeError(message)
        return completed


def load_knowledge_database_runtime_lock(
    repository_root: Path,
) -> KnowledgeDatabaseRuntimeLock:
    path = repository_root / "server/runtime/knowledge/postgres-pgvector.lock.json"
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=8 * 1024,
        field="knowledge database runtime lock",
        containment_root=repository_root,
    )
    expected_keys = {
        "schemaVersion",
        "image",
        "platform",
        "manifestDigest",
        "observedImageId",
        "postgresVersion",
        "pgvectorVersion",
        "source",
        "license",
    }
    if set(value) != expected_keys:
        raise ValueError("knowledge database runtime lock fields differ")
    if (
        value["schemaVersion"] != 1
        or not isinstance(value["image"], str)
        or not value["image"]
        or value["platform"] != "linux/arm64"
        or not isinstance(value["manifestDigest"], str)
        or _IMAGE_SHA256.fullmatch(value["manifestDigest"]) is None
        or not isinstance(value["observedImageId"], str)
        or _IMAGE_SHA256.fullmatch(value["observedImageId"]) is None
        or not isinstance(value["postgresVersion"], str)
        or not re.fullmatch(r"17\.[0-9]+-[0-9A-Za-z.+~-]+", value["postgresVersion"])
        or not isinstance(value["pgvectorVersion"], str)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["pgvectorVersion"])
        or not isinstance(value["source"], str)
        or not value["source"].startswith("https://github.com/pgvector/")
        or value["license"] != "PostgreSQL"
    ):
        raise ValueError("knowledge database runtime lock is invalid")
    return KnowledgeDatabaseRuntimeLock(
        image=value["image"],
        platform=value["platform"],
        manifest_digest=value["manifestDigest"],
        image_id=value["observedImageId"],
        postgres_version=value["postgresVersion"],
        pgvector_version=value["pgvectorVersion"],
        lock_sha256=identity,
    )


def _one_published_binding(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or set(value) != {"5432/tcp"}:
        return None
    bindings = value["5432/tcp"]
    if (
        not isinstance(bindings, list)
        or len(bindings) != 1
        or not isinstance(bindings[0], dict)
        or set(bindings[0]) != {"HostIp", "HostPort"}
        or not isinstance(bindings[0]["HostIp"], str)
        or not isinstance(bindings[0]["HostPort"], str)
        or not bindings[0]["HostPort"].isdigit()
    ):
        return None
    port = int(bindings[0]["HostPort"])
    return bindings[0] if 1 <= port <= 65535 else None


def _one_loopback_binding(value: object, *, assigned: bool) -> bool:
    binding = _one_published_binding(value) if assigned else None
    if assigned:
        return binding is not None and binding["HostIp"] == "127.0.0.1"
    if not isinstance(value, dict) or set(value) != {"5432/tcp"}:
        return False
    bindings = value["5432/tcp"]
    return (
        isinstance(bindings, list)
        and len(bindings) == 1
        and isinstance(bindings[0], dict)
        and set(bindings[0]) == {"HostIp", "HostPort"}
        and bindings[0]["HostIp"] == "127.0.0.1"
        and isinstance(bindings[0]["HostPort"], str)
        and (bindings[0]["HostPort"] in {"", "0"} or bindings[0]["HostPort"].isdigit())
    )


def _exact_owned_volume_mount(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], dict)
        and value[0].get("Type") == "volume"
        and value[0].get("Name") == _VOLUME_NAME
        and value[0].get("Destination") == "/var/lib/postgresql/data"
        and value[0].get("RW") is True
    )


def _single_inspection(
    completed: subprocess.CompletedProcess[str],
) -> dict[str, object]:
    try:
        value = json.loads(completed.stdout)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("Docker inspection is invalid") from error
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError("Docker inspection is ambiguous")
    return value[0]


def _listener_is_absent(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.25)
        return client.connect_ex(("127.0.0.1", port)) != 0


def _process_is_absent(process_id: int) -> bool:
    return not Path(f"/proc/{process_id}").exists()


__all__ = [
    "KnowledgeDatabaseRuntimeLock",
    "OwnedPostgresKnowledgeRuntime",
    "StartedKnowledgeDatabase",
    "load_knowledge_database_runtime_lock",
]
