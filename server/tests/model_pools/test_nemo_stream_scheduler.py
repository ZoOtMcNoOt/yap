from __future__ import annotations

from dataclasses import dataclass
import threading
import unittest

from yap_server.pools.nemo_stream_scheduler import (
    NemoStreamCancelled,
    NemoStreamCapacityExceeded,
    NemoStreamProtocolError,
    NemoStreamRuntimeFenced,
    NemoStreamScheduler,
)


@dataclass(frozen=True, slots=True)
class _Frame:
    stream_id: int
    is_last: bool
    label: str


@dataclass(frozen=True, slots=True)
class _Output:
    stream_id: int
    final_transcript: str


class _Pipeline:
    def __init__(self) -> None:
        self.batches: list[tuple[int, ...]] = []
        self.entered = threading.Event()
        self.resume = threading.Event()
        self.block = False
        self.fail = False
        self.duplicate_outputs = False
        self.stream_ids_by_label: dict[str, int] = {}

    def transcribe_step(self, requests: list[_Frame]) -> list[_Output]:
        self.batches.append(tuple(frame.stream_id for frame in requests))
        self.stream_ids_by_label.update(
            (frame.label, frame.stream_id) for frame in requests
        )
        self.entered.set()
        if self.block:
            self.resume.wait(timeout=2)
        if self.fail:
            raise RuntimeError("synthetic pipeline failure")
        if self.duplicate_outputs and len(requests) > 1:
            return [
                _Output(
                    stream_id=requests[0].stream_id,
                    final_transcript=frame.label if frame.is_last else "",
                )
                for frame in requests
            ]
        return [
            _Output(
                stream_id=frame.stream_id,
                final_transcript=frame.label if frame.is_last else "",
            )
            for frame in requests
        ]


class _Fixture:
    def __init__(self, *, max_streams: int = 2) -> None:
        self.pipeline = _Pipeline()
        self.released: list[int] = []
        self.release_failures: set[int] = set()
        self.scheduler = NemoStreamScheduler(
            pipeline=self.pipeline,
            stream_factory=self._stream,
            release_stream=self._release,
            max_streams=max_streams,
            batch_window_seconds=0.05,
            shutdown_timeout_seconds=2,
        )

    @staticmethod
    def _stream(
        pcm_bytes: bytes,
        _language: str,
        stream_id: int,
    ):
        label = pcm_bytes.decode("ascii")
        for index in range(2):
            yield [
                _Frame(
                    stream_id=stream_id,
                    is_last=index == 1,
                    label=label,
                )
            ]

    def _release(self, stream_id: int) -> None:
        self.released.append(stream_id)
        if stream_id in self.release_failures:
            raise RuntimeError("synthetic cleanup failure")

    def close(self) -> None:
        self.pipeline.resume.set()
        self.scheduler.close()


class NemoStreamSchedulerTests(unittest.TestCase):
    def test_batches_concurrent_streams_without_crossing_results(self) -> None:
        fixture = _Fixture()
        barrier = threading.Barrier(3)
        results: dict[str, str] = {}

        def run(label: str) -> None:
            barrier.wait()
            results[label] = fixture.scheduler.transcribe(
                pcm_bytes=label.encode("ascii"),
                language="en-US",
            ).raw_transcript

        threads = [
            threading.Thread(target=run, args=(label,))
            for label in ("alpha", "bravo")
        ]
        try:
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=2)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(results, {"alpha": "alpha", "bravo": "bravo"})
            self.assertTrue(any(len(batch) == 2 for batch in fixture.pipeline.batches))
        finally:
            fixture.close()

    def test_cancellation_releases_only_the_target_and_sibling_completes(self) -> None:
        fixture = _Fixture()
        fixture.pipeline.block = True
        cancelled = threading.Event()
        outcomes: dict[str, object] = {}
        barrier = threading.Barrier(3)

        def run(label: str, cancellation: threading.Event | None) -> None:
            barrier.wait()
            try:
                outcomes[label] = fixture.scheduler.transcribe(
                    pcm_bytes=label.encode("ascii"),
                    language="en-US",
                    cancelled=(cancellation.is_set if cancellation else None),
                ).raw_transcript
            except BaseException as error:
                outcomes[label] = error

        threads = [
            threading.Thread(target=run, args=("cancel", cancelled)),
            threading.Thread(target=run, args=("sibling", None)),
        ]
        try:
            for thread in threads:
                thread.start()
            barrier.wait()
            self.assertTrue(fixture.pipeline.entered.wait(timeout=1))
            cancelled.set()
            fixture.pipeline.resume.set()
            for thread in threads:
                thread.join(timeout=2)

            self.assertIsInstance(outcomes["cancel"], NemoStreamCancelled)
            self.assertEqual(outcomes["sibling"], "sibling")
            self.assertEqual(len(fixture.released), 2)
            self.assertEqual(len(set(fixture.released)), 2)
        finally:
            fixture.close()

    def test_admission_is_bounded_while_one_stream_is_active(self) -> None:
        fixture = _Fixture(max_streams=1)
        fixture.pipeline.block = True
        outcome: list[object] = []

        def run_first() -> None:
            try:
                outcome.append(
                    fixture.scheduler.transcribe(
                        pcm_bytes=b"first",
                        language="en-US",
                    )
                )
            except BaseException as error:
                outcome.append(error)

        thread = threading.Thread(target=run_first)
        try:
            thread.start()
            self.assertTrue(fixture.pipeline.entered.wait(timeout=1))
            with self.assertRaisesRegex(NemoStreamCapacityExceeded, "admission"):
                fixture.scheduler.transcribe(
                    pcm_bytes=b"second",
                    language="en-US",
                )
            fixture.pipeline.resume.set()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(outcome), 1)
        finally:
            fixture.close()

    def test_pipeline_failure_fences_future_admission_and_cleans_active_streams(
        self,
    ) -> None:
        fixture = _Fixture(max_streams=1)
        fixture.pipeline.fail = True
        try:
            with self.assertRaisesRegex(NemoStreamRuntimeFenced, "pipeline failed"):
                fixture.scheduler.transcribe(
                    pcm_bytes=b"failed",
                    language="en-US",
                )
            with self.assertRaisesRegex(NemoStreamRuntimeFenced, "fenced"):
                fixture.scheduler.transcribe(
                    pcm_bytes=b"later",
                    language="en-US",
                )
            self.assertEqual(len(fixture.released), 1)
        finally:
            fixture.close()

    def test_framing_failure_is_isolated_and_the_runtime_recovers(self) -> None:
        fixture = _Fixture(max_streams=1)

        def malformed_stream(
            pcm_bytes: bytes,
            _language: str,
            stream_id: int,
        ):
            label = pcm_bytes.decode("ascii")
            if label == "malformed":
                yield [_Frame(stream_id=stream_id, is_last=False, label="")]
                raise ValueError(label)
            for index in range(2):
                yield [
                    _Frame(
                        stream_id=stream_id,
                        is_last=index == 1,
                        label=label,
                    )
                ]

        fixture.scheduler.close()
        fixture.scheduler = NemoStreamScheduler(
            pipeline=fixture.pipeline,
            stream_factory=malformed_stream,
            release_stream=fixture._release,
            max_streams=1,
            batch_window_seconds=0,
            shutdown_timeout_seconds=2,
        )
        try:
            with self.assertRaisesRegex(NemoStreamProtocolError, "framing failed"):
                fixture.scheduler.transcribe(
                    pcm_bytes=b"malformed",
                    language="en-US",
                )

            recovered = fixture.scheduler.transcribe(
                pcm_bytes=b"recovered",
                language="en-US",
            )
            self.assertEqual(recovered.raw_transcript, "recovered")
        finally:
            fixture.close()

    def test_cancellation_callback_failure_cancels_only_its_stream(self) -> None:
        fixture = _Fixture(max_streams=1)
        cancellation_checks = 0

        def broken_cancellation_callback() -> bool:
            nonlocal cancellation_checks
            cancellation_checks += 1
            if cancellation_checks >= 3:
                raise RuntimeError("synthetic callback failure")
            return False

        try:
            with self.assertRaises(NemoStreamCancelled):
                fixture.scheduler.transcribe(
                    pcm_bytes=b"cancelled",
                    language="en-US",
                    cancelled=broken_cancellation_callback,
                )
            recovered = fixture.scheduler.transcribe(
                pcm_bytes=b"recovered",
                language="en-US",
            )
            self.assertEqual(recovered.raw_transcript, "recovered")
        finally:
            fixture.close()

    def test_cleanup_failure_fences_a_sibling_and_future_admission(self) -> None:
        fixture = _Fixture(max_streams=2)
        fixture.pipeline.block = True
        cancelled = threading.Event()
        outcomes: dict[str, object] = {}
        barrier = threading.Barrier(3)

        def run(label: str, cancellation: threading.Event | None) -> None:
            barrier.wait()
            try:
                outcomes[label] = fixture.scheduler.transcribe(
                    pcm_bytes=label.encode("ascii"),
                    language="en-US",
                    cancelled=(cancellation.is_set if cancellation else None),
                )
            except BaseException as error:
                outcomes[label] = error

        threads = [
            threading.Thread(target=run, args=("cleanup", cancelled)),
            threading.Thread(target=run, args=("sibling", None)),
        ]
        try:
            for thread in threads:
                thread.start()
            barrier.wait()
            self.assertTrue(fixture.pipeline.entered.wait(timeout=1))
            cleanup_stream_id = fixture.pipeline.stream_ids_by_label["cleanup"]
            fixture.release_failures.add(cleanup_stream_id)
            cancelled.set()
            fixture.pipeline.resume.set()
            for thread in threads:
                thread.join(timeout=2)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertIsInstance(outcomes["cleanup"], NemoStreamRuntimeFenced)
            self.assertIsInstance(outcomes["sibling"], NemoStreamRuntimeFenced)
            with self.assertRaisesRegex(NemoStreamRuntimeFenced, "fenced"):
                fixture.scheduler.transcribe(
                    pcm_bytes=b"later",
                    language="en-US",
                )
        finally:
            fixture.close()

    def test_duplicate_pipeline_output_identities_fence_every_stream(self) -> None:
        fixture = _Fixture(max_streams=2)
        fixture.pipeline.duplicate_outputs = True
        outcomes: list[BaseException] = []
        barrier = threading.Barrier(3)

        def run(label: str) -> None:
            barrier.wait()
            try:
                fixture.scheduler.transcribe(
                    pcm_bytes=label.encode("ascii"),
                    language="en-US",
                )
            except BaseException as error:
                outcomes.append(error)

        threads = [threading.Thread(target=run, args=(label,)) for label in ("a", "b")]
        try:
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=2)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(outcomes), 2)
            self.assertTrue(
                all(isinstance(error, NemoStreamRuntimeFenced) for error in outcomes)
            )
            self.assertEqual(len(fixture.released), 2)
        finally:
            fixture.close()

    def test_close_during_an_active_step_unblocks_the_caller(self) -> None:
        fixture = _Fixture(max_streams=1)
        fixture.pipeline.block = True
        outcomes: list[BaseException] = []

        def transcribe() -> None:
            try:
                fixture.scheduler.transcribe(
                    pcm_bytes=b"active",
                    language="en-US",
                )
            except BaseException as error:
                outcomes.append(error)

        worker = threading.Thread(target=transcribe)
        closer = threading.Thread(target=fixture.scheduler.close)
        try:
            worker.start()
            self.assertTrue(fixture.pipeline.entered.wait(timeout=1))
            closer.start()
            fixture.pipeline.resume.set()
            worker.join(timeout=2)
            closer.join(timeout=2)

            self.assertFalse(worker.is_alive())
            self.assertFalse(closer.is_alive())
            self.assertEqual(len(outcomes), 1)
            self.assertIsInstance(outcomes[0], NemoStreamCancelled)
            with self.assertRaisesRegex(NemoStreamRuntimeFenced, "closed"):
                fixture.scheduler.transcribe(
                    pcm_bytes=b"late",
                    language="en-US",
                )
        finally:
            fixture.close()

    def test_eight_admitted_streams_share_one_gpu_step(self) -> None:
        fixture = _Fixture(max_streams=8)
        barrier = threading.Barrier(9)
        results: dict[str, str] = {}

        def run(label: str) -> None:
            barrier.wait()
            results[label] = fixture.scheduler.transcribe(
                pcm_bytes=label.encode("ascii"),
                language="en-US",
            ).raw_transcript

        labels = tuple(f"s{index}" for index in range(8))
        threads = [threading.Thread(target=run, args=(label,)) for label in labels]
        try:
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=2)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(results, {label: label for label in labels})
            self.assertTrue(any(len(batch) == 8 for batch in fixture.pipeline.batches))
        finally:
            fixture.close()

    def test_close_is_idempotent_and_rejects_new_work(self) -> None:
        fixture = _Fixture(max_streams=1)
        fixture.close()
        fixture.scheduler.close()

        with self.assertRaisesRegex(NemoStreamRuntimeFenced, "closed"):
            fixture.scheduler.transcribe(
                pcm_bytes=b"late",
                language="en-US",
            )


if __name__ == "__main__":
    unittest.main()
