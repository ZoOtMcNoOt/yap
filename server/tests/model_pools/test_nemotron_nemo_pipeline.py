from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest

from yap_server.pools.nemotron_nemo_pipeline import (
    NemotronNemoPipeline,
    _is_locked_streaming_profile,
    _validated_prompt_dictionary,
    _validated_runtime_file,
)


class _ContextManager:
    def __init__(self) -> None:
        self.streamidx2slotidx = {7: 0}

    def reset_slots(self, stream_ids: list[int], terminal: list[bool]) -> None:
        if terminal != [True]:
            raise AssertionError("terminal cleanup was not requested")
        for stream_id in stream_ids:
            self.streamidx2slotidx.pop(stream_id)


class _FeatureBuffer:
    def __init__(self) -> None:
        self.streamidx2slotidx = {7: 0}
        self.reset_slot_ids: list[int] = []

    def reset_slots(self, slot_ids: list[int]) -> None:
        self.reset_slot_ids.extend(slot_ids)

    def free_slots(self, slot_ids: list[int]) -> None:
        for stream_id, slot_id in tuple(self.streamidx2slotidx.items()):
            if slot_id in slot_ids:
                self.streamidx2slotidx.pop(stream_id)


class _Pipeline:
    def __init__(self) -> None:
        self._state_pool = {7: object()}
        self.context_manager = _ContextManager()
        self.bufferer = _FeatureBuffer()
        self.close_calls = 0

    def delete_state(self, stream_id: int) -> None:
        self._state_pool.pop(stream_id)

    def close_session(self) -> None:
        self.close_calls += 1


class _Scheduler:
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        if self.failure is not None:
            raise self.failure


class _Cuda:
    def __init__(self) -> None:
        self.empty_cache_calls = 0
        self.synchronize_calls = 0

    def empty_cache(self) -> None:
        self.empty_cache_calls += 1

    def synchronize(self) -> None:
        self.synchronize_calls += 1


class NemotronNemoPipelineTests(unittest.TestCase):
    def test_prompt_dictionary_accepts_aliases_but_bounds_integer_ids(self) -> None:
        self.assertEqual(
            _validated_prompt_dictionary(
                {"auto": 3, "en-US": 1, "en-GB": 1},
                num_prompts=4,
            ),
            {"auto": 3, "en-US": 1, "en-GB": 1},
        )
        for invalid, num_prompts in (
            ({"auto": False, "en-US": 1}, 2),
            ({"auto": 0, "en-US": 2}, 2),
            ({"en-US": 0}, 1),
            ({"auto": 0}, False),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(RuntimeError, "prompt catalog"):
                    _validated_prompt_dictionary(
                        invalid,
                        num_prompts=num_prompts,
                    )

    def test_runtime_files_must_be_absolute_canonical_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            checkpoint = root / "model.nemo"
            checkpoint.write_bytes(b"model")

            self.assertEqual(
                _validated_runtime_file(
                    checkpoint,
                    label="checkpoint",
                    suffix=".nemo",
                ),
                checkpoint,
            )
            with self.assertRaisesRegex(ValueError, "path is invalid"):
                _validated_runtime_file(
                    Path("model.nemo"),
                    label="checkpoint",
                    suffix=".nemo",
                )
            with self.assertRaisesRegex(ValueError, "path is invalid"):
                _validated_runtime_file(
                    checkpoint,
                    label="configuration",
                    suffix=".yaml",
                )

    def test_runtime_file_rejects_a_symbolic_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            checkpoint = root / "model.nemo"
            link = root / "linked.nemo"
            checkpoint.write_bytes(b"model")
            try:
                link.symlink_to(checkpoint)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            with self.assertRaisesRegex(ValueError, "canonical regular file"):
                _validated_runtime_file(
                    link,
                    label="checkpoint",
                    suffix=".nemo",
                )

    def test_locked_profile_rejects_cache_or_decoder_drift(self) -> None:
        profile = _locked_profile()
        self.assertTrue(_is_locked_streaming_profile(profile))

        profile.streaming.use_cache = False
        self.assertFalse(_is_locked_streaming_profile(profile))
        profile.streaming.use_cache = True
        profile.asr.decoding.greedy.use_cuda_graph_decoder = True
        self.assertFalse(_is_locked_streaming_profile(profile))

    def test_close_releases_every_stream_state_and_is_idempotent(self) -> None:
        pipeline = _Pipeline()
        scheduler = _Scheduler()
        cuda = _Cuda()
        runtime = _runtime(pipeline=pipeline, scheduler=scheduler, cuda=cuda)

        runtime.close()
        runtime.close()

        self.assertEqual(scheduler.close_calls, 1)
        self.assertEqual(pipeline.close_calls, 1)
        self.assertEqual(pipeline._state_pool, {})
        self.assertEqual(pipeline.context_manager.streamidx2slotidx, {})
        self.assertEqual(pipeline.bufferer.streamidx2slotidx, {})
        self.assertEqual(pipeline.bufferer.reset_slot_ids, [0])
        self.assertEqual(cuda.empty_cache_calls, 1)
        self.assertEqual(cuda.synchronize_calls, 1)
        self.assertIsNone(runtime._scheduler)
        self.assertIsNone(runtime._pipeline)

    def test_failed_shutdown_stays_failed_instead_of_claiming_success(self) -> None:
        failure = RuntimeError("synthetic shutdown failure")
        scheduler = _Scheduler(failure=failure)
        runtime = _runtime(
            pipeline=_Pipeline(),
            scheduler=scheduler,
            cuda=_Cuda(),
        )

        with self.assertRaisesRegex(RuntimeError, "synthetic shutdown failure"):
            runtime.close()
        with self.assertRaisesRegex(RuntimeError, "previously failed"):
            runtime.close()
        self.assertEqual(scheduler.close_calls, 1)


def _runtime(*, pipeline: _Pipeline, scheduler: _Scheduler, cuda: _Cuda):
    runtime = NemotronNemoPipeline.__new__(NemotronNemoPipeline)
    runtime._closed = threading.Event()
    runtime._close_lock = threading.Lock()
    runtime._close_error = None
    runtime._pipeline = pipeline
    runtime._scheduler = scheduler
    runtime._torch = SimpleNamespace(cuda=cuda)
    return runtime


def _locked_profile() -> SimpleNamespace:
    greedy = SimpleNamespace(
        use_cuda_graph_decoder=False,
        enable_per_stream_biasing=False,
        preserve_frame_confidence=False,
    )
    decoding = SimpleNamespace(
        strategy="greedy_batch",
        preserve_alignments=False,
        fused_batch_size=-1,
        greedy=greedy,
    )
    asr = SimpleNamespace(
        device="cuda",
        device_id=0,
        compute_dtype="bfloat16",
        use_amp=False,
        decoding=decoding,
    )
    streaming = SimpleNamespace(
        sample_rate=16_000,
        batch_size=8,
        num_slots=8,
        att_context_size=[56, 13],
        use_cache=True,
        use_feat_cache=True,
        chunk_size_in_secs=None,
        request_type="frame",
    )
    return SimpleNamespace(
        asr=asr,
        streaming=streaming,
        pipeline_type="cache_aware",
        asr_decoding_type="rnnt",
        matmul_precision="high",
        enable_itn=False,
        enable_nmt=False,
        asr_output_granularity="segment",
        return_tail_result=True,
    )


if __name__ == "__main__":
    unittest.main()
