"""Run the complete checked gate for governed knowledge and agent routes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Mapping, Sequence

from yap_server.evaluation.private_json_evidence import (
    write_new_private_json_evidence,
)
from yap_server.evaluation.agent_route_qualification_evidence import (
    admit_agent_route_qualification,
    load_agent_route_qualification_reference,
)
from yap_server.evaluation.checked_candidate import (
    admit_checked_candidate,
    bind_checked_candidate_evidence,
)
from yap_server.evaluation.owned_postgres_knowledge_runtime import (
    KnowledgeDatabaseRuntimeLock,
    OwnedPostgresKnowledgeRuntime,
    StartedKnowledgeDatabase,
    load_knowledge_database_runtime_lock,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOCAL_OFFLINE_DESKTOP_BASE_HEAD = "6d1400ccdf481333840700b51f516c813960272b"
_EXPECTED_DATABASE_MODULES = (
    "tests.knowledge.test_postgres_generation_ledger",
    "tests.knowledge.test_postgres_permission_safe_retrieval",
    "tests.knowledge.test_reviewed_meeting_postgres_route",
    "tests.knowledge.test_terminology_ledger",
)
_EXPECTED_DATABASE_TEST_COUNT = 17
_EXPECTED_PORTABLE_PACKAGES = frozenset(
    {"numpy", "psycopg", "psycopg-binary", "rapidfuzz", "regex"}
)
_EXPECTED_PORTABLE_MODULES = (
    "tests.agents.test_agent_admission_client",
    "tests.evaluation.test_agent_model_acceptance",
    "tests.evaluation.test_agent_model_final_response_retry",
    "tests.evaluation.test_agent_model_fixture_runner",
    "tests.evaluation.test_agent_model_qualification",
    "tests.evaluation.test_agent_model_scoring",
    "tests.evaluation.test_agent_route_qualification_evidence",
    "tests.evaluation.test_agent_runtime_pressure",
    "tests.evaluation.test_agent_service_lifecycle_runtime",
    "tests.evaluation.test_agent_vllm_metrics",
    "tests.evaluation.test_agent_vllm_runtime",
    "tests.evaluation.test_checked_candidate",
    "tests.evaluation.test_governed_knowledge_gate",
    "tests.evaluation.test_owned_postgres_knowledge_runtime",
    "tests.evaluation.test_private_json_evidence",
    "tests.evaluation.test_provider_runtime_observations",
    "tests.evaluation.test_vllm_runtime_metrics",
    "tests.infra.test_agent_admission_service",
    "tests.knowledge.test_agent_reasoning_routes",
    "tests.knowledge.test_cancellable_database_operation",
    "tests.knowledge.test_governed_answer_protocol",
    "tests.knowledge.test_governed_knowledge_mcp",
    "tests.knowledge.test_governed_rag_agent",
    "tests.knowledge.test_okf_compiler",
    "tests.knowledge.test_reviewed_meeting_knowledge",
    "tests.knowledge.test_terminology_authorization",
    "tests.knowledge.test_terminology_snapshot",
    "tests.knowledge.test_vllm_reasoning_client",
)
_EXPECTED_PORTABLE_TEST_COUNT = 169


def evaluate_governed_knowledge_gate(
    *,
    repository_root: Path,
    checked_head: str,
    agent_route_evidence_root: Path,
    receipt_path: Path,
    runner: Runner = subprocess.run,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    root = repository_root.resolve(strict=True)
    server_root = root / "server"
    verification_root = root / "verification"
    input_paths = (
        server_root / "runtime/knowledge/postgres-pgvector.lock.json",
        server_root / "agent-model-route-qualification.lock.json",
        server_root / "pyproject.toml",
        server_root / "uv.lock",
        verification_root / "run-portable-server-suite.py",
        verification_root / "run-governed-knowledge-portable-suite.py",
        verification_root / "run-governed-knowledge-postgres-suite.py",
        verification_root / "run-governed-knowledge-restart-probe.py",
    )
    candidate = admit_checked_candidate(
        repository_root=root,
        checked_head=checked_head,
        input_paths=input_paths,
        runner=runner,
    )
    _validate_receipt_path(receipt_path, root)
    source_environment = dict(os.environ if environment is None else environment)
    if source_environment.get("YAP_TEST_POSTGRES_DSN"):
        raise ValueError("the governed knowledge gate owns its Postgres DSN")
    runtime_lock = load_knowledge_database_runtime_lock(root)
    route_reference = load_agent_route_qualification_reference(root)
    admitted_routes = admit_agent_route_qualification(
        root,
        checked_head=checked_head,
        evidence_root=agent_route_evidence_root,
        reference=route_reference,
        runner=runner,
    )
    local_boundary = verify_local_offline_dependency_boundary(
        root,
        checked_head=checked_head,
        runner=runner,
    )
    runtime = OwnedPostgresKnowledgeRuntime(
        checked_head=checked_head,
        runtime_lock=runtime_lock,
        runner=runner,
    )
    started: StartedKnowledgeDatabase | None = None
    teardown: dict[str, bool] | None = None
    try:
        started = runtime.start(timeout_seconds=120)
        database_environment = dict(source_environment)
        database_environment["YAP_TEST_POSTGRES_DSN"] = started.dsn
        python_identity = _run_json_command(
            [
                sys.executable,
                str(verification_root / "run-portable-server-suite.py"),
                "--identity-only",
            ],
            cwd=server_root,
            environment=database_environment,
            runner=runner,
            label="portable server identity",
        )
        _validate_python_identity(
            python_identity, candidate.input_sha256["server/uv.lock"]
        )
        portable_result = _run_json_command(
            [
                sys.executable,
                str(
                    verification_root
                    / "run-governed-knowledge-portable-suite.py"
                ),
            ],
            cwd=server_root,
            environment=database_environment,
            runner=runner,
            label="governed knowledge portable suite",
            timeout=1_800,
        )
        _validate_portable_test_result(portable_result)
        _run_command(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                ".",
                "../infra/yap-server-node/owned-process-supervisor.py",
            ],
            cwd=server_root,
            environment=database_environment,
            runner=runner,
            label="server lint",
            timeout=300,
        )
        database_result = _run_json_command(
            [
                sys.executable,
                str(verification_root / "run-governed-knowledge-postgres-suite.py"),
            ],
            cwd=server_root,
            environment=database_environment,
            runner=runner,
            label="governed knowledge Postgres suite",
            timeout=900,
        )
        _validate_database_test_result(database_result, runtime_lock)
        restart_seed = _run_json_command(
            [
                sys.executable,
                str(verification_root / "run-governed-knowledge-restart-probe.py"),
                "seed",
            ],
            cwd=server_root,
            environment=database_environment,
            runner=runner,
            label="governed knowledge restart seed",
            timeout=120,
        )
        _validate_restart_seed(restart_seed)
        restarted = runtime.restart(timeout_seconds=120)
        database_environment["YAP_TEST_POSTGRES_DSN"] = restarted.dsn
        restart_runtime = {
            "loopbackBindingReobserved": True,
            "newProcessObserved": restarted.process_id != started.process_id,
            "sameContainerObserved": restarted.container_id == started.container_id,
        }
        restart_result = _run_json_command(
            [
                sys.executable,
                str(verification_root / "run-governed-knowledge-restart-probe.py"),
                "verify",
                "--tenant-id",
                str(restart_seed["tenantId"]),
                "--generation-sha256",
                str(restart_seed["generationSha256"]),
            ],
            cwd=server_root,
            environment=database_environment,
            runner=runner,
            label="governed knowledge restart verification",
            timeout=120,
        )
        _validate_restart_result(restart_result, restart_seed)
        teardown = runtime.stop(timeout_seconds=15)
    except BaseException as error:
        if started is not None:
            try:
                runtime.contain_failed_run()
            except BaseException as containment_error:
                raise containment_error from error
        raise
    candidate.verify_unchanged(runner=runner)
    if teardown is None:
        raise RuntimeError("governed knowledge gate teardown evidence is missing")
    receipt = bind_checked_candidate_evidence(
        {
            "schemaVersion": 1,
            "outcome": "governed-knowledge-gate-passed",
            "agentRoutes": {
                "checkedHead": admitted_routes.checked_head,
                "evidenceSha256": admitted_routes.evidence_sha256,
                "lockSha256": admitted_routes.lock_sha256,
                "outcome": admitted_routes.outcome,
            },
            "database": {
                "image": runtime_lock.image,
                "imageId": runtime_lock.image_id,
                "lockSha256": runtime_lock.lock_sha256,
                "manifestDigest": runtime_lock.manifest_digest,
                "pgvectorVersion": database_result["pgvectorVersion"],
                "platform": runtime_lock.platform,
                "postgresVersion": database_result["postgresVersion"],
                "restart": {
                    **restart_runtime,
                    "retrievalRecovered": restart_result[
                        "retrievalRecoveredAfterRestart"
                    ],
                    "staleGenerationRejected": restart_result[
                        "staleGenerationRejected"
                    ],
                    "successorRetrievalPassed": restart_result[
                        "successorRetrievalPassed"
                    ],
                },
                "testModules": database_result["modules"],
                "testsRun": database_result["testsRun"],
            },
            "localOfflineBoundary": local_boundary,
            "server": {
                "lockSha256": python_identity["lockSha256"],
                "python": python_identity["python"],
                "portableTestModules": portable_result["modules"],
                "portableSuitePassed": True,
                "portableTestsRun": portable_result["testsRun"],
                "ruffPassed": True,
            },
            "teardown": teardown,
        },
        candidate,
    )
    write_new_private_json_evidence(receipt_path, receipt)
    return receipt


def verify_local_offline_dependency_boundary(
    repository_root: Path,
    *,
    checked_head: str,
    runner: Runner,
) -> dict[str, object]:
    ancestor = _git(
        repository_root,
        ("merge-base", "--is-ancestor", _LOCAL_OFFLINE_DESKTOP_BASE_HEAD, checked_head),
        runner=runner,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("local/offline desktop dependency baseline is not an ancestor")
    changed = _git(
        repository_root,
        (
            "diff",
            "--name-only",
            f"{_LOCAL_OFFLINE_DESKTOP_BASE_HEAD}..{checked_head}",
            "--",
            "desktop",
        ),
        runner=runner,
    ).stdout.splitlines()
    if changed:
        raise ValueError(
            "governed knowledge changed the local/offline desktop dependency boundary"
        )
    return {
        "baselineHead": _LOCAL_OFFLINE_DESKTOP_BASE_HEAD,
        "desktopChanged": False,
        "evidenceKind": "unchanged-desktop-dependency-boundary",
    }


def _validate_database_test_result(
    value: Mapping[str, object],
    runtime_lock: KnowledgeDatabaseRuntimeLock,
) -> None:
    if set(value) != {
        "modules",
        "pgvectorVersion",
        "postgresVersion",
        "schemaVersion",
        "skipped",
        "testsRun",
    }:
        raise ValueError("governed knowledge Postgres result fields differ")
    postgres_prefix = runtime_lock.postgres_version.split("-", 1)[0]
    if (
        value["schemaVersion"] != 1
        or value["modules"] != list(_EXPECTED_DATABASE_MODULES)
        or value["testsRun"] != _EXPECTED_DATABASE_TEST_COUNT
        or value["skipped"] != 0
        or value["pgvectorVersion"] != runtime_lock.pgvector_version
        or not isinstance(value["postgresVersion"], str)
        or not value["postgresVersion"].startswith(postgres_prefix)
    ):
        raise ValueError("governed knowledge Postgres result did not pass")


def _validate_portable_test_result(value: Mapping[str, object]) -> None:
    if (
        set(value)
        != {
            "expectedFailures",
            "modules",
            "schemaVersion",
            "skipped",
            "testsRun",
            "unexpectedSuccesses",
        }
        or value["schemaVersion"] != 1
        or value["expectedFailures"] != 0
        or value["modules"] != list(_EXPECTED_PORTABLE_MODULES)
        or value["testsRun"] != _EXPECTED_PORTABLE_TEST_COUNT
        or value["skipped"] != 0
        or value["unexpectedSuccesses"] != 0
    ):
        raise ValueError("governed knowledge portable result did not pass")


def _validate_restart_seed(value: Mapping[str, object]) -> None:
    if (
        set(value)
        != {
            "schemaVersion",
            "tenantId",
            "subjectId",
            "generationSha256",
            "seedRetrievalPassed",
        }
        or value["schemaVersion"] != 1
        or not isinstance(value["tenantId"], str)
        or re.fullmatch(r"gate-[0-9a-f]{32}", value["tenantId"]) is None
        or value["subjectId"] != "restart-probe"
        or not isinstance(value["generationSha256"], str)
        or _SHA256.fullmatch(value["generationSha256"]) is None
        or value["seedRetrievalPassed"] is not True
    ):
        raise ValueError("governed knowledge restart seed differs")


def _validate_restart_result(
    value: Mapping[str, object],
    seed: Mapping[str, object],
) -> None:
    if (
        set(value)
        != {
            "schemaVersion",
            "originalGenerationSha256",
            "successorGenerationSha256",
            "retrievalRecoveredAfterRestart",
            "staleGenerationRejected",
            "successorRetrievalPassed",
        }
        or value["schemaVersion"] != 1
        or value["originalGenerationSha256"] != seed["generationSha256"]
        or not isinstance(value["successorGenerationSha256"], str)
        or _SHA256.fullmatch(value["successorGenerationSha256"]) is None
        or value["successorGenerationSha256"] == value["originalGenerationSha256"]
        or value["retrievalRecoveredAfterRestart"] is not True
        or value["staleGenerationRejected"] is not True
        or value["successorRetrievalPassed"] is not True
    ):
        raise ValueError("governed knowledge restart verification differs")


def _validate_python_identity(value: Mapping[str, object], expected_lock: str) -> None:
    if (
        set(value) != {"lockSha256", "packages", "python"}
        or value["lockSha256"] != expected_lock
        or not isinstance(value["packages"], dict)
        or set(value["packages"]) != _EXPECTED_PORTABLE_PACKAGES
        or not isinstance(value["python"], str)
        or re.fullmatch(r"3\.12\.[0-9]+", value["python"]) is None
    ):
        raise ValueError("portable server identity differs")


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    runner: Runner,
    label: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = runner(
            list(command),
            cwd=cwd,
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise RuntimeError(f"{label} could not execute") from error
    if completed.returncode != 0:
        raise RuntimeError(f"{label} failed")
    return completed


def _run_json_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    runner: Runner,
    label: str,
    timeout: int = 60,
) -> dict[str, object]:
    completed = _run_command(
        command,
        cwd=cwd,
        environment=environment,
        runner=runner,
        label=label,
        timeout=timeout,
    )
    try:
        value = json.loads(completed.stdout)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError(f"{label} result is invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} result must be an object")
    return value


def _validate_receipt_path(path: Path, repository_root: Path) -> None:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ValueError("governed knowledge gate receipt must be a new absolute file")
    parent = path.parent
    try:
        resolved_parent = parent.resolve(strict=True)
    except OSError as error:
        raise ValueError("governed knowledge gate receipt parent is invalid") from error
    if (
        parent.is_symlink()
        or getattr(resolved_parent, "is_junction", lambda: False)()
        or not resolved_parent.is_dir()
        or os.path.normcase(os.path.abspath(parent))
        != os.path.normcase(os.path.abspath(resolved_parent))
    ):
        raise ValueError("governed knowledge gate receipt parent is invalid")
    try:
        resolved_parent.relative_to(repository_root)
    except ValueError:
        return
    raise ValueError("governed knowledge gate receipt must stay outside the repository")


def _git(
    repository_root: Path,
    arguments: Sequence[str],
    *,
    runner: Runner,
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
            "governed knowledge gate Git state could not be verified"
        ) from error
    if check and completed.returncode != 0:
        raise ValueError("governed knowledge gate Git state could not be verified")
    return completed


def _parse_arguments(arguments: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--agent-route-evidence-root", required=True, type=Path)
    parser.add_argument("--receipt-path", required=True, type=Path)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parse_arguments(sys.argv[1:] if arguments is None else arguments)
    receipt = evaluate_governed_knowledge_gate(
        repository_root=options.repository_root,
        checked_head=options.checked_head,
        agent_route_evidence_root=options.agent_route_evidence_root,
        receipt_path=options.receipt_path,
    )
    print(
        json.dumps(
            {
                "checkedHead": receipt["candidate"]["checkedHead"],
                "evidenceSha256": receipt["evidenceSha256"],
                "outcome": receipt["outcome"],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "evaluate_governed_knowledge_gate",
    "verify_local_offline_dependency_boundary",
]
