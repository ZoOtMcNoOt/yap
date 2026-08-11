"""Admit one previously reviewed private agent-route qualification tree."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Callable, Mapping, Sequence

from yap_server.evaluation.agent_model_acceptance import (
    load_agent_model_acceptance,
)
from yap_server.evaluation.agent_model_candidate_runner import (
    AgentCandidateRun,
)
from yap_server.evaluation.agent_model_qualification import (
    _candidate_models,
    _candidate_summary,
)
from yap_server.evaluation.checked_candidate import CheckedCandidate
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)
from yap_server.private_artifact import (
    read_bounded_regular_file,
    read_json_object_with_identity,
)


GitRunner = Callable[..., subprocess.CompletedProcess[str]]
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_CANDIDATES = (
    "qwen3.6-35b-a3b-nvfp4",
    "gemma-4-31b-it-nvfp4",
)
_MODEL_INPUT_PATHS = (
    "server/agent-model-acceptance.json",
    "server/agent-reasoning-candidates.lock.json",
    "server/agent-workload-fixtures.json",
    "server/runtime/agent-vllm/Dockerfile",
    "server/runtime/agent-vllm/build-qwen-vllm-runtime.sh",
    "server/runtime/agent-vllm/THIRD_PARTY_NOTICES.md",
)
_MODEL_DEPENDENCY_PATHS = (
    "server/pyproject.toml",
    "server/uv.lock",
)
_CANDIDATE_ARTIFACTS = (
    "results.json",
    "runtime-receipt.json",
    "children/cancellation.json",
    "children/fixtures.json",
    "children/lifecycle.json",
    "children/pressure.json",
    "children/resources.json",
)
_EXPECTED_ARTIFACTS = (
    "qualification.json",
    *(
        f"{candidate_id}/{relative}"
        for candidate_id in _REQUIRED_CANDIDATES
        for relative in _CANDIDATE_ARTIFACTS
    ),
)
_PROTECTED_ROUTE_PATHS = frozenset(
    {
        *_MODEL_INPUT_PATHS,
        *_MODEL_DEPENDENCY_PATHS,
        "server/src/yap_server/private_artifact.py",
        "server/src/yap_server/evaluation/agent_route_qualification_evidence.py",
        "server/src/yap_server/evaluation/governed_knowledge_gate.py",
        "server/src/yap_server/evaluation/private_json_evidence.py",
        "server/src/yap_server/evaluation/checked_candidate.py",
        "server/src/yap_server/evaluation/provider_runtime_observations.py",
        "server/src/yap_server/evaluation/vllm_runtime_metrics.py",
        "server/src/yap_server/knowledge/agent_reasoning_routes.py",
        "server/src/yap_server/knowledge/governed_answer_protocol.py",
        "server/src/yap_server/knowledge/governed_knowledge_tools.py",
        "server/src/yap_server/knowledge/governed_rag_agent.py",
        "server/src/yap_server/knowledge/knowledge_tool_contract.py",
        "server/src/yap_server/knowledge/vllm_reasoning_client.py",
        "server/tests/evaluation/test_vllm_runtime_metrics.py",
        "server/tests/evaluation/test_agent_route_qualification_evidence.py",
        "server/tests/evaluation/test_governed_knowledge_gate.py",
        "server/tests/knowledge/test_agent_reasoning_routes.py",
        "server/tests/knowledge/test_governed_answer_protocol.py",
        "server/tests/knowledge/test_governed_knowledge_mcp.py",
        "server/tests/knowledge/test_governed_rag_agent.py",
        "server/tests/knowledge/test_vllm_reasoning_client.py",
    }
)


@dataclass(frozen=True, slots=True)
class AgentRouteQualificationReference:
    checked_head: str
    outcome: str
    evidence_sha256: str
    input_sha256: Mapping[str, str]
    dependency_sha256: Mapping[str, str]
    artifact_sha256: Mapping[str, str]
    lock_sha256: str


@dataclass(frozen=True, slots=True)
class AdmittedAgentRouteQualification:
    checked_head: str
    outcome: str
    evidence_sha256: str
    lock_sha256: str


def load_agent_route_qualification_reference(
    repository_root: Path,
) -> AgentRouteQualificationReference:
    path = repository_root / "server/agent-model-route-qualification.lock.json"
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=32 * 1024,
        field="agent route qualification reference",
        containment_root=repository_root,
    )
    if set(value) != {
        "schemaVersion",
        "checkedHead",
        "outcome",
        "evidenceSha256",
        "inputSha256",
        "dependencySha256",
        "artifactSha256",
    }:
        raise ValueError("agent route qualification reference fields differ")
    inputs = value["inputSha256"]
    dependencies = value["dependencySha256"]
    artifacts = value["artifactSha256"]
    if (
        value["schemaVersion"] != 3
        or not isinstance(value["checkedHead"], str)
        or _SHA40.fullmatch(value["checkedHead"]) is None
        or value["outcome"] != "required-workload-routes-qualified"
        or not _digest(value["evidenceSha256"])
        or not isinstance(inputs, dict)
        or set(inputs) != set(_MODEL_INPUT_PATHS)
        or not all(_digest(item) for item in inputs.values())
        or not isinstance(dependencies, dict)
        or set(dependencies) != set(_MODEL_DEPENDENCY_PATHS)
        or not all(_digest(item) for item in dependencies.values())
        or not isinstance(artifacts, dict)
        or set(artifacts) != set(_EXPECTED_ARTIFACTS)
        or not all(_digest(item) for item in artifacts.values())
    ):
        raise ValueError("agent route qualification reference is invalid")
    return AgentRouteQualificationReference(
        checked_head=value["checkedHead"],
        outcome=value["outcome"],
        evidence_sha256=value["evidenceSha256"],
        input_sha256=dict(sorted(inputs.items())),
        dependency_sha256=dict(sorted(dependencies.items())),
        artifact_sha256=dict(sorted(artifacts.items())),
        lock_sha256=identity,
    )


def admit_agent_route_qualification(
    repository_root: Path,
    *,
    checked_head: str,
    evidence_root: Path,
    reference: AgentRouteQualificationReference,
    runner: GitRunner = subprocess.run,
) -> AdmittedAgentRouteQualification:
    _verify_unchanged_route_inputs(
        repository_root,
        checked_head=checked_head,
        reference=reference,
        runner=runner,
    )
    root = _real_private_root(evidence_root, repository_root)
    _verify_exact_artifact_tree(root, reference.artifact_sha256)
    artifacts = {
        relative: read_json_object_with_identity(
            root / relative,
            maximum_bytes=64 * 1024 * 1024,
            field="private agent route qualification artifact",
            expected_sha256=reference.artifact_sha256[relative],
            containment_root=root,
        )[0]
        for relative in _EXPECTED_ARTIFACTS
    }
    _validate_qualification_tree(
        repository_root,
        reference=reference,
        artifacts=artifacts,
    )
    _verify_unchanged_route_inputs(
        repository_root,
        checked_head=checked_head,
        reference=reference,
        runner=runner,
    )
    return AdmittedAgentRouteQualification(
        checked_head=reference.checked_head,
        outcome=reference.outcome,
        evidence_sha256=reference.evidence_sha256,
        lock_sha256=reference.lock_sha256,
    )


def is_agent_route_evidence_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized in _PROTECTED_ROUTE_PATHS:
        return True
    return normalized.startswith(
        (
            "server/src/yap_server/evaluation/agent_model_",
            "server/src/yap_server/evaluation/agent_runtime_pressure.py",
            "server/src/yap_server/evaluation/agent_vllm_",
            "server/tests/evaluation/test_agent_model_",
            "server/tests/evaluation/test_agent_runtime_pressure.py",
            "server/tests/evaluation/test_agent_vllm_",
        )
    )


def _verify_unchanged_route_inputs(
    repository_root: Path,
    *,
    checked_head: str,
    reference: AgentRouteQualificationReference,
    runner: GitRunner,
) -> None:
    ancestor = _git(
        repository_root,
        ("merge-base", "--is-ancestor", reference.checked_head, checked_head),
        runner=runner,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("agent route qualification head is not an ancestor")
    checked_inputs = {**reference.input_sha256, **reference.dependency_sha256}
    for relative, expected in checked_inputs.items():
        body = read_bounded_regular_file(
            repository_root / relative,
            maximum_bytes=16 * 1024 * 1024,
            field="agent route qualification input",
            containment_root=repository_root,
        )
        if hashlib.sha256(body).hexdigest() != expected:
            raise ValueError("agent route qualification input changed")
    changed = _git(
        repository_root,
        ("diff", "--name-only", f"{reference.checked_head}..{checked_head}"),
        runner=runner,
    ).stdout.splitlines()
    for path in changed:
        if is_agent_route_evidence_path(path):
            raise ValueError("agent route qualification implementation changed")


def _validate_qualification_tree(
    repository_root: Path,
    *,
    reference: AgentRouteQualificationReference,
    artifacts: Mapping[str, dict[str, object]],
) -> None:
    acceptance = load_agent_model_acceptance(repository_root)
    if (
        acceptance.plan_sha256
        != reference.input_sha256["server/agent-model-acceptance.json"]
        or acceptance.candidate_lock_sha256
        != reference.input_sha256["server/agent-reasoning-candidates.lock.json"]
        or acceptance.fixture_sha256
        != reference.input_sha256["server/agent-workload-fixtures.json"]
        or acceptance.candidate_ids != _REQUIRED_CANDIDATES
    ):
        raise ValueError("agent route qualification acceptance identity differs")
    historic_candidate = CheckedCandidate(
        repository_root=repository_root,
        checked_head=reference.checked_head,
        input_sha256=reference.input_sha256,
        _input_paths=tuple(repository_root / item for item in _MODEL_INPUT_PATHS),
    )
    models = _candidate_models(repository_root, acceptance.candidate_lock_sha256)
    summaries: list[dict[str, object]] = []
    for candidate_id in acceptance.candidate_ids:
        prefix = f"{candidate_id}/"
        children = {
            name: artifacts[f"{prefix}children/{name}.json"]
            for name in (
                "fixtures",
                "pressure",
                "cancellation",
                "resources",
                "lifecycle",
            )
        }
        run = AgentCandidateRun(
            candidate_id=candidate_id,
            evidence=artifacts[f"{prefix}results.json"],
            runtime_receipt=artifacts[f"{prefix}runtime-receipt.json"],
            children=children,
        )
        expected = models[candidate_id]
        summaries.append(
            _candidate_summary(
                historic_candidate,
                run,
                expected=expected,
                route_policy=acceptance.route_evidence[str(expected["workloadClass"])],
            )
        )
    qualification = artifacts["qualification.json"]
    supplied_hash = qualification.get("evidenceSha256")
    unhashed = dict(qualification)
    unhashed.pop("evidenceSha256", None)
    expected = {
        "schemaVersion": 1,
        "qualificationScope": "governed-agent-reasoning",
        "outcome": "required-workload-routes-qualified",
        "admittedModelCandidates": sorted(_REQUIRED_CANDIDATES),
        "reasonCodes": ["every-required-workload-route-passed-frozen-evidence"],
        "candidateSummaries": summaries,
        "candidate": {
            "checkedHead": reference.checked_head,
            "repositoryState": "clean",
            "inputs": dict(sorted(reference.input_sha256.items())),
        },
    }
    if (
        unhashed != expected
        or supplied_hash != reference.evidence_sha256
        or supplied_hash != canonical_evidence_sha256(unhashed)
    ):
        raise ValueError("private agent route qualification decision differs")


def _verify_exact_artifact_tree(
    root: Path,
    artifact_sha256: Mapping[str, str],
) -> None:
    observed: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("private agent route qualification tree contains a link")
        if path.is_file():
            _require_private_mode(path, directory=False)
            observed.add(relative)
        elif path.is_dir():
            _require_private_mode(path, directory=True)
        else:
            raise ValueError("private agent route qualification tree is invalid")
    if observed != set(artifact_sha256):
        raise ValueError("private agent route qualification tree differs")


def _real_private_root(path: Path, repository_root: Path) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("agent route evidence root must be an absolute real directory")
    try:
        requested = Path(os.path.abspath(path))
        resolved = path.resolve(strict=True)
        metadata = resolved.lstat()
    except OSError as error:
        raise ValueError(
            "agent route evidence root must be an absolute real directory"
        ) from error
    if (
        requested != resolved
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or getattr(resolved, "is_junction", lambda: False)()
    ):
        raise ValueError("agent route evidence root must be an absolute real directory")
    _require_private_mode(resolved, directory=True)
    try:
        resolved.relative_to(repository_root)
    except ValueError:
        return resolved
    raise ValueError("agent route evidence must remain outside the repository")


def _require_private_mode(path: Path, *, directory: bool) -> None:
    if os.name != "posix":
        return
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError(
            "private agent route qualification permissions are invalid"
        ) from error
    expected_type = (
        stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    )
    current_user = getattr(os, "geteuid", lambda: metadata.st_uid)()
    if (
        not expected_type
        or metadata.st_mode & 0o077
        or getattr(metadata, "st_uid", current_user) != current_user
    ):
        raise ValueError("private agent route qualification permissions are invalid")


def _git(
    repository_root: Path,
    arguments: Sequence[str],
    *,
    runner: GitRunner,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = runner(
            ["git", "-C", str(repository_root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ValueError(
            "agent route qualification Git state could not be verified"
        ) from error
    if check and completed.returncode != 0:
        raise ValueError("agent route qualification Git state could not be verified")
    return completed


def _digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


__all__ = [
    "AdmittedAgentRouteQualification",
    "AgentRouteQualificationReference",
    "admit_agent_route_qualification",
    "is_agent_route_evidence_path",
    "load_agent_route_qualification_reference",
]
