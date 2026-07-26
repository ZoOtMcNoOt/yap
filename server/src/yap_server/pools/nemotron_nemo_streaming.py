from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import version as package_version
import os
from pathlib import Path
import re
import sys
from typing import Mapping, Sequence

from yap_server.language_tags import canonical_bcp47
from yap_server.pools.model_lock import ModelPoolLock
from yap_server.pools.nemotron_engine import (
    MAX_NEMOTRON_LANGUAGE_SEGMENTS,
    NemotronAsrEngine,
    NemotronAsrInput,
    NemotronInferenceCancelled,
    NemotronUtteranceTranscript,
)
from yap_server.pools.nemo_stream_scheduler import NemoStreamCancelled
from yap_server.pools.nemotron_nemo_cleanup import (
    NATIVE_RUNTIME_CLEANUP_TIMEOUT_SECONDS,
    close_native_runtime_or_fail_stop,
    fail_stop_native_runtime,
)
from yap_server.pools.nemotron_nemo_pipeline import (
    NEMOTRON_STREAMING_ATTENTION_CONTEXT,
    NEMOTRON_STREAMING_CHUNK_SECONDS,
    NEMOTRON_STREAMING_MAX_STREAMS,
    NemotronNemoPipeline,
    NemotronNemoPartialInitializationError,
)
from yap_server.transcript_text import canonical_transcript


_NEMO_LANGUAGE_TAG = re.compile(r"<([^<>\s]{1,64})>")
_MISSING_TAG = "MISSING_LANGUAGE_TAG"
_DISABLED_TAG = "DISABLED_LANGUAGE_TAG"
_EMPTY_TAGGED_TEXT = "EMPTY_TAGGED_TRANSCRIPT"
NEMOTRON_STREAMING_CONFIG_ENV = "YAP_NEMOTRON_STREAMING_CONFIG"
_NATIVE_RUNTIME_CLEANUP_TIMEOUT_SECONDS = NATIVE_RUNTIME_CLEANUP_TIMEOUT_SECONDS


def parse_nemo_transcript(
    raw_transcript: object,
    *,
    requested_language: str,
    prompt_locales: Sequence[str],
    enabled_locales: Sequence[str],
) -> tuple[str, list[dict[str, object]] | None]:
    """Separate NeMo language metadata from spoken transcript text.

    Nemotron emits ``<xx-YY>`` language tags after terminal punctuation. They
    are model metadata, not spoken words. Only tags present in the restored
    checkpoint's prompt catalog are accepted; unexpected tag-shaped output
    fails closed instead of becoming language authority or display text.
    """

    if not isinstance(raw_transcript, str):
        raise RuntimeError("NeMo returned a non-text hypothesis")
    transcript = canonical_transcript(
        " ".join(raw_transcript.split()),
        "NeMo Nemotron raw transcript",
    )
    prompts = _validated_prompt_locales(prompt_locales)
    enabled = _validated_enabled_locales(enabled_locales)
    requested = (
        "auto"
        if requested_language == "auto"
        else canonical_bcp47(requested_language, "NeMo requested language")
    )
    if requested != "auto" and requested not in prompts:
        raise RuntimeError("the requested locale is absent from the NeMo prompt catalog")

    matches: list[tuple[re.Match[str], str]] = []
    for match in _NEMO_LANGUAGE_TAG.finditer(transcript):
        candidate = match.group(1)
        try:
            locale = canonical_bcp47(candidate, "NeMo emitted language tag")
        except ValueError as error:
            raise RuntimeError("NeMo emitted an invalid metadata tag") from error
        if locale not in prompts:
            raise RuntimeError("NeMo emitted a language tag outside the prompt catalog")
        matches.append((match, locale))
        if len(matches) > MAX_NEMOTRON_LANGUAGE_SEGMENTS:
            raise RuntimeError("NeMo output exceeded the language segment bound")

    if requested != "auto":
        # The selected prompt remains authoritative for a fixed route. Nemotron
        # may emit another known locale for an accent, regional variant, or a
        # short code-switched span; those tags are model metadata and must not
        # override the user's/LID router's immutable language decision or make
        # an otherwise valid transcription fail.
        return _without_language_tags(transcript, matches), None

    segments: list[dict[str, object]] = []
    cursor = 0
    for match, locale in matches:
        text = _canonical_fragment(transcript[cursor : match.start()])
        if not text:
            segments.append(
                _unknown_segment(
                    index=len(segments),
                    text="",
                    raw_tag=locale,
                    reason=_EMPTY_TAGGED_TEXT,
                )
            )
        elif locale in enabled:
            segments.append(
                {
                    "index": len(segments),
                    "text": text,
                    "status": "detected",
                    "languageBcp47": locale,
                    "rawLanguageTag": locale,
                    "reason": None,
                }
            )
        else:
            segments.append(
                _unknown_segment(
                    index=len(segments),
                    text=text,
                    raw_tag=locale,
                    reason=_DISABLED_TAG,
                )
            )
        cursor = match.end()

    trailing = _canonical_fragment(transcript[cursor:])
    if trailing or not matches:
        segments.append(
            _unknown_segment(
                index=len(segments),
                text=trailing,
                raw_tag=None,
                reason=_MISSING_TAG,
            )
        )
    display_text = canonical_transcript(
        " ".join(str(segment["text"]) for segment in segments if segment["text"]),
        "NeMo Nemotron display transcript",
    )
    return display_text, segments


class NemotronNemoStreamingEngine(NemotronAsrEngine):
    """Cache-aware NeMo/BF16 adapter for one locked Nemotron checkpoint."""

    def __init__(self, *, model_dir: Path, lock: ModelPoolLock) -> None:
        if lock.pool_id != "nemotron-batch":
            raise ValueError("NeMo Nemotron engine requires the Nemotron model lock")
        if lock.engine != "nemo":
            raise ValueError("NeMo Nemotron engine requires a NeMo model lock")
        if "auto" not in lock.supported_languages:
            raise ValueError("Nemotron model lock must include explicit auto mode")
        checkpoint_artifacts = [
            artifact for artifact in lock.artifacts if artifact.path.endswith(".nemo")
        ]
        if len(checkpoint_artifacts) != 1 or len(lock.artifacts) != 1:
            raise ValueError("the NeMo Nemotron lock must contain one .nemo checkpoint")
        checkpoint = model_dir / checkpoint_artifacts[0].path
        config_value = os.environ.get(NEMOTRON_STREAMING_CONFIG_ENV)
        if not config_value:
            raise RuntimeError("NeMo streaming configuration was not provided")
        config_path = Path(config_value)
        if not config_path.is_absolute():
            raise RuntimeError("NeMo streaming configuration path must be absolute")
        try:
            runtime = NemotronNemoPipeline(
                checkpoint=checkpoint,
                config_path=config_path,
            )
        except NemotronNemoPartialInitializationError:
            # No complete owner exists to close. Immediate process exit is the
            # only bounded cleanup boundary that cannot be stranded by Python
            # finalizers or partially initialized native worker threads.
            fail_stop_native_runtime()
        try:
            versions = {
                name: package_version(name)
                for name, _expected_version in lock.runtime_overlay_packages
            }
            if (
                versions != dict(lock.runtime_overlay_packages)
                or runtime.torch_version != lock.runtime_torch_version
                or runtime.torch_cuda_version != lock.runtime_torch_cuda_version
            ):
                raise RuntimeError("NeMo runtime identity differs from the model lock")
            prompts = _validated_model_prompt_dictionary(runtime.prompt_dictionary)
            fixed_locales = tuple(
                language
                for language in lock.supported_languages
                if language != "auto"
            )
            if any(locale not in prompts for locale in fixed_locales):
                raise RuntimeError("NeMo prompt catalog differs from the model lock")
        except BaseException:
            close_native_runtime_or_fail_stop(
                runtime.close,
                timeout_seconds=_NATIVE_RUNTIME_CLEANUP_TIMEOUT_SECONDS,
            )
            raise
        self._runtime = runtime
        self._lock = lock
        self._versions = versions
        self._fixed_locales = fixed_locales
        self._prompt_locales = tuple(prompts)
        self._closed = False

    @property
    def model_load_ms(self) -> int:
        return self._runtime.model_load_ms

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._runtime.close()

    def serving_identity(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "model": {
                "poolId": self._lock.pool_id,
                "id": self._lock.model_id,
                "revision": self._lock.model_revision,
            },
            "runtime": {
                "device": "cuda",
                "deviceName": self._runtime.device_name,
                "computeCapability": list(self._runtime.compute_capability),
                "pythonVersion": sys.version.split()[0],
                "torchVersion": self._runtime.torch_version,
                "torchCudaVersion": self._runtime.torch_cuda_version,
                "overlayPackages": dict(self._versions),
                "dtype": self._runtime.dtype,
                "servingEngine": "nemo-cache-aware",
                "servingEngineVersion": self._versions["nemo_toolkit"],
                "streamingChunkMs": round(
                    NEMOTRON_STREAMING_CHUNK_SECONDS * 1_000
                ),
                "attentionContext": list(NEMOTRON_STREAMING_ATTENTION_CONTEXT),
            },
            "capacity": {
                "maxActiveRequests": NEMOTRON_STREAMING_MAX_STREAMS,
            },
        }

    def _infer_utterance(
        self,
        request: NemotronAsrInput,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> NemotronUtteranceTranscript:
        self._validate_request(request, require_bounded_utterance=True)
        try:
            result = self._runtime.transcribe(
                pcm_bytes=request.audio.pcm_bytes,
                language=request.language,
                cancelled=cancelled,
            )
        except NemoStreamCancelled as error:
            raise NemotronInferenceCancelled(
                "Nemotron streaming inference was cancelled"
            ) from error
        transcript, segments = parse_nemo_transcript(
            result.raw_transcript,
            requested_language=request.language,
            prompt_locales=self._prompt_locales,
            enabled_locales=self._fixed_locales,
        )
        return NemotronUtteranceTranscript(
            text=transcript,
            language_segments=segments,
            inference_ms=result.inference_ms,
            inference_passes=result.inference_steps,
            max_batch_size=result.max_batch_size,
            queue_ms=result.queue_ms,
            total_ms=result.total_ms,
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
            "deviceName": self._runtime.device_name,
            "computeCapability": list(self._runtime.compute_capability),
            "pythonVersion": sys.version.split()[0],
            "torchVersion": self._lock.runtime_torch_version,
            "torchCudaVersion": self._lock.runtime_torch_cuda_version,
            "overlayPackages": dict(self._versions),
            "dtype": self._runtime.dtype,
            "modelLoadMs": self._runtime.model_load_ms,
            "inferenceMs": inference_ms,
            "batchSize": max_batch_size,
            "chunkCount": chunk_count,
            "inferencePasses": inference_passes,
            "queueMs": queue_ms,
            "totalRuntimeMs": total_ms,
            "servingEngine": "nemo-cache-aware",
            "servingEngineVersion": self._versions["nemo_toolkit"],
            "streamingChunkMs": round(NEMOTRON_STREAMING_CHUNK_SECONDS * 1_000),
            "attentionContext": list(NEMOTRON_STREAMING_ATTENTION_CONTEXT),
            "memory": self._runtime.memory_payload(),
        }


def _validated_model_prompt_dictionary(prompts: object) -> dict[str, int]:
    if not isinstance(prompts, Mapping) or not prompts or len(prompts) > 512:
        raise RuntimeError("NeMo checkpoint prompt catalog is invalid")
    validated: dict[str, int] = {}
    for locale, prompt_id in prompts.items():
        if not isinstance(locale, str):
            raise RuntimeError("NeMo checkpoint prompt catalog is invalid")
        if locale == "auto":
            canonical = locale
        else:
            try:
                canonical = canonical_bcp47(locale, "NeMo prompt locale")
            except ValueError:
                continue
        if (
            not isinstance(prompt_id, int)
            or isinstance(prompt_id, bool)
            or prompt_id < 0
            or (
                canonical in validated
                and validated[canonical] != prompt_id
            )
        ):
            raise RuntimeError("NeMo checkpoint prompt catalog is invalid")
        validated[canonical] = prompt_id
    if "auto" not in validated:
        raise RuntimeError("NeMo checkpoint prompt catalog omits automatic mode")
    return validated


def _validated_prompt_locales(value: Sequence[str]) -> frozenset[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
        or len(value) > 512
    ):
        raise RuntimeError("NeMo prompt catalog is invalid")
    prompts: set[str] = set()
    for locale in value:
        if locale == "auto":
            continue
        prompts.add(canonical_bcp47(locale, "NeMo prompt locale"))
    if not prompts:
        raise RuntimeError("NeMo prompt catalog contains no fixed locale")
    return frozenset(prompts)


def _validated_enabled_locales(value: Sequence[str]) -> frozenset[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
        or len(value) > 256
    ):
        raise RuntimeError("NeMo enabled locale catalog is invalid")
    enabled = frozenset(
        canonical_bcp47(locale, "NeMo enabled locale") for locale in value
    )
    if len(enabled) != len(value):
        raise RuntimeError("NeMo enabled locale catalog contains duplicates")
    return enabled


def _without_language_tags(
    transcript: str,
    matches: Sequence[tuple[re.Match[str], str]],
) -> str:
    parts: list[str] = []
    cursor = 0
    for match, _locale in matches:
        parts.append(transcript[cursor : match.start()])
        cursor = match.end()
    parts.append(transcript[cursor:])
    return canonical_transcript(
        " ".join("".join(parts).split()),
        "NeMo Nemotron display transcript",
    )


def _canonical_fragment(value: str) -> str:
    return canonical_transcript(
        " ".join(value.split()),
        "NeMo Nemotron transcript segment",
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
