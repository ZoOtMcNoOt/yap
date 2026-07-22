"""Build-time assertions for the isolated Linux ARM64 LID image."""

from __future__ import annotations

import importlib.metadata as metadata
from pathlib import Path
import sys

import torch

from yap_server.lid.component_lock import (
    load_lid_component_lock,
    verify_lid_requirements,
)


EXPECTED_PACKAGES = {
    "speechbrain": "1.1.0",
    "torch": "2.11.0+cpu",
    "torchaudio": "2.11.0+cpu",
}
IMAGE_ROOT = Path("/opt/yap-repo")


def main() -> None:
    actual = {name: metadata.version(name) for name in EXPECTED_PACKAGES}
    assert actual == EXPECTED_PACKAGES, (actual, EXPECTED_PACKAGES)
    assert sys.version_info[:3] == (3, 12, 13)
    assert torch.version.cuda is None
    assert not torch.cuda.is_available()
    lock = load_lid_component_lock(
        IMAGE_ROOT / "server" / "lid-component.lock.json"
    )
    verify_lid_requirements(lock, IMAGE_ROOT)


if __name__ == "__main__":
    main()
