from __future__ import annotations

import unittest

from yap_server.meeting_transcription.speaker_epoch_reconciliation import (
    EpochSpeaker,
    EpochTurn,
    SpeakerEpoch,
    reconcile_speaker_epochs,
)


def _speaker(
    local_id: str,
    embedding: tuple[float, ...] | None,
    *,
    speech_samples: int = 32_000,
) -> EpochSpeaker:
    return EpochSpeaker(
        local_speaker_id=local_id,
        embedding=embedding,
        clean_speech_sample_count=speech_samples,
    )


def _epoch(
    index: int,
    speakers: tuple[EpochSpeaker, ...],
) -> SpeakerEpoch:
    start = index * 480_000
    turns = tuple(
        EpochTurn(
            local_speaker_id=speaker.local_speaker_id,
            start_sample=start + offset * 16_000,
            end_sample=start + (offset + 1) * 16_000,
            text=f"epoch {index} speaker {offset}",
        )
        for offset, speaker in enumerate(speakers)
    )
    return SpeakerEpoch(
        end_sample=start + 480_000,
        index=index,
        speakers=speakers,
        start_sample=start,
        turns=turns,
    )


class SpeakerEpochReconciliationTests(unittest.TestCase):
    def test_subthreshold_embedding_cannot_establish_a_session_speaker(self) -> None:
        result = reconcile_speaker_epochs(
            (
                _epoch(
                    0,
                    (_speaker("SPEAKER_00", (1.0, 0.0), speech_samples=25_599),),
                ),
            )
        )

        self.assertEqual(result.session_speaker_ids, ())
        self.assertIsNone(result.turns[0].session_speaker_id)

        boundary = reconcile_speaker_epochs(
            (
                _epoch(
                    0,
                    (_speaker("SPEAKER_00", (1.0, 0.0), speech_samples=25_600),),
                ),
            )
        )
        self.assertEqual(boundary.session_speaker_ids, ("speaker-1",))
        self.assertEqual(boundary.turns[0].session_speaker_id, "speaker-1")

    def test_accepts_a_silent_epoch_without_speaker_state(self) -> None:
        result = reconcile_speaker_epochs(
            (
                SpeakerEpoch(
                    end_sample=16_000,
                    index=0,
                    speakers=(),
                    start_sample=0,
                    turns=(),
                ),
            )
        )

        self.assertEqual(result.session_speaker_ids, ())
        self.assertEqual(result.turns, ())

    def test_links_an_unambiguous_late_return_without_persisting_embeddings(
        self,
    ) -> None:
        result = reconcile_speaker_epochs(
            (
                _epoch(0, (_speaker("SPEAKER_00", (1.0, 0.0)),)),
                _epoch(1, (_speaker("SPEAKER_00", (0.0, 1.0)),)),
                _epoch(2, (_speaker("SPEAKER_00", (0.99, 0.01)),)),
            )
        )

        self.assertEqual(result.session_speaker_ids, ("speaker-1", "speaker-2"))
        self.assertEqual(
            [turn.session_speaker_id for turn in result.turns],
            ["speaker-1", "speaker-2", "speaker-1"],
        )
        self.assertNotIn("embedding", repr(result).lower())

    def test_never_merges_two_local_speakers_from_the_same_epoch(self) -> None:
        result = reconcile_speaker_epochs(
            (
                _epoch(0, (_speaker("SPEAKER_00", (1.0, 0.0)),)),
                _epoch(
                    1,
                    (
                        _speaker("SPEAKER_00", (1.0, 0.0)),
                        _speaker("SPEAKER_01", (1.0, 0.0)),
                    ),
                ),
            )
        )

        self.assertEqual(result.turns[1].session_speaker_id, "speaker-1")
        self.assertEqual(result.turns[2].session_speaker_id, "speaker-2")

    def test_ambiguous_or_weak_unmatched_evidence_is_not_forced(self) -> None:
        result = reconcile_speaker_epochs(
            (
                _epoch(
                    0,
                    (
                        _speaker("SPEAKER_00", (1.0, 0.0)),
                        _speaker("SPEAKER_01", (0.98, 0.2)),
                    ),
                ),
                _epoch(1, (_speaker("SPEAKER_00", (0.995, 0.1)),)),
                _epoch(
                    2,
                    (_speaker("SPEAKER_00", None, speech_samples=8_000),),
                ),
            )
        )

        self.assertEqual(result.turns[2].session_speaker_id, "speaker-3")
        self.assertIsNone(result.turns[3].session_speaker_id)
        self.assertEqual(result.unknown_turn_count, 1)

    def test_supports_the_32_speaker_target_and_fails_closed_at_64(self) -> None:
        target = reconcile_speaker_epochs(
            tuple(
                _epoch(
                    index,
                    (_speaker("SPEAKER_00", (float(index + 1), 1.0)),),
                )
                for index in range(32)
            ),
            similarity_threshold=1.0,
        )
        self.assertEqual(len(target.session_speaker_ids), 32)
        self.assertFalse(target.session_speaker_ceiling_reached)

        exact_ceiling = reconcile_speaker_epochs(
            tuple(
                _epoch(
                    index,
                    (_speaker("SPEAKER_00", (float(index + 1), 1.0)),),
                )
                for index in range(64)
            ),
            similarity_threshold=1.0,
        )
        self.assertEqual(len(exact_ceiling.session_speaker_ids), 64)
        self.assertTrue(exact_ceiling.session_speaker_ceiling_reached)

        ceiling = reconcile_speaker_epochs(
            tuple(
                _epoch(
                    index,
                    (_speaker("SPEAKER_00", (float(index + 1), 1.0)),),
                )
                for index in range(65)
            ),
            similarity_threshold=1.0,
        )
        self.assertEqual(len(ceiling.session_speaker_ids), 64)
        self.assertTrue(ceiling.session_speaker_ceiling_reached)
        self.assertIsNone(ceiling.turns[-1].session_speaker_id)

    def test_rejects_overlapping_epoch_bounds_and_non_finite_embeddings(self) -> None:
        first = _epoch(0, (_speaker("SPEAKER_00", (1.0, 0.0)),))
        overlapping = SpeakerEpoch(
            end_sample=first.end_sample + 480_000,
            index=1,
            speakers=(_speaker("SPEAKER_00", (0.0, 1.0)),),
            start_sample=first.end_sample - 1,
            turns=(
                EpochTurn(
                    end_sample=first.end_sample + 16_000,
                    local_speaker_id="SPEAKER_00",
                    start_sample=first.end_sample,
                    text="overlap",
                ),
            ),
        )
        with self.assertRaisesRegex(ValueError, "epoch bounds"):
            reconcile_speaker_epochs((first, overlapping))

        invalid = _epoch(0, (_speaker("SPEAKER_00", (float("nan"), 0.0)),))
        with self.assertRaisesRegex(ValueError, "embedding"):
            reconcile_speaker_epochs((invalid,))


if __name__ == "__main__":
    unittest.main()
