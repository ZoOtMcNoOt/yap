from __future__ import annotations

from importlib.metadata import version
import json
from pathlib import Path
import tomllib
import unittest


SERVER_ROOT = Path(__file__).resolve().parents[2]
PROVENANCE_PATH = SERVER_ROOT / "live-websocket-runtime.lock.json"
PROJECT_PATH = SERVER_ROOT / "pyproject.toml"
UV_LOCK_PATH = SERVER_ROOT / "uv.lock"


class LiveWebSocketProvenanceTests(unittest.TestCase):
    def test_pinned_dependency_matches_machine_readable_provenance(self) -> None:
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
        project = tomllib.loads(PROJECT_PATH.read_text(encoding="utf-8"))
        lock = tomllib.loads(UV_LOCK_PATH.read_text(encoding="utf-8"))

        package = provenance["package"]
        self.assertEqual(package["name"], "websockets")
        self.assertEqual(package["version"], "16.1.1")
        self.assertEqual(package["license"], "BSD-3-Clause")
        self.assertEqual(package["requiresPython"], ">=3.10")
        self.assertEqual(version("websockets"), package["version"])
        self.assertIn(
            f"{package['name']}=={package['version']}",
            project["project"]["dependencies"],
        )

        locked = next(
            candidate
            for candidate in lock["package"]
            if candidate["name"] == package["name"]
        )
        self.assertEqual(locked["version"], package["version"])
        locked_distributions = {
            (
                Path(distribution["url"]).name,
                distribution["hash"].removeprefix("sha256:"),
                distribution["size"],
            )
            for distribution in [locked["sdist"], *locked["wheels"]]
        }
        for distribution in package["distributions"]:
            self.assertIn(
                (
                    distribution["filename"],
                    distribution["sha256"],
                    distribution["sizeBytes"],
                ),
                locked_distributions,
            )

    def test_provenance_records_the_private_transport_boundary(self) -> None:
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            provenance["package"]["verifiedMetadataSource"],
            "https://pypi.org/pypi/websockets/16.1.1/json",
        )
        self.assertEqual(
            provenance["boundary"],
            {
                "bind": "loopback-only application transport",
                "tls": "external secure edge",
                "liveAsrInference": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
