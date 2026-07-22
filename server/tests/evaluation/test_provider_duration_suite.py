from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from yap_server.evaluation import provider_duration_suite
from yap_server.evaluation.provider_duration_suite import (
    bind_provider_load_case_tracks,
    build_provider_duration_suite,
    load_provider_duration_suite,
    load_provider_load_case_tracks,
    select_provider_duration_requirements,
    verify_provider_load_case_tracks_unchanged,
)
from yap_server.evaluation.runtime_plan import (
    load_runtime_evaluation_plan,
    load_runtime_evaluation_plan_snapshot,
)
from yap_server.evaluation.duration_tracks import LoadedDurationTrack


SERVER_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = SERVER_ROOT / "asr-evaluation-plan.json"


@dataclass(frozen=True, slots=True)
class _WrittenProviderSuite:
    cache_root: Path
    suite_path: Path
    suite_bytes: bytes
    plan_sha256: str
    manifests: dict[Path, dict[str, object]]


def _write_provider_suite(cache_root: Path) -> _WrittenProviderSuite:
    snapshot = load_runtime_evaluation_plan_snapshot(PLAN_PATH)
    selection = select_provider_duration_requirements(snapshot.plan)
    collection = (
        cache_root / "runtime-tracks" / "resident-provider-duration-suite-v1"
    )
    collection.mkdir(parents=True)
    manifests: dict[Path, dict[str, object]] = {}
    cases: list[dict[str, object]] = []
    for requirement in selection.tracks:
        track_root = collection / requirement.case_id
        track_root.mkdir()
        manifest_path = track_root / "manifest.json"
        manifest = {
            "schemaVersion": 1,
            "caseId": requirement.case_id,
            "audio": {"durationSamples": requirement.duration_samples},
        }
        manifest_bytes = provider_duration_suite._canonical_json_bytes(manifest)
        manifest_path.write_bytes(manifest_bytes)
        manifests[manifest_path] = manifest
        cases.append(
            {
                "caseId": requirement.case_id,
                "durationSamples": requirement.duration_samples,
                "requiredBy": list(requirement.required_by),
                "trackManifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
            }
        )
    suite_bytes = provider_duration_suite._canonical_json_bytes(
        {
            "schemaVersion": 1,
            "planSha256": snapshot.sha256,
            "providerSystemIds": [
                "vllm-cohere-batch",
                "nemo-nemotron-finalized",
            ],
            "rejectionBoundarySamples": [230_400_001],
            "cases": cases,
        }
    )
    suite_path = collection / "suite.json"
    suite_path.write_bytes(suite_bytes)
    if provider_duration_suite.os.name == "posix":
        for directory in (cache_root, cache_root / "runtime-tracks", collection):
            provider_duration_suite.os.chmod(directory, 0o700)
        provider_duration_suite.os.chmod(suite_path, 0o600)
        for path in manifests:
            provider_duration_suite.os.chmod(path.parent, 0o700)
            provider_duration_suite.os.chmod(path, 0o600)
    return _WrittenProviderSuite(
        cache_root=cache_root,
        suite_path=suite_path,
        suite_bytes=suite_bytes,
        plan_sha256=snapshot.sha256,
        manifests=manifests,
    )


def _fake_loaded_track(
    path: Path,
    manifests: dict[Path, dict[str, object]],
) -> LoadedDurationTrack:
    return LoadedDurationTrack(
        audio_path=path.parent / "audio.wav",
        manifest=manifests[path],
    )


class ProviderDurationSuiteTests(unittest.TestCase):
    def test_selects_every_resident_provider_duration_once(self) -> None:
        selection = select_provider_duration_requirements(
            load_runtime_evaluation_plan(PLAN_PATH)
        )

        self.assertEqual(
            [requirement.duration_samples for requirement in selection.tracks],
            [
                4_000,
                8_000,
                12_000,
                16_000,
                17_920,
                32_000,
                80_000,
                160_000,
                480_000,
                1_920_000,
                4_800_000,
                14_400_000,
                28_800_000,
                57_600_000,
                115_200_000,
                524_287,
                262_144,
                230_400_000,
            ],
        )
        self.assertEqual(selection.rejection_boundary_samples, (230_400_001,))
        thirty_seconds = next(
            requirement
            for requirement in selection.tracks
            if requirement.duration_samples == 480_000
        )
        self.assertIn("duration-ladder:server-finalized-utterance", thirty_seconds.required_by)
        self.assertIn("duration-ladder:batch-file", thirty_seconds.required_by)
        self.assertIn("load-case:vllm-short-tail", thirty_seconds.required_by)
        self.assertIn("load-case:nemo-finalized-short-tail", thirty_seconds.required_by)
        maximum = selection.tracks[-1]
        self.assertEqual(maximum.required_by, ("boundary-case:batch-maximum-exact",))

    def test_builder_binds_plan_track_hashes_and_requirement_provenance(self) -> None:
        captured: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "resident-provider-duration-suite-v1"

            def fake_build_collection(**arguments: object) -> Path:
                captured.update(arguments)
                tracks = arguments["tracks"]
                manifests = {
                    track.case_id: {
                        "schemaVersion": 1,
                        "caseId": track.case_id,
                        "durationSamples": track.duration_samples,
                    }
                    for track in tracks  # type: ignore[union-attr]
                }
                manifest_name, manifest_bytes = arguments["manifest_factory"](
                    manifests
                )  # type: ignore[operator]
                captured["manifest_name"] = manifest_name
                captured["manifest_bytes"] = manifest_bytes
                return destination

            with mock.patch.object(
                provider_duration_suite,
                "build_duration_track_collection",
                side_effect=fake_build_collection,
            ):
                result = build_provider_duration_suite(
                    source_paths=[Path("licensed-source.wav")],
                    plan_path=PLAN_PATH,
                    environ={"YAP_EVAL_CACHE": str(Path(temporary) / "cache")},
                )

        manifest_bytes = captured["manifest_bytes"]
        self.assertIsInstance(manifest_bytes, bytes)
        suite = json.loads(manifest_bytes)
        tracks = captured["tracks"]
        self.assertEqual(captured["manifest_name"], "suite.json")
        self.assertEqual(
            set(suite),
            {
                "schemaVersion",
                "planSha256",
                "providerSystemIds",
                "rejectionBoundarySamples",
                "cases",
            },
        )
        serialized = manifest_bytes.decode("utf-8")
        self.assertNotIn("licensed-source.wav", serialized)
        self.assertNotIn("transcript", serialized.lower())
        self.assertEqual(len(tracks), 18)  # type: ignore[arg-type]
        self.assertEqual(
            [case["caseId"] for case in suite["cases"]],
            [track.case_id for track in tracks],  # type: ignore[union-attr]
        )
        self.assertEqual(
            suite["cases"][0]["trackManifestSha256"],
            hashlib.sha256(
                provider_duration_suite._canonical_json_bytes(
                    {
                        "schemaVersion": 1,
                        "caseId": "provider-duration-4000-samples",
                        "durationSamples": 4_000,
                    }
                )
            ).hexdigest(),
        )
        self.assertIn(
            "duration-ladder:server-finalized-utterance",
            suite["cases"][8]["requiredBy"],
        )
        self.assertEqual(result.suite_path, destination / "suite.json")
        self.assertEqual(
            result.suite_sha256,
            hashlib.sha256(manifest_bytes).hexdigest(),
        )
        self.assertEqual(result.track_count, 18)

    def test_selection_rejects_a_plan_without_the_exact_maximum_boundary(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        plan["boundaryCases"] = [
            case
            for case in plan["boundaryCases"]  # type: ignore[index]
            if case["id"] != "batch-maximum-exact"
        ]

        with self.assertRaisesRegex(ValueError, "exact batch maximum"):
            select_provider_duration_requirements(plan)

    def test_selection_rejects_a_malformed_boundary_collection_cleanly(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        plan["boundaryCases"] = None

        with self.assertRaisesRegex(ValueError, "batch maximum boundaries"):
            select_provider_duration_requirements(plan)

    def test_loader_verifies_the_out_of_band_suite_and_selects_exact_durations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = _write_provider_suite(Path(temporary).resolve())

            with mock.patch.object(
                provider_duration_suite,
                "load_duration_track",
                side_effect=lambda path: _fake_loaded_track(path, fixture.manifests),
            ) as load_track:
                loaded = load_provider_duration_suite(
                    suite_path=fixture.suite_path,
                    expected_sha256=hashlib.sha256(fixture.suite_bytes).hexdigest(),
                    plan_path=PLAN_PATH,
                    environ={"YAP_EVAL_CACHE": str(fixture.cache_root)},
                )

        self.assertEqual(load_track.call_count, 18)
        self.assertEqual(loaded.plan_sha256, fixture.plan_sha256)
        selected = loaded.manifest_paths_for((480_000, 262_144, 480_000))
        self.assertEqual(
            [path.parent.name for path in selected],
            [
                "provider-duration-480000-samples",
                "provider-duration-262144-samples",
            ],
        )

    def test_load_case_selection_hashes_audio_only_for_required_durations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = _write_provider_suite(Path(temporary).resolve())

            with mock.patch.object(
                provider_duration_suite,
                "load_duration_track",
                side_effect=lambda path: _fake_loaded_track(path, fixture.manifests),
            ) as load_track:
                selected = load_provider_load_case_tracks(
                    suite_path=fixture.suite_path,
                    expected_suite_sha256=hashlib.sha256(fixture.suite_bytes).hexdigest(),
                    plan_path=PLAN_PATH,
                    load_case_id="vllm-cancelled-sibling",
                    environ={"YAP_EVAL_CACHE": str(fixture.cache_root)},
                )

        self.assertEqual(load_track.call_count, 3)
        self.assertEqual(selected.duration_samples, (524_287, 262_144, 16_000))
        self.assertEqual(len(selected.manifest_paths), 3)
        self.assertEqual(set(selected.indexed_tracks()), set(selected.duration_samples))
        self.assertEqual(
            selected.public_identity(),
            {
                "sha256": hashlib.sha256(fixture.suite_bytes).hexdigest(),
                "planSha256": fixture.plan_sha256,
                "selectedDurationSamples": [524_287, 262_144, 16_000],
            },
        )
        bound = bind_provider_load_case_tracks(
            {
                "schemaVersion": 1,
                "passed": True,
                "evidenceSha256": "0" * 64,
            },
            selected,
        )
        self.assertNotIn("evidenceSha256", bound)
        self.assertEqual(bound["durationSuite"], selected.public_identity())

        with mock.patch.object(
            provider_duration_suite,
            "load_provider_duration_suite",
            return_value=selected.suite,
        ) as reload_suite:
            verify_provider_load_case_tracks_unchanged(
                selected,
                plan_path=PLAN_PATH,
            )
        reload_suite.assert_called_once_with(
            suite_path=selected.suite.suite_path,
            expected_sha256=selected.suite.suite_sha256,
            plan_path=PLAN_PATH,
            required_duration_samples=selected.duration_samples,
            environ={"YAP_EVAL_CACHE": str(selected.suite.cache_root)},
        )
        with (
            mock.patch.object(
                provider_duration_suite,
                "load_provider_duration_suite",
                return_value=replace(selected.suite, plan_sha256="f" * 64),
            ),
            self.assertRaisesRegex(ValueError, "changed during qualification"),
        ):
            verify_provider_load_case_tracks_unchanged(
                selected,
                plan_path=PLAN_PATH,
            )

    def test_loader_rejects_a_wrong_out_of_band_suite_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = _write_provider_suite(Path(temporary).resolve())

            with self.assertRaisesRegex(ValueError, "out-of-band digest"):
                load_provider_duration_suite(
                    suite_path=fixture.suite_path,
                    expected_sha256="0" * 64,
                    plan_path=PLAN_PATH,
                    environ={"YAP_EVAL_CACHE": str(fixture.cache_root)},
                )

    def test_loader_rejects_a_relative_suite_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary).resolve()
            runtime_tracks = cache / "runtime-tracks"
            runtime_tracks.mkdir()
            if provider_duration_suite.os.name == "posix":
                provider_duration_suite.os.chmod(cache, 0o700)
                provider_duration_suite.os.chmod(runtime_tracks, 0o700)

            with self.assertRaisesRegex(ValueError, "absolute real file"):
                load_provider_duration_suite(
                    suite_path=Path("suite.json"),
                    expected_sha256="0" * 64,
                    plan_path=PLAN_PATH,
                    environ={"YAP_EVAL_CACHE": str(cache)},
                )

    def test_load_case_selection_rejects_a_reference_system(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a resident provider"):
            load_provider_load_case_tracks(
                suite_path=Path("C:/private/suite.json"),
                expected_suite_sha256="0" * 64,
                plan_path=PLAN_PATH,
                load_case_id="transformers-reference-slot-capacity",
                environ={"YAP_EVAL_CACHE": "C:/private"},
            )


if __name__ == "__main__":
    unittest.main()
