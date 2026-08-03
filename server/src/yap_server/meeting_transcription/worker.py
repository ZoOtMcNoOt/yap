from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Mapping, Protocol

from yap_server.meeting_transcription.runtime_provenance import (
    MeetingRuntimeProvenance,
    load_meeting_runtime_provenance,
    verify_repository_source_directory,
)
from yap_server.limits import MAX_TRANSCRIPT_BYTES, MAX_WORKER_RESULT_BYTES
from yap_server.pools import pcm_audio
from yap_server.pools.batch_contract import validate_batch_job_id

from .contract import (
    MAX_MEETING_DURATION_SECONDS,
    MAX_MEETING_SEGMENT_COUNT,
    MAX_MEETING_SPEAKERS,
    is_meeting_speaker_id,
    maximum_upstream_window_count,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE = re.compile(r"^[A-Za-z][A-Za-z-]{0,34}$")
_UPSTREAM_RESULT_KEYS = {
    "duration",
    "language",
    "speakers",
    "segments",
    "num_chunks",
    "elapsed_s",
    "two_pass",
}
_UPSTREAM_SEGMENT_KEYS = {"speaker", "start", "end", "text"}
_MAX_DIAGNOSTIC_BYTES = 64 * 1024


class TironEngine(Protocol):
    def transcribe(
        self,
        audio: str,
        *,
        language: str,
        max_speakers: int,
        two_pass: bool,
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class MeetingWorkerRequest:
    job_id: str
    input_sha256: str
    capture_manifest_sha256: str
    language: str
    max_speakers: int

    def __post_init__(self) -> None:
        validate_batch_job_id(self.job_id)
        for value, field in (
            (self.input_sha256, "input SHA-256"),
            (self.capture_manifest_sha256, "capture manifest SHA-256"),
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"{field} is invalid")
        if self.language != "auto" and _LANGUAGE.fullmatch(self.language) is None:
            raise ValueError("meeting language is invalid")
        if (
            not isinstance(self.max_speakers, int)
            or isinstance(self.max_speakers, bool)
            or not 1 <= self.max_speakers <= MAX_MEETING_SPEAKERS
        ):
            raise ValueError("meeting max speakers must be between one and eight")


def transcribe_meeting(
    *,
    request: MeetingWorkerRequest,
    input_path: Path,
    audio: pcm_audio.PcmAudio,
    runtime_lock_sha256: str,
    provenance: MeetingRuntimeProvenance,
    engine: TironEngine,
) -> dict[str, object]:
    if request.input_sha256 != audio.sha256:
        raise ValueError("meeting input SHA-256 differs from the canonical audio")
    if _SHA256.fullmatch(runtime_lock_sha256) is None:
        raise ValueError("meeting runtime lock SHA-256 is invalid")
    resolved_input = input_path.resolve(strict=True)
    with redirect_stdout(sys.stderr):
        raw_result = engine.transcribe(
            str(resolved_input),
            language=request.language,
            max_speakers=request.max_speakers,
            two_pass=True,
        )
    meeting = _validated_meeting_result(raw_result, audio)
    return {
        "schemaVersion": 1,
        "jobId": request.job_id,
        "captureManifestSha256": request.capture_manifest_sha256,
        "model": {
            "id": provenance.model.identifier,
            "revision": provenance.model.revision,
            "runtimeHarnessRevision": provenance.harness.revision,
            "speakerEncoderRevision": provenance.speaker_encoder.revision,
            "runtimeLockSha256": runtime_lock_sha256,
        },
        "audio": {
            "sha256": audio.sha256,
            "durationMs": audio.duration_ms,
            "sampleRateHz": audio.sample_rate,
            "frameCount": audio.frame_count,
        },
        "meeting": meeting,
        "runtime": {
            "device": "cuda:0",
            "dtype": "bfloat16",
            "constrainedDecoding": True,
            "twoPass": True,
        },
    }


def _validated_meeting_result(
    value: object,
    audio: pcm_audio.PcmAudio,
) -> dict[str, object]:
    result = _exact_mapping(value, _UPSTREAM_RESULT_KEYS, "Tiron result")
    source_duration = audio.frame_count / audio.sample_rate
    duration = _finite_number(result["duration"], "Tiron duration")
    if abs(duration - source_duration) > 0.011:
        raise ValueError("Tiron duration differs from the canonical source")

    language = result["language"]
    if not isinstance(language, str) or _LANGUAGE.fullmatch(language) is None:
        raise ValueError("Tiron language is invalid")
    raw_speakers = result["speakers"]
    if (
        not isinstance(raw_speakers, list)
        or len(raw_speakers) > MAX_MEETING_SPEAKERS
        or any(not is_meeting_speaker_id(item) for item in raw_speakers)
        or raw_speakers != sorted(set(raw_speakers))
    ):
        raise ValueError("Tiron speakers are invalid")

    raw_segments = result["segments"]
    if (
        not isinstance(raw_segments, list)
        or len(raw_segments) > MAX_MEETING_SEGMENT_COUNT
    ):
        raise ValueError("Tiron segments exceed the bounded contract")
    segments: list[dict[str, object]] = []
    transcript_bytes = 0
    previous_start = -1
    observed_speakers: set[str] = set()
    for index, raw_segment in enumerate(raw_segments):
        segment = _exact_mapping(
            raw_segment,
            _UPSTREAM_SEGMENT_KEYS,
            f"Tiron segment {index}",
        )
        speaker = segment["speaker"]
        text = segment["text"]
        if not is_meeting_speaker_id(speaker):
            raise ValueError("Tiron segment speaker is invalid")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Tiron segment text is invalid")
        transcript_bytes += len(text.encode("utf-8"))
        if transcript_bytes > MAX_TRANSCRIPT_BYTES:
            raise ValueError("Tiron transcript exceeds the bounded contract")
        start = _finite_number(segment["start"], "Tiron segment start")
        end = _finite_number(segment["end"], "Tiron segment end")
        start_sample = round(start * audio.sample_rate)
        end_sample = round(end * audio.sample_rate)
        if (
            start_sample < 0
            or start_sample < previous_start
            or end_sample <= start_sample
            or end_sample > audio.frame_count
        ):
            raise ValueError("Tiron segment source bounds are invalid")
        previous_start = start_sample
        observed_speakers.add(speaker)
        segments.append(
            {
                "index": index,
                "speaker": speaker,
                "startSample": start_sample,
                "endSample": end_sample,
                "text": text,
            }
        )
    if observed_speakers != set(raw_speakers):
        raise ValueError("Tiron speaker inventory differs from its segments")

    num_chunks = result["num_chunks"]
    maximum_chunks = maximum_upstream_window_count(source_duration)
    if (
        not isinstance(num_chunks, int)
        or isinstance(num_chunks, bool)
        or not 1 <= num_chunks <= maximum_chunks
    ):
        raise ValueError("Tiron chunk count is invalid")
    elapsed = _finite_number(result["elapsed_s"], "Tiron elapsed time")
    if elapsed < 0:
        raise ValueError("Tiron elapsed time is invalid")
    try:
        diagnostics = json.dumps(
            result["two_pass"],
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("Tiron two-pass diagnostics are invalid") from error
    if len(diagnostics) > _MAX_DIAGNOSTIC_BYTES:
        raise ValueError("Tiron two-pass diagnostics exceed the bounded contract")

    return {
        "language": language,
        "speakers": raw_speakers,
        "segments": segments,
        "numWindows": num_chunks,
        "sourceTimeUnit": "samples",
    }


def _load_engine(model_dir: Path, speaker_encoder_dir: Path) -> TironEngine:
    from tiron import config
    from tiron.engine import TironEngine as UpstreamTironEngine

    config.ECAPA_MODEL = str(speaker_encoder_dir)
    return UpstreamTironEngine(
        model_id=str(model_dir),
        device="cuda:0",
        dtype="bf16",
        ecapa_device="cuda:0",
        constrained_decoding=True,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one isolated offline Tiron meeting-transcription job"
    )
    parser.add_argument(
        "--runtime-lock",
        default=os.environ.get("YAP_MEETING_TRANSCRIPTION_RUNTIME_LOCK"),
    )
    parser.add_argument(
        "--model-dir",
        default=os.environ.get("YAP_TIRON_MODEL_DIR"),
    )
    parser.add_argument(
        "--speaker-encoder-dir",
        default=os.environ.get("YAP_TIRON_ECAPA_DIR"),
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--capture-manifest-sha256", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--max-speakers", type=int, default=8)
    return parser


def _exact_mapping(
    value: object,
    keys: set[str],
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{field} fields are invalid")
    return value


def _finite_number(value: object, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValueError(f"{field} is invalid")
    return float(value)


def _emit_error(code: str, message: str) -> None:
    print(
        json.dumps(
            {"schemaVersion": 1, "code": code, "message": message},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if (
        not arguments.runtime_lock
        or not arguments.model_dir
        or not arguments.speaker_encoder_dir
    ):
        _emit_error(
            "MEETING_WORKER_COMPONENT_INVALID",
            "the runtime lock and verified model directories are required",
        )
        return 2
    try:
        request = MeetingWorkerRequest(
            job_id=arguments.job_id,
            input_sha256=arguments.input_sha256,
            capture_manifest_sha256=arguments.capture_manifest_sha256,
            language=arguments.language,
            max_speakers=arguments.max_speakers,
        )
        runtime_lock_path = Path(arguments.runtime_lock).resolve(strict=True)
        runtime_lock_bytes = runtime_lock_path.read_bytes()
        if len(runtime_lock_bytes) > 256 * 1024:
            raise ValueError("meeting runtime lock exceeds the bounded contract")
        runtime_lock_sha256 = hashlib.sha256(runtime_lock_bytes).hexdigest()
        provenance = load_meeting_runtime_provenance(runtime_lock_path)
        model_dir = verify_repository_source_directory(
            provenance.model,
            Path(arguments.model_dir),
        )
        speaker_encoder_dir = verify_repository_source_directory(
            provenance.speaker_encoder,
            Path(arguments.speaker_encoder_dir),
        )
        input_path = Path(arguments.input)
        audio = pcm_audio.read_pcm16_wav(
            input_path,
            max_audio_seconds=MAX_MEETING_DURATION_SECONDS,
        )
        engine = _load_engine(model_dir, speaker_encoder_dir)
        result = transcribe_meeting(
            request=request,
            input_path=input_path,
            audio=audio,
            runtime_lock_sha256=runtime_lock_sha256,
            provenance=provenance,
            engine=engine,
        )
        encoded = json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(encoded.encode("utf-8")) > MAX_WORKER_RESULT_BYTES:
            raise ValueError("meeting worker result exceeds the bounded contract")
    except (OSError, ValueError) as error:
        _emit_error("MEETING_WORKER_INPUT_INVALID", str(error))
        return 2
    except Exception:
        _emit_error("MEETING_WORKER_INFERENCE_FAILED", "meeting transcription failed")
        return 1
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
