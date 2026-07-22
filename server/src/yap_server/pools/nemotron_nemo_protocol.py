from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from yap_server.pools.batch_contract import validate_batch_job_id


NEMOTRON_NEMO_READY_PATH = "/ready"
NEMOTRON_NEMO_TRANSCRIPTION_PATH = "/v1/transcriptions"
NEMOTRON_NEMO_PROTOCOL_VERSION = 1
NEMOTRON_NEMO_MAX_REQUEST_BYTES = 16 * 1024
NEMOTRON_NEMO_MAX_ACTIVE_REQUESTS = 8

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_PATH_CHARACTERS = 4_096
_MAX_LANGUAGE_CHARACTERS = 64


@dataclass(frozen=True, slots=True)
class NemotronNemoServiceRequest:
    job_id: str
    input_path: str
    input_sha256: str
    utterance_plan_path: str
    utterance_plan_sha256: str
    language: str
    punctuation: bool

    def __post_init__(self) -> None:
        validate_batch_job_id(self.job_id)
        for value in (self.input_path, self.utterance_plan_path):
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= _MAX_PATH_CHARACTERS
                or any(character in value for character in ("\0", "\r", "\n"))
            ):
                raise ValueError("Nemotron NeMo request path is invalid")
        if (
            _SHA256.fullmatch(self.input_sha256) is None
            or _SHA256.fullmatch(self.utterance_plan_sha256) is None
        ):
            raise ValueError("Nemotron NeMo request identity is invalid")
        if (
            not isinstance(self.language, str)
            or not 1 <= len(self.language) <= _MAX_LANGUAGE_CHARACTERS
            or any(character.isspace() for character in self.language)
        ):
            raise ValueError("Nemotron NeMo request language is invalid")
        if not isinstance(self.punctuation, bool):
            raise ValueError("Nemotron NeMo punctuation flag is invalid")

    def to_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": NEMOTRON_NEMO_PROTOCOL_VERSION,
            "jobId": self.job_id,
            "inputPath": self.input_path,
            "inputSha256": self.input_sha256,
            "utterancePlanPath": self.utterance_plan_path,
            "utterancePlanSha256": self.utterance_plan_sha256,
            "language": self.language,
            "punctuation": self.punctuation,
        }

    @classmethod
    def from_payload(cls, value: object) -> NemotronNemoServiceRequest:
        expected_fields = {
            "schemaVersion",
            "jobId",
            "inputPath",
            "inputSha256",
            "utterancePlanPath",
            "utterancePlanSha256",
            "language",
            "punctuation",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != expected_fields
            or value.get("schemaVersion") != NEMOTRON_NEMO_PROTOCOL_VERSION
        ):
            raise ValueError("Nemotron NeMo request fields are invalid")
        return cls(
            job_id=value["jobId"],  # type: ignore[arg-type]
            input_path=value["inputPath"],  # type: ignore[arg-type]
            input_sha256=value["inputSha256"],  # type: ignore[arg-type]
            utterance_plan_path=value["utterancePlanPath"],  # type: ignore[arg-type]
            utterance_plan_sha256=value["utterancePlanSha256"],  # type: ignore[arg-type]
            language=value["language"],  # type: ignore[arg-type]
            punctuation=value["punctuation"],  # type: ignore[arg-type]
        )


def cancellation_path(job_id: str) -> str:
    validate_batch_job_id(job_id)
    return f"{NEMOTRON_NEMO_TRANSCRIPTION_PATH}/{job_id}"
