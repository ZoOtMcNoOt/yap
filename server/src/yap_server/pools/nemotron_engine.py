from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import version as package_version
from pathlib import Path
import re
import sys
import time
from typing import Callable, Mapping, Sequence

from yap_server.alignment_contract import (
    COHERE_ATTENTION_ALIGNMENT_CANDIDATE_REVISION,
    AlignmentUnavailableReason,
    unavailable_alignment,
)
from yap_server.language_tags import canonical_bcp47
from yap_server.language_span_contract import (
    ServerUtteranceLanguageObservation,
    build_server_language_span_evidence,
)
from yap_server.pools.model_lock import ModelPoolLock
from yap_server.pools.pcm_audio import PcmAudio
from yap_server.pools.utterance_plan import UtterancePlan, snapshot_utterance_plan
from yap_server.transcript_text import canonical_transcript


MAX_NEMOTRON_UTTERANCE_SECONDS = 30
MAX_NEMOTRON_GENERATED_TOKENS = 2_048
MAX_NEMOTRON_LANGUAGE_SEGMENTS = 256
MAX_NEMOTRON_RECORDING_SEGMENTS = 4_096

_LANGUAGE_TOKEN = re.compile(r"^<([^<>]+)>$")
_MISSING_TAG = "MISSING_LANGUAGE_TAG"
_DISABLED_TAG = "DISABLED_LANGUAGE_TAG"
_EMPTY_TAGGED_TEXT = "EMPTY_TAGGED_TRANSCRIPT"
_NEMOTRON_PROVIDER_ID = "nemotron"


class NemotronInferenceCancelled(RuntimeError):
    """A bounded recording stopped between finalized utterance windows."""


@dataclass(frozen=True, slots=True)
class NemotronAsrInput:
    job_id: str
    audio: PcmAudio
    language: str
    punctuation: bool


@dataclass(frozen=True, slots=True)
class NemotronUtteranceTranscript:
    text: str
    language_segments: list[dict[str, object]] | None
    inference_ms: int
    inference_passes: int = 1
    max_batch_size: int = 1
    queue_ms: int = 0
    total_ms: int = 0


def language_tag_token_map(
    tokenizer: object,
    *,
    prompt_locales: Sequence[str],
) -> dict[int, str]:
    """Return immutable BCP-47 tag tokens from the pinned tokenizer.

    Dynamic evidence is split on token identity before display decoding removes
    special tokens. This avoids treating arbitrary angle-bracket text as model
    authority and still lets disabled/adaptation-only tags survive as Unknown.
    """

    get_added_vocab = getattr(tokenizer, "get_added_vocab", None)
    if not callable(get_added_vocab):
        raise RuntimeError("Nemotron tokenizer does not expose its added vocabulary")
    added_vocab = get_added_vocab()
    if not isinstance(added_vocab, Mapping) or len(added_vocab) > 1_024:
        raise RuntimeError("Nemotron tokenizer added vocabulary is invalid")
    prompt_catalog = _validated_prompt_locales(prompt_locales)
    tags: dict[int, str] = {}
    for token, token_id in added_vocab.items():
        if not isinstance(token, str):
            raise RuntimeError("Nemotron tokenizer contains a non-text token")
        match = _LANGUAGE_TOKEN.fullmatch(token)
        if match is None:
            continue
        candidate = match.group(1)
        try:
            locale = canonical_bcp47(candidate, "Nemotron language token")
        except ValueError:
            continue
        if locale not in prompt_catalog and locale.split("-", 1)[0] not in prompt_catalog:
            continue
        if (
            not isinstance(token_id, int)
            or isinstance(token_id, bool)
            or token_id < 0
            or token_id in tags
        ):
            raise RuntimeError("Nemotron tokenizer language tokens are invalid")
        tags[token_id] = locale
    if not tags:
        raise RuntimeError("Nemotron tokenizer exposes no language tag tokens")
    return tags


def tagged_language_segments(
    token_ids: Sequence[int],
    *,
    tag_tokens: Mapping[int, str],
    enabled_locales: Sequence[str],
    decode: Callable[[list[int]], object],
) -> tuple[str, list[dict[str, object]]]:
    """Split one automatic transcript without inventing a language decision."""

    if (
        not isinstance(token_ids, Sequence)
        or isinstance(token_ids, (str, bytes, bytearray))
        or len(token_ids) > MAX_NEMOTRON_GENERATED_TOKENS
        or any(
            not isinstance(token_id, int) or isinstance(token_id, bool) or token_id < 0
            for token_id in token_ids
        )
    ):
        raise RuntimeError("Nemotron generation returned invalid token IDs")
    normalized_tags = _validated_tag_tokens(tag_tokens)
    enabled = _validated_enabled_locales(enabled_locales)
    tag_positions = [
        (index, normalized_tags[token_id])
        for index, token_id in enumerate(token_ids)
        if token_id in normalized_tags
    ]
    if len(tag_positions) > MAX_NEMOTRON_LANGUAGE_SEGMENTS:
        raise RuntimeError("Nemotron generation exceeded the language segment bound")

    segments: list[dict[str, object]] = []
    cursor = 0
    for tag_index, raw_tag in tag_positions:
        text = _decode_canonical(decode, list(token_ids[cursor:tag_index]))
        if not text:
            segments.append(
                _unknown_segment(
                    index=len(segments),
                    text="",
                    raw_tag=raw_tag,
                    reason=_EMPTY_TAGGED_TEXT,
                )
            )
        elif raw_tag in enabled:
            segments.append(
                {
                    "index": len(segments),
                    "text": text,
                    "status": "detected",
                    "languageBcp47": raw_tag,
                    "rawLanguageTag": raw_tag,
                    "reason": None,
                }
            )
        else:
            segments.append(
                _unknown_segment(
                    index=len(segments),
                    text=text,
                    raw_tag=raw_tag,
                    reason=_DISABLED_TAG,
                )
            )
        cursor = tag_index + 1

    trailing_text = _decode_canonical(decode, list(token_ids[cursor:]))
    if trailing_text or not tag_positions:
        segments.append(
            _unknown_segment(
                index=len(segments),
                text=trailing_text,
                raw_tag=None,
                reason=_MISSING_TAG,
            )
        )
    display_text = canonical_transcript(
        " ".join(
            str(segment["text"])
            for segment in segments
            if segment["text"]
        ),
        "Nemotron dynamic display transcript",
    )
    return display_text, segments


class NemotronAsrEngine:
    """One exact Transformers/BF16 Nemotron reference model on CUDA.

    This reference deliberately accepts one bounded finalized utterance. Long
    recording segmentation and source-time reconciliation stay outside the
    model adapter so a whole recording cannot be mislabeled as one utterance.
    """

    def __init__(self, *, model_dir: Path, lock: ModelPoolLock) -> None:
        import numpy as np
        import torch
        from transformers import AutoModelForRNNT, AutoProcessor

        if lock.pool_id != "nemotron-batch":
            raise ValueError("Nemotron engine requires the Nemotron model lock")
        if lock.engine != "transformers":
            raise ValueError("Nemotron Transformers engine requires a Transformers lock")
        if "auto" not in lock.supported_languages:
            raise ValueError("Nemotron model lock must include explicit auto mode")
        if not torch.cuda.is_available():
            raise RuntimeError("the Nemotron ASR engine requires an NVIDIA GPU")

        fixed_locales = tuple(
            language for language in lock.supported_languages if language != "auto"
        )
        load_started = time.monotonic()
        processor = AutoProcessor.from_pretrained(
            str(model_dir),
            local_files_only=True,
        )
        prompts = getattr(processor, "prompt_dictionary", None)
        if not isinstance(prompts, Mapping) or any(
            locale not in prompts for locale in (*fixed_locales, "auto")
        ):
            raise RuntimeError("Nemotron processor prompt catalog differs from the lock")
        tag_tokens = language_tag_token_map(
            processor.tokenizer,
            prompt_locales=tuple(prompts),
        )
        missing_tags = sorted(set(fixed_locales) - set(tag_tokens.values()))
        if missing_tags:
            raise RuntimeError("Nemotron tokenizer omits a locked language tag")
        if processor.feature_extractor.sampling_rate != 16_000:
            raise RuntimeError("the Nemotron processor sampling rate is invalid")

        model = AutoModelForRNNT.from_pretrained(
            str(model_dir),
            local_files_only=True,
            dtype=torch.bfloat16,
        )
        model.to("cuda")
        model.eval()
        torch.cuda.synchronize()
        self._model_load_ms = round((time.monotonic() - load_started) * 1_000)
        self._np = np
        self._torch = torch
        self._processor = processor
        self._model = model
        self._lock = lock
        self._fixed_locales = fixed_locales
        self._tag_tokens = tag_tokens

    @property
    def model_load_ms(self) -> int:
        return self._model_load_ms

    def transcribe(self, request: NemotronAsrInput) -> dict[str, object]:
        self._validate_request(request, require_bounded_utterance=True)
        utterance = self._infer_utterance(request)
        return _result_payload(
            request=request,
            lock=self._lock,
            transcript=utterance.text,
            language_segments=utterance.language_segments,
            language_span_evidence=None,
            runtime=self._runtime_payload(
                inference_ms=utterance.inference_ms,
                chunk_count=1,
                inference_passes=utterance.inference_passes,
                max_batch_size=utterance.max_batch_size,
                queue_ms=utterance.queue_ms,
                total_ms=utterance.total_ms,
            ),
        )

    def transcribe_recording(
        self,
        request: NemotronAsrInput,
        plan: UtterancePlan,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        """Transcribe one complete recording through ordered bounded windows."""

        self._validate_request(request, require_bounded_utterance=False)
        if (
            not isinstance(plan, UtterancePlan)
            or plan.input_wav_sha256 != request.audio.sha256
            or plan.input_sample_count != request.audio.frame_count
        ):
            raise ValueError("Nemotron utterance plan differs from the recording")

        transcript_parts: list[str] = []
        language_segments: list[dict[str, object]] | None = (
            [] if request.language == "auto" else None
        )
        language_observations: list[ServerUtteranceLanguageObservation] | None = (
            [] if request.language == "auto" else None
        )
        plan_sha256 = snapshot_utterance_plan(plan).sha256
        inference_ms = 0
        inference_passes = 0
        max_batch_size = 1
        queue_ms = 0
        total_ms = 0
        for window in plan.utterances:
            if cancelled is not None and cancelled():
                raise NemotronInferenceCancelled(
                    "Nemotron recording inference was cancelled"
                )
            pcm = request.audio.pcm_bytes[
                window.start_sample * 2 : window.end_sample_exclusive * 2
            ]
            frame_count = window.end_sample_exclusive - window.start_sample
            utterance = NemotronAsrInput(
                job_id=request.job_id,
                audio=PcmAudio(
                    pcm_bytes=pcm,
                    sample_rate=request.audio.sample_rate,
                    frame_count=frame_count,
                    duration_ms=max(
                        1,
                        round(frame_count * 1_000 / request.audio.sample_rate),
                    ),
                    sha256=hashlib.sha256(pcm).hexdigest(),
                ),
                language=request.language,
                punctuation=request.punctuation,
            )
            outcome = self._infer_utterance(
                utterance,
                cancelled=cancelled,
            )
            if cancelled is not None and cancelled():
                raise NemotronInferenceCancelled(
                    "Nemotron recording inference was cancelled"
                )
            inference_ms += outcome.inference_ms
            inference_passes += outcome.inference_passes
            max_batch_size = max(max_batch_size, outcome.max_batch_size)
            queue_ms += outcome.queue_ms
            total_ms += outcome.total_ms
            if outcome.text:
                transcript_parts.append(outcome.text)
            if language_segments is not None:
                if outcome.language_segments is None or language_observations is None:
                    raise RuntimeError(
                        "Nemotron automatic inference omitted language evidence"
                    )
                source_span_index = len(language_observations)
                for segment in outcome.language_segments:
                    if len(language_segments) >= MAX_NEMOTRON_RECORDING_SEGMENTS:
                        raise RuntimeError(
                            "Nemotron recording exceeded the language segment bound"
                        )
                    copied = dict(segment)
                    copied["index"] = len(language_segments)
                    copied["sourceSpanIndex"] = source_span_index
                    language_segments.append(copied)
                language_observations.append(
                    ServerUtteranceLanguageObservation(
                        start_sample=window.start_sample,
                        end_sample=window.end_sample_exclusive,
                        language_segments=outcome.language_segments,
                    )
                )
            elif outcome.language_segments is not None:
                raise RuntimeError(
                    "Nemotron fixed inference returned dynamic language evidence"
                )

        transcript = canonical_transcript(
            " ".join(transcript_parts),
            "Nemotron recording transcript",
        )
        language_span_evidence = (
            build_server_language_span_evidence(
                source_end_sample=request.audio.frame_count,
                provider_id=_NEMOTRON_PROVIDER_ID,
                pool_id=self._lock.pool_id,
                model_id=self._lock.model_id,
                model_revision=self._lock.model_revision,
                utterance_plan_sha256=plan_sha256,
                utterances=language_observations,
            )
            if language_observations is not None
            else None
        )
        return _result_payload(
            request=request,
            lock=self._lock,
            transcript=transcript,
            language_segments=language_segments,
            language_span_evidence=language_span_evidence,
            runtime=self._runtime_payload(
                inference_ms=inference_ms,
                chunk_count=len(plan.utterances),
                inference_passes=inference_passes,
                max_batch_size=max_batch_size,
                queue_ms=queue_ms,
                total_ms=total_ms,
            ),
        )

    def _validate_request(
        self,
        request: NemotronAsrInput,
        *,
        require_bounded_utterance: bool,
    ) -> None:
        if request.language not in self._lock.supported_languages:
            raise ValueError("Nemotron ASR language is not supported by the model lock")
        if not request.punctuation:
            raise ValueError("Nemotron reference inference always emits punctuation")
        if (
            request.audio.sample_rate != 16_000
            or request.audio.frame_count < 1
            or len(request.audio.pcm_bytes) != request.audio.frame_count * 2
            or (
                require_bounded_utterance
                and request.audio.frame_count
                > MAX_NEMOTRON_UTTERANCE_SECONDS * request.audio.sample_rate
            )
        ):
            raise ValueError("Nemotron reference input is not a bounded 16 kHz utterance")

    def _infer_utterance(
        self,
        request: NemotronAsrInput,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> NemotronUtteranceTranscript:
        self._validate_request(request, require_bounded_utterance=True)

        if cancelled is not None and cancelled():
            raise NemotronInferenceCancelled("Nemotron inference was cancelled")

        samples = (
            self._np.frombuffer(request.audio.pcm_bytes, dtype="<i2").astype(
                self._np.float32
            )
            / 32_768.0
        )
        inputs = self._processor(
            samples,
            sampling_rate=request.audio.sample_rate,
            language=request.language,
            return_tensors="pt",
        )
        inputs = inputs.to(device=self._model.device, dtype=self._model.dtype)
        inference_started = time.monotonic()
        with self._torch.inference_mode():
            output = self._model.generate(
                **inputs,
                return_dict_in_generate=True,
                max_new_tokens=MAX_NEMOTRON_GENERATED_TOKENS,
            )
        self._torch.cuda.synchronize()
        inference_ms = round((time.monotonic() - inference_started) * 1_000)
        if cancelled is not None and cancelled():
            raise NemotronInferenceCancelled("Nemotron inference was cancelled")
        token_ids = _single_token_row(output)

        language_segments: list[dict[str, object]] | None = None
        if request.language == "auto":
            transcript, language_segments = tagged_language_segments(
                token_ids,
                tag_tokens=self._tag_tokens,
                enabled_locales=self._fixed_locales,
                decode=lambda row: self._processor.decode(
                    row,
                    skip_special_tokens=True,
                ),
            )
        else:
            transcript = _decode_canonical(
                lambda row: self._processor.decode(
                    row,
                    skip_special_tokens=True,
                ),
                token_ids,
            )
        return NemotronUtteranceTranscript(
            text=transcript,
            language_segments=language_segments,
            inference_ms=inference_ms,
            total_ms=inference_ms,
        )

    def _runtime_payload(
        self,
        *,
        inference_ms: int,
        chunk_count: int,
        inference_passes: int,
        max_batch_size: int,
        queue_ms: int,
        total_ms: int,
    ) -> dict[str, object]:
        return {
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
            "batchSize": max_batch_size,
            "chunkCount": chunk_count,
            "inferencePasses": inference_passes,
            "queueMs": queue_ms,
            "totalRuntimeMs": total_ms,
        }


def _validated_tag_tokens(value: Mapping[int, str]) -> dict[int, str]:
    if not isinstance(value, Mapping) or not value or len(value) > 1_024:
        raise RuntimeError("Nemotron language tag map is invalid")
    validated: dict[int, str] = {}
    for token_id, locale in value.items():
        if (
            not isinstance(token_id, int)
            or isinstance(token_id, bool)
            or token_id < 0
        ):
            raise RuntimeError("Nemotron language tag map is invalid")
        validated[token_id] = canonical_bcp47(locale, "Nemotron language tag")
    return validated


def _validated_prompt_locales(value: Sequence[str]) -> frozenset[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
        or len(value) > 512
        or any(not isinstance(locale, str) for locale in value)
    ):
        raise RuntimeError("Nemotron processor prompt catalog is invalid")
    canonical: set[str] = set()
    for locale in value:
        try:
            canonical.add(canonical_bcp47(locale, "Nemotron processor prompt"))
        except ValueError:
            continue
    if not canonical:
        raise RuntimeError("Nemotron processor prompt catalog has no language prompts")
    return frozenset(canonical)


def _validated_enabled_locales(value: Sequence[str]) -> frozenset[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
        or len(value) > 256
    ):
        raise RuntimeError("Nemotron enabled locale catalog is invalid")
    enabled = frozenset(
        canonical_bcp47(locale, "Nemotron enabled locale") for locale in value
    )
    if len(enabled) != len(value):
        raise RuntimeError("Nemotron enabled locale catalog contains duplicates")
    return enabled


def _single_token_row(output: object) -> list[int]:
    sequences = getattr(output, "sequences", None)
    detach = getattr(sequences, "detach", None)
    if not callable(detach):
        raise RuntimeError("Nemotron generation omitted token sequences")
    rows = detach().cpu().tolist()
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], list)
        or len(rows[0]) > MAX_NEMOTRON_GENERATED_TOKENS
        or any(
            not isinstance(token_id, int) or isinstance(token_id, bool)
            for token_id in rows[0]
        )
    ):
        raise RuntimeError("Nemotron generation returned the wrong request count")
    return rows[0]


def _decode_canonical(
    decode: Callable[[list[int]], object],
    token_ids: list[int],
) -> str:
    decoded = decode(token_ids)
    if isinstance(decoded, (list, tuple)) and len(decoded) == 1:
        decoded = decoded[0]
    if not isinstance(decoded, str):
        raise RuntimeError("Nemotron decoder returned an unexpected result")
    return canonical_transcript(
        " ".join(decoded.split()),
        "Nemotron decoded transcript",
    )


def _unknown_segment(
    *,
    index: int,
    text: str,
    raw_tag: str | None,
    reason: str,
) -> dict[str, object]:
    return {
        "index": index,
        "text": text,
        "status": "unknown",
        "languageBcp47": None,
        "rawLanguageTag": raw_tag,
        "reason": reason,
    }


def _result_payload(
    *,
    request: NemotronAsrInput,
    lock: ModelPoolLock,
    transcript: str,
    language_segments: list[dict[str, object]] | None,
    language_span_evidence: dict[str, object] | None,
    runtime: dict[str, object],
) -> dict[str, object]:
    transcript_payload: dict[str, object] = {
        "text": transcript,
        "language": request.language,
        "punctuation": request.punctuation,
    }
    if language_segments is not None:
        transcript_payload["languageSegments"] = language_segments
    if language_span_evidence is not None:
        transcript_payload["languageSpanEvidence"] = language_span_evidence
    return {
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
        "transcript": transcript_payload,
        "alignment": unavailable_alignment(
            AlignmentUnavailableReason.PROVIDER_UNSUPPORTED,
            component_revision=COHERE_ATTENTION_ALIGNMENT_CANDIDATE_REVISION,
        ),
        "runtime": dict(runtime),
    }
