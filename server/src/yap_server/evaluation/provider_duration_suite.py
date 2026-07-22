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
from yap_server.pools.batch_asr_worker import MAX_AUDIO_SECONDS, SAMPLE_RATE_HZ


_COLLECTION_ID = "resident-provider-duration-suite-v1"
_MANIFEST_NAME = "suite.json"
_PROVIDER_SYSTEM_IDS = (
    "vllm-cohere-batch",
    "nemo-nemotron-finalized",
)
_EXACT_MAXIMUM_BOUNDARY_ID = "batch-maximum-exact"
_REJECTION_BOUNDARY_ID = "batch-maximum-plus-one"
_EXACT_MAXIMUM_SAMPLES = MAX_AUDIO_SECONDS * SAMPLE_RATE_HZ
_DEFAULT_PLAN_PATH = Path(__file__).resolve().parents[3] / "asr-evaluation-plan.json"


@dataclass(frozen=True, slots=True)
class ProviderDurationRequirement:
    case_id: str
    duration_samples: int
    required_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderDurationSelection:
    tracks: tuple[ProviderDurationRequirement, ...]
    rejection_boundary_samples: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BuiltProviderDurationSuite:
    suite_path: Path
    suite_sha256: str
    track_count: int


def select_provider_duration_requirements(
    plan: Mapping[str, object],
) -> ProviderDurationSelection:
    """Select every immutable input required by the two resident providers."""

    _require_boundary_identifiers(plan)
    validate_runtime_evaluation_plan(plan)
    requirements: dict[int, list[str]] = {}

    ladders = plan["durationLadders"]
    if not isinstance(ladders, list):
        raise RuntimeError("validated duration ladders changed shape")
    for ladder in ladders:
        if not isinstance(ladder, Mapping):
            raise RuntimeError("validated duration ladder changed shape")
        system_ids = ladder["systemIds"]
        if not isinstance(system_ids, list):
            raise RuntimeError("validated duration-ladder systems changed shape")
        if not any(system_id in _PROVIDER_SYSTEM_IDS for system_id in system_ids):
            continue
        ladder_id = _text(ladder["id"], "duration ladder ID")
        _add_durations(
            requirements,
            ladder["durationSamples"],
            required_by=f"duration-ladder:{ladder_id}",
        )

    load_cases = plan["loadCases"]
    if not isinstance(load_cases, list):
        raise RuntimeError("validated load cases changed shape")
    for load_case in load_cases:
        if not isinstance(load_case, Mapping):
            raise RuntimeError("validated load case changed shape")
        if load_case["systemId"] not in _PROVIDER_SYSTEM_IDS:
            continue
        load_case_id = _text(load_case["id"], "load-case ID")
        mix = load_case["mix"]
        if not isinstance(mix, list):
            raise RuntimeError("validated load-case mix changed shape")
        for item in mix:
            if not isinstance(item, Mapping):
                raise RuntimeError("validated load-case mix item changed shape")
            _add_duration(
                requirements,
                _positive_int(item["durationSamples"], "load-case duration"),
                required_by=f"load-case:{load_case_id}",
            )

    exact_maximum, rejection = _validated_batch_boundaries(plan)
    _add_duration(
        requirements,
        exact_maximum,
        required_by=f"boundary-case:{_EXACT_MAXIMUM_BOUNDARY_ID}",
    )
    return ProviderDurationSelection(
        tracks=tuple(
            ProviderDurationRequirement(
                case_id=f"provider-duration-{duration_samples}-samples",
                duration_samples=duration_samples,
                required_by=tuple(required_by),
            )
            for duration_samples, required_by in requirements.items()
        ),
        rejection_boundary_samples=(rejection,),
    )


def build_provider_duration_suite(
    *,
    source_paths: Sequence[Path],
    plan_path: Path = _DEFAULT_PLAN_PATH,
    environ: Mapping[str, str] = os.environ,
) -> BuiltProviderDurationSuite:
    """Build all private exact-duration inputs for resident-provider qualification."""

    snapshot = load_runtime_evaluation_plan_snapshot(plan_path)
    selection = select_provider_duration_requirements(snapshot.plan)
    planned_case_ids = {track.case_id for track in selection.tracks}
    suite_bytes: bytes | None = None

    def suite_manifest(
        manifests: Mapping[str, dict[str, object]],
    ) -> tuple[str, bytes]:
        nonlocal suite_bytes
        if set(manifests) != planned_case_ids:
            raise RuntimeError("duration-track manifests differ from the provider plan")
        suite = {
            "schemaVersion": 1,
            "planSha256": snapshot.sha256,
            "providerSystemIds": list(_PROVIDER_SYSTEM_IDS),
            "rejectionBoundarySamples": list(
                selection.rejection_boundary_samples
            ),
            "cases": [
                {
                    "caseId": requirement.case_id,
                    "durationSamples": requirement.duration_samples,
                    "requiredBy": list(requirement.required_by),
                    "trackManifestSha256": hashlib.sha256(
                        _canonical_json_bytes(manifests[requirement.case_id])
                    ).hexdigest(),
                }
                for requirement in selection.tracks
            ],
        }
        suite_bytes = _canonical_json_bytes(suite)
        return _MANIFEST_NAME, suite_bytes

    destination = build_duration_track_collection(
        collection_id=_COLLECTION_ID,
        tracks=[
            DurationTrackSpec(
                case_id=requirement.case_id,
                duration_samples=requirement.duration_samples,
            )
            for requirement in selection.tracks
        ],
        source_paths=list(source_paths),
        manifest_factory=suite_manifest,
        environ=environ,
    )
    if suite_bytes is None:
        raise RuntimeError("duration-track collection did not build its suite manifest")
    return BuiltProviderDurationSuite(
        suite_path=destination / _MANIFEST_NAME,
        suite_sha256=hashlib.sha256(suite_bytes).hexdigest(),
        track_count=len(selection.tracks),
    )


def _require_boundary_identifiers(plan: Mapping[str, object]) -> None:
    boundaries = plan.get("boundaryCases")
    if not isinstance(boundaries, list):
        raise ValueError("runtime plan omitted the batch maximum boundaries")
    identifiers = {
        boundary.get("id")
        for boundary in boundaries
        if isinstance(boundary, Mapping)
    }
    if _EXACT_MAXIMUM_BOUNDARY_ID not in identifiers:
        raise ValueError("runtime plan omitted the exact batch maximum boundary")
    if _REJECTION_BOUNDARY_ID not in identifiers:
        raise ValueError("runtime plan omitted the batch maximum rejection boundary")


def _validated_batch_boundaries(plan: Mapping[str, object]) -> tuple[int, int]:
    boundaries = plan["boundaryCases"]
    if not isinstance(boundaries, list):
        raise RuntimeError("validated boundary cases changed shape")
    indexed = {
        boundary["id"]: boundary
        for boundary in boundaries
        if isinstance(boundary, Mapping)
    }
    exact = indexed[_EXACT_MAXIMUM_BOUNDARY_ID]
    rejection = indexed[_REJECTION_BOUNDARY_ID]
    expected_exact = _EXACT_MAXIMUM_SAMPLES
    if (
        exact.get("systemId") != "all-batch-adapters"
        or exact.get("unit") != "audioSamples"
        or exact.get("values") != [expected_exact]
        or exact.get("expected") != "complete"
    ):
        raise ValueError("exact batch maximum boundary differs from the runtime contract")
    if (
        rejection.get("systemId") != "all-batch-adapters"
        or rejection.get("unit") != "audioSamples"
        or rejection.get("values") != [expected_exact + 1]
        or rejection.get("expected") != "reject-before-inference"
    ):
        raise ValueError("batch maximum rejection boundary differs from the runtime contract")
    return expected_exact, expected_exact + 1


def _add_durations(
    requirements: dict[int, list[str]],
    values: object,
    *,
    required_by: str,
) -> None:
    if not isinstance(values, list):
        raise RuntimeError("validated duration list changed shape")
    for value in values:
        _add_duration(
            requirements,
            _positive_int(value, "provider duration"),
            required_by=required_by,
        )


def _add_duration(
    requirements: dict[int, list[str]],
    duration_samples: int,
    *,
    required_by: str,
) -> None:
    owners = requirements.setdefault(duration_samples, [])
    if required_by not in owners:
        owners.append(required_by)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError(f"validated {label} changed type")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"validated {label} changed type")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the private resident-provider exact-duration suite"
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=_DEFAULT_PLAN_PATH,
    )
    parser.add_argument("--source", action="append", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    result = build_provider_duration_suite(
        source_paths=arguments.source,
        plan_path=arguments.plan,
    )
    print(
        json.dumps(
            {
                "suitePath": str(result.suite_path),
                "suiteSha256": result.suite_sha256,
                "trackCount": result.track_count,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
