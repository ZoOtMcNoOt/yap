from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import gc
import logging
import stat
import threading
import time

from yap_server.pools.nemo_stream_scheduler import (
    NemoStreamScheduler,
    ScheduledTranscript,
)


NEMOTRON_STREAMING_ATTENTION_CONTEXT = (56, 13)
NEMOTRON_STREAMING_CHUNK_SECONDS = 1.12
NEMOTRON_STREAMING_MAX_STREAMS = 8


@dataclass(frozen=True, slots=True)
class NemotronNemoRuntimeResult:
    raw_transcript: str
    inference_ms: int
    inference_steps: int
    max_batch_size: int
    queue_ms: int
    total_ms: int


class NemotronNemoPipeline:
    """Resident prompt-aware NeMo pipeline with one bounded GPU scheduler."""

    def __init__(self, *, checkpoint: Path, config_path: Path) -> None:
        checkpoint = _validated_runtime_file(
            checkpoint,
            label="Nemotron NeMo checkpoint",
            suffix=".nemo",
        )
        config_path = _validated_runtime_file(
            config_path,
            label="Nemotron NeMo streaming configuration",
            suffix=".yaml",
        )
        from nemo.utils import logging as nemo_logging
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("Nemotron NeMo streaming requires an NVIDIA GPU")
        nemo_logging.setLevel(logging.ERROR)
        torch.set_grad_enabled(False)

        loaded_at = time.monotonic()
        pipeline = _build_prompted_pipeline(
            checkpoint=checkpoint,
            config_path=config_path,
            torch_module=torch,
        )
        torch.cuda.synchronize()
        self._model_load_ms = round((time.monotonic() - loaded_at) * 1_000)
        self._torch = torch
        self._pipeline = pipeline
        self._closed = threading.Event()
        self._close_lock = threading.Lock()
        self._close_error: BaseException | None = None

        model = pipeline.asr_model.asr_model
        model_defaults = getattr(model.cfg, "model_defaults", None)
        prompts = getattr(model_defaults, "prompt_dictionary", None)
        num_prompts = getattr(model_defaults, "num_prompts", None)
        self._prompt_dictionary = _validated_prompt_dictionary(
            prompts,
            num_prompts=num_prompts,
        )
        self._dtype = str(next(model.parameters()).dtype).removeprefix("torch.")
        self._scheduler = NemoStreamScheduler(
            pipeline=pipeline,
            stream_factory=self._stream_factory,
            release_stream=self._release_stream,
            max_streams=NEMOTRON_STREAMING_MAX_STREAMS,
        )

    @property
    def model_load_ms(self) -> int:
        return self._model_load_ms

    @property
    def prompt_dictionary(self) -> Mapping[str, int]:
        return dict(self._prompt_dictionary)

    @property
    def dtype(self) -> str:
        return self._dtype

    @property
    def device_name(self) -> str:
        return str(self._torch.cuda.get_device_name(0))

    @property
    def compute_capability(self) -> tuple[int, int]:
        return tuple(self._torch.cuda.get_device_capability(0))

    @property
    def torch_version(self) -> str:
        return str(self._torch.__version__)

    @property
    def torch_cuda_version(self) -> str:
        return str(self._torch.version.cuda)

    def memory_payload(self) -> dict[str, int]:
        return {
            "allocatedMiB": round(self._torch.cuda.memory_allocated() / 1024 / 1024),
            "reservedMiB": round(self._torch.cuda.memory_reserved() / 1024 / 1024),
            "peakAllocatedMiB": round(
                self._torch.cuda.max_memory_allocated() / 1024 / 1024
            ),
            "peakReservedMiB": round(
                self._torch.cuda.max_memory_reserved() / 1024 / 1024
            ),
        }

    def transcribe(
        self,
        *,
        pcm_bytes: bytes,
        language: str,
        cancelled: Callable[[], bool] | None = None,
    ) -> NemotronNemoRuntimeResult:
        scheduler = self._scheduler
        if self._closed.is_set() or scheduler is None:
            raise RuntimeError("Nemotron NeMo pipeline is closed")
        if (
            not isinstance(pcm_bytes, bytes)
            or not pcm_bytes
            or len(pcm_bytes) % 2 != 0
        ):
            raise ValueError("Nemotron NeMo input must be non-empty PCM16 bytes")
        if language not in self._prompt_dictionary:
            raise ValueError("Nemotron NeMo language is absent from the prompt catalog")
        result: ScheduledTranscript = scheduler.transcribe(
            pcm_bytes=pcm_bytes,
            language=language,
            cancelled=cancelled,
        )
        return NemotronNemoRuntimeResult(
            raw_transcript=result.raw_transcript,
            inference_ms=result.inference_ms,
            inference_steps=result.inference_steps,
            max_batch_size=result.max_batch_size,
            queue_ms=result.queue_ms,
            total_ms=result.total_ms,
        )

    def close(self) -> None:
        with self._close_lock:
            if self._closed.is_set():
                if self._close_error is not None:
                    raise RuntimeError(
                        "Nemotron NeMo pipeline shutdown previously failed"
                    ) from self._close_error
                return
            self._closed.set()
            scheduler = self._scheduler
            pipeline = self._pipeline
            try:
                scheduler.close()
                for stream_id in _resident_stream_ids(pipeline):
                    self._release_stream(stream_id)
                remaining_stream_ids = _resident_stream_ids(pipeline)
                if remaining_stream_ids:
                    raise RuntimeError(
                        "Nemotron NeMo pipeline retained stream state during shutdown"
                    )
                pipeline.close_session()
                self._scheduler = None
                self._pipeline = None
                del scheduler
                del pipeline
                gc.collect()
                self._torch.cuda.empty_cache()
                self._torch.cuda.synchronize()
            except BaseException as error:
                self._close_error = error
                raise

    def _stream_factory(self, pcm_bytes: bytes, language: str, stream_id: int):
        from nemo.collections.asr.inference.streaming.framing.mono_stream import (
            MonoStream,
        )
        from nemo.collections.asr.inference.streaming.framing.request_options import (
            ASRRequestOptions,
        )

        samples = self._torch.frombuffer(
            bytearray(pcm_bytes),
            dtype=self._torch.int16,
        ).to(self._torch.float32)
        samples.div_(32_768.0)
        stream = MonoStream(
            rate=16_000,
            frame_size_in_secs=NEMOTRON_STREAMING_CHUNK_SECONDS,
            stream_id=stream_id,
            pad_last_frame=True,
        )
        stream.load_audio(samples, ASRRequestOptions(language_code=language))
        return iter(stream)

    def _release_stream(self, stream_id: int) -> None:
        pipeline = self._pipeline
        if pipeline is None:
            return
        context_manager = pipeline.context_manager
        if stream_id in context_manager.streamidx2slotidx:
            context_manager.reset_slots([stream_id], [True])
        bufferer = pipeline.bufferer
        slot_id = bufferer.streamidx2slotidx.get(stream_id)
        if slot_id is not None:
            bufferer.reset_slots([slot_id])
            bufferer.free_slots([slot_id])
        if stream_id in pipeline._state_pool:
            pipeline.delete_state(stream_id)


def _validated_runtime_file(path: Path, *, label: str, suffix: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.suffix != suffix:
        raise ValueError(f"{label} path is invalid")
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{label} is missing") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or resolved != path
    ):
        raise ValueError(f"{label} must be a canonical regular file")
    return path


def _validated_prompt_dictionary(
    prompts: object,
    *,
    num_prompts: object,
) -> dict[str, int]:
    if (
        not isinstance(prompts, Mapping)
        or not prompts
        or len(prompts) > 512
        or not isinstance(num_prompts, int)
        or isinstance(num_prompts, bool)
        or not 1 <= num_prompts <= 512
    ):
        raise RuntimeError("Nemotron NeMo prompt catalog is invalid")
    validated: dict[str, int] = {}
    for language, prompt_id in prompts.items():
        if (
            not isinstance(language, str)
            or not language
            or len(language) > 64
            or not isinstance(prompt_id, int)
            or isinstance(prompt_id, bool)
            or not 0 <= prompt_id < num_prompts
        ):
            raise RuntimeError("Nemotron NeMo prompt catalog is invalid")
        validated[language] = prompt_id
    if "auto" not in validated:
        raise RuntimeError("Nemotron NeMo prompt catalog is invalid")
    return validated


def _resident_stream_ids(pipeline) -> set[int]:
    stream_ids = set(pipeline._state_pool)
    stream_ids.update(pipeline.context_manager.streamidx2slotidx)
    stream_ids.update(pipeline.bufferer.streamidx2slotidx)
    return stream_ids


def _build_prompted_pipeline(*, checkpoint: Path, config_path: Path, torch_module):
    from nemo.collections.asr.inference.factory.cache_aware_pipeline_builder import (
        CacheAwarePipelineBuilder,
    )
    from nemo.collections.asr.inference.factory.pipeline_builder import PipelineBuilder
    from nemo.collections.asr.inference.model_wrappers.cache_aware_rnnt_inference_wrapper import (
        CacheAwareRNNTInferenceWrapper,
    )
    from nemo.collections.asr.inference.pipelines.cache_aware_rnnt_pipeline import (
        CacheAwareRNNTPipeline,
    )
    from omegaconf import OmegaConf, open_dict

    class PerStreamPromptCacheAwareRnntWrapper(CacheAwareRNNTInferenceWrapper):
        """Correct NeMo's dropped per-stream prompt vector at decode input."""

        def execute_step(
            self,
            processed_signal,
            processed_signal_length,
            context,
            previous_hypotheses,
            drop_extra_pre_encoded,
            keep_all_outputs,
            drop_left_context=None,
            valid_out_len=None,
            prompt_vectors=None,
        ):
            encoded, encoded_len, new_context = self.encoder_step(
                processed_signal=processed_signal,
                processed_signal_length=processed_signal_length,
                context=context,
                drop_extra_pre_encoded=drop_extra_pre_encoded,
                keep_all_outputs=keep_all_outputs,
                drop_left_context=drop_left_context,
                valid_out_len=valid_out_len,
            )
            if getattr(self.asr_model, "concat", False):
                if prompt_vectors is None:
                    raise RuntimeError(
                        "prompt-conditioned NeMo stream omitted its per-stream prompt"
                    )
                encoded = encoded.transpose(1, 2)
                batch_size, time_steps, _encoded_size = encoded.shape
                prompt_count = int(self.asr_model.cfg.model_defaults.num_prompts)
                if (
                    prompt_vectors.ndim != 2
                    or prompt_vectors.shape[0] != batch_size
                    or prompt_vectors.shape[1] != prompt_count
                ):
                    raise RuntimeError(
                        "prompt-conditioned NeMo stream received misaligned prompts"
                    )
                prompts = prompt_vectors.to(
                    device=encoded.device,
                    dtype=encoded.dtype,
                ).unsqueeze(1)
                prompts = prompts.expand(batch_size, time_steps, -1)
                encoded_dtype = encoded.dtype
                encoded = self.asr_model.prompt_kernel(
                    torch_module.cat([encoded, prompts], dim=-1)
                ).to(encoded_dtype)
                encoded = encoded.transpose(1, 2)
            hypotheses = self.asr_model.decoding.rnnt_decoder_predictions_tensor(
                encoded,
                encoded_len,
                return_hypotheses=True,
                partial_hypotheses=previous_hypotheses,
            )
            return hypotheses, new_context

    cfg = OmegaConf.load(config_path)
    with open_dict(cfg):
        cfg.asr.model_name = str(checkpoint)
    if not _is_locked_streaming_profile(cfg):
        raise RuntimeError("Nemotron NeMo streaming configuration is not the locked profile")

    PipelineBuilder.set_log_level(cfg.log_level)
    PipelineBuilder.set_matmul_precision(cfg.matmul_precision)
    decoding_cfg = CacheAwarePipelineBuilder.get_rnnt_decoding_cfg(cfg)
    wrapper = PerStreamPromptCacheAwareRnntWrapper(
        model_name=str(checkpoint),
        decoding_cfg=decoding_cfg,
        device=cfg.asr.device,
        device_id=cfg.asr.device_id,
        compute_dtype=cfg.asr.compute_dtype,
        use_amp=cfg.asr.use_amp,
    )
    pipeline = CacheAwareRNNTPipeline(cfg, wrapper)
    if not pipeline.prompt_enabled:
        raise RuntimeError("Nemotron NeMo checkpoint is not prompt-conditioned")
    if (
        tuple(wrapper.asr_model.encoder.att_context_size)
        != NEMOTRON_STREAMING_ATTENTION_CONTEXT
    ):
        raise RuntimeError("Nemotron NeMo attention context differs from the locked profile")
    if abs(pipeline.chunk_size_in_secs - NEMOTRON_STREAMING_CHUNK_SECONDS) > 1e-9:
        raise RuntimeError("Nemotron NeMo chunk duration differs from the locked profile")
    pipeline.open_session()
    return pipeline


def _is_locked_streaming_profile(cfg) -> bool:
    decoding = cfg.asr.decoding
    greedy = decoding.greedy
    streaming = cfg.streaming
    return (
        cfg.asr.device == "cuda"
        and cfg.asr.device_id == 0
        and cfg.asr.compute_dtype == "bfloat16"
        and not cfg.asr.use_amp
        and decoding.strategy == "greedy_batch"
        and not decoding.preserve_alignments
        and decoding.fused_batch_size == -1
        and not greedy.use_cuda_graph_decoder
        and not greedy.enable_per_stream_biasing
        and not greedy.preserve_frame_confidence
        and cfg.pipeline_type == "cache_aware"
        and cfg.asr_decoding_type == "rnnt"
        and streaming.sample_rate == 16_000
        and streaming.batch_size == NEMOTRON_STREAMING_MAX_STREAMS
        and streaming.num_slots == NEMOTRON_STREAMING_MAX_STREAMS
        and tuple(streaming.att_context_size)
        == NEMOTRON_STREAMING_ATTENTION_CONTEXT
        and streaming.use_cache
        and streaming.use_feat_cache
        and streaming.chunk_size_in_secs is None
        and streaming.request_type == "frame"
        and cfg.matmul_precision == "high"
        and not cfg.enable_itn
        and not cfg.enable_nmt
        and cfg.asr_output_granularity == "segment"
        and cfg.return_tail_result
    )
