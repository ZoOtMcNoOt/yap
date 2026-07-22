from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
import wave

from yap_server.evaluation.duration_tracks import (
    build_duration_track,
    load_duration_track,
)
from yap_server.evaluation.provider_qualification_requests import (
    LockedProviderRequestFactory,
)
from yap_server.pools.model_lock import load_model_pool_lock


SERVER_ROOT = Path(__file__).resolve().parents[2]


class ProviderQualificationRequestTests(unittest.TestCase):
    def test_builds_fixed_vllm_and_automatic_nemo_jobs_from_exact_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            _write_source(source)
            cache = root / "cache"
            build_duration_track(
                case_id="one-second",
                duration_samples=16_000,
                source_paths=[source],
                environ={"YAP_EVAL_CACHE": str(cache)},
            )
            track = load_duration_track(
                cache / "runtime-tracks" / "one-second" / "manifest.json"
            )
            cohere = LockedProviderRequestFactory(
                system_id="vllm-cohere-batch",
                provider_id="cohere",
                catalog_language="en-US",
                provider_language="en",
                lock=load_model_pool_lock(SERVER_ROOT / "cohere-vllm-serving.lock.json"),
                tracks={16_000: track},
                output_root=cache / "cohere-output",
                environ={"YAP_EVAL_CACHE": str(cache)},
            ).create(
                load_case_id="vllm-short-tail",
                concurrency=1,
                ordinal=0,
                duration_samples=16_000,
            )
            nemo = LockedProviderRequestFactory(
                system_id="nemo-nemotron-finalized",
                provider_id="nemotron",
                catalog_language="und",
                provider_language="auto",
                lock=load_model_pool_lock(SERVER_ROOT / "nemotron-nemo-serving.lock.json"),
                tracks={16_000: track},
                output_root=cache / "nemo-output",
                environ={"YAP_EVAL_CACHE": str(cache)},
            ).create(
                load_case_id="nemo-finalized-short-tail",
                concurrency=1,
                ordinal=0,
                duration_samples=16_000,
            )

            self.assertEqual(cohere.job.route.execution_mode, "fixedBatch")
            self.assertIsNone(cohere.job.utterance_plan_path)
            self.assertEqual(nemo.job.route.execution_mode, "dynamicBatch")
            self.assertEqual(nemo.job.route.provider_language, "auto")
            self.assertIsNotNone(nemo.job.utterance_plan_path)
            assert nemo.job.utterance_plan_path is not None
            self.assertTrue(nemo.job.utterance_plan_path.is_file())

    def test_rejects_output_inside_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            _write_source(source)
            cache = root / "cache"
            build_duration_track(
                case_id="one-second",
                duration_samples=16_000,
                source_paths=[source],
                environ={"YAP_EVAL_CACHE": str(cache)},
            )
            track = load_duration_track(
                cache / "runtime-tracks" / "one-second" / "manifest.json"
            )
            with self.assertRaisesRegex(ValueError, "outside the repository"):
                LockedProviderRequestFactory(
                    system_id="vllm-cohere-batch",
                    provider_id="cohere",
                    catalog_language="en-US",
                    provider_language="en",
                    lock=load_model_pool_lock(
                        SERVER_ROOT / "cohere-vllm-serving.lock.json"
                    ),
                    tracks={16_000: track},
                    output_root=SERVER_ROOT / ".runtime" / "qualification",
                    environ={"YAP_EVAL_CACHE": str(cache)},
                )

    def test_rejects_tracks_or_results_outside_the_private_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            _write_source(source)
            cache = root / "cache"
            build_duration_track(
                case_id="one-second",
                duration_samples=16_000,
                source_paths=[source],
                environ={"YAP_EVAL_CACHE": str(cache)},
            )
            track = load_duration_track(
                cache / "runtime-tracks" / "one-second" / "manifest.json"
            )
            common = {
                "system_id": "vllm-cohere-batch",
                "provider_id": "cohere",
                "catalog_language": "en-US",
                "provider_language": "en",
                "lock": load_model_pool_lock(
                    SERVER_ROOT / "cohere-vllm-serving.lock.json"
                ),
                "environ": {"YAP_EVAL_CACHE": str(cache)},
            }

            with self.assertRaisesRegex(ValueError, "inside YAP_EVAL_CACHE"):
                LockedProviderRequestFactory(
                    **common,
                    tracks={16_000: track},
                    output_root=root / "outside-results",
                )

            outside_track = type(track)(
                audio_path=source.resolve(),
                manifest=track.manifest,
            )
            with self.assertRaisesRegex(ValueError, "duration tracks"):
                LockedProviderRequestFactory(
                    **common,
                    tracks={16_000: outside_track},
                    output_root=cache / "results",
                )


def _write_source(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * 16_000)
    if os.name == "posix":
        os.chmod(path, 0o600)


if __name__ == "__main__":
    unittest.main()
