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

from yap_server.lid.component_lock import (
    LidComponentLock,
    load_lid_component_lock,
)
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


def _test_lock(root: Path) -> LidComponentLock:
    payload = json.loads(COMPONENT_LOCK.read_text(encoding="utf-8"))
    policy = payload["component"]["policy"]
    policy["minimumSourceSamples"] = 32
    policy["maximumWindowSamples"] = 16
    policy["minimumVoicedSamplesPerWindow"] = 8
    path = root / "lid-component.lock.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_lid_component_lock(path)


def _wav_bytes(
    *,
    frames: int = 16,
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


def _request(
    hashes: list[str],
    *,
    source_samples: int = 40,
) -> dict[str, object]:
    windows = ((0, 16, 10), (20, 36, 12))
    return {
        "schemaVersion": 1,
        "requestId": "lid-request-1",
        "sourceSamples": source_samples,
        "probes": [
            {
                "index": index,
                "fileName": f"probe-{index}.wav",
                "wavSha256": digest,
                "sourceStartSample": windows[index][0],
                "sourceEndSample": windows[index][1],
                "voicedSamples": windows[index][2],
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
    def test_runs_two_bounded_probes_without_publishing_paths_or_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = _test_lock(root)
            hashes = [
                _write_probe(root, 0, _wav_bytes()),
                _write_probe(root, 1, _wav_bytes()),
            ]
            request = load_lid_worker_request(
                _write_request(root, _request(hashes)),
                lock,
            )
            classifier = _Classifier(
                iter(
                    (
                        LidClassification("fr: French", -0.25, 1.5),
                        LidClassification("fr: French", -0.40, 1.1),
                    )
                )
            )

            result = run_lid_worker_request(
                lock=lock,
                request=request,
                probe_root=root,
                classifier=classifier,
            )

            self.assertEqual(classifier.frame_counts, [16, 16])
            self.assertEqual(result["schemaVersion"], 1)
            self.assertEqual(result["requestId"], "lid-request-1")
            self.assertEqual(result["model"]["revision"], lock.model.revision)
            self.assertEqual(result["policyRevision"], lock.policy.revision)
            self.assertEqual(len(result["observations"]), 2)
            self.assertEqual(
                result["observations"][0],
                {
                    "index": 0,
                    "probeSha256": hashes[0],
                    "sourceStartSample": 0,
                    "sourceEndSample": 16,
                    "voicedSamples": 10,
                    "rawLabel": "fr: French",
                    "topScore": -0.25,
                    "scoreMargin": 1.5,
                },
            )
            serialized = json.dumps(result, sort_keys=True)
            self.assertNotIn("probe-0.wav", serialized)
            self.assertNotIn("confidence", serialized.lower())
            self.assertNotIn("pcm", serialized.lower())

    def test_rejects_unknown_fields_traversal_overlap_and_extra_probes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = _test_lock(root)
            encoded = _wav_bytes()
            hashes = [
                _write_probe(root, 0, encoded),
                _write_probe(root, 1, encoded),
            ]
            mutations = (
                lambda value: value.update({"unexpected": True}),
                lambda value: value["probes"][0].update(
                    {"fileName": "../probe-0.wav"}
                ),
                lambda value: value["probes"][1].update(
                    {"sourceStartSample": 15}
                ),
                lambda value: value["probes"].append(
                    {
                        **value["probes"][1],
                        "index": 2,
                        "fileName": "probe-2.wav",
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
                            lock,
                        )

    def test_rejects_hash_shape_span_and_link_mismatches(self) -> None:
        cases = (
            ("hash", _wav_bytes(), "0" * 64, 16),
            ("channels", _wav_bytes(channels=2), None, 16),
            ("sample rate", _wav_bytes(sample_rate=8_000), None, 16),
            ("frame span", _wav_bytes(frames=15), None, 16),
        )
        for name, encoded, requested_hash, end_sample in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                lock = _test_lock(root)
                actual_hash = _write_probe(root, 0, encoded)
                payload = _request([requested_hash or actual_hash])
                payload["probes"][0]["sourceEndSample"] = end_sample
                request = load_lid_worker_request(
                    _write_request(root, payload),
                    lock,
                )
                classifier = _Classifier(
                    iter((LidClassification("en: English", -0.1, 2.0),))
                )
                with self.assertRaises(WorkerInputError):
                    run_lid_worker_request(
                        lock=lock,
                        request=request,
                        probe_root=root,
                        classifier=classifier,
                    )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = _test_lock(root)
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
                lock,
            )
            with self.assertRaises(WorkerInputError):
                run_lid_worker_request(
                    lock=lock,
                    request=request,
                    probe_root=root,
                    classifier=_Classifier(
                        iter((LidClassification("en: English", -0.1, 2.0),))
                    ),
                )

    def test_rejects_invalid_classifier_evidence(self) -> None:
        invalid = (
            LidClassification("", -0.2, 1.0),
            LidClassification("en: English\nsecret", -0.2, 1.0),
            LidClassification("en: English", math.nan, 1.0),
            LidClassification("en: English", 0.1, 1.0),
            LidClassification("en: English", -0.2, -0.1),
        )
        for output in invalid:
            with (
                self.subTest(output=output),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                lock = _test_lock(root)
                encoded = _wav_bytes()
                digest = _write_probe(root, 0, encoded)
                request = load_lid_worker_request(
                    _write_request(root, _request([digest])),
                    lock,
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "invalid evidence",
                ):
                    run_lid_worker_request(
                        lock=lock,
                        request=request,
                        probe_root=root,
                        classifier=_Classifier(iter((output,))),
                    )

    def test_result_validation_rebinds_every_authoritative_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = _test_lock(root)
            encoded = _wav_bytes()
            digest = _write_probe(root, 0, encoded)
            request = load_lid_worker_request(
                _write_request(root, _request([digest])),
                lock,
            )
            result = run_lid_worker_request(
                lock=lock,
                request=request,
                probe_root=root,
                classifier=_Classifier(
                    iter((LidClassification("en: English", -0.2, 1.0),))
                ),
            )
            validate_lid_worker_result(result, request=request, lock=lock)

            mutations = (
                lambda value: value.update({"requestId": "other"}),
                lambda value: value["model"].update({"revision": "b" * 40}),
                lambda value: value["observations"][0].update(
                    {"sourceStartSample": 1}
                ),
                lambda value: value["observations"][0].update(
                    {"probeSha256": "b" * 64}
                ),
                lambda value: value["observations"][0].update(
                    {"topScore": 0.1}
                ),
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
