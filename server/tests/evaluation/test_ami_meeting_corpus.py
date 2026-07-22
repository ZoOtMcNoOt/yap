from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from yap_server.evaluation.ami_meeting_corpus import (
    inspect_ami_meeting_corpus,
    load_ami_condition_audio,
    load_ami_word_timeline,
)
from yap_server.evaluation.ami_meeting_lock import load_ami_meeting_corpus_lock
from yap_server.evaluation.ami_word_timeline import render_ami_scoring_reference
from tests.evaluation.ami_meeting_fixture import build_ami_meeting_fixture


class AmiMeetingCorpusTests(unittest.TestCase):
    def test_repository_lock_freezes_the_exact_non_promotional_meeting_inputs(self) -> None:
        lock = load_ami_meeting_corpus_lock(
            Path(__file__).resolve().parents[2] / "ami-meeting-comparator.lock.json"
        )

        self.assertEqual(lock.identity.release, "1.6.2")
        self.assertEqual(lock.identity.meeting_id, "ES2004a")
        self.assertEqual(lock.identity.language_bcp47, "en")
        self.assertFalse(lock.usage.promotion_eligible)
        self.assertEqual(lock.usage.exposure_status, "unknown")
        self.assertEqual(lock.annotations.member_count, 5_183)
        self.assertEqual(lock.annotations.uncompressed_bytes, 205_293_665)
        self.assertEqual(lock.audio.frame_count, 16_789_675)
        self.assertEqual(
            lock.annotations.artifact.sha256,
            "b56e5babb2496b8795deeeda7e71178d7fbc9963f94276cf2a3f4b56ebbc9f9d",
        )
        self.assertEqual(
            [
                member.word_element_count
                for member in lock.annotations.transcript_members
            ],
            [379, 1_260, 517, 979],
        )
        self.assertEqual(
            [condition.identifier for condition in lock.audio.conditions],
            ["close-mix", "far-field-array1-channel1"],
        )

    def test_inspection_verifies_audio_and_returns_no_transcript_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path, cache = build_ami_meeting_fixture(Path(temporary))
            lock = load_ami_meeting_corpus_lock(lock_path)

            inspection = inspect_ami_meeting_corpus(
                lock,
                environ={"YAP_EVAL_CACHE": str(cache)},
            )

        self.assertEqual(inspection.word_element_count, 4)
        self.assertEqual(inspection.vocal_sound_count, 1)
        self.assertEqual(inspection.disfluency_marker_count, 1)
        self.assertEqual(inspection.gap_count, 1)
        self.assertEqual(inspection.cross_speaker_overlap_word_count, 2)
        self.assertEqual(inspection.frame_count, 1_600)
        self.assertEqual(len(inspection.audio), 2)
        self.assertNotIn("Alpha", repr(inspection))
        self.assertNotIn("Bravo", repr(inspection))

    def test_timeline_preserves_words_events_and_deterministic_overlap_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path, cache = build_ami_meeting_fixture(Path(temporary))
            timeline = load_ami_word_timeline(
                load_ami_meeting_corpus_lock(lock_path),
                environ={"YAP_EVAL_CACHE": str(cache)},
            )

        self.assertEqual(
            [(word.agent_id, word.text) for word in timeline.merged_words],
            [("A", "Alpha"), ("B", "Bravo"), ("C", "Charlie"), ("D", ".")],
        )
        self.assertTrue(timeline.merged_words[-1].punctuation)
        self.assertTrue(timeline.merged_words[-2].truncated)
        self.assertEqual(
            timeline.flat_ordering_policy,
            "start-end-agent-source-ordinal-v1",
        )
        self.assertNotIn("Alpha", repr(timeline))
        self.assertNotIn("Alpha", repr(timeline.words[0]))
        self.assertEqual(
            render_ami_scoring_reference(timeline),
            "Alpha Bravo Charlie .",
        )

    def test_scoring_reference_requires_a_real_nonempty_timeline(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty timeline"):
            render_ami_scoring_reference(None)  # type: ignore[arg-type]

    def test_audio_loader_uses_the_existing_four_hour_pcm_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path, cache = build_ami_meeting_fixture(Path(temporary))
            audio = load_ami_condition_audio(
                load_ami_meeting_corpus_lock(lock_path),
                "close-mix",
                environ={"YAP_EVAL_CACHE": str(cache)},
            )

        self.assertEqual(audio.sample_rate, 16_000)
        self.assertEqual(audio.frame_count, 1_600)
        self.assertEqual(len(audio.pcm_bytes), 3_200)

    def test_changed_artifact_and_wrong_audio_shape_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path, cache = build_ami_meeting_fixture(Path(temporary))
            annotation = cache / "corpora/ami/1.6.2/ami_public_manual_1.6.2.zip"
            annotation.write_bytes(annotation.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "size"):
                load_ami_word_timeline(
                    load_ami_meeting_corpus_lock(lock_path),
                    environ={"YAP_EVAL_CACHE": str(cache)},
                )

        with tempfile.TemporaryDirectory() as temporary:
            lock_path, cache = build_ami_meeting_fixture(
                Path(temporary), audio_channels=2
            )
            with self.assertRaisesRegex(ValueError, "PCM contract"):
                load_ami_condition_audio(
                    load_ami_meeting_corpus_lock(lock_path),
                    "close-mix",
                    environ={"YAP_EVAL_CACHE": str(cache)},
                )

    def test_archive_path_escape_compression_bomb_and_active_xml_fail_closed(self) -> None:
        cases = (
            ({"unsafe_member": "../escape.xml"}, "member is unsafe"),
            ({"compression_bomb": True}, "compression ratio"),
            ({"unsafe_xml": True}, "declarations are unsafe"),
        )
        for options, message in cases:
            with self.subTest(options=options):
                with tempfile.TemporaryDirectory() as temporary:
                    lock_path, cache = build_ami_meeting_fixture(
                        Path(temporary), **options
                    )
                    with self.assertRaisesRegex(ValueError, message):
                        load_ami_word_timeline(
                            load_ami_meeting_corpus_lock(lock_path),
                            environ={"YAP_EVAL_CACHE": str(cache)},
                        )

    def test_lock_rejects_duplicate_keys_and_promotion_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path, _cache = build_ami_meeting_fixture(Path(temporary))
            body = lock_path.read_text(encoding="utf-8")
            duplicate = body.replace(
                '"schemaVersion": 1,',
                '"schemaVersion": 1, "schemaVersion": 1,',
                1,
            )
            lock_path.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                load_ami_meeting_corpus_lock(lock_path)

        with tempfile.TemporaryDirectory() as temporary:
            lock_path, _cache = build_ami_meeting_fixture(Path(temporary))
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
            payload["purpose"]["promotionEligible"] = True
            lock_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-promotional"):
                load_ami_meeting_corpus_lock(lock_path)

    def test_private_cache_is_mandatory_and_has_no_repository_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path, _cache = build_ami_meeting_fixture(Path(temporary))
            with self.assertRaisesRegex(ValueError, "YAP_EVAL_CACHE"):
                load_ami_word_timeline(
                    load_ami_meeting_corpus_lock(lock_path),
                    environ={},
                )


if __name__ == "__main__":
    unittest.main()
