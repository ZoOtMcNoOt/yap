from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from yap_server.pools.checked_runtime_image import (
    CheckedRuntimeImageError,
    external_base_references,
    prepare_checked_runtime_image,
    preparation_receipt,
    runtime_image_contract,
    verify_prepared_checked_image,
    verify_local_checked_image,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CHECKED_HEAD = "a" * 40


class CheckedRuntimeImageTests(unittest.TestCase):
    def test_every_external_base_is_digest_pinned(self) -> None:
        for runtime in (
            "cohere-vllm",
            "nemotron-nemo",
            "language-detection",
            "meeting-transcription",
            "reference-batch-asr",
        ):
            contract = runtime_image_contract(REPOSITORY_ROOT, runtime, CHECKED_HEAD)
            bases = external_base_references(contract.dockerfile)
            dockerfile = contract.dockerfile.read_text(encoding="utf-8")

            self.assertGreaterEqual(len(bases), 1)
            self.assertTrue(
                all("@sha256:" in reference for reference in bases),
                runtime,
            )
            self.assertIn(
                f'com.mcnatg1.yap.runtime="{runtime}"',
                dockerfile,
            )

    def test_missing_prepared_image_fails_without_build_or_network_fallback(self) -> None:
        contract = runtime_image_contract(
            REPOSITORY_ROOT,
            "nemotron-nemo",
            CHECKED_HEAD,
        )
        commands: list[list[str]] = []

        def missing_image(
            command: list[str],
            **_: object,
        ) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            raise subprocess.CalledProcessError(1, command, stderr="No such image")

        with self.assertRaisesRegex(
            CheckedRuntimeImageError,
            "Prepared checked runtime image is required",
        ):
            verify_local_checked_image(contract, runner=missing_image)

        self.assertEqual(commands, [["docker", "image", "inspect", contract.image]])
        self.assertFalse(any("build" in command for command in commands))

    def test_preparation_requires_the_exact_local_base_before_building(self) -> None:
        contract = runtime_image_contract(
            REPOSITORY_ROOT,
            "nemotron-nemo",
            CHECKED_HEAD,
        )
        base = external_base_references(contract.dockerfile)[0]
        commands: list[list[str]] = []

        def missing_base(
            command: list[str],
            **_: object,
        ) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            raise subprocess.CalledProcessError(1, command, stderr="No such image")

        with self.assertRaisesRegex(
            CheckedRuntimeImageError,
            "Cached digest-pinned base image is required",
        ):
            prepare_checked_runtime_image(
                REPOSITORY_ROOT,
                contract,
                runner=missing_base,
            )

        self.assertEqual(commands, [["docker", "image", "inspect", base]])
        self.assertFalse(any("build" in command for command in commands))

    def test_valid_prepared_image_returns_immutable_identity(self) -> None:
        contract = runtime_image_contract(
            REPOSITORY_ROOT,
            "language-detection",
            CHECKED_HEAD,
        )
        payload = f"""
        [{{
          "Id": "sha256:{"b" * 64}",
          "Architecture": "arm64",
          "Config": {{
            "Labels": {{
              "org.opencontainers.image.revision": "{CHECKED_HEAD}",
              "com.mcnatg1.yap.base-platform-digest": "{contract.base_digest}",
              "com.mcnatg1.yap.runtime": "{contract.runtime}"
            }}
          }}
        }}]
        """

        def prepared_image(
            command: list[str],
            **_: object,
        ) -> subprocess.CompletedProcess[str]:
            self.assertEqual(command, ["docker", "image", "inspect", contract.image])
            return subprocess.CompletedProcess(command, 0, stdout=payload, stderr="")

        result = verify_local_checked_image(contract, runner=prepared_image)

        self.assertEqual(result["image"], contract.image)
        self.assertEqual(result["architecture"], "arm64")
        self.assertEqual(result["revision"], CHECKED_HEAD)

    def test_prepared_image_identity_mismatches_fail_closed(self) -> None:
        contract = runtime_image_contract(
            REPOSITORY_ROOT,
            "language-detection",
            CHECKED_HEAD,
        )
        cases = (
            (
                "amd64",
                CHECKED_HEAD,
                contract.base_digest,
                contract.runtime,
                "not ARM64",
            ),
            (
                "arm64",
                "b" * 40,
                contract.base_digest,
                contract.runtime,
                "revision differs",
            ),
            (
                "arm64",
                CHECKED_HEAD,
                f"sha256:{'d' * 64}",
                contract.runtime,
                "base digest differs",
            ),
            (
                "arm64",
                CHECKED_HEAD,
                contract.base_digest,
                "reference-batch-asr",
                "runtime identity differs",
            ),
        )

        for architecture, revision, base_digest, runtime, expected_error in cases:
            with self.subTest(expected_error):
                payload = json.dumps(
                    [
                        {
                            "Id": f"sha256:{'c' * 64}",
                            "Architecture": architecture,
                            "Config": {
                                "Labels": {
                                    "org.opencontainers.image.revision": revision,
                                    "com.mcnatg1.yap.base-platform-digest": base_digest,
                                    "com.mcnatg1.yap.runtime": runtime,
                                }
                            },
                        }
                    ]
                )

                def mismatched_image(
                    command: list[str],
                    **_: object,
                ) -> subprocess.CompletedProcess[str]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=payload,
                        stderr="",
                    )

                with self.assertRaisesRegex(
                    CheckedRuntimeImageError,
                    expected_error,
                ):
                    verify_local_checked_image(contract, runner=mismatched_image)

    def test_malformed_image_configuration_fails_with_owned_error(self) -> None:
        contract = runtime_image_contract(
            REPOSITORY_ROOT,
            "cohere-vllm",
            CHECKED_HEAD,
        )
        payload = f"""
        [{{
          "Id": "sha256:{"c" * 64}",
          "Architecture": "arm64",
          "Config": null
        }}]
        """

        def malformed_image(
            command: list[str],
            **_: object,
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, stdout=payload, stderr="")

        with self.assertRaisesRegex(
            CheckedRuntimeImageError,
            "invalid image configuration",
        ):
            verify_local_checked_image(contract, runner=malformed_image)

    def test_frozen_preparation_receipt_rejects_matching_labels_with_another_id(
        self,
    ) -> None:
        contract = runtime_image_contract(
            REPOSITORY_ROOT,
            "nemotron-nemo",
            CHECKED_HEAD,
        )
        prepared = {
            "runtime": contract.runtime,
            "image": contract.image,
            "imageId": f"sha256:{'d' * 64}",
            "architecture": "arm64",
            "revision": CHECKED_HEAD,
            "baseDigest": contract.base_digest,
        }
        receipt_bytes = json.dumps(
            preparation_receipt(contract, prepared),
            sort_keys=True,
        ).encode()
        substituted_payload = json.dumps(
            [
                {
                    "Id": f"sha256:{'e' * 64}",
                    "Architecture": "arm64",
                    "Config": {
                        "Labels": {
                            "org.opencontainers.image.revision": CHECKED_HEAD,
                            "com.mcnatg1.yap.base-platform-digest": (
                                contract.base_digest
                            ),
                            "com.mcnatg1.yap.runtime": contract.runtime,
                        }
                    },
                }
            ]
        )

        def substituted_image(
            command: list[str],
            **_: object,
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=substituted_payload,
                stderr="",
            )

        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory).resolve() / "preparation.json"
            receipt_path.write_bytes(receipt_bytes)
            with self.assertRaisesRegex(
                CheckedRuntimeImageError,
                "differs from its frozen preparation receipt",
            ):
                verify_prepared_checked_image(
                    contract,
                    receipt_path=receipt_path,
                    receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
                    runner=substituted_image,
                )


if __name__ == "__main__":
    unittest.main()
