from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from yap_server.evaluation.duration_tracks import (
    DurationTrackSpec,
    build_duration_track_collection,
)
from yap_server.evaluation.runtime_plan import (
    load_runtime_evaluation_plan_snapshot,
    validate_runtime_evaluation_plan,
)


_COLLECTION_ID = "local-stream-duration-suite-v1"
_MANIFEST_NAME = "suite.json"
_LOCAL_LADDER_IDS = ("live-endpoint", "live-session")
_LOCAL_SYSTEM_ID = "local-live-nemotron"
_DEFAULT_PLAN_PATH = Path(__file__).resolve().parents[3] / "asr-evaluation-plan.json"


@dataclass(frozen=True, slots=True)
class LocalStreamDurationCase:
    ladder_id: str
    case_id: str
    duration_samples: int


@dataclass(frozen=True, slots=True)
class BuiltLocalStreamDurationSuite:
    suite_path: Path
    suite_sha256: str
    case_count: int


def select_local_stream_duration_cases(
    plan: Mapping[str, object],
) -> tuple[LocalStreamDurationCase, ...]:
    """Select the two local-live ladders in their frozen plan order."""

    validate_runtime_evaluation_plan(plan)
    raw_ladders = plan["durationLadders"]
    if not isinstance(raw_ladders, list):
        raise RuntimeError("validated duration ladders changed shape")
    indexed = {
        str(ladder["id"]): ladder
        for ladder in raw_ladders
        if isinstance(ladder, Mapping)
    }
    cases: list[LocalStreamDurationCase] = []
    for ladder_id in _LOCAL_LADDER_IDS:
        ladder = indexed.get(ladder_id)
        if ladder is None:
            raise RuntimeError("validated local duration ladder disappeared")
        if ladder["systemIds"] != [_LOCAL_SYSTEM_ID] or ladder["pacing"] != "realtime":
            raise ValueError("local duration ladder execution contract is invalid")
        durations = ladder["durationSamples"]
        if not isinstance(durations, list):
            raise RuntimeError("validated local duration samples changed shape")
        for duration_samples in durations:
            if not isinstance(duration_samples, int) or isinstance(
                duration_samples, bool
            ):
                raise RuntimeError("validated local duration sample changed type")
            cases.append(
                LocalStreamDurationCase(
                    ladder_id=ladder_id,
                    case_id=f"{ladder_id}-{duration_samples}-samples",
                    duration_samples=duration_samples,
                )
            )
    return tuple(cases)


def build_local_stream_duration_suite(
    *,
    source_paths: Sequence[Path],
    expect_text_case_ids: frozenset[str] = frozenset(),
    plan_path: Path = _DEFAULT_PLAN_PATH,
    environ: Mapping[str, str] = os.environ,
) -> BuiltLocalStreamDurationSuite:
    """Build the hash-bound private inputs for the desktop duration gate."""

    snapshot = load_runtime_evaluation_plan_snapshot(plan_path)
    cases = select_local_stream_duration_cases(snapshot.plan)
    planned_case_ids = {case.case_id for case in cases}
    if any(not isinstance(case_id, str) for case_id in expect_text_case_ids):
        raise ValueError("expect-text case IDs must be text")
    unknown_expectations = expect_text_case_ids - planned_case_ids
    if unknown_expectations:
        raise ValueError(
            "expect-text cases are not in the local duration plan: "
            + ", ".join(sorted(unknown_expectations))
        )

    suite_bytes: bytes | None = None

    def suite_manifest(
        manifests: Mapping[str, dict[str, object]],
    ) -> tuple[str, bytes]:
        nonlocal suite_bytes
        if set(manifests) != planned_case_ids:
            raise RuntimeError("duration-track manifests differ from the local plan")
        suite = {
            "schemaVersion": 1,
            "planSha256": snapshot.sha256,
            "cases": [
                {
                    "ladderId": case.ladder_id,
                    "caseId": case.case_id,
                    "durationSamples": case.duration_samples,
                    "trackManifestSha256": hashlib.sha256(
                        _canonical_json_bytes(manifests[case.case_id])
                    ).hexdigest(),
                    "expectText": case.case_id in expect_text_case_ids,
                }
                for case in cases
            ],
        }
        suite_bytes = _canonical_json_bytes(suite)
        return _MANIFEST_NAME, suite_bytes

    destination = build_duration_track_collection(
        collection_id=_COLLECTION_ID,
        tracks=[
            DurationTrackSpec(
                case_id=case.case_id,
                duration_samples=case.duration_samples,
            )
            for case in cases
        ],
        source_paths=list(source_paths),
        manifest_factory=suite_manifest,
        environ=environ,
    )
    if suite_bytes is None:
        raise RuntimeError("duration-track collection did not build its suite manifest")
    return BuiltLocalStreamDurationSuite(
        suite_path=destination / _MANIFEST_NAME,
        suite_sha256=hashlib.sha256(suite_bytes).hexdigest(),
        case_count=len(cases),
    )


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the private local-stream exact-duration suite"
    )
    parser.add_argument("--plan", type=Path, default=_DEFAULT_PLAN_PATH)
    parser.add_argument("--source", action="append", type=Path, required=True)
    parser.add_argument("--expect-text-case", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    expectation_ids = arguments.expect_text_case
    if len(expectation_ids) != len(set(expectation_ids)):
        raise ValueError("expect-text case IDs must be unique")
    result = build_local_stream_duration_suite(
        source_paths=arguments.source,
        expect_text_case_ids=frozenset(expectation_ids),
        plan_path=arguments.plan,
    )
    print(
        json.dumps(
            {
                "caseCount": result.case_count,
                "suitePath": str(result.suite_path),
                "suiteSha256": result.suite_sha256,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
