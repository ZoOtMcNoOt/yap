"""Finalize checked resident-provider evidence after host-boundary teardown."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from yap_server.bounded_file import read_regular_file
from yap_server.evaluation.private_evaluation_artifact import (
    read_json_object_with_identity,
)
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)
from yap_server.evaluation.provider_runtime_qualification import (
    write_private_evidence,
)


_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAXIMUM_SNAPSHOT_BYTES = 16 * 1024 * 1024
_MAXIMUM_CHILD_EVIDENCE_BYTES = 16 * 1024 * 1024
_UNCHANGED_SNAPSHOTS = ("listeners.txt", "firewall.txt", "services.txt")
_EMPTY_RUNTIME_SNAPSHOTS = (
    "containers.txt",
    "runtime-processes.txt",
    "networks.txt",
)
_FIREWALL_OBSERVATION_METHODS = {
    "ufw-status",
    "ufw-config-metadata",
    "nft",
    "iptables-save",
}


@dataclass(frozen=True, slots=True)
class _ChildRequirement:
    kind: str
    system_id: str
    identity: str
    selected_concurrencies: tuple[int, ...] = ()
    repeat_count: int | None = None
    completed_request_count: int | None = None
    duration_samples: tuple[int, ...] = ()
    exact_maximum_included: bool | None = None
    qualification_scope: str | None = None


_FINALIZED_DURATION_SAMPLES = (
    4_000,
    8_000,
    12_000,
    16_000,
    17_920,
    32_000,
    80_000,
    160_000,
    480_000,
)
_BATCH_DURATION_SAMPLES = (
    480_000,
    1_920_000,
    4_800_000,
    14_400_000,
    28_800_000,
    57_600_000,
    115_200_000,
    230_400_000,
)


_CHILD_REQUIREMENTS = {
    "vllm/readiness.json": _ChildRequirement(
        "readiness", "vllm-cohere-batch", "readiness"
    ),
    "vllm/short-tail.json": _ChildRequirement(
        "load",
        "vllm-cohere-batch",
        "vllm-short-tail",
        selected_concurrencies=(1, 2, 4),
        repeat_count=1,
        completed_request_count=600,
        duration_samples=(480_000,),
        qualification_scope="request-lifecycle",
    ),
    "vllm/cancellation.json": _ChildRequirement(
        "load", "vllm-cohere-batch", "vllm-cancelled-sibling"
    ),
    "vllm/slot-capacity.json": _ChildRequirement(
        "load", "vllm-cohere-batch", "vllm-slot-capacity"
    ),
    "vllm/pcm-capacity.json": _ChildRequirement(
        "load", "vllm-cohere-batch", "vllm-pcm-capacity"
    ),
    "vllm/duration-batch.json": _ChildRequirement(
        "duration",
        "vllm-cohere-batch",
        "batch-file",
        completed_request_count=8,
        duration_samples=_BATCH_DURATION_SAMPLES,
        exact_maximum_included=True,
    ),
    "vllm/resource-load.json": _ChildRequirement(
        "resource-load",
        "vllm-cohere-batch",
        "vllm-short-tail",
        selected_concurrencies=(8,),
        repeat_count=8,
        completed_request_count=1_600,
        duration_samples=(480_000,),
    ),
    "vllm/resources.json": _ChildRequirement(
        "resource", "vllm-cohere-batch", "vllm-short-tail"
    ),
    "nemo/readiness.json": _ChildRequirement(
        "readiness", "nemo-nemotron-finalized", "readiness"
    ),
    "nemo/short-tail.json": _ChildRequirement(
        "load",
        "nemo-nemotron-finalized",
        "nemo-finalized-short-tail",
        selected_concurrencies=(1, 2, 4),
        repeat_count=1,
        completed_request_count=600,
        duration_samples=(480_000,),
        qualification_scope="request-lifecycle",
    ),
    "nemo/long-windows.json": _ChildRequirement(
        "load",
        "nemo-nemotron-finalized",
        "nemo-finalized-long-windows",
        selected_concurrencies=(2,),
        repeat_count=1,
        completed_request_count=4,
        duration_samples=(14_400_000,),
        qualification_scope="request-lifecycle",
    ),
    "nemo/language-parity.json": _ChildRequirement(
        "load",
        "nemo-nemotron-finalized",
        "nemo-finalized-fixed-auto-parity",
    ),
    "nemo/cancellation.json": _ChildRequirement(
        "load",
        "nemo-nemotron-finalized",
        "nemo-finalized-cancelled-sibling",
    ),
    "nemo/active-capacity.json": _ChildRequirement(
        "load", "nemo-nemotron-finalized", "nemo-finalized-active-capacity"
    ),
    "nemo/duration-finalized.json": _ChildRequirement(
        "duration",
        "nemo-nemotron-finalized",
        "server-finalized-utterance",
        completed_request_count=9,
        duration_samples=_FINALIZED_DURATION_SAMPLES,
        exact_maximum_included=False,
    ),
    "nemo/duration-batch.json": _ChildRequirement(
        "duration",
        "nemo-nemotron-finalized",
        "batch-file",
        completed_request_count=8,
        duration_samples=_BATCH_DURATION_SAMPLES,
        exact_maximum_included=True,
    ),
    "nemo/resource-load.json": _ChildRequirement(
        "resource-load",
        "nemo-nemotron-finalized",
        "nemo-finalized-short-tail",
        selected_concurrencies=(8,),
        repeat_count=8,
        completed_request_count=1_600,
        duration_samples=(480_000,),
    ),
    "nemo/resources.json": _ChildRequirement(
        "resource", "nemo-nemotron-finalized", "nemo-finalized-short-tail"
    ),
}


def finalize_resident_provider_lifecycle_evidence(
    *,
    before_dir: Path,
    after_dir: Path,
    provider_evidence_root: Path,
    checked_head: str,
    output_path: Path,
) -> dict[str, object]:
    """Validate every required child and publish only after clean teardown."""

    if _GIT_SHA.fullmatch(checked_head) is None:
        raise ValueError("checked head must be a full lowercase Git SHA")
    host_boundary = _validate_host_boundary(before_dir, after_dir)
    children, duration_suite = _validate_child_evidence(
        provider_evidence_root,
        checked_head=checked_head,
    )
    evidence: dict[str, object] = {
        "schemaVersion": 1,
        "checkedHead": checked_head,
        "hardwareProfile": "dgx-spark-gb10",
        "executionShape": "sequential-resident-providers",
        "durationSuite": duration_suite,
        "hostBoundary": host_boundary,
        "childEvidence": children,
        "passed": True,
    }
    evidence["evidenceSha256"] = canonical_evidence_sha256(evidence)
    _validate_new_output(output_path)
    write_private_evidence(output_path, evidence)
    return evidence


def _validate_host_boundary(before_dir: Path, after_dir: Path) -> dict[str, object]:
    before = {
        name: _read_regular_file(
            before_dir / name,
            maximum_bytes=_MAXIMUM_SNAPSHOT_BYTES,
        )
        for name in (*_UNCHANGED_SNAPSHOTS, *_EMPTY_RUNTIME_SNAPSHOTS)
    }
    after = {
        name: _read_regular_file(
            after_dir / name,
            maximum_bytes=_MAXIMUM_SNAPSHOT_BYTES,
        )
        for name in (*_UNCHANGED_SNAPSHOTS, *_EMPTY_RUNTIME_SNAPSHOTS)
    }
    for name in _UNCHANGED_SNAPSHOTS:
        if before[name] != after[name]:
            raise RuntimeError(f"resident provider gate changed host state: {name}")
    for name in _EMPTY_RUNTIME_SNAPSHOTS:
        if before[name].strip():
            raise RuntimeError(f"resident provider gate started with state: {name}")
        if after[name].strip():
            raise RuntimeError(f"resident provider gate left state: {name}")
    firewall_method = _firewall_method(before["firewall.txt"])
    return {
        "listenerStateUnchanged": True,
        "firewallObservationUnchanged": True,
        "firewallObservationMethod": firewall_method,
        "serviceUnitsUnchanged": True,
        "remainingProviderContainers": 0,
        "remainingProviderRuntimeProcesses": 0,
        "remainingProviderNetworks": 0,
        "snapshotSha256": {
            name.removesuffix(".txt"): hashlib.sha256(before[name]).hexdigest()
            for name in _UNCHANGED_SNAPSHOTS
        },
    }


def _validate_child_evidence(
    root: Path,
    *,
    checked_head: str,
) -> tuple[dict[str, str], dict[str, str]]:
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("provider evidence root must be an absolute real directory")
    resolved = root.resolve(strict=True)
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("provider evidence root must be an absolute real directory")
    discovered = {
        path.relative_to(resolved).as_posix()
        for path in resolved.glob("*/*.json")
    }
    if discovered != set(_CHILD_REQUIREMENTS):
        raise ValueError("resident provider child evidence set differs from the gate")
    child_hashes: dict[str, str] = {}
    suite_identities: set[tuple[str, str]] = set()
    for relative, requirement in _CHILD_REQUIREMENTS.items():
        value = _read_json_object(
            resolved / relative,
            maximum_bytes=_MAXIMUM_CHILD_EVIDENCE_BYTES,
            containment_root=resolved,
        )
        evidence_sha256 = _validate_child(
            value,
            requirement=requirement,
            checked_head=checked_head,
        )
        child_hashes[relative.removesuffix(".json")] = evidence_sha256
        suite = value.get("durationSuite")
        if suite is not None:
            if not isinstance(suite, Mapping):
                raise ValueError("resident provider duration-suite evidence is invalid")
            suite_sha = suite.get("sha256")
            plan_sha = suite.get("planSha256")
            selected = suite.get("selectedDurationSamples")
            if (
                not isinstance(suite_sha, str)
                or _SHA256.fullmatch(suite_sha) is None
                or not isinstance(plan_sha, str)
                or _SHA256.fullmatch(plan_sha) is None
                or not isinstance(selected, list)
                or not selected
            ):
                raise ValueError("resident provider duration-suite evidence is invalid")
            suite_identities.add((suite_sha, plan_sha))
            if requirement.duration_samples and selected != list(
                requirement.duration_samples
            ):
                raise ValueError(
                    "resident provider duration-suite selection is incomplete"
                )
    if len(suite_identities) != 1:
        raise ValueError("resident provider cells used different duration suites")
    suite_sha256, plan_sha256 = suite_identities.pop()
    return (
        dict(sorted(child_hashes.items())),
        {"sha256": suite_sha256, "planSha256": plan_sha256},
    )


def _validate_child(
    value: Mapping[str, object],
    *,
    requirement: _ChildRequirement,
    checked_head: str,
) -> str:
    if (
        value.get("schemaVersion") != 1
        or value.get("systemId") != requirement.system_id
        or value.get("passed") is not True
    ):
        raise ValueError("resident provider child evidence did not pass its contract")
    candidate = value.get("candidate")
    if (
        not isinstance(candidate, Mapping)
        or candidate.get("checkedHead") != checked_head
        or candidate.get("repositoryState") != "clean"
        or not isinstance(candidate.get("inputs"), Mapping)
        or not candidate.get("inputs")
    ):
        raise ValueError("resident provider child evidence has the wrong candidate")
    recorded_hash = value.get("evidenceSha256")
    if not isinstance(recorded_hash, str) or _SHA256.fullmatch(recorded_hash) is None:
        raise ValueError("resident provider child evidence hash is invalid")
    unhashed = dict(value)
    unhashed.pop("evidenceSha256", None)
    if canonical_evidence_sha256(unhashed) != recorded_hash:
        raise ValueError("resident provider child evidence hash does not match")
    if requirement.kind == "readiness":
        if (
            value.get("readinessBoundary") != "probe-start-to-exact-model-ready"
            or not _positive_int(value.get("attemptCount"))
            or not _nonnegative_int(value.get("readyAfterMs"))
            or "durationSuite" in value
        ):
            raise ValueError("resident provider readiness evidence is invalid")
    elif requirement.kind == "duration":
        if (
            value.get("durationLadderId") != requirement.identity
            or value.get("qualificationScope") != "duration-transport-and-lifecycle"
            or value.get("representativeAccuracyClaim") is not False
            or value.get("selectedDurationSamples")
            != list(requirement.duration_samples)
            or value.get("exactMaximumIncluded")
            is not requirement.exact_maximum_included
            or value.get("completedRequestCount")
            != requirement.completed_request_count
        ):
            raise ValueError("resident provider duration evidence is invalid")
    else:
        if value.get("loadCaseId") != requirement.identity:
            raise ValueError("resident provider load evidence identity is invalid")
        if requirement.selected_concurrencies and (
            value.get("selectedConcurrencies")
            != list(requirement.selected_concurrencies)
            or value.get("repeatCount") != requirement.repeat_count
            or value.get("completedRequestCount")
            != requirement.completed_request_count
        ):
            raise ValueError("resident provider standard load evidence is incomplete")
        if (
            requirement.qualification_scope is not None
            and value.get("qualificationScope") != requirement.qualification_scope
        ):
            raise ValueError("resident provider load scope is invalid")
        if requirement.kind == "resource-load" and value.get(
            "qualificationScope"
        ) != "resource-lifecycle":
            raise ValueError("resident provider resource load scope is invalid")
        if requirement.kind == "resource" and (
            value.get("hardwareProfile") != "dgx-spark-gb10"
            or value.get("concurrency") != 8
            or value.get("completedRequestCount") != 1_600
            or "durationSuite" in value
        ):
            raise ValueError("resident provider resource evidence is invalid")
    return recorded_hash


def _read_json_object(
    path: Path,
    *,
    maximum_bytes: int,
    containment_root: Path,
) -> dict[str, object]:
    value, _identity = read_json_object_with_identity(
        path,
        maximum_bytes=maximum_bytes,
        field="resident provider child evidence",
        containment_root=containment_root,
    )
    return value


def _read_regular_file(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        return read_regular_file(path, maximum_bytes)
    except ValueError as error:
        raise ValueError("resident provider evidence input is unavailable") from error


def _firewall_method(payload: bytes) -> str:
    try:
        first_line = payload.splitlines()[0].decode("ascii")
    except (IndexError, UnicodeDecodeError) as error:
        raise RuntimeError("firewall evidence has an invalid observation method") from error
    if not first_line.startswith("tool="):
        raise RuntimeError("firewall evidence has an invalid observation method")
    method = first_line.removeprefix("tool=")
    if method not in _FIREWALL_OBSERVATION_METHODS:
        raise RuntimeError("firewall evidence has an invalid observation method")
    return method


def _validate_new_output(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("resident provider lifecycle output must be an absolute new file")
    parent = path.parent.resolve(strict=True)
    metadata = parent.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("resident provider lifecycle output parent is invalid")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("resident provider lifecycle output parent must be private")
    if path.exists() or path.is_symlink():
        raise ValueError("resident provider lifecycle output must be new")


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Finalize sequential resident-provider lifecycle evidence",
    )
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--provider-evidence-root", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    evidence = finalize_resident_provider_lifecycle_evidence(
        before_dir=arguments.before,
        after_dir=arguments.after,
        provider_evidence_root=arguments.provider_evidence_root,
        checked_head=arguments.checked_head,
        output_path=arguments.output,
    )
    print(json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
