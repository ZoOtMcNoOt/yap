from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Callable, Mapping, Sequence

from yap_server.private_artifact import (
    read_bounded_regular_file,
)
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)


_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_MAXIMUM_CANDIDATE_INPUT_BYTES = 16 * 1024 * 1024
GitRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class CheckedCandidate:
    repository_root: Path
    checked_head: str
    input_sha256: Mapping[str, str]
    _input_paths: tuple[Path, ...]

    def verify_unchanged(
        self,
        *,
        runner: GitRunner = subprocess.run,
    ) -> None:
        """Re-read the repository and candidate inputs before evidence publication."""

        _assert_repository_state(
            self.repository_root,
            self.checked_head,
            runner=runner,
        )
        current = _input_identities(self.repository_root, self._input_paths)
        if current != dict(self.input_sha256):
            raise ValueError("checked candidate input changed during qualification")
        _assert_repository_state(
            self.repository_root,
            self.checked_head,
            runner=runner,
        )


def admit_checked_candidate(
    *,
    repository_root: Path,
    checked_head: str,
    input_paths: Sequence[Path],
    runner: GitRunner = subprocess.run,
) -> CheckedCandidate:
    """Admit one clean exact-head repository plus its public qualification inputs."""

    if _GIT_SHA.fullmatch(checked_head) is None:
        raise ValueError("checked head must be a full lowercase Git SHA")
    root = _real_repository_root(repository_root)
    paths = tuple(input_paths)
    _assert_repository_state(root, checked_head, runner=runner)
    input_sha256 = _input_identities(root, paths)
    _assert_repository_state(root, checked_head, runner=runner)
    return CheckedCandidate(
        repository_root=root,
        checked_head=checked_head,
        input_sha256=input_sha256,
        _input_paths=paths,
    )


def bind_checked_candidate_evidence(
    evidence: Mapping[str, object],
    candidate: CheckedCandidate,
) -> dict[str, object]:
    """Bind and rehash an aggregate only after the candidate's final read-back."""

    if not isinstance(candidate, CheckedCandidate):
        raise TypeError("checked candidate evidence binding is invalid")
    bound = dict(evidence)
    if "candidate" in bound:
        raise ValueError("qualification evidence already contains a candidate binding")
    bound.pop("evidenceSha256", None)
    bound["candidate"] = {
        "checkedHead": candidate.checked_head,
        "repositoryState": "clean",
        "inputs": dict(sorted(candidate.input_sha256.items())),
    }
    bound["evidenceSha256"] = canonical_evidence_sha256(bound)
    return bound


def _real_repository_root(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("candidate repository root must be an absolute real directory")
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.lstat()
    except OSError as error:
        raise ValueError(
            "candidate repository root must be an absolute real directory"
        ) from error
    is_junction = getattr(resolved, "is_junction", lambda: False)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or is_junction()
    ):
        raise ValueError("candidate repository root must be an absolute real directory")
    return resolved


def _assert_repository_state(
    repository_root: Path,
    checked_head: str,
    *,
    runner: GitRunner,
) -> None:
    top_level = _git(
        repository_root,
        ("rev-parse", "--show-toplevel"),
        runner=runner,
    ).strip()
    if not top_level or not _same_path(Path(top_level), repository_root):
        raise ValueError("candidate path is not the Git worktree root")
    actual_head = _git(
        repository_root,
        ("rev-parse", "HEAD"),
        runner=runner,
    ).strip()
    if actual_head != checked_head:
        raise ValueError("candidate repository HEAD differs from checked head")
    status = _git(
        repository_root,
        ("status", "--porcelain=v1", "--untracked-files=normal"),
        runner=runner,
    )
    if status:
        raise ValueError("provider qualification requires a clean Git worktree")


def _git(
    repository_root: Path,
    arguments: tuple[str, ...],
    *,
    runner: GitRunner,
) -> str:
    try:
        completed = runner(
            ["git", "-C", str(repository_root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ValueError("candidate Git state could not be verified") from error
    if completed.returncode != 0:
        raise ValueError("candidate Git state could not be verified")
    return completed.stdout


def _input_identities(
    repository_root: Path,
    input_paths: tuple[Path, ...],
) -> dict[str, str]:
    identities: dict[str, str] = {}
    for path in input_paths:
        if not path.is_absolute():
            raise ValueError("candidate input paths must be absolute")
        body = read_bounded_regular_file(
            path,
            maximum_bytes=_MAXIMUM_CANDIDATE_INPUT_BYTES,
            field="candidate input",
            containment_root=repository_root,
        )
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(repository_root).as_posix()
        if relative in identities:
            raise ValueError("candidate input paths must be unique")
        identities[relative] = hashlib.sha256(body).hexdigest()
    return dict(sorted(identities.items()))


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(
        os.path.abspath(second)
    )
