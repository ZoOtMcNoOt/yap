from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from yap_server.evaluation.checked_candidate import (
    admit_checked_candidate,
    bind_checked_candidate_evidence,
)


class CheckedCandidateTests(unittest.TestCase):
    def test_clean_exact_head_and_inputs_are_verified_twice(self) -> None:
        checked_head = "a" * 40
        calls: list[tuple[str, ...]] = []
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            plan = repository / "server" / "asr-evaluation-plan.json"
            plan.parent.mkdir()
            plan.write_bytes(b'{"schemaVersion":5}\n')
            runner = self._git_runner(repository, checked_head, calls=calls)

            candidate = admit_checked_candidate(
                repository_root=repository,
                checked_head=checked_head,
                input_paths=(plan,),
                runner=runner,
            )
            candidate.verify_unchanged(runner=runner)

        self.assertEqual(candidate.checked_head, checked_head)
        self.assertEqual(
            candidate.input_sha256,
            {
                "server/asr-evaluation-plan.json": hashlib.sha256(
                    b'{"schemaVersion":5}\n'
                ).hexdigest()
            },
        )
        self.assertEqual(calls.count(("rev-parse", "--show-toplevel")), 4)
        self.assertEqual(calls.count(("rev-parse", "HEAD")), 4)
        self.assertEqual(
            calls.count(("status", "--porcelain=v1", "--untracked-files=normal")),
            4,
        )

    def test_dirty_worktree_is_rejected(self) -> None:
        checked_head = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            runner = self._git_runner(
                repository,
                checked_head,
                status=" M server/asr-evaluation-plan.json\n",
            )

            with self.assertRaisesRegex(ValueError, "clean Git worktree"):
                admit_checked_candidate(
                    repository_root=repository,
                    checked_head=checked_head,
                    input_paths=(),
                    runner=runner,
                )

    def test_changed_head_or_candidate_input_is_rejected(self) -> None:
        checked_head = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            plan = repository / "plan.json"
            plan.write_bytes(b"first\n")
            candidate = admit_checked_candidate(
                repository_root=repository,
                checked_head=checked_head,
                input_paths=(plan,),
                runner=self._git_runner(repository, checked_head),
            )

            with self.assertRaisesRegex(ValueError, "repository HEAD"):
                candidate.verify_unchanged(
                    runner=self._git_runner(repository, "b" * 40)
                )

            plan.write_bytes(b"second\n")
            with self.assertRaisesRegex(ValueError, "candidate input changed"):
                candidate.verify_unchanged(
                    runner=self._git_runner(repository, checked_head)
                )

    def test_bound_evidence_rehashes_the_complete_candidate_envelope(self) -> None:
        checked_head = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            plan = repository / "plan.json"
            plan.write_bytes(b"plan\n")
            candidate = admit_checked_candidate(
                repository_root=repository,
                checked_head=checked_head,
                input_paths=(plan,),
                runner=self._git_runner(repository, checked_head),
            )
            evidence = bind_checked_candidate_evidence(
                {
                    "schemaVersion": 1,
                    "passed": True,
                    "evidenceSha256": "0" * 64,
                },
                candidate,
            )

        digest = evidence.pop("evidenceSha256")
        self.assertEqual(
            evidence["candidate"],
            {
                "checkedHead": checked_head,
                "repositoryState": "clean",
                "inputs": {
                    "plan.json": hashlib.sha256(b"plan\n").hexdigest(),
                },
            },
        )
        self.assertEqual(
            digest,
            hashlib.sha256(
                json.dumps(
                    evidence,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        )

    @staticmethod
    def _git_runner(
        repository: Path,
        head: str,
        *,
        status: str = "",
        calls: list[tuple[str, ...]] | None = None,
    ):
        def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            del kwargs
            command = args[0]
            assert isinstance(command, list)
            git_arguments = tuple(command[3:])
            if calls is not None:
                calls.append(git_arguments)
            outputs = {
                ("rev-parse", "--show-toplevel"): str(repository) + "\n",
                ("rev-parse", "HEAD"): head + "\n",
                ("status", "--porcelain=v1", "--untracked-files=normal"): status,
            }
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=outputs[git_arguments],
                stderr="",
            )

        return run


if __name__ == "__main__":
    unittest.main()
