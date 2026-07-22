from __future__ import annotations

from collections.abc import Callable
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import BinaryIO, Protocol
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


_COPY_BYTES = 4 * 1024 * 1024
_ARTIFACT_HOST_SUFFIXES = ("huggingface.co", "hf.co")
_REPOSITORY_ID = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
Opener = Callable[..., BinaryIO]
StatusSink = Callable[[str], None]
ErrorType = type[RuntimeError]


class LockedArtifact(Protocol):
    path: str
    size: int
    sha256: str


class PinnedArtifactRedirectHandler(HTTPRedirectHandler):
    def __init__(self, error_type: ErrorType) -> None:
        super().__init__()
        self._error_type = error_type

    def redirect_request(
        self,
        request: Request,
        response: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> Request | None:
        validate_artifact_destination(new_url, self._error_type)
        return super().redirect_request(
            request,
            response,
            code,
            message,
            headers,
            new_url,
        )


def huggingface_artifact_url(
    repository_id: str,
    revision: str,
    artifact_path: str,
) -> str:
    parsed_path = PurePosixPath(artifact_path)
    if _REPOSITORY_ID.fullmatch(repository_id) is None:
        raise ValueError("artifact repository ID is invalid")
    if _REVISION.fullmatch(revision) is None:
        raise ValueError("artifact revision must be a full immutable commit")
    if (
        parsed_path.is_absolute()
        or len(parsed_path.parts) != 1
        or parsed_path.name in {"", ".", ".."}
    ):
        raise ValueError("artifact path must be a single safe file name")
    encoded_path = quote(artifact_path, safe="")
    return (
        f"https://huggingface.co/{repository_id}/resolve/"
        f"{revision}/{encoded_path}"
    )


def sync_huggingface_artifacts(
    *,
    repository_id: str,
    revision: str,
    artifacts: tuple[LockedArtifact, ...],
    model_dir: Path,
    verify: Callable[[Path], None],
    error_type: ErrorType,
    user_agent: str,
    opener: Opener | None = None,
    timeout_seconds: float = 120.0,
    status_sink: StatusSink | None = print,
) -> None:
    """Explicitly stage hash-pinned files with bounded, checked redirects."""

    if timeout_seconds <= 0:
        raise ValueError("download timeout must be positive")
    if not artifacts:
        raise ValueError("at least one locked artifact is required")
    if not user_agent or any(character in user_agent for character in "\r\n"):
        raise ValueError("artifact download user agent is invalid")
    try:
        existing = model_dir.lstat()
    except FileNotFoundError:
        model_dir.mkdir(parents=True, exist_ok=False)
    else:
        if stat.S_ISLNK(existing.st_mode) or not stat.S_ISDIR(existing.st_mode):
            raise error_type("model destination is not a regular directory")
    root = model_dir.resolve(strict=True)

    resolved_opener = opener or build_opener(
        PinnedArtifactRedirectHandler(error_type)
    ).open
    for artifact in artifacts:
        url = huggingface_artifact_url(repository_id, revision, artifact.path)
        destination = root / artifact.path
        if _matches(destination, artifact):
            if status_sink is not None:
                status_sink(f"verified {artifact.path}")
            continue
        _reject_unsafe_existing(destination, error_type)
        destination.unlink(missing_ok=True)
        _download_artifact(
            url,
            destination,
            artifact,
            error_type=error_type,
            opener=resolved_opener,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
        )
        if status_sink is not None:
            status_sink(f"downloaded {artifact.path}")
    verify(root)


def validate_artifact_destination(url: str, error_type: ErrorType) -> None:
    parsed = urlsplit(url)
    hostname = parsed.hostname.lower().rstrip(".") if parsed.hostname else ""
    try:
        port = parsed.port
    except ValueError as error:
        raise error_type("model artifact redirect has an invalid port") from error
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not any(
            hostname == suffix or hostname.endswith(f".{suffix}")
            for suffix in _ARTIFACT_HOST_SUFFIXES
        )
    ):
        raise error_type("model artifact redirect left approved HTTPS hosts")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(_COPY_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _matches(path: Path, artifact: LockedArtifact) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return False
    return metadata.st_size == artifact.size and _sha256_file(path) == artifact.sha256


def _reject_unsafe_existing(path: Path, error_type: ErrorType) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise error_type("model destination contains an unsafe artifact path")


def _download_artifact(
    url: str,
    destination: Path,
    artifact: LockedArtifact,
    *,
    error_type: ErrorType,
    opener: Opener,
    timeout_seconds: float,
    user_agent: str,
) -> None:
    partial = destination.with_name(destination.name + ".part")
    _reject_unsafe_existing(partial, error_type)
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > artifact.size:
        partial.unlink()
        offset = 0
    if offset == artifact.size:
        if _matches(partial, artifact):
            os.replace(partial, destination)
            return
        partial.unlink()
        offset = 0

    request = Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": user_agent,
            **({"Range": f"bytes={offset}-"} if offset else {}),
        },
    )
    with opener(request, timeout=timeout_seconds) as response:
        status = getattr(response, "status", None)
        if status not in {200, 206} or (not offset and status != 200):
            raise error_type("model artifact server returned an invalid status")
        append = offset > 0 and status == 206
        if offset and not append:
            offset = 0
        mode = "ab" if append else "wb"
        downloaded = offset
        oversized = False
        with partial.open(mode) as output:
            while True:
                block = response.read(_COPY_BYTES)
                if not block:
                    break
                if downloaded + len(block) > artifact.size:
                    oversized = True
                    break
                output.write(block)
                downloaded += len(block)
            if not oversized:
                output.flush()
                os.fsync(output.fileno())

    if oversized:
        partial.unlink(missing_ok=True)
        raise error_type(
            f"downloaded artifact exceeded locked size: {artifact.path}"
        )
    if not _matches(partial, artifact):
        raise error_type(
            f"downloaded artifact failed verification: {artifact.path}"
        )
    partial.chmod(0o640)
    os.replace(partial, destination)
