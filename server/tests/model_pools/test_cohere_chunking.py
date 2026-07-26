from __future__ import annotations

import unittest

import numpy as np

from yap_server.pools.cohere_chunking import energy_chunk_ranges
from yap_server.pools.cohere_engine import _decoded_text


class CohereChunkingTests(unittest.TestCase):
    def test_partitions_long_pcm_with_the_checked_energy_boundary_policy(self) -> None:
        samples = np.zeros(70 * 16_000, dtype="<i2")

        ranges = energy_chunk_ranges(
            samples,
            chunk_frames=35 * 16_000,
            boundary_context_frames=5 * 16_000,
            energy_window_frames=1_600,
        )

        self.assertEqual(
            ranges,
            (
                (0, 30 * 16_000),
                (30 * 16_000, 60 * 16_000),
                (60 * 16_000, 70 * 16_000),
            ),
        )

    def test_prefers_the_first_quietest_window_near_the_chunk_boundary(self) -> None:
        samples = np.full(70 * 16_000, 2_000, dtype="<i2")
        quiet_start = 33 * 16_000
        samples[quiet_start : quiet_start + 1_600] = 0

        ranges = energy_chunk_ranges(
            samples,
            chunk_frames=35 * 16_000,
            boundary_context_frames=5 * 16_000,
            energy_window_frames=1_600,
        )

        self.assertEqual(ranges[0], (0, quiet_start))
        self.assertEqual(ranges[-1][1], len(samples))
        self.assertTrue(
            all(ranges[index - 1][1] == start for index, (start, _end) in enumerate(ranges) if index)
        )

    def test_rejects_invalid_pcm_and_limits(self) -> None:
        with self.assertRaises(ValueError):
            energy_chunk_ranges(
                np.zeros((2, 2), dtype="<i2"),
                chunk_frames=10,
                boundary_context_frames=2,
                energy_window_frames=1,
            )
        with self.assertRaises(ValueError):
            energy_chunk_ranges(
                np.zeros(10, dtype="<i2"),
                chunk_frames=10,
                boundary_context_frames=10,
                energy_window_frames=1,
            )

    def test_decoder_canonicalizes_a_successful_empty_transcript(self) -> None:
        self.assertEqual(_decoded_text(""), "")
        self.assertEqual(_decoded_text("  \n  "), "")
        self.assertEqual(_decoded_text(" hello   world "), "hello world")


if __name__ == "__main__":
    unittest.main()
