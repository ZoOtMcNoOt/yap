from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from yap_server.lid.component_lock import load_lid_component_lock
from yap_server.lid.materialization import remove_materialized_lid_request
from yap_server.lid.transport import (
    LidTransportError,
    materialize_lid_transport_request,
    parse_lid_preflight_envelope,
)
from yap_server.lid.worker_contract import load_lid_worker_request


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "server" / "lid-component.lock.json"
CATALOG_REVISION = "c" * 64


class LidTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lid_component_lock(LOCK_PATH)

    def test_parses_and_materializes_only_two_digest_bound_pcm_spans(self) -> None:
        manifest, pcm = _fixture(self.lock)
        request = parse_lid_preflight_envelope(
            _encode(manifest, pcm),
            lock=self.lock,
            expected_catalog_revision=CATALOG_REVISION,
        )
        self.assertEqual(request.request_id, "job-lid-transport")
        self.assertEqual(len(request.probes), 2)
        self.assertEqual(request.probes[0].pcm_bytes, pcm[0])
        self.assertEqual(request.probes[1].pcm_bytes, pcm[1])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialized = materialize_lid_transport_request(
                request,
                destination=root / "request",
                lock=self.lock,
            )
            persisted = load_lid_worker_request(
                materialized.request_path,
                self.lock,
            )
            self.assertEqual(persisted.source_samples, 480_000)
            self.assertEqual(
                [probe.voiced_samples for probe in persisted.probes],
                [128_000, 128_000],
            )
            remove_materialized_lid_request(materialized)
            self.assertEqual(list(root.iterdir()), [])

    def test_rejects_stale_identity_hash_length_vad_and_trailing_bytes(self) -> None:
        mutations = (
            lambda value: value.__setitem__("catalogRevision", "d" * 64),
            lambda value: value.__setitem__("policyRevision", "stale"),
            lambda value: value["probes"][0].__setitem__("pcmSha256", "0" * 64),
            lambda value: value["probes"][0].__setitem__("pcmByteLength", 2),
            lambda value: value["probes"][0].__setitem__("voicedSamples", 128_001),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                manifest, pcm = _fixture(self.lock)
                mutate(manifest)
                with self.assertRaises(LidTransportError):
                    parse_lid_preflight_envelope(
                        _encode(manifest, pcm),
                        lock=self.lock,
                        expected_catalog_revision=CATALOG_REVISION,
                    )

        manifest, pcm = _fixture(self.lock)
        with self.assertRaisesRegex(LidTransportError, "trailing"):
            parse_lid_preflight_envelope(
                _encode(manifest, pcm) + b"x",
                lock=self.lock,
                expected_catalog_revision=CATALOG_REVISION,
            )

    def test_rejects_duplicate_manifest_keys_and_unbounded_interval_lists(self) -> None:
        duplicate = (
            b'{"schemaVersion":1,"schemaVersion":1}'
        )
        body = len(duplicate).to_bytes(4, "big") + duplicate
        with self.assertRaisesRegex(LidTransportError, "duplicate"):
            parse_lid_preflight_envelope(
                body,
                lock=self.lock,
                expected_catalog_revision=CATALOG_REVISION,
            )

        manifest, pcm = _fixture(self.lock)
        manifest["probes"][0]["vadIntervals"] = [
            {"startSample": index, "endSampleExclusive": index + 1}
            for index in range(129)
        ]
        with self.assertRaises(LidTransportError):
            parse_lid_preflight_envelope(
                _encode(manifest, pcm),
                lock=self.lock,
                expected_catalog_revision=CATALOG_REVISION,
            )


def _fixture(lock: object) -> tuple[dict[str, object], tuple[bytes, bytes]]:
    pcm = (b"\x01\x00" * 128_000, b"\x02\x00" * 128_000)
    probes = []
    for index, (start, body) in enumerate(zip((0, 240_000), pcm, strict=True)):
        probes.append(
            {
                "index": index,
                "sourceStartSample": start,
                "sourceEndSample": start + 128_000,
                "voicedSamples": 128_000,
                "pcmByteLength": len(body),
                "pcmSha256": hashlib.sha256(body).hexdigest(),
                "vadIntervals": [
                    {
                        "startSample": start,
                        "endSampleExclusive": start + 128_000,
                    }
                ],
            }
        )
    return (
        {
            "schemaVersion": 1,
            "requestId": "job-lid-transport",
            "sourceSamples": 480_000,
            "sourcePcmSha256": "a" * 64,
            "catalogRevision": CATALOG_REVISION,
            "policyRevision": lock.policy.revision,
            "probes": probes,
        },
        pcm,
    )


def _encode(manifest: dict[str, object], pcm: tuple[bytes, bytes]) -> bytes:
    encoded = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    return len(encoded).to_bytes(4, "big") + encoded + b"".join(pcm)


if __name__ == "__main__":
    unittest.main()
