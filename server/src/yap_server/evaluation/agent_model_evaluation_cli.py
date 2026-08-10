from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from yap_server.private_artifact import read_json_object_with_identity

from .agent_model_acceptance import load_agent_model_acceptance
from .agent_model_fixture_runner import run_agent_model_fixtures
from .agent_model_scoring import score_agent_model_results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:30000")
    arguments = parser.parse_args()
    repository_root = arguments.repository_root.resolve(strict=True)
    evidence_root = _evidence_root(repository_root)
    candidate = _candidate(repository_root, arguments.candidate_id)
    endpoint = _loopback_endpoint(arguments.endpoint)

    def request_json(payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            endpoint + "/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(4_000_001)
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError("agent model endpoint request failed") from error
        if len(body) > 4_000_000:
            raise ValueError("agent model response exceeds its byte bound")
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("agent model response is not valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("agent model response must be an object")
        return value

    results = run_agent_model_fixtures(
        repository_root,
        model=str(candidate["model"]),
        request_json=request_json,
    )
    records = tuple(item.record() for item in results)
    score = score_agent_model_results(repository_root, records)
    destination = evidence_root / "agent-model" / arguments.candidate_id / "results.json"
    _write_private_json(
        destination,
        {
            "schemaVersion": 1,
            "candidateId": arguments.candidate_id,
            "model": candidate["model"],
            "revision": candidate["revision"],
            "results": list(records),
        },
    )
    print(
        json.dumps(
            {
                "candidateId": arguments.candidate_id,
                "caseCount": score.case_count,
                "passed": score.passed,
                "privateEvidenceWritten": True,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if score.passed else 1


def _candidate(repository_root: Path, candidate_id: str) -> dict[str, object]:
    acceptance = load_agent_model_acceptance(repository_root)
    lock, _identity = read_json_object_with_identity(
        repository_root / "server" / "agent-reasoning-candidates.lock.json",
        maximum_bytes=64_000,
        field="agent reasoning candidate lock",
        expected_sha256=acceptance.candidate_lock_sha256,
        containment_root=repository_root,
    )
    candidates = lock["candidates"]
    assert isinstance(candidates, list)
    matches = [item for item in candidates if item["candidateId"] == candidate_id]
    if len(matches) != 1:
        raise ValueError("agent model candidate is not admitted")
    return matches[0]


def _evidence_root(repository_root: Path) -> Path:
    value = os.environ.get("YAP_EVAL_CACHE")
    if not value:
        raise ValueError("YAP_EVAL_CACHE is required")
    root = Path(value).resolve(strict=True)
    try:
        root.relative_to(repository_root)
    except ValueError:
        return root
    raise ValueError("agent model evidence must remain outside the repository")


def _loopback_endpoint(value: str) -> str:
    if value not in {"http://127.0.0.1:30000", "http://localhost:30000"}:
        raise ValueError("agent model endpoint must be loopback")
    return value


def _write_private_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.exists():
        raise ValueError("agent model evidence destination must be new and real")
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())


if __name__ == "__main__":
    raise SystemExit(main())
