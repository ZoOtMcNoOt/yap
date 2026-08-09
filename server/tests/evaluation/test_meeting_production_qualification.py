from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from yap_server.evaluation.checked_candidate import admit_checked_candidate
from yap_server.evaluation.meeting_production_qualification import (
    evaluate_meeting_production_qualification,
)


SERVER_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_PLAN = SERVER_ROOT / "meeting-transcription-acceptance.json"
RUNTIME_LOCK = SERVER_ROOT / "meeting-transcription-runtime.lock.json"


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


class MeetingProductionQualificationTests(unittest.TestCase):
    def test_missing_private_cache_closes_as_unadvertised_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            server = repository / "server"
            server.mkdir()
            plan = server / ACCEPTANCE_PLAN.name
            lock = server / RUNTIME_LOCK.name
            plan.write_bytes(ACCEPTANCE_PLAN.read_bytes())
            lock.write_bytes(RUNTIME_LOCK.read_bytes())
            _git(repository, "init")
            _git(repository, "config", "user.email", "qualification@example.invalid")
            _git(repository, "config", "user.name", "Qualification Test")
            _git(repository, "add", "server")
            _git(repository, "commit", "-m", "qualification candidate")
            checked_head = _git(repository, "rev-parse", "HEAD")
            candidate = admit_checked_candidate(
                repository_root=repository,
                checked_head=checked_head,
                input_paths=(plan, lock),
            )

            decision = evaluate_meeting_production_qualification(
                candidate=candidate,
                acceptance_plan_path=plan,
                environ={},
            )

            self.assertEqual(decision["outcome"], "unadvertised-baseline")
            self.assertEqual(decision["reasonCodes"], ["private-cache-unconfigured"])
            self.assertEqual(decision["candidate"]["checkedHead"], checked_head)
            self.assertEqual(decision["candidate"]["repositoryState"], "clean")
            self.assertEqual(
                set(decision["candidate"]["inputs"]),
                {
                    "server/meeting-transcription-acceptance.json",
                    "server/meeting-transcription-runtime.lock.json",
                },
            )
            self.assertRegex(decision["evidenceSha256"], r"^[0-9a-f]{64}$")
            serialized = json.dumps(decision, sort_keys=True)
            self.assertNotIn(str(repository), serialized)
            self.assertNotIn("audioPath", serialized)
            self.assertNotIn("transcriptText", serialized)


if __name__ == "__main__":
    unittest.main()
