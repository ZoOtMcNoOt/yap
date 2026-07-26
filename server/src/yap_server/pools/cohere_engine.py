from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version as package_version
import json
from pathlib import Path
import sys
import time
from typing import Callable, cast

from yap_server.alignment_contract import (
    MAX_ALIGNMENT_WORDS,
    AlignedWordEvidence,
    AlignmentUnavailable,
    AlignmentUnavailableReason,
    available_alignment,
    unavailable_alignment,
)
from yap_server.limits import MAX_WORKER_RESULT_BYTES
from yap_server.pools.cohere_alignment import (
    ALIGNMENT_MEDIAN_FILTER_WIDTH,
    ALIGNMENT_SELECTED_HEADS,
    MAX_ALIGNMENT_MATRIX_TOKENS,
    MAX_ALIGNMENT_TOKENS,
    align_cohere_word_scores,
    valid_encoder_frame_count,
)
from yap_server.pools.model_lock import ModelPoolLock
from yap_server.pools.pcm_audio import PcmAudio


MAX_ENGINE_BATCH_SIZE = 8


@dataclass(frozen=True, slots=True)
class CohereAsrInput:
    job_id: str
    audio: PcmAudio
    language: str
    punctuation: bool


@dataclass(frozen=True, slots=True)
class _ChunkPlan:
    request_index: int
    chunk_index: int
    start_frame: int
    end_frame: int


@dataclass(frozen=True, slots=True)
class _ChunkAlignment:
    words: tuple[AlignedWordEvidence, ...]
    unavailable_reason: AlignmentUnavailableReason | None


@dataclass(frozen=True, slots=True)
class _GeneratedChunk:
    plan: _ChunkPlan
    token_ids: list[int]
    alignment: _ChunkAlignment


class CohereAsrEngine:
    """One warm, GPU-resident Cohere model with true same-route batching."""

    def __init__(self, *, model_dir: Path, lock: ModelPoolLock) -> None:
        # Importing health, routing, and job code must never initialize the GPU
        # stack. These imports occur only in a dedicated worker process.
        import numpy as np
        import torch
        from transformers import AutoProcessor, CohereAsrForConditionalGeneration

        if not torch.cuda.is_available():
            raise RuntimeError("the Cohere ASR engine requires an NVIDIA GPU")
        load_started = time.monotonic()
        processor = AutoProcessor.from_pretrained(
            str(model_dir),
            local_files_only=True,
        )
        model = CohereAsrForConditionalGeneration.from_pretrained(
            str(model_dir),
            local_files_only=True,
            dtype=torch.bfloat16,
        )
        model.to("cuda")
        model.eval()
        torch.cuda.synchronize()
        self._model_load_ms = round((time.monotonic() - load_started) * 1000)
        self._np = np
        self._torch = torch
        self._processor = processor
        self._model = model
        self._lock = lock
        extractor = processor.feature_extractor
        if extractor.sampling_rate != 16000:
            raise RuntimeError("the Cohere processor sampling rate is invalid")
        self._chunk_frames = round(
            float(extractor.max_audio_clip_s) * extractor.sampling_rate
        )
        self._boundary_context_frames = round(
            float(extractor.overlap_chunk_second) * extractor.sampling_rate
        )
        self._energy_window_frames = int(extractor.min_energy_window_samples)
        if (
            self._chunk_frames < 1
            or not 1 <= self._boundary_context_frames < self._chunk_frames
            or self._energy_window_frames < 1
        ):
            raise RuntimeError("the Cohere processor chunking contract is invalid")

    @property
    def model_load_ms(self) -> int:
        return self._model_load_ms

    def transcribe_batch(
        self,
        requests: list[CohereAsrInput],
    ) -> list[dict[str, object]]:
        results = self._transcribe_batch(requests, cancellation_checks=None)
        if any(result is None for result in results):
            raise RuntimeError("non-cancellable Cohere inference was cancelled")
        return cast(list[dict[str, object]], results)

    def transcribe_batch_cancellable(
        self,
        requests: list[CohereAsrInput],
        cancellation_checks: list[Callable[[], bool]],
    ) -> list[dict[str, object] | None]:
        if len(cancellation_checks) != len(requests) or not all(
            callable(check) for check in cancellation_checks
        ):
            raise ValueError("Cohere cancellation checks do not match the batch")
        return self._transcribe_batch(
            requests,
            cancellation_checks=cancellation_checks,
        )

    def _transcribe_batch(
        self,
        requests: list[CohereAsrInput],
        *,
        cancellation_checks: list[Callable[[], bool]] | None,
    ) -> list[dict[str, object] | None]:
        if not 1 <= len(requests) <= MAX_ENGINE_BATCH_SIZE:
            raise ValueError("Cohere ASR engine batch size is invalid")
        language = requests[0].language
        punctuation = requests[0].punctuation
        if any(
            request.language != language or request.punctuation is not punctuation
            for request in requests
        ):
            raise ValueError("Cohere ASR engine batches require one route")
        if language not in self._lock.supported_languages:
            raise ValueError("Cohere ASR language is not supported by the model lock")

        from yap_server.pools.cohere_chunking import energy_chunk_ranges

        sample_views = [
            self._np.frombuffer(request.audio.pcm_bytes, dtype="<i2")
            for request in requests
        ]
        request_ranges = [
            energy_chunk_ranges(
                samples,
                chunk_frames=self._chunk_frames,
                boundary_context_frames=self._boundary_context_frames,
                energy_window_frames=self._energy_window_frames,
            )
            for samples in sample_views
        ]
        plans = [
            _ChunkPlan(
                request_index=request_index,
                chunk_index=chunk_index,
                start_frame=start_frame,
                end_frame=end_frame,
            )
            for chunk_index in range(max(len(ranges) for ranges in request_ranges))
            for request_index, ranges in enumerate(request_ranges)
            if chunk_index < len(ranges)
            for start_frame, end_frame in (ranges[chunk_index],)
        ]
        generated_by_request: list[list[_GeneratedChunk]] = [
            [] for _request in requests
        ]
        processed_chunks = 0
        inference_passes = 0

        def cancelled(request_index: int) -> bool:
            return bool(
                cancellation_checks is not None
                and cancellation_checks[request_index]()
            )

        inference_started = time.monotonic()
        pending: list[_ChunkPlan] = []
        for plan in plans:
            if not cancelled(plan.request_index):
                pending.append(plan)
            if len(pending) == MAX_ENGINE_BATCH_SIZE:
                processed = self._generate_microbatch(
                    pending,
                    requests=requests,
                    sample_views=sample_views,
                    language=language,
                    punctuation=punctuation,
                    cancelled=cancelled,
                )
                for chunk in processed:
                    generated_by_request[chunk.plan.request_index].append(chunk)
                processed_chunks += len(processed)
                inference_passes += 1
                pending = []
        if pending:
            processed = self._generate_microbatch(
                pending,
                requests=requests,
                sample_views=sample_views,
                language=language,
                punctuation=punctuation,
                cancelled=cancelled,
            )
            for chunk in processed:
                generated_by_request[chunk.plan.request_index].append(chunk)
            processed_chunks += len(processed)
            inference_passes += 1
        self._torch.cuda.synchronize()
        inference_ms = round((time.monotonic() - inference_started) * 1000)
        decoded: list[str | None] = []
        alignments: list[dict[str, object] | None] = []
        for request_index, generated in enumerate(generated_by_request):
            if cancelled(request_index):
                decoded.append(None)
                alignments.append(None)
                continue
            generated.sort(key=lambda item: item.plan.chunk_index)
            if len(generated) != len(request_ranges[request_index]):
                raise RuntimeError("ASR generation omitted a required audio chunk")
            audio_chunk_index = [
                (0, None if len(generated) == 1 else chunk.plan.chunk_index)
                for chunk in generated
            ]
            reassembled = self._processor.decode(
                [chunk.token_ids for chunk in generated],
                skip_special_tokens=True,
                audio_chunk_index=audio_chunk_index,
                language=language,
            )
            if not isinstance(reassembled, (list, tuple)) or len(reassembled) != 1:
                raise RuntimeError("ASR decoder returned the wrong request count")
            transcript = _decoded_text(reassembled[0])
            decoded.append(transcript)
            alignments.append(_merge_chunk_alignments(generated, transcript))
        runtime = {
            "device": "cuda",
            "deviceName": str(self._torch.cuda.get_device_name(0)),
            "computeCapability": list(self._torch.cuda.get_device_capability(0)),
            "pythonVersion": sys.version.split()[0],
            "torchVersion": str(self._torch.__version__),
            "torchCudaVersion": str(self._torch.version.cuda),
            "overlayPackages": {
                name: package_version(name)
                for name, _expected_version in self._lock.runtime_overlay_packages
            },
            "dtype": str(self._model.dtype).removeprefix("torch."),
            "modelLoadMs": self._model_load_ms,
            "inferenceMs": inference_ms,
            "batchSize": len(requests),
            "chunkCount": processed_chunks,
            "inferencePasses": inference_passes,
        }
        return [
            (
                None
                if decoded[index] is None
                else _result_payload(
                    request=request,
                    lock=self._lock,
                    transcript=cast(str, decoded[index]),
                    alignment=cast(dict[str, object], alignments[index]),
                    runtime=runtime,
                )
            )
            for index, request in enumerate(requests)
        ]

    def _generate_microbatch(
        self,
        plans: list[_ChunkPlan],
        *,
        requests: list[CohereAsrInput],
        sample_views: list[object],
        language: str,
        punctuation: bool,
        cancelled: Callable[[int], bool],
    ) -> list[_GeneratedChunk]:
        active = [plan for plan in plans if not cancelled(plan.request_index)]
        if not active:
            return []
        samples = [
            sample_views[plan.request_index][plan.start_frame : plan.end_frame].astype(
                self._np.float32
            )
            / 32768.0
            for plan in active
        ]
        inputs = self._processor(
            audio=samples,
            sampling_rate=requests[0].audio.sample_rate,
            return_tensors="pt",
            language=language,
            punctuation=punctuation,
        )
        processor_chunks = inputs.get("audio_chunk_index")
        if (
            not isinstance(processor_chunks, list)
            or len(processor_chunks) != len(active)
            or any(
                not isinstance(item, tuple)
                or len(item) != 2
                or item[0] != index
                or item[1] not in (None, 0)
                for index, item in enumerate(processor_chunks)
            )
        ):
            raise RuntimeError("the Cohere processor rechunked a bounded microbatch")
        inputs = inputs.to(device=self._model.device, dtype=self._model.dtype)
        with self._torch.inference_mode():
            output = self._model.generate(**inputs, max_new_tokens=256)
        token_rows = output.detach().cpu().tolist()
        if not isinstance(token_rows, list) or len(token_rows) != len(active):
            raise RuntimeError("ASR generation returned the wrong microbatch size")
        if any(
            not isinstance(token_ids, list)
            or not all(
                isinstance(token_id, int) and not isinstance(token_id, bool)
                for token_id in token_ids
            )
            for token_ids in token_rows
        ):
            raise RuntimeError("ASR generation returned invalid token IDs")
        alignments = self._align_generated_microbatch(
            active,
            inputs=inputs,
            generated=output,
            token_rows=token_rows,
            language=language,
            cancelled=cancelled,
        )
        results: list[_GeneratedChunk] = []
        for plan, token_ids, alignment in zip(
            active,
            token_rows,
            alignments,
            strict=True,
        ):
            if cancelled(plan.request_index):
                continue
            results.append(
                _GeneratedChunk(
                    plan=plan,
                    token_ids=token_ids,
                    alignment=alignment,
                )
            )
        return results

    def _align_generated_microbatch(
        self,
        plans: list[_ChunkPlan],
        *,
        inputs: object,
        generated: object,
        token_rows: list[list[int]],
        language: str,
        cancelled: Callable[[int], bool],
    ) -> list[_ChunkAlignment]:
        if language != "en":
            return [
                _unavailable_chunk(AlignmentUnavailableReason.LANGUAGE_UNSUPPORTED)
                for _plan in plans
            ]

        default = _unavailable_chunk(AlignmentUnavailableReason.RUNTIME_FAILED)
        results = [default for _plan in plans]
        try:
            decoder_input_ids = inputs.get("decoder_input_ids")
            prompt_token_count = int(decoder_input_ids.shape[1])
            if not 1 <= prompt_token_count <= 32:
                raise RuntimeError("Cohere alignment prompt length is invalid")
            metadata: dict[int, tuple[str, tuple[str, ...], int]] = {}
            selected_indices: list[int] = []
            for index, (plan, token_ids) in enumerate(
                zip(plans, token_rows, strict=True)
            ):
                if cancelled(plan.request_index):
                    continue
                try:
                    metadata[index] = _alignment_token_metadata(
                        self._processor,
                        token_ids,
                        prompt_token_count=prompt_token_count,
                        language=language,
                    )
                except AlignmentUnavailable as error:
                    results[index] = _unavailable_chunk(error.reason)
                    continue
                selected_indices.append(index)
            if not selected_indices:
                return results

            index_tensor = self._torch.tensor(
                selected_indices,
                dtype=self._torch.long,
                device=self._model.device,
            )
            teacher_inputs = _selected_teacher_inputs(inputs, index_tensor)
            selected_generated = generated.index_select(0, index_tensor)

            captured: dict[tuple[int, int], object] = {}
            hooks = []
            try:
                layers = self._model.model.decoder.layers
                for layer_index, head_index in ALIGNMENT_SELECTED_HEADS:
                    module = layers[layer_index].encoder_attn

                    def capture(
                        current: object,
                        _args: object,
                        kwargs: dict[str, object],
                        *,
                        key: tuple[int, int] = (layer_index, head_index),
                        selected_head: int = head_index,
                    ) -> None:
                        if key in captured:
                            raise RuntimeError("Cohere alignment hook ran more than once")
                        captured[key] = self._selected_head_logits(
                            current,
                            kwargs,
                            selected_head,
                        )

                    hooks.append(
                        module.register_forward_pre_hook(capture, with_kwargs=True)
                    )
                with self._torch.inference_mode():
                    self._model(
                        **teacher_inputs,
                        decoder_input_ids=selected_generated,
                        use_cache=False,
                        return_dict=True,
                    )
            finally:
                for hook in hooks:
                    hook.remove()
            if set(captured) != set(ALIGNMENT_SELECTED_HEADS):
                raise RuntimeError("Cohere alignment hook evidence is incomplete")

            for local_index, original_index in enumerate(selected_indices):
                plan = plans[original_index]
                transcript, token_pieces, matrix_token_count = metadata[original_index]
                try:
                    encoder_frames = valid_encoder_frame_count(
                        plan.end_frame - plan.start_frame
                    )
                    head_logits = self._torch.stack(
                        [
                            captured[key][
                                local_index,
                                :matrix_token_count,
                                :encoder_frames,
                            ]
                            for key in ALIGNMENT_SELECTED_HEADS
                        ]
                    )
                    if (
                        head_logits.shape
                        != (
                            len(ALIGNMENT_SELECTED_HEADS),
                            matrix_token_count,
                            encoder_frames,
                        )
                        or not bool(self._torch.isfinite(head_logits).all())
                    ):
                        raise AlignmentUnavailable(
                            AlignmentUnavailableReason.EVIDENCE_INVALID
                        )
                    weights = self._torch.softmax(head_logits, dim=-1)
                    standard_deviation = weights.std(
                        dim=-2,
                        keepdim=True,
                        unbiased=False,
                    )
                    normalized = (
                        weights - weights.mean(dim=-2, keepdim=True)
                    ) / standard_deviation.clamp_min(1e-6)
                    filtered = _median_filter_last_dimension(
                        self._torch,
                        normalized,
                        ALIGNMENT_MEDIAN_FILTER_WIDTH,
                    )
                    scores = filtered.mean(dim=0)
                    if not bool(self._torch.isfinite(scores).all()):
                        raise AlignmentUnavailable(
                            AlignmentUnavailableReason.EVIDENCE_INVALID
                        )
                    words = align_cohere_word_scores(
                        transcript=transcript,
                        token_pieces=token_pieces,
                        score_matrix=scores.detach().cpu().tolist(),
                        content_token_offset=prompt_token_count,
                        source_start_sample=plan.start_frame,
                        source_frame_count=plan.end_frame - plan.start_frame,
                    )
                    results[original_index] = _ChunkAlignment(
                        words=words,
                        unavailable_reason=None,
                    )
                except AlignmentUnavailable as error:
                    results[original_index] = _unavailable_chunk(error.reason)
                except (OverflowError, RuntimeError, TypeError, ValueError):
                    results[original_index] = _unavailable_chunk(
                        AlignmentUnavailableReason.RUNTIME_FAILED
                    )
        except (AttributeError, IndexError, OverflowError, RuntimeError, TypeError, ValueError):
            return results
        return results

    def _selected_head_logits(
        self,
        module: object,
        kwargs: dict[str, object],
        head_index: int,
    ) -> object:
        hidden_states = kwargs.get("hidden_states")
        encoder_hidden_states = kwargs.get("encoder_hidden_states")
        if hidden_states is None or encoder_hidden_states is None:
            raise RuntimeError("Cohere alignment hook omitted hidden states")
        head_dimension = int(module.head_dim)
        first = head_index * head_dimension
        last = first + head_dimension
        functional = self._torch.nn.functional
        query_bias = module.q_proj.bias
        key_bias = module.k_proj.bias
        query = functional.linear(
            hidden_states.float(),
            module.q_proj.weight[first:last].float(),
            None if query_bias is None else query_bias[first:last].float(),
        )
        key = functional.linear(
            encoder_hidden_states.float(),
            module.k_proj.weight[first:last].float(),
            None if key_bias is None else key_bias[first:last].float(),
        )
        logits = self._torch.matmul(query, key.transpose(-2, -1)) * float(
            module.scaling
        )
        if logits.ndim != 3:
            raise RuntimeError("Cohere alignment logits have the wrong shape")
        return logits


def _alignment_token_metadata(
    processor: object,
    token_ids: list[int],
    *,
    prompt_token_count: int,
    language: str,
) -> tuple[str, tuple[str, ...], int]:
    tokenizer = processor.tokenizer
    if (
        not 1 <= prompt_token_count < len(token_ids)
        or len(token_ids) > MAX_ALIGNMENT_MATRIX_TOKENS
    ):
        raise AlignmentUnavailable(AlignmentUnavailableReason.TOKEN_LIMIT)
    pieces = tokenizer.convert_ids_to_tokens(token_ids)
    if not isinstance(pieces, list) or len(pieces) != len(token_ids):
        raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)
    eos_token_id = tokenizer.eos_token_id
    try:
        eos_index = token_ids.index(eos_token_id, prompt_token_count)
    except ValueError as error:
        raise AlignmentUnavailable(
            AlignmentUnavailableReason.TOKEN_TRANSCRIPT_DIVERGED
        ) from error
    content_pieces = tuple(pieces[prompt_token_count:eos_index])
    if not content_pieces:
        raise AlignmentUnavailable(AlignmentUnavailableReason.EMPTY_TRANSCRIPT)
    if len(content_pieces) > MAX_ALIGNMENT_TOKENS:
        raise AlignmentUnavailable(AlignmentUnavailableReason.TOKEN_LIMIT)
    decoded = processor.decode(
        [token_ids[: eos_index + 1]],
        skip_special_tokens=True,
        audio_chunk_index=[(0, None)],
        language=language,
    )
    if not isinstance(decoded, (list, tuple)) or len(decoded) != 1:
        raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)
    return _decoded_text(decoded[0]), content_pieces, eos_index + 1


def _selected_teacher_inputs(
    inputs: object,
    index_tensor: object,
) -> dict[str, object]:
    items = getattr(inputs, "items", None)
    if not callable(items):
        raise RuntimeError("Cohere teacher inputs are not a mapping")
    selected: dict[str, object] = {}
    for name, value in items():
        if name in {
            "audio_chunk_index",
            "decoder_input_ids",
            "decoder_attention_mask",
        }:
            continue
        index_select = getattr(value, "index_select", None)
        if not callable(index_select):
            raise RuntimeError("Cohere teacher input is not a tensor")
        selected[name] = index_select(0, index_tensor)
    if not selected:
        raise RuntimeError("Cohere teacher inputs omitted encoder evidence")
    return selected


def _median_filter_last_dimension(
    torch: object,
    value: object,
    width: int,
) -> object:
    if width <= 0 or width % 2 != 1:
        raise ValueError("alignment median-filter width is invalid")
    padding = width // 2
    if value.shape[-1] <= padding:
        return value
    padded = torch.nn.functional.pad(
        value,
        (padding, padding, 0, 0),
        mode="reflect",
    )
    return padded.unfold(-1, width, 1).sort()[0][..., padding]


def _unavailable_chunk(reason: AlignmentUnavailableReason) -> _ChunkAlignment:
    return _ChunkAlignment(words=(), unavailable_reason=reason)


def _merge_chunk_alignments(
    generated: list[_GeneratedChunk],
    transcript: str,
) -> dict[str, object]:
    for chunk in generated:
        if chunk.alignment.unavailable_reason is not None:
            return unavailable_alignment(chunk.alignment.unavailable_reason)
    words: list[AlignedWordEvidence] = []
    for chunk in generated:
        for word in chunk.alignment.words:
            if len(words) >= MAX_ALIGNMENT_WORDS:
                return unavailable_alignment(AlignmentUnavailableReason.WORD_LIMIT)
            words.append(
                AlignedWordEvidence(
                    word_index=len(words),
                    text=word.text,
                    start_ms=word.start_ms,
                    end_ms=word.end_ms,
                )
            )
    if not words:
        return unavailable_alignment(AlignmentUnavailableReason.EMPTY_TRANSCRIPT)
    if " ".join(word.text for word in words) != transcript:
        return unavailable_alignment(
            AlignmentUnavailableReason.TOKEN_TRANSCRIPT_DIVERGED
        )
    try:
        return available_alignment(words)
    except AlignmentUnavailable as error:
        return unavailable_alignment(error.reason)


def _decoded_text(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError("ASR decoder returned an unexpected result")
    return " ".join(value.split())


def _result_payload(
    *,
    request: CohereAsrInput,
    lock: ModelPoolLock,
    transcript: str,
    alignment: dict[str, object],
    runtime: dict[str, object],
) -> dict[str, object]:
    payload = {
        "schemaVersion": 1,
        "jobId": request.job_id,
        "model": {
            "poolId": lock.pool_id,
            "id": lock.model_id,
            "revision": lock.model_revision,
        },
        "audio": {
            "sha256": request.audio.sha256,
            "durationMs": request.audio.duration_ms,
            "sampleRateHz": request.audio.sample_rate,
        },
        "transcript": {
            "text": transcript,
            "language": request.language,
            "punctuation": request.punctuation,
        },
        "alignment": alignment,
        "runtime": dict(runtime),
    }
    if (
        len(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        > MAX_WORKER_RESULT_BYTES
    ):
        payload["alignment"] = unavailable_alignment(
            AlignmentUnavailableReason.RESULT_LIMIT
        )
    return payload
