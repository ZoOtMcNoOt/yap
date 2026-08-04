from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Protocol

from yap_server.meeting_transcription.runtime_provenance import (
    MeetingRuntimeProvenance,
    load_meeting_runtime_provenance,
    verify_repository_source_directory,
)
from yap_server.limits import MAX_WORKER_RESULT_BYTES
from yap_server.pools import pcm_audio
from yap_server.pools.batch_contract import validate_batch_job_id

from .contract import MAX_MEETING_DURATION_SECONDS
from .speaker_capacity import speaker_capacity_degradation_to_wire
from .source_time_epoch_transcription import (
    SpeakerEmbeddingEncoder,
    SpeechBrainSpeakerEncoder,
    SourceTimeMeetingTranscription,
    transcribe_source_time_epochs,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_LANGUAGE = re.compile(r"^[A-Za-z][A-Za-z-]{0,34}$")


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


def transcribe_meeting(
    *,
    request: MeetingWorkerRequest,
    audio: pcm_audio.PcmAudio,
    runtime_lock_sha256: str,
    application_revision: str,
    provenance: MeetingRuntimeProvenance,
    engine: TironEngine,
    speaker_encoder: SpeakerEmbeddingEncoder,
) -> dict[str, object]:
    if request.input_sha256 != audio.sha256:
        raise ValueError("meeting input SHA-256 differs from the canonical audio")
    if _SHA256.fullmatch(runtime_lock_sha256) is None:
        raise ValueError("meeting runtime lock SHA-256 is invalid")
    if _GIT_SHA.fullmatch(application_revision) is None:
        raise ValueError("meeting application revision is invalid")
    with redirect_stdout(sys.stderr):
        transcription = transcribe_source_time_epochs(
            audio=audio,
            engine=engine,
            language=request.language,
            speaker_encoder=speaker_encoder,
        )
    return {
        "schemaVersion": 1,
        "jobId": request.job_id,
        "captureManifestSha256": request.capture_manifest_sha256,
        "model": {
            "id": provenance.model.identifier,
            "revision": provenance.model.revision,
            "runtimeHarnessRevision": provenance.harness.revision,
            "speakerEncoderRevision": provenance.speaker_encoder.revision,
            "applicationRevision": application_revision,
            "runtimeLockSha256": runtime_lock_sha256,
        },
        "audio": {
            "sha256": audio.sha256,
            "durationMs": audio.duration_ms,
            "sampleRateHz": audio.sample_rate,
            "frameCount": audio.frame_count,
        },
        "meeting": _meeting_payload(transcription),
        "runtime": {
            "device": "cuda:0",
            "dtype": "bfloat16",
            "constrainedDecoding": True,
            "twoPass": True,
        },
    }


def _meeting_payload(
    transcription: SourceTimeMeetingTranscription,
) -> dict[str, object]:
    degradation = transcription.capacity_degradation
    return {
        "language": transcription.language,
        "sessionSpeakerIds": list(transcription.session_speaker_ids),
        "turns": [
            {
                "index": index,
                "sessionSpeakerId": turn.session_speaker_id,
                "startSample": turn.start_sample,
                "endSample": turn.end_sample,
                "text": turn.text,
            }
            for index, turn in enumerate(transcription.turns)
        ],
        "numDecodeWindows": transcription.num_decode_windows,
        "sourceTimeUnit": "samples",
        "speakerCapacityDegradation": speaker_capacity_degradation_to_wire(degradation),
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
    parser.add_argument("--application-revision", required=True)
    return parser


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
        speaker_encoder = SpeechBrainSpeakerEncoder(getattr(engine, "ecapa", None))
        result = transcribe_meeting(
            request=request,
            audio=audio,
            runtime_lock_sha256=runtime_lock_sha256,
            application_revision=arguments.application_revision,
            provenance=provenance,
            engine=engine,
            speaker_encoder=speaker_encoder,
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
