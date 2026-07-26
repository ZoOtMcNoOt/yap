import json
import subprocess
import unittest

from yap_server.pools.gb10_asr_runtime_gate import (
    inspect_container_image,
    validate_gb10_runtime,
)


class Gb10AsrRuntimeGateTests(unittest.TestCase):
    def test_image_inspection_attests_arm64_and_checked_revision(self) -> None:
        checked_head = "a" * 40

        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            del args, kwargs
            return subprocess.CompletedProcess(
                args=["docker"],
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "Id": "sha256:" + "b" * 64,
                            "Architecture": "arm64",
                            "RepoDigests": [],
                            "Config": {
                                "Labels": {
                                    "org.opencontainers.image.revision": checked_head,
                                }
                            },
                        }
                    ]
                ),
                stderr="",
            )

        image = inspect_container_image(
            "yap-gb10-asr:checked-head-aaaaaaaaaaaaaaaa",
            checked_head,
            runner=runner,
        )

        self.assertEqual(image["architecture"], "arm64")
        self.assertEqual(image["revision"], checked_head)

    def test_image_inspection_rejects_a_different_revision(self) -> None:
        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            del args, kwargs
            return subprocess.CompletedProcess(
                args=["docker"],
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "Id": "sha256:" + "b" * 64,
                            "Architecture": "arm64",
                            "RepoDigests": [],
                            "Config": {
                                "Labels": {
                                    "org.opencontainers.image.revision": "c" * 40,
                                }
                            },
                        }
                    ]
                ),
                stderr="",
            )

        with self.assertRaises(RuntimeError):
            inspect_container_image(
                "yap-gb10-asr:checked-head-aaaaaaaaaaaaaaaa",
                "a" * 40,
                runner=runner,
            )

    def test_gate_requires_the_exact_gb10_bfloat16_runtime(self) -> None:
        runtime = {
            "device": "cuda",
            "deviceName": "NVIDIA GB10",
            "computeCapability": [12, 1],
            "dtype": "bfloat16",
        }

        validate_gb10_runtime(runtime)

        for field, value in (
            ("device", "cpu"),
            ("deviceName", "NVIDIA H100 80GB HBM3"),
            ("computeCapability", [9, 0]),
            ("dtype", "float16"),
        ):
            with self.subTest(field=field):
                invalid = dict(runtime)
                invalid[field] = value
                with self.assertRaises(RuntimeError):
                    validate_gb10_runtime(invalid)


if __name__ == "__main__":
    unittest.main()
