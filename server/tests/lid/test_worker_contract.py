from __future__ import annotations

from collections.abc import Iterator
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
import wave

from yap_server.lid.component_lock import load_lid_component_lock
from yap_server.lid.worker_contract import (
    LidClassification,
    ProbeAudio,
    WorkerInputError,
    WorkerResultError,
    load_lid_worker_request,
    run_lid_worker_request,
    validate_lid_worker_result,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPONENT_LOCK = REPO_ROOT / "server" / "lid-component.lock.json"
REGION_SAMPLES = 96_000
SOURCE_SAMPLES = REGION_SAMPLES * 5


def _lock():
    return load_lid_component_lock(COMPONENT_LOCK)


def _wav_bytes(
    *,
    frames: int = REGION_SAMPLES,
    channels: int = 1,
    sample_rate: int = 16_000,
    sample_width: int = 2,
) -> bytes:
    with tempfile.SpooledTemporaryFile() as target:
        with wave.open(target, "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(sample_width)
            output.setframerate(sample_rate)
            output.writeframes(b"\0" * frames * channels * sample_width)
        target.seek(0)
        return target.read()


def _write_probe(root: Path, index: int, encoded: bytes) -> str:
    (root / f"probe-{index}.wav").write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _request(hashes: list[str]) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "requestId": "lid-request-1",
        "sourceSamples": SOURCE_SAMPLES,
        "probes": [
            {
                "index": index,
                "fileName": f"probe-{index}.wav",
                "wavSha256": digest,
                "sourceStartSample": index * REGION_SAMPLES,
                "sourceEndSample": (index + 1) * REGION_SAMPLES,
                "voicedSamples": 60_000,
            }
            for index, digest in enumerate(hashes)
        ],
    }


def _write_request(root: Path, payload: dict[str, object]) -> Path:
    path = root / "request.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class _Classifier:
    def __init__(self, outputs: Iterator[LidClassification]) -> None:
        self._outputs = outputs
        self.frame_counts: list[int] = []

    def classify(self, audio: ProbeAudio) -> LidClassification:
        self.frame_counts.append(audio.frame_count)
        return next(self._outputs)


class LidWorkerContractTests(unittest.TestCase):
    def test_runs_five_bounded_regions_without_publishing_paths_or_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            encoded = _wav_bytes()
            hashes = [_write_probe(root, index, encoded) for index in range(5)]
            request = load_lid_worker_request(
                _write_request(root, _request(hashes)),
                _lock(),
            )
            classifier = _Classifier(
                iter(LidClassification("fr", -0.25, 1.5) for _ in range(5))
            )

            result = run_lid_worker_request(
                lock=_lock(),
                request=request,
                probe_root=root,
                classifier=classifier,
            )

            self.assertEqual(classifier.frame_counts, [REGION_SAMPLES] * 5)
            self.assertEqual(result["schemaVersion"], 1)
            self.assertEqual(result["requestId"], "lid-request-1")
            self.assertEqual(len(result["observations"]), 5)
            self.assertEqual(result["observations"][0]["rawLabel"], "fr")
            serialized = json.dumps(result, sort_keys=True)
            self.assertNotIn("probe-0.wav", serialized)
            self.assertNotIn("confidence", serialized.lower())
            self.assertNotIn("pcm", serialized.lower())

    def test_rejects_unknown_fields_traversal_overlap_and_sixth_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            encoded = _wav_bytes()
            hashes = [_write_probe(root, index, encoded) for index in range(5)]
            mutations = (
                lambda value: value.update({"unexpected": True}),
                lambda value: value["probes"][0].update(
                    {"fileName": "../probe-0.wav"}
                ),
                lambda value: value["probes"][1].update(
                    {"sourceStartSample": REGION_SAMPLES - 1}
                ),
                lambda value: value["probes"].append(
                    {
                        **value["probes"][-1],
                        "index": 5,
                        "fileName": "probe-5.wav",
                    }
                ),
            )
            for mutate in mutations:
                with self.subTest(mutate=mutate):
                    payload = _request(hashes)
                    mutate(payload)
                    with self.assertRaises(WorkerInputError):
                        load_lid_worker_request(
                            _write_request(root, payload),
                            _lock(),
                        )

    def test_rejects_hash_shape_span_and_link_mismatches(self) -> None:
        cases = (
            ("hash", _wav_bytes(), "0" * 64),
            ("channels", _wav_bytes(channels=2), None),
            ("sample rate", _wav_bytes(sample_rate=8_000), None),
            ("frame span", _wav_bytes(frames=REGION_SAMPLES - 1), None),
        )
        for name, encoded, requested_hash in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                actual_hash = _write_probe(root, 0, encoded)
                request = load_lid_worker_request(
                    _write_request(root, _request([requested_hash or actual_hash])),
                    _lock(),
                )
                with self.assertRaises(WorkerInputError):
                    run_lid_worker_request(
                        lock=_lock(),
                        request=request,
                        probe_root=root,
                        classifier=_Classifier(
                            iter((LidClassification("en", -0.1, 2.0),))
                        ),
                    )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "outside.wav"
            encoded = _wav_bytes()
            target.write_bytes(encoded)
            try:
                os.symlink(target, root / "probe-0.wav")
            except OSError:
                return
            request = load_lid_worker_request(
                _write_request(
                    root,
                    _request([hashlib.sha256(encoded).hexdigest()]),
                ),
                _lock(),
            )
            with self.assertRaises(WorkerInputError):
                run_lid_worker_request(
                    lock=_lock(),
                    request=request,
                    probe_root=root,
                    classifier=_Classifier(
                        iter((LidClassification("en", -0.1, 2.0),))
                    ),
                )

    def test_rejects_invalid_classifier_evidence(self) -> None:
        invalid = (
            LidClassification("", -0.2, 1.0),
            LidClassification("en\nsecret", -0.2, 1.0),
            LidClassification("en", math.nan, 1.0),
            LidClassification("en", 0.1, 1.0),
            LidClassification("en", -0.2, -0.1),
        )
        for output in invalid:
            with self.subTest(output=output), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                encoded = _wav_bytes()
                digest = _write_probe(root, 0, encoded)
                request = load_lid_worker_request(
                    _write_request(root, _request([digest])),
                    _lock(),
                )
                with self.assertRaisesRegex(RuntimeError, "invalid evidence"):
                    run_lid_worker_request(
                        lock=_lock(),
                        request=request,
                        probe_root=root,
                        classifier=_Classifier(iter((output,))),
                    )

    def test_result_validation_rebinds_every_authoritative_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            encoded = _wav_bytes()
            digest = _write_probe(root, 0, encoded)
            lock = _lock()
            request = load_lid_worker_request(
                _write_request(root, _request([digest])),
                lock,
            )
            result = run_lid_worker_request(
                lock=lock,
                request=request,
                probe_root=root,
                classifier=_Classifier(
                    iter((LidClassification("en", -0.2, 1.0),))
                ),
            )
            validate_lid_worker_result(result, request=request, lock=lock)

            mutations = (
                lambda value: value.update({"requestId": "other"}),
                lambda value: value["model"].update({"revision": "9.9.9"}),
                lambda value: value["observations"][0].update(
                    {"sourceStartSample": 1}
                ),
                lambda value: value["observations"][0].update(
                    {"probeSha256": "b" * 64}
                ),
                lambda value: value["observations"][0].update({"topScore": 0.1}),
                lambda value: value["observations"][0].update({"index": False}),
                lambda value: value.update({"unexpected": True}),
            )
            for mutate in mutations:
                with self.subTest(mutate=mutate):
                    candidate = json.loads(json.dumps(result))
                    mutate(candidate)
                    with self.assertRaises(WorkerResultError):
                        validate_lid_worker_result(
                            candidate,
                            request=request,
                            lock=lock,
                        )


if __name__ == "__main__":
    unittest.main()
