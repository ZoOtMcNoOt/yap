# SPDX-License-Identifier: BSD-3-Clause
"""Apply the exact upstream PyTorch library-finalizer safety fix.

The digest-pinned NVIDIA 26.06 image predates PyTorch commit
c5f8ebc91a8727a9056734f73329c217328b8989. That commit avoids calling an
uncached torch operator through C++ after the runtime has begun interpreter
shutdown. Keep this build-time backport fail-closed against the pinned source.
"""

from __future__ import annotations

from pathlib import Path


UPSTREAM_REVISION = "c5f8ebc91a8727a9056734f73329c217328b8989"
_PINNED_SOURCE = (
    "        namespace = getattr(torch.ops, ns)\n"
    "        if not hasattr(namespace, name):\n"
    "            continue\n"
)
_PATCHED_SOURCE = (
    "        namespace = getattr(torch.ops, ns)\n"
    "        if name not in vars(namespace):\n"
    "            continue\n"
)


def patch_pytorch_library_source(source: str) -> str:
    """Replace the one unsafe pinned finalizer check or fail closed."""

    if not isinstance(source, str) or source.count(_PINNED_SOURCE) != 1:
        raise RuntimeError("PyTorch library finalizer differs from the exact pinned source")
    patched = source.replace(_PINNED_SOURCE, _PATCHED_SOURCE, 1)
    if patched.count(_PATCHED_SOURCE) != 1:
        raise RuntimeError("PyTorch library finalizer fix was not applied exactly once")
    return patched


def main() -> int:
    import torch.library

    module_file = getattr(torch.library, "__file__", None)
    if not isinstance(module_file, str) or not module_file:
        raise RuntimeError("PyTorch library source path is unavailable")
    source_path = Path(module_file).resolve()
    source = source_path.read_text(encoding="utf-8")
    patched = patch_pytorch_library_source(source)
    compile(patched, str(source_path), "exec")
    source_path.write_text(patched, encoding="utf-8", newline="\n")
    if source_path.read_text(encoding="utf-8") != patched:
        raise RuntimeError("PyTorch library finalizer fix did not persist exactly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
