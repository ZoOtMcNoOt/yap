from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from yap_server.private_artifact import read_json_object_with_identity

from .agent_model_acceptance import load_agent_model_acceptance
from .agent_model_evidence import write_new_agent_model_evidence
from .checked_candidate import CheckedCandidate, admit_checked_candidate


_INPUTS = (
    Path("server/agent-model-acceptance.json"),
    Path("server/agent-reasoning-candidates.lock.json"),
    Path("server/agent-workload-fixtures.json"),
)


def freeze_agent_model_evidence_registry(
    *,
    candidate: CheckedCandidate,
    evidence_root: Path,
) -> tuple[dict[str, object], str]:
    """Freeze exact private candidate artifacts for independent qualification."""

    acceptance = load_agent_model_acceptance(candidate.repository_root)
    entries: list[dict[str, str]] = []
    for candidate_id in acceptance.candidate_ids:
        directory = evidence_root / "agent-model" / candidate_id
        result, result_sha256 = read_json_object_with_identity(
            directory / "results.json",
            maximum_bytes=16_000_000,
            field="agent model result evidence",
            containment_root=evidence_root,
        )
        _receipt, receipt_sha256 = read_json_object_with_identity(
            directory / "runtime-receipt.json",
            maximum_bytes=256_000,
            field="agent model runtime receipt",
            containment_root=evidence_root,
        )
        if (
            result.get("candidateId") != candidate_id
            or result.get("runtimeReceiptSha256") != receipt_sha256
        ):
            raise ValueError("agent model evidence registry binding differs")
        entries.append(
            {
                "candidateId": candidate_id,
                "resultSha256": result_sha256,
                "runtimeReceiptSha256": receipt_sha256,
            }
        )
    candidate.verify_unchanged()
    value = {
        "schemaVersion": 1,
        "checkedHead": candidate.checked_head,
        "inputs": dict(sorted(candidate.input_sha256.items())),
        "candidates": entries,
    }
    destination = evidence_root / "agent-model" / "evidence-registry.json"
    write_new_agent_model_evidence(destination, value)
    return value, hashlib.sha256(destination.read_bytes()).hexdigest()


def _evidence_root(repository_root: Path) -> Path:
    raw = os.environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required")
    root = Path(raw).resolve(strict=True)
    try:
        root.relative_to(repository_root)
    except ValueError:
        return root
    raise ValueError("agent model evidence must remain outside the repository")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze agent evidence identities")
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    arguments = parser.parse_args(argv)
    repository_root = arguments.repository_root.resolve(strict=True)
    candidate = admit_checked_candidate(
        repository_root=repository_root,
        checked_head=arguments.checked_head,
        input_paths=tuple(repository_root / path for path in _INPUTS),
    )
    _registry, digest = freeze_agent_model_evidence_registry(
        candidate=candidate,
        evidence_root=_evidence_root(repository_root),
    )
    print(json.dumps({"evidenceRegistrySha256": digest}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["freeze_agent_model_evidence_registry"]
