from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from yap_server.pools.utterance_plan import (
    MAX_UTTERANCE_SAMPLES,
    SAMPLE_RATE_HZ,
    UtterancePlanSource,
    build_utterance_plan,
    publish_utterance_plan,
    read_utterance_plan,
)


_WAV_SHA256 = "a" * 64
_VAD_SHA256 = "b" * 64


class UtterancePlanTests(unittest.TestCase):
    def test_stage_fingerprint_binds_pcm_vad_and_partition_policy(self) -> None:
        baseline = UtterancePlanSource(
            input_sample_count=16_000,
            source_sample_count=16_000,
            vad_status="complete",
            vad_evidence_sha256="b" * 64,
            vad_intervals=((0, 8_000),),
        )
        changed_vad = UtterancePlanSource(
            input_sample_count=16_000,
            source_sample_count=16_000,
            vad_status="complete",
            vad_evidence_sha256="c" * 64,
            vad_intervals=((0, 8_000),),
        )

        self.assertEqual(
            baseline.input_fingerprint("d" * 64),
            baseline.input_fingerprint("d" * 64),
        )
        self.assertNotEqual(
            baseline.input_fingerprint("d" * 64),
            changed_vad.input_fingerprint("d" * 64),
        )
        self.assertNotEqual(
            baseline.input_fingerprint("d" * 64),
            baseline.input_fingerprint("e" * 64),
        )

    def test_vad_selects_safe_boundaries_without_dropping_source_audio(self) -> None:
        second = SAMPLE_RATE_HZ
        plan = build_utterance_plan(
            input_wav_sha256=_WAV_SHA256,
            input_sample_count=70 * second,
            source_sample_count=70 * second,
            vad_status="complete",
            vad_evidence_sha256=_VAD_SHA256,
            vad_intervals=(
                (0, 28 * second),
                (29 * second, 58 * second),
                (59 * second, 70 * second),
            ),
        )

        self.assertEqual(
            [window.boundary_reason for window in plan.utterances],
            ["vadSilence", "vadSilence", "endOfInput"],
        )
        self.assertEqual(plan.utterances[0].end_sample_exclusive, 28 * second + second // 2)
        self.assertEqual(plan.utterances[-1].end_sample_exclusive, 70 * second)
        self.assertTrue(
            all(
                previous.end_sample_exclusive == current.start_sample
                for previous, current in zip(plan.utterances, plan.utterances[1:])
            )
        )
        self.assertTrue(
            all(
                window.end_sample_exclusive - window.start_sample
                <= MAX_UTTERANCE_SAMPLES
                for window in plan.utterances
            )
        )

    def test_failed_vad_falls_back_to_a_complete_hard_bounded_partition(self) -> None:
        second = SAMPLE_RATE_HZ
        plan = build_utterance_plan(
            input_wav_sha256=_WAV_SHA256,
            input_sample_count=65 * second,
            source_sample_count=65 * second,
            vad_status="error",
            vad_evidence_sha256=_VAD_SHA256,
            vad_intervals=(),
        )

        self.assertEqual(
            [window.end_sample_exclusive for window in plan.utterances],
            [30 * second, 60 * second, 65 * second],
        )
        self.assertEqual(
            [window.boundary_reason for window in plan.utterances],
            ["maxDuration", "maxDuration", "endOfInput"],
        )

    def test_terminal_normalization_padding_remains_in_the_partition(self) -> None:
        plan = build_utterance_plan(
            input_wav_sha256=_WAV_SHA256,
            input_sample_count=16_015,
            source_sample_count=16_000,
            vad_status="complete",
            vad_evidence_sha256=_VAD_SHA256,
            vad_intervals=((0, 16_000),),
        )

        self.assertEqual(plan.utterances[0].start_sample, 0)
        self.assertEqual(plan.utterances[0].end_sample_exclusive, 16_015)

    def test_private_plan_is_hash_bound_to_the_checked_input_wav(self) -> None:
        plan = build_utterance_plan(
            input_wav_sha256=_WAV_SHA256,
            input_sample_count=16_000,
            source_sample_count=16_000,
            vad_status="complete",
            vad_evidence_sha256=_VAD_SHA256,
            vad_intervals=(),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "utterance-plan.json"
            digest = publish_utterance_plan(path, plan)

            loaded = read_utterance_plan(
                path,
                expected_sha256=digest,
                expected_input_wav_sha256=_WAV_SHA256,
                expected_input_sample_count=16_000,
            )
            self.assertEqual(loaded, plan)

            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "immutable identity"):
                read_utterance_plan(
                    path,
                    expected_sha256=digest,
                    expected_input_wav_sha256=_WAV_SHA256,
                    expected_input_sample_count=16_000,
                )

    def test_rejects_overlapping_or_failed_vad_intervals(self) -> None:
        for status, intervals in (
            ("complete", ((0, 1_000), (999, 2_000))),
            ("error", ((0, 1_000),)),
        ):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "source|interval"):
                    build_utterance_plan(
                        input_wav_sha256=_WAV_SHA256,
                        input_sample_count=16_000,
                        source_sample_count=16_000,
                        vad_status=status,
                        vad_evidence_sha256=_VAD_SHA256,
                        vad_intervals=intervals,
                    )


if __name__ == "__main__":
    unittest.main()
