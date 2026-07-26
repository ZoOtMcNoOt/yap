from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import re
import sys

from yap_server.pools.model_lock import (
    ModelPoolLock,
    load_model_pool_lock,
    verify_model_artifacts,
)
from yap_server.pools.pcm_audio import (
    MAX_AUDIO_SECONDS,
    MAX_ENCODED_AUDIO_BYTES,
    SAMPLE_RATE_HZ,
    PcmAudio,
    PcmWavSnapshot,
    WorkerInputError,
    decode_pcm16_wav,
    read_pcm16_wav,
    read_pcm16_wav_snapshot,
)
from yap_server.pools.utterance_plan import UtterancePlan, read_utterance_plan


__all__ = [
    "MAX_AUDIO_SECONDS",
    "MAX_ENCODED_AUDIO_BYTES",
    "SAMPLE_RATE_HZ",
    "PcmAudio",
    "PcmWavSnapshot",
    "WorkerInputError",
    "decode_pcm16_wav",
    "read_pcm16_wav",
    "read_pcm16_wav_snapshot",
    "transcribe",
]

_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_job_id(value: str) -> str:
    if not _JOB_ID.fullmatch(value):
        raise WorkerInputError("job id must be an opaque path-safe identifier")
    return value


def transcribe(
    *,
    job_id: str,
    model_dir: Path,
    lock: ModelPoolLock,
    audio: PcmAudio,
    language: str,
    punctuation: bool,
    utterance_plan: UtterancePlan | None = None,
) -> dict[str, object]:
    if lock.pool_id == "cohere-batch":
        if lock.engine != "transformers":
            raise WorkerInputError(
                "the isolated Cohere worker requires a Transformers model lock"
            )
        if utterance_plan is not None:
            raise WorkerInputError("Cohere batch work does not consume an utterance plan")
        from yap_server.pools.cohere_engine import CohereAsrEngine, CohereAsrInput

        with redirect_stdout(sys.stderr):
            engine = CohereAsrEngine(model_dir=model_dir, lock=lock)
            result = engine.transcribe_batch(
                [
                    CohereAsrInput(
                        job_id=job_id,
                        audio=audio,
                        language=language,
                        punctuation=punctuation,
                    )
                ]
            )[0]
        return result
    if lock.pool_id == "nemotron-batch":
        from yap_server.pools.nemotron_engine import NemotronAsrInput

        if utterance_plan is None:
            raise WorkerInputError("Nemotron batch work requires an utterance plan")
        with redirect_stdout(sys.stderr):
            engine = None
            if lock.engine == "transformers":
                from yap_server.pools.nemotron_engine import NemotronAsrEngine

                engine = NemotronAsrEngine(model_dir=model_dir, lock=lock)
            elif lock.engine == "nemo":
                from yap_server.pools.nemotron_nemo_streaming import (
                    NemotronNemoStreamingEngine,
                )

                engine = NemotronNemoStreamingEngine(model_dir=model_dir, lock=lock)
            else:
                raise WorkerInputError(
                    "Nemotron model lock selects an unsupported engine"
                )
            try:
                result = engine.transcribe_recording(
                    NemotronAsrInput(
                        job_id=job_id,
                        audio=audio,
                        language=language,
                        punctuation=punctuation,
                    ),
                    utterance_plan,
                )
            finally:
                close = getattr(engine, "close", None)
                if callable(close):
                    close()
        return result
    raise WorkerInputError("model pool has no checked reference engine")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one isolated offline batch-ASR job")
    parser.add_argument("--lock", default=os.environ.get("YAP_MODEL_LOCK"))
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--utterance-plan")
    parser.add_argument("--utterance-plan-sha256")
    parser.add_argument("--no-punctuation", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if not arguments.lock:
            raise WorkerInputError("a model lock is required")
        job_id = validate_job_id(arguments.job_id)
        lock = load_model_pool_lock(Path(arguments.lock))
        if arguments.language not in lock.supported_languages:
            raise WorkerInputError("language is not supported by the locked model")
        model_dir = Path(arguments.model_dir).resolve(strict=True)
        verify_model_artifacts(lock, model_dir)
        audio = read_pcm16_wav(Path(arguments.input).resolve(strict=True))
        if bool(arguments.utterance_plan) != bool(arguments.utterance_plan_sha256):
            raise WorkerInputError(
                "utterance plan path and identity must be supplied together"
            )
        utterance_plan = None
        if arguments.utterance_plan:
            utterance_plan = read_utterance_plan(
                Path(arguments.utterance_plan).resolve(strict=True),
                expected_sha256=arguments.utterance_plan_sha256,
                expected_input_wav_sha256=audio.sha256,
                expected_input_sample_count=audio.frame_count,
            )
        result = transcribe(
            job_id=job_id,
            model_dir=model_dir,
            lock=lock,
            audio=audio,
            language=arguments.language,
            punctuation=not arguments.no_punctuation,
            utterance_plan=utterance_plan,
        )
    except (OSError, ValueError) as error:
        payload = {
            "schemaVersion": 1,
            "code": "WORKER_INPUT_INVALID",
            "message": str(error),
        }
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
