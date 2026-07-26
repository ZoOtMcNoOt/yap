"""Reproducible cgroup-v2 sampling for checked resident ASR providers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from typing import Callable, Mapping

from yap_server.evaluation.provider_resource_observations import (
    ProviderResourceSample,
)


_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_RESIDENT_CONTAINER_NAMES = frozenset(
    {
        "yap-cohere-vllm",
        "yap-nemotron-nemo",
    }
)
_MAXIMUM_KERNEL_FILE_BYTES = 256 * 1024
_MAXIMUM_SAMPLES = 100_000
_MINIMUM_INTERVAL_MS = 10
_MAXIMUM_INTERVAL_MS = 5_000
DockerRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class ResidentProviderResourceBoundary:
    container_name: str
    process_id: int
    proc_root: Path
    cgroup_root: Path
    cgroup_path: Path
    cgroup_membership: str


@dataclass(frozen=True, slots=True)
class ResidentProviderWorkloadWindow:
    workload_start_ms: int
    workload_end_ms: int
    sample_count: int

    def public_evidence(self) -> dict[str, int]:
        return {
            "schemaVersion": 1,
            "workloadStartMs": self.workload_start_ms,
            "workloadEndMs": self.workload_end_ms,
            "sampleCount": self.sample_count,
        }


def inspect_resident_provider_resource_boundary(
    *,
    container_name: str,
    checked_head: str,
    runner: DockerRunner = subprocess.run,
    docker_binary: str = "docker",
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> ResidentProviderResourceBoundary:
    """Resolve one owned running container to its real unified cgroup."""

    if container_name not in _RESIDENT_CONTAINER_NAMES:
        raise ValueError("resident provider container name is invalid")
    if _GIT_SHA.fullmatch(checked_head) is None:
        raise ValueError("checked head must be a full lowercase Git SHA")
    if not docker_binary or any(character.isspace() for character in docker_binary):
        raise ValueError("Docker binary is invalid")
    try:
        completed = runner(
            [docker_binary, "container", "inspect", container_name],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ValueError("resident provider container could not be inspected") from error
    if completed.returncode != 0:
        raise ValueError("resident provider container could not be inspected")
    try:
        inspected = json.loads(completed.stdout)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("resident provider container inspection is invalid") from error
    if (
        not isinstance(inspected, list)
        or len(inspected) != 1
        or not isinstance(inspected[0], dict)
    ):
        raise ValueError("resident provider container inspection is invalid")
    container = inspected[0]
    state = container.get("State")
    config = container.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    process_id = state.get("Pid") if isinstance(state, dict) else None
    if (
        not isinstance(state, dict)
        or state.get("Running") is not True
        or isinstance(process_id, bool)
        or not isinstance(process_id, int)
        or process_id < 2
        or not isinstance(labels, dict)
        or labels.get("io.yap.owner") != "private-inference"
        or labels.get("io.yap.revision") != checked_head
    ):
        raise ValueError("resident provider container ownership is invalid")

    admitted_proc_root = _real_directory(proc_root, "process filesystem root")
    admitted_cgroup_root = _real_directory(cgroup_root, "cgroup-v2 filesystem root")
    process_root = admitted_proc_root / str(process_id)
    membership = _read_unified_cgroup_membership(process_root / "cgroup")
    requested_cgroup = admitted_cgroup_root / membership.lstrip("/")
    cgroup_path = _real_directory(requested_cgroup, "resident provider cgroup")
    if admitted_cgroup_root not in cgroup_path.parents:
        raise ValueError("resident provider cgroup escaped the unified hierarchy")
    status = _read_process_status(process_root / "status")
    if status["uid"] == 0:
        raise ValueError("resident provider container must use a non-root identity")
    return ResidentProviderResourceBoundary(
        container_name=container_name,
        process_id=process_id,
        proc_root=admitted_proc_root,
        cgroup_root=admitted_cgroup_root,
        cgroup_path=cgroup_path,
        cgroup_membership=membership,
    )


def read_resident_provider_resource_sample(
    boundary: ResidentProviderResourceBoundary,
    *,
    elapsed_ms: int,
) -> ProviderResourceSample:
    """Capture one internally consistent process and cgroup observation."""

    if (
        isinstance(elapsed_ms, bool)
        or not isinstance(elapsed_ms, int)
        or elapsed_ms < 0
    ):
        raise ValueError("resident provider sample time is invalid")
    process_root = boundary.proc_root / str(boundary.process_id)
    current_membership = _read_unified_cgroup_membership(process_root / "cgroup")
    if current_membership != boundary.cgroup_membership:
        raise ValueError("resident provider process changed cgroups during sampling")
    status = _read_process_status(process_root / "status")
    if status["uid"] == 0:
        raise ValueError("resident provider process changed to a root identity")
    memory_stat = _read_counter_map(boundary.cgroup_path / "memory.stat")
    memory_events = _read_counter_map(boundary.cgroup_path / "memory.events")
    cpu_stat = _read_counter_map(boundary.cgroup_path / "cpu.stat")
    return ProviderResourceSample(
        elapsed_ms=elapsed_ms,
        memory_current_bytes=_read_counter(boundary.cgroup_path / "memory.current"),
        memory_peak_bytes=_read_counter(boundary.cgroup_path / "memory.peak"),
        cgroup_anon_bytes=_required_counter(memory_stat, "anon", "memory.stat"),
        cgroup_file_bytes=_required_counter(memory_stat, "file", "memory.stat"),
        cgroup_kernel_bytes=_required_counter(memory_stat, "kernel", "memory.stat"),
        process_resident_bytes=status["resident_bytes"],
        process_resident_anon_bytes=status["resident_anon_bytes"],
        process_resident_file_bytes=status["resident_file_bytes"],
        process_resident_shared_bytes=status["resident_shared_bytes"],
        process_virtual_data_bytes=status["virtual_data_bytes"],
        process_thread_count=status["thread_count"],
        memory_high_events=_required_counter(memory_events, "high", "memory.events"),
        memory_max_events=_required_counter(memory_events, "max", "memory.events"),
        memory_oom_events=_required_counter(memory_events, "oom", "memory.events"),
        memory_oom_kill_events=_required_counter(
            memory_events,
            "oom_kill",
            "memory.events",
        ),
        cpu_usage_usec=_required_counter(cpu_stat, "usage_usec", "cpu.stat"),
        task_count=_read_counter(boundary.cgroup_path / "pids.current"),
    )


def collect_resident_provider_resource_samples(
    boundary: ResidentProviderResourceBoundary,
    *,
    output_path: Path,
    control_directory: Path,
    interval_ms: int = 250,
) -> ResidentProviderWorkloadWindow:
    """Sample until start, end, and stop markers define one workload window."""

    if (
        isinstance(interval_ms, bool)
        or not isinstance(interval_ms, int)
        or not _MINIMUM_INTERVAL_MS <= interval_ms <= _MAXIMUM_INTERVAL_MS
    ):
        raise ValueError("resident provider sample interval is invalid")
    if output_path.exists() or output_path.is_symlink():
        raise ValueError("resident provider sample output must be new")
    output_parent = _real_directory(output_path.parent, "sample output parent")
    if output_parent != output_path.parent.resolve(strict=True):
        raise ValueError("resident provider sample output parent is invalid")
    control = _real_directory(control_directory, "sample control directory")
    marker_paths = {
        name: control / name
        for name in (
            "ready.json",
            "workload-start",
            "workload-end",
            "stop",
            "workload-window.json",
        )
    }
    if any(path.exists() or path.is_symlink() for path in marker_paths.values()):
        raise ValueError("resident provider sample control directory is not fresh")

    origin_ns = time.monotonic_ns()
    sample_count = 0
    last_elapsed_ms = -1
    workload_start_ms: int | None = None
    workload_end_ms: int | None = None
    with output_path.open("x", encoding="utf-8", newline="\n") as output:
        os.chmod(output_path, 0o600)

        def capture(elapsed_ms: int) -> None:
            nonlocal last_elapsed_ms, sample_count
            if sample_count >= _MAXIMUM_SAMPLES:
                raise ValueError("resident provider sample count exceeds its bound")
            sample = read_resident_provider_resource_sample(
                boundary,
                elapsed_ms=elapsed_ms,
            )
            output.write(
                json.dumps(
                    _sample_payload(sample),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            output.write("\n")
            output.flush()
            sample_count += 1
            last_elapsed_ms = elapsed_ms

        capture(0)
        _write_new_json(
            marker_paths["ready.json"],
            {
                "schemaVersion": 1,
                "container": boundary.container_name,
                "processId": boundary.process_id,
            },
        )
        while True:
            time.sleep(interval_ms / 1_000)
            elapsed_ms = max(
                last_elapsed_ms + 1,
                (time.monotonic_ns() - origin_ns) // 1_000_000,
            )
            if (
                _regular_marker_exists(marker_paths["workload-start"])
                and workload_start_ms is None
            ):
                workload_start_ms = elapsed_ms
            if _regular_marker_exists(marker_paths["workload-end"]) and workload_end_ms is None:
                if workload_start_ms is None:
                    raise ValueError("workload end marker preceded its start marker")
                workload_end_ms = elapsed_ms
            capture(elapsed_ms)
            if _regular_marker_exists(marker_paths["stop"]):
                if workload_start_ms is None or workload_end_ms is None:
                    raise ValueError("resource sampler stopped before the workload closed")
                if workload_end_ms <= workload_start_ms:
                    raise ValueError("resource sampler workload window is empty")
                output.flush()
                os.fsync(output.fileno())
                window = ResidentProviderWorkloadWindow(
                    workload_start_ms=workload_start_ms,
                    workload_end_ms=workload_end_ms,
                    sample_count=sample_count,
                )
                _write_new_json(
                    marker_paths["workload-window.json"],
                    window.public_evidence(),
                )
                return window


def _regular_marker_exists(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError("resident provider sample marker could not be inspected") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("resident provider sample marker must be a real file")
    if metadata.st_size != 0:
        raise ValueError("resident provider sample marker must be empty")
    return True


def _sample_payload(sample: ProviderResourceSample) -> dict[str, int]:
    return {
        "elapsedMs": sample.elapsed_ms,
        "memoryCurrentBytes": sample.memory_current_bytes,
        "memoryPeakBytes": sample.memory_peak_bytes,
        "cgroupAnonBytes": sample.cgroup_anon_bytes,
        "cgroupFileBytes": sample.cgroup_file_bytes,
        "cgroupKernelBytes": sample.cgroup_kernel_bytes,
        "processResidentBytes": sample.process_resident_bytes,
        "processResidentAnonBytes": sample.process_resident_anon_bytes,
        "processResidentFileBytes": sample.process_resident_file_bytes,
        "processResidentSharedBytes": sample.process_resident_shared_bytes,
        "processVirtualDataBytes": sample.process_virtual_data_bytes,
        "processThreadCount": sample.process_thread_count,
        "memoryHighEvents": sample.memory_high_events,
        "memoryMaxEvents": sample.memory_max_events,
        "memoryOomEvents": sample.memory_oom_events,
        "memoryOomKillEvents": sample.memory_oom_kill_events,
        "cpuUsageUsec": sample.cpu_usage_usec,
        "taskCount": sample.task_count,
    }


def _read_unified_cgroup_membership(path: Path) -> str:
    lines = _read_kernel_text(path).splitlines()
    unified = [line[3:] for line in lines if line.startswith("0::")]
    if len(unified) != 1:
        raise ValueError("resident provider process is not in one cgroup-v2 hierarchy")
    membership = unified[0]
    candidate = Path(membership)
    if (
        not membership.startswith("/")
        or membership == "/"
        or ".." in candidate.parts
        or "\x00" in membership
    ):
        raise ValueError("resident provider cgroup membership is invalid")
    return membership


def _read_process_status(path: Path) -> dict[str, int]:
    values: dict[str, str] = {}
    for line in _read_kernel_text(path).splitlines():
        key, separator, raw = line.partition(":")
        if not separator:
            continue
        if key in values:
            raise ValueError("resident provider process status contains duplicate fields")
        values[key] = raw.strip()
    required = {
        "Uid",
        "VmRSS",
        "RssAnon",
        "RssFile",
        "RssShmem",
        "VmData",
        "Threads",
    }
    if not required <= set(values):
        raise ValueError("resident provider process status is incomplete")
    uid_parts = values["Uid"].split()
    if len(uid_parts) != 4 or any(not value.isdecimal() for value in uid_parts):
        raise ValueError("resident provider process identity is invalid")
    thread_count = _decimal_counter(values["Threads"], "process thread count")
    if thread_count < 1:
        raise ValueError("resident provider process thread count is invalid")
    return {
        "uid": int(uid_parts[0]),
        "resident_bytes": _kilobytes(values["VmRSS"], "VmRSS"),
        "resident_anon_bytes": _kilobytes(values["RssAnon"], "RssAnon"),
        "resident_file_bytes": _kilobytes(values["RssFile"], "RssFile"),
        "resident_shared_bytes": _kilobytes(values["RssShmem"], "RssShmem"),
        "virtual_data_bytes": _kilobytes(values["VmData"], "VmData"),
        "thread_count": thread_count,
    }


def _read_counter_map(path: Path) -> dict[str, int]:
    counters: dict[str, int] = {}
    for line in _read_kernel_text(path).splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[0] in counters:
            raise ValueError(f"{path.name} counter shape is invalid")
        counters[parts[0]] = _decimal_counter(parts[1], f"{path.name} counter")
    if not counters:
        raise ValueError(f"{path.name} counters are empty")
    return counters


def _required_counter(counters: Mapping[str, int], key: str, field: str) -> int:
    value = counters.get(key)
    if value is None:
        raise ValueError(f"{field} omitted the {key} counter")
    return value


def _read_counter(path: Path) -> int:
    return _decimal_counter(_read_kernel_text(path).strip(), path.name)


def _decimal_counter(value: str, field: str) -> int:
    if not value or not value.isdecimal():
        raise ValueError(f"{field} is not a nonnegative integer")
    parsed = int(value)
    if parsed > (1 << 63) - 1:
        raise ValueError(f"{field} exceeds its bound")
    return parsed


def _kilobytes(value: str, field: str) -> int:
    match = re.fullmatch(r"([0-9]+) kB", value)
    if match is None:
        raise ValueError(f"{field} is not a Linux kilobyte counter")
    return _decimal_counter(match.group(1), field) * 1_024


def _read_kernel_text(path: Path) -> str:
    if path.is_symlink():
        raise ValueError(f"{path.name} must be a real kernel file")
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError(f"{path.name} could not be inspected") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{path.name} must be a real kernel file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"{path.name} could not be opened") from error
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            body = stream.read(_MAXIMUM_KERNEL_FILE_BYTES + 1)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    if not body or len(body) > _MAXIMUM_KERNEL_FILE_BYTES:
        raise ValueError(f"{path.name} size is invalid")
    try:
        return body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError(f"{path.name} is not UTF-8") from error


def _real_directory(path: Path, field: str) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{field} must be an absolute real directory")
    try:
        requested = Path(os.path.abspath(path))
        resolved = path.resolve(strict=True)
        metadata = resolved.lstat()
    except OSError as error:
        raise ValueError(f"{field} must be an absolute real directory") from error
    is_junction = getattr(resolved, "is_junction", lambda: False)
    if (
        requested != resolved
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or is_junction()
    ):
        raise ValueError(f"{field} must be an absolute real directory")
    return resolved


def _write_new_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    with path.open("xb") as output:
        os.chmod(path, 0o600)
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())


def _private_cache_root(environ: Mapping[str, str]) -> Path:
    raw = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required for provider resource sampling")
    root = _real_directory(Path(raw), "YAP_EVAL_CACHE")
    repository = Path(__file__).resolve().parents[4]
    if root == repository or repository in root.parents:
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    if os.name == "posix" and stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError("YAP_EVAL_CACHE must use private permissions")
    return root


def _private_child_directory(path: Path, *, cache_root: Path, field: str) -> Path:
    resolved = _real_directory(path, field)
    if cache_root not in resolved.parents:
        raise ValueError(f"{field} must remain inside YAP_EVAL_CACHE")
    if os.name == "posix" and stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise ValueError(f"{field} must use private permissions")
    return resolved


def _private_new_output(path: Path, *, cache_root: Path) -> Path:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ValueError("provider resource sample output must be a new absolute file")
    prospective = path.resolve(strict=False)
    if cache_root not in prospective.parents:
        raise ValueError("provider resource sample output must remain inside YAP_EVAL_CACHE")
    _private_child_directory(
        prospective.parent,
        cache_root=cache_root,
        field="provider resource sample output parent",
    )
    return prospective


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sample one checked resident ASR provider through cgroup v2",
    )
    parser.add_argument("--container", required=True)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--control-directory", type=Path, required=True)
    parser.add_argument("--interval-ms", type=int, default=250)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    cache_root = _private_cache_root(os.environ)
    output = _private_new_output(arguments.output, cache_root=cache_root)
    control = _private_child_directory(
        arguments.control_directory,
        cache_root=cache_root,
        field="provider resource sample control directory",
    )
    boundary = inspect_resident_provider_resource_boundary(
        container_name=arguments.container,
        checked_head=arguments.checked_head,
        docker_binary=os.environ.get("YAP_DOCKER_BINARY", "docker"),
    )
    window = collect_resident_provider_resource_samples(
        boundary,
        output_path=output,
        control_directory=control,
        interval_ms=arguments.interval_ms,
    )
    print(
        json.dumps(
            window.public_evidence(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
