from __future__ import annotations

from dataclasses import replace
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from urllib.request import Request

from yap_server.lid.component_lock import (
    LidComponentArtifactError,
    LidComponentLock,
    LockedLidArtifact,
    load_lid_component_lock,
)
from yap_server.lid.model_assets import (
    _PinnedArtifactRedirectHandler,
    artifact_url,
    sync_lid_model_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPONENT_LOCK = REPO_ROOT / "server" / "lid-component.lock.json"


class _Response(io.BytesIO):
    def __init__(self, content: bytes, *, status: int) -> None:
        super().__init__(content)
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _small_lock() -> tuple[LidComponentLock, dict[str, bytes]]:
    lock = load_lid_component_lock(COMPONENT_LOCK)
    contents = {
        artifact.path: f"locked:{artifact.path}".encode()
        for artifact in lock.model.artifacts
    }
    artifacts = tuple(
        LockedLidArtifact(
            path=artifact.path,
            size=len(contents[artifact.path]),
            sha256=hashlib.sha256(contents[artifact.path]).hexdigest(),
        )
        for artifact in lock.model.artifacts
    )
    return replace(lock, model=replace(lock.model, artifacts=artifacts)), contents


class LidModelAssetTests(unittest.TestCase):
    def test_urls_use_the_exact_original_model_and_immutable_revision(self) -> None:
        lock, _contents = _small_lock()

        self.assertEqual(
            artifact_url(lock, lock.model.artifacts[0]),
            "https://huggingface.co/"
            "speechbrain/lang-id-voxlingua107-ecapa/resolve/"
            "0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9/"
            "classifier.ckpt",
        )

    def test_explicit_sync_downloads_then_reuses_only_verified_artifacts(self) -> None:
        lock, contents = _small_lock()
        calls: list[str] = []

        def opener(request: Request, **kwargs: object) -> _Response:
            del kwargs
            file_name = request.full_url.rsplit("/", maxsplit=1)[-1]
            calls.append(file_name)
            return _Response(contents[file_name], status=200)

        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory) / "lid-model"
            sync_lid_model_artifacts(lock, model_dir, opener=opener)
            sync_lid_model_artifacts(lock, model_dir, opener=opener)

            self.assertEqual(set(calls), set(contents))
            self.assertEqual(len(calls), len(contents))
            for name, content in contents.items():
                self.assertEqual((model_dir / name).read_bytes(), content)
                self.assertFalse((model_dir / f"{name}.part").exists())

    def test_rejects_redirects_outside_approved_https_distribution_hosts(
        self,
    ) -> None:
        handler = _PinnedArtifactRedirectHandler()
        request = Request(
            "https://huggingface.co/example/model/resolve/revision/file"
        )

        redirected = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://cdn-lfs.hf.co/example/file",
        )
        assert redirected is not None
        self.assertEqual(redirected.full_url, "https://cdn-lfs.hf.co/example/file")
        for unsafe in (
            "http://cdn-lfs.hf.co/example/file",
            "https://127.0.0.1/internal",
            "https://169.254.169.254/latest/meta-data",
            "https://example.invalid/file",
            "https://user:secret@huggingface.co/file",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(LidComponentArtifactError):
                    handler.redirect_request(
                        request,
                        None,
                        302,
                        "Found",
                        {},
                        unsafe,
                    )


if __name__ == "__main__":
    unittest.main()
