"""Derive the Phase 8 meeting-production decision from private evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Mapping

from yap_server.evaluation.checked_candidate import (
    CheckedCandidate,
    admit_checked_candidate,
    bind_checked_candidate_evidence,
)
from yap_server.evaluation.meeting_acceptance_plan import (
    load_meeting_acceptance_plan,
)


PRIVATE_CACHE_ENVIRONMENT = "YAP_EVAL_CACHE"
_ACCEPTANCE_PLAN = Path("server/meeting-transcription-acceptance.json")
_RUNTIME_LOCK = Path("server/meeting-transcription-runtime.lock.json")
_MEETING_CATALOG = Path("server/tiron-candidate-asr-capabilities.lock.json")


def evaluate_meeting_production_qualification(
    *,
    candidate: CheckedCandidate,
    acceptance_plan_path: Path,
    environ: Mapping[str, str],
) -> dict[str, object]:
    """Return one transcript-free, exact-candidate Phase 8 decision."""

    load_meeting_acceptance_plan(acceptance_plan_path)
    candidate.verify_unchanged()
    cache_value = environ.get(PRIVATE_CACHE_ENVIRONMENT, "").strip()
    if not cache_value:
        decision = _unadvertised("private-cache-unconfigured")
    else:
        decision = _unadvertised("independent-holdout-unavailable")
    candidate.verify_unchanged()
    return bind_checked_candidate_evidence(decision, candidate)


def _unadvertised(reason_code: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "qualificationScope": "meeting-transcription",
        "outcome": "unadvertised-baseline",
        "reasonCodes": [reason_code],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive the exact-candidate Phase 8 meeting qualification decision"
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    arguments = parser.parse_args(argv)
    repository_root = arguments.repository_root.resolve(strict=True)
    acceptance_plan = repository_root / _ACCEPTANCE_PLAN
    candidate = admit_checked_candidate(
        repository_root=repository_root,
        checked_head=arguments.checked_head,
        input_paths=(
            acceptance_plan,
            repository_root / _RUNTIME_LOCK,
            repository_root / _MEETING_CATALOG,
        ),
    )
    decision = evaluate_meeting_production_qualification(
        candidate=candidate,
        acceptance_plan_path=acceptance_plan,
        environ=os.environ,
    )
    print(json.dumps(decision, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
