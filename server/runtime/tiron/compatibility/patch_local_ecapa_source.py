# SPDX-License-Identifier: Apache-2.0
"""Make the pinned Tiron runtime consume a verified local ECAPA snapshot.

The upstream engine accepts a local Tiron model path but passes only its fixed
ECAPA source into SpeechBrain. The pinned ECAPA hyperparameters repeat the Hub
identifier as ``pretrained_path``, which attempts a network fetch even when
``source`` is replaced with a local directory. Override that existing field
with the same configured source so an offline local directory remains local.
"""

from __future__ import annotations

from pathlib import Path


UPSTREAM_REVISION = "d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c"
_PINNED_SOURCE = (
    "        self.ecapa = EncoderClassifier.from_hparams(\n"
    "            source=config.ECAPA_MODEL,\n"
    '            run_opts={"device": self.ecapa_device},\n'
    "        )\n"
)
_PATCHED_SOURCE = (
    "        self.ecapa = EncoderClassifier.from_hparams(\n"
    "            source=config.ECAPA_MODEL,\n"
    '            overrides={"pretrained_path": config.ECAPA_MODEL},\n'
    '            run_opts={"device": self.ecapa_device},\n'
    "        )\n"
)


def patch_tiron_engine_source(source: str) -> str:
    """Apply the one local-artifact override or fail against source drift."""

    if not isinstance(source, str) or source.count(_PINNED_SOURCE) != 1:
        raise RuntimeError("Tiron ECAPA loader differs from the exact pinned source")
    patched = source.replace(_PINNED_SOURCE, _PATCHED_SOURCE, 1)
    if patched.count(_PATCHED_SOURCE) != 1:
        raise RuntimeError("Tiron local ECAPA override was not applied exactly once")
    return patched


def main() -> int:
    source_path = Path("/opt/tiron-runtime/tiron/engine.py")
    source = source_path.read_text(encoding="utf-8")
    patched = patch_tiron_engine_source(source)
    compile(patched, str(source_path), "exec")
    source_path.write_text(patched, encoding="utf-8", newline="\n")
    if source_path.read_text(encoding="utf-8") != patched:
        raise RuntimeError("Tiron local ECAPA override did not persist exactly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
