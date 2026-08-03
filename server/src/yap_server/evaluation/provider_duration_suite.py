from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping, Sequence

from yap_server.evaluation.duration_tracks import (
    DurationTrackSpec,
    LoadedDurationTrack,
    build_duration_track_collection,
    load_duration_track,
)
from yap_server.private_artifact import (
    read_json_object_with_identity,
)
from yap_server.evaluation.runtime_plan import (
    load_runtime_evaluation_plan,
    load_runtime_evaluation_plan_snapshot,
    select_runtime_load_case,
    validate_runtime_evaluation_plan,
)
from yap_server.pools.pcm_audio import MAX_AUDIO_SECONDS, SAMPLE_RATE_HZ


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
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAXIMUM_SUITE_BYTES = 64 * 1024
_MAXIMUM_TRACK_MANIFEST_BYTES = 4 * 1024 * 1024


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


@dataclass(frozen=True, slots=True)
class LoadedProviderDurationSuite:
    suite_path: Path
    suite_sha256: str
    plan_sha256: str
    cache_root: Path
    tracks: tuple[tuple[int, LoadedDurationTrack], ...]

    def indexed_tracks_for(
        self,
        duration_samples: Sequence[int],
    ) -> dict[int, LoadedDurationTrack]:
        selected = self._tracks_for(duration_samples)
        return {duration: track for duration, track in selected}

    def manifest_paths_for(self, duration_samples: Sequence[int]) -> tuple[Path, ...]:
        """Return each requested duration once, preserving caller order."""

        return tuple(
            track.audio_path.parent / "manifest.json"
            for _duration, track in self._tracks_for(duration_samples)
        )

    def _tracks_for(
        self,
        duration_samples: Sequence[int],
    ) -> tuple[tuple[int, LoadedDurationTrack], ...]:
        indexed = dict(self.tracks)
        selected: list[tuple[int, LoadedDurationTrack]] = []
        seen: set[int] = set()
        for value in duration_samples:
            duration = _positive_int(value, "requested provider duration")
            if duration in seen:
                continue
            track = indexed.get(duration)
            if track is None:
                raise ValueError("provider duration suite omitted a requested track")
            selected.append((duration, track))
            seen.add(duration)
        if not selected:
            raise ValueError("provider duration selection must not be empty")
        return tuple(selected)


@dataclass(frozen=True, slots=True)
class ProviderLoadCaseDurationTracks:
    suite: LoadedProviderDurationSuite
    duration_samples: tuple[int, ...]

    @property
    def manifest_paths(self) -> tuple[Path, ...]:
        return self.suite.manifest_paths_for(self.duration_samples)

    def indexed_tracks(self) -> dict[int, LoadedDurationTrack]:
        """Return a fresh exact-duration index for one qualification runner."""

        indexed = self.suite.indexed_tracks_for(self.duration_samples)
        if set(indexed) != set(self.duration_samples):
            raise ValueError(
                "provider duration tracks differ from the selected load case"
            )
        return indexed

    def public_identity(self) -> dict[str, object]:
        return {
            "sha256": self.suite.suite_sha256,
            "planSha256": self.suite.plan_sha256,
            "selectedDurationSamples": list(self.duration_samples),
        }


def bind_provider_load_case_tracks(
    evidence: Mapping[str, object],
    tracks: ProviderLoadCaseDurationTracks,
) -> dict[str, object]:
    return bind_provider_duration_suite(
        evidence,
        suite=tracks.suite,
        duration_samples=tracks.duration_samples,
    )


def bind_provider_duration_suite(
    evidence: Mapping[str, object],
    *,
    suite: LoadedProviderDurationSuite,
    duration_samples: Sequence[int],
) -> dict[str, object]:
    selected_durations = list(suite.indexed_tracks_for(duration_samples))
    bound = dict(evidence)
    if "durationSuite" in bound:
        raise ValueError("provider evidence already contains a duration-suite binding")
    bound.pop("evidenceSha256", None)
    bound["durationSuite"] = {
        "sha256": suite.suite_sha256,
        "planSha256": suite.plan_sha256,
        "selectedDurationSamples": selected_durations,
    }
    return bound


def verify_provider_load_case_tracks_unchanged(
    tracks: ProviderLoadCaseDurationTracks,
    *,
    plan_path: Path,
) -> None:
    verify_provider_duration_suite_unchanged(
        tracks.suite,
        duration_samples=tracks.duration_samples,
        plan_path=plan_path,
    )


def verify_provider_duration_suite_unchanged(
    suite: LoadedProviderDurationSuite,
    *,
    duration_samples: Sequence[int],
    plan_path: Path,
) -> None:
    """Re-read a private suite and its selected audio before publishing evidence."""

    current = load_provider_duration_suite(
        suite_path=suite.suite_path,
        expected_sha256=suite.suite_sha256,
        plan_path=plan_path,
        required_duration_samples=duration_samples,
        environ={"YAP_EVAL_CACHE": str(suite.cache_root)},
    )
    if current != suite:
        raise ValueError("provider duration suite changed during qualification")


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
            "rejectionBoundarySamples": list(selection.rejection_boundary_samples),
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


def load_provider_duration_suite(
    *,
    suite_path: Path,
    expected_sha256: str,
    plan_path: Path = _DEFAULT_PLAN_PATH,
    required_duration_samples: Sequence[int] | None = None,
    environ: Mapping[str, str] = os.environ,
) -> LoadedProviderDurationSuite:
    """Load one out-of-band-pinned provider suite and all immutable tracks."""

    if _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError("provider duration suite digest must be a lowercase SHA-256")
    cache_root = _private_cache_root(environ)
    runtime_track_root = _real_private_directory(
        cache_root / "runtime-tracks",
        field="provider duration-track root",
    )
    if not suite_path.is_absolute() or suite_path.is_symlink():
        raise ValueError("provider duration suite path must be an absolute real file")
    collection_root = _real_private_directory(
        suite_path.parent,
        field="provider duration suite collection",
    )
    if collection_root.parent != runtime_track_root:
        raise ValueError("provider duration suite escaped the runtime-track root")
    requested_suite = suite_path.resolve(strict=True)
    if (
        requested_suite.parent != collection_root
        or requested_suite.name != _MANIFEST_NAME
    ):
        raise ValueError("provider duration suite path is invalid")
    suite, suite_sha256 = read_json_object_with_identity(
        requested_suite,
        maximum_bytes=_MAXIMUM_SUITE_BYTES,
        field="provider duration suite",
        expected_sha256=expected_sha256,
        containment_root=cache_root,
    )
    snapshot = load_runtime_evaluation_plan_snapshot(plan_path)
    selection = select_provider_duration_requirements(snapshot.plan)
    planned_durations = {
        requirement.duration_samples for requirement in selection.tracks
    }
    if required_duration_samples is None:
        required_durations = planned_durations
    else:
        required_durations = {
            _positive_int(value, "requested provider duration")
            for value in required_duration_samples
        }
        if not required_durations or not required_durations <= planned_durations:
            raise ValueError("requested durations differ from the provider suite")
    _validate_loaded_suite_header(
        suite,
        expected_plan_sha256=snapshot.sha256,
        rejection_boundary_samples=selection.rejection_boundary_samples,
    )
    raw_cases = suite["cases"]
    if not isinstance(raw_cases, list) or len(raw_cases) != len(selection.tracks):
        raise ValueError("provider duration suite cases differ from the runtime plan")

    loaded_tracks: list[tuple[int, LoadedDurationTrack]] = []
    expected_entries = {_MANIFEST_NAME}
    for raw_case, requirement in zip(raw_cases, selection.tracks, strict=True):
        if not isinstance(raw_case, Mapping) or set(raw_case) != {
            "caseId",
            "durationSamples",
            "requiredBy",
            "trackManifestSha256",
        }:
            raise ValueError(
                "provider duration suite case fields differ from the contract"
            )
        expected_manifest_sha256 = raw_case["trackManifestSha256"]
        if (
            raw_case["caseId"] != requirement.case_id
            or raw_case["durationSamples"] != requirement.duration_samples
            or raw_case["requiredBy"] != list(requirement.required_by)
            or not isinstance(expected_manifest_sha256, str)
            or _SHA256.fullmatch(expected_manifest_sha256) is None
        ):
            raise ValueError(
                "provider duration suite case differs from the runtime plan"
            )
        expected_entries.add(requirement.case_id)
        track_root = _real_private_directory(
            collection_root / requirement.case_id,
            field="provider duration track",
        )
        manifest_path = track_root / "manifest.json"
        manifest, _manifest_file_sha256 = read_json_object_with_identity(
            manifest_path,
            maximum_bytes=_MAXIMUM_TRACK_MANIFEST_BYTES,
            field="provider duration track manifest",
            containment_root=cache_root,
        )
        audio = manifest.get("audio")
        if (
            manifest.get("caseId") != requirement.case_id
            or not isinstance(audio, Mapping)
            or audio.get("durationSamples") != requirement.duration_samples
            or hashlib.sha256(_canonical_json_bytes(manifest)).hexdigest()
            != expected_manifest_sha256
        ):
            raise ValueError("provider duration track differs from its suite")
        if requirement.duration_samples in required_durations:
            loaded = load_duration_track(manifest_path)
            if loaded.manifest != manifest:
                raise ValueError(
                    "provider duration track changed while it was admitted"
                )
            loaded_tracks.append((requirement.duration_samples, loaded))

    if {entry.name for entry in collection_root.iterdir()} != expected_entries:
        raise ValueError("provider duration suite collection has unexpected entries")
    return LoadedProviderDurationSuite(
        suite_path=requested_suite,
        suite_sha256=suite_sha256,
        plan_sha256=snapshot.sha256,
        cache_root=cache_root,
        tracks=tuple(loaded_tracks),
    )


def load_provider_load_case_tracks(
    *,
    suite_path: Path,
    expected_suite_sha256: str,
    plan_path: Path,
    load_case_id: str,
    environ: Mapping[str, str] = os.environ,
) -> ProviderLoadCaseDurationTracks:
    """Admit exactly the immutable tracks required by one runtime-plan cell."""

    plan = load_runtime_evaluation_plan(plan_path)
    load_case = select_runtime_load_case(plan, load_case_id)
    if load_case.system_id not in _PROVIDER_SYSTEM_IDS:
        raise ValueError("runtime load case is not a resident provider scenario")
    durations = tuple(
        item.duration_samples for item in load_case.mix for _index in range(item.count)
    )
    unique_durations = tuple(dict.fromkeys(durations))
    suite = load_provider_duration_suite(
        suite_path=suite_path,
        expected_sha256=expected_suite_sha256,
        plan_path=plan_path,
        required_duration_samples=unique_durations,
        environ=environ,
    )
    return ProviderLoadCaseDurationTracks(
        suite=suite,
        duration_samples=unique_durations,
    )


def _require_boundary_identifiers(plan: Mapping[str, object]) -> None:
    boundaries = plan.get("boundaryCases")
    if not isinstance(boundaries, list):
        raise ValueError("runtime plan omitted the batch maximum boundaries")
    identifiers = {
        boundary.get("id") for boundary in boundaries if isinstance(boundary, Mapping)
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
        raise ValueError(
            "exact batch maximum boundary differs from the runtime contract"
        )
    if (
        rejection.get("systemId") != "all-batch-adapters"
        or rejection.get("unit") != "audioSamples"
        or rejection.get("values") != [expected_exact + 1]
        or rejection.get("expected") != "reject-before-inference"
    ):
        raise ValueError(
            "batch maximum rejection boundary differs from the runtime contract"
        )
    return expected_exact, expected_exact + 1


def _validate_loaded_suite_header(
    suite: Mapping[str, object],
    *,
    expected_plan_sha256: str,
    rejection_boundary_samples: tuple[int, ...],
) -> None:
    if set(suite) != {
        "schemaVersion",
        "planSha256",
        "providerSystemIds",
        "rejectionBoundarySamples",
        "cases",
    }:
        raise ValueError("provider duration suite fields differ from the contract")
    if (
        suite["schemaVersion"] != 1
        or suite["planSha256"] != expected_plan_sha256
        or suite["providerSystemIds"] != list(_PROVIDER_SYSTEM_IDS)
        or suite["rejectionBoundarySamples"] != list(rejection_boundary_samples)
    ):
        raise ValueError("provider duration suite header differs from the runtime plan")


def _private_cache_root(environ: Mapping[str, str]) -> Path:
    raw = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required for provider duration tracks")
    requested = Path(raw)
    if not requested.is_absolute() or requested.is_symlink():
        raise ValueError("YAP_EVAL_CACHE must be an absolute real directory")
    repository = Path(__file__).resolve().parents[4]
    resolved = _real_private_directory(requested, field="YAP_EVAL_CACHE")
    if resolved == repository or repository in resolved.parents:
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    return resolved


def _real_private_directory(path: Path, *, field: str) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{field} must be an absolute real directory")
    try:
        admitted = path.lstat()
        resolved = path.resolve(strict=True)
        metadata = resolved.lstat()
    except OSError as error:
        raise ValueError(f"{field} must be a real directory") from error
    requested_is_junction = getattr(path, "is_junction", lambda: False)
    resolved_is_junction = getattr(resolved, "is_junction", lambda: False)
    if (
        stat.S_ISLNK(admitted.st_mode)
        or not stat.S_ISDIR(admitted.st_mode)
        or requested_is_junction()
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or resolved_is_junction()
        or (os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077)
    ):
        raise ValueError(f"{field} must be a private real directory")
    return resolved


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
