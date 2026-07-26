from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading

from yap_server.pools.batch_contract import AsrRouteDecision, BatchAsrJob
from yap_server.pools.utterance_plan import (
    UtterancePlanSource,
    publish_utterance_plan,
)

from .artifacts import PcmChunkSource, publish_wav, sha256_file


class BatchInputIntegrityError(ValueError):
    """Uploaded PCM no longer agrees with its immutable declarations."""


class BatchInputStorageError(OSError):
    """Private input preparation could not complete its bounded I/O."""


@dataclass(frozen=True, slots=True)
class BatchInputPreparation:
    """Immutable recipe executed only after bounded GPU capacity is reserved."""

    job_id: str
    job_root: Path
    chunk_sources: tuple[PcmChunkSource, ...]
    language: str
    language_bcp47: str
    route: AsrRouteDecision
    expected_output_pcm_sha256: str | None
    utterance_plan_source: UtterancePlanSource | None

    @property
    def pcm_byte_length(self) -> int:
        length = sum(source.byte_length for source in self.chunk_sources)
        if length < 1:
            raise ValueError("batch input preparation requires PCM bytes")
        return length

    def prepare(self, cancellation: threading.Event) -> BatchAsrJob:
        input_path = self.job_root / "input.wav"
        try:
            output_pcm_sha256 = publish_wav(
                input_path,
                self.chunk_sources,
                cancellation=cancellation,
            )
        except ValueError as error:
            raise BatchInputIntegrityError(
                "uploaded PCM failed immutable identity verification"
            ) from error
        except OSError as error:
            raise BatchInputStorageError(
                "private input publication failed"
            ) from error
        if (
            self.expected_output_pcm_sha256 is not None
            and output_pcm_sha256 != self.expected_output_pcm_sha256
        ):
            raise BatchInputIntegrityError(
                "uploaded PCM differs from preprocessing evidence"
            )
        try:
            input_sha256 = sha256_file(input_path, cancellation=cancellation)
        except OSError as error:
            raise BatchInputStorageError("private input hashing failed") from error
        utterance_plan_path: Path | None = None
        utterance_plan_sha256: str | None = None
        if self.utterance_plan_source is not None:
            if self.utterance_plan_source.input_sample_count != self.pcm_byte_length // 2:
                raise BatchInputIntegrityError(
                    "utterance plan source differs from the uploaded PCM"
                )
            utterance_plan_path = self.job_root / "utterance-plan.json"
            try:
                utterance_plan_sha256 = publish_utterance_plan(
                    utterance_plan_path,
                    self.utterance_plan_source.build(input_sha256),
                    cancellation=cancellation,
                )
            except ValueError as error:
                raise BatchInputIntegrityError(
                    "bounded utterance planning rejected the admitted evidence"
                ) from error
            except OSError as error:
                raise BatchInputStorageError(
                    "private utterance plan publication failed"
                ) from error
        return BatchAsrJob(
            job_id=self.job_id,
            input_path=input_path,
            result_path=self.job_root / "worker-result.json",
            language=self.language,
            input_sha256=input_sha256,
            route=self.route,
            utterance_plan_path=utterance_plan_path,
            utterance_plan_sha256=utterance_plan_sha256,
        )
