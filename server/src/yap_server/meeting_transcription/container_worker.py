from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
from typing import Callable, Mapping
from uuid import uuid4

from yap_server.meeting_transcription.runtime_provenance import (
    MeetingRuntimeProvenance,
    load_meeting_runtime_provenance,
)
from yap_server.limits import MAX_TRANSCRIPT_BYTES, MAX_WORKER_RESULT_BYTES
from yap_server.pools.batch_contract import (
    WorkerExecutionError,
    validate_batch_job_id,
)
from yap_server.pools.batch_result import publish_result
from yap_server.pools.container_runtime import (
    CONTAINER_LABEL_VALUE,
    JOB_LABEL,
    OWNER_LABEL,
    OWNER_VALUE,
    REVISION_LABEL,
    RUNTIME_LABEL,
    STORAGE_LABEL,
    force_remove_container,
    run_bounded_process,
    validate_worker_output,
)
from yap_server.transcript_text import canonical_transcript

from .contract import (
    MAX_MEETING_FRAME_COUNT,
    MAX_MEETING_SEGMENT_COUNT,
    MAX_MEETING_SPEAKERS,
    MEETING_SAMPLE_RATE_HZ,
    is_meeting_speaker_id,
    maximum_upstream_window_count,
)


_IMAGE = re.compile(r"^(?:sha256:[0-9a-f]{64}|.+@sha256:[0-9a-f]{64})$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE = re.compile(r"^[A-Za-z][A-Za-z-]{0,34}$")
_MEMORY_LIMIT = "48g"
_CPU_LIMIT = "8"


@dataclass(frozen=True, slots=True)
class MeetingTranscriptionJob:
    job_id: str
    input_path: Path
    result_path: Path
    input_sha256: str
    capture_manifest_sha256: str
    language: str
    max_speakers: int
    frame_count: int

    def __post_init__(self) -> None:
        validate_batch_job_id(self.job_id)
        for value, field in (
            (self.input_sha256, "input SHA-256"),
            (self.capture_manifest_sha256, "capture manifest SHA-256"),
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"meeting {field} is invalid")
        if self.language != "auto" and _LANGUAGE.fullmatch(self.language) is None:
            raise ValueError("meeting language is invalid")
        if (
            not isinstance(self.max_speakers, int)
            or isinstance(self.max_speakers, bool)
            or not 1 <= self.max_speakers <= MAX_MEETING_SPEAKERS
        ):
            raise ValueError("meeting max speakers must be between one and eight")
        if (
            not isinstance(self.frame_count, int)
            or isinstance(self.frame_count, bool)
            or not 1 <= self.frame_count <= MAX_MEETING_FRAME_COUNT
        ):
            raise ValueError("meeting frame count is outside the runtime boundary")

    @property
    def duration_ms(self) -> int:
        return max(1, round(self.frame_count * 1_000 / MEETING_SAMPLE_RATE_HZ))


class ContainerMeetingTranscriptionWorker:
    """Runs one pinned upstream Tiron meeting job in an isolated container."""

    def __init__(
        self,
        *,
        image: str,
        model_dir: Path,
        speaker_encoder_dir: Path,
        runtime_lock_path: Path,
        run_as_uid: int,
        run_as_gid: int,
        checked_head: str,
        storage_namespace: str,
        runtime_instance_id: str | None = None,
        docker_binary: str = "docker",
        timeout_seconds: float = 3 * 60 * 60,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        if _IMAGE.fullmatch(image) is None:
            raise ValueError("meeting worker image must use an immutable identity")
        if _GIT_SHA.fullmatch(checked_head) is None:
            raise ValueError("meeting worker checked head must be a full Git SHA")
        if timeout_seconds <= 0:
            raise ValueError("meeting worker timeout must be positive")
        if CONTAINER_LABEL_VALUE.fullmatch(storage_namespace) is None:
            raise ValueError("meeting worker storage namespace is invalid")
        resolved_runtime_id = runtime_instance_id or uuid4().hex
        if CONTAINER_LABEL_VALUE.fullmatch(resolved_runtime_id) is None:
            raise ValueError("meeting worker runtime instance ID is invalid")
        if (
            not isinstance(run_as_uid, int)
            or isinstance(run_as_uid, bool)
            or run_as_uid < 1
            or not isinstance(run_as_gid, int)
            or isinstance(run_as_gid, bool)
            or run_as_gid < 1
        ):
            raise ValueError(
                "meeting worker identity must be an explicit non-root UID/GID"
            )

        lock_path = runtime_lock_path.resolve(strict=True)
        lock_bytes = lock_path.read_bytes()
        if len(lock_bytes) > 256 * 1024:
            raise ValueError("meeting runtime lock exceeds the bounded contract")
        self._provenance = load_meeting_runtime_provenance(lock_path)
        self._runtime_lock_sha256 = hashlib.sha256(lock_bytes).hexdigest()
        self._image = image
        self._model_dir = _mount_directory(model_dir, "Tiron model")
        self._speaker_encoder_dir = _mount_directory(
            speaker_encoder_dir,
            "Tiron speaker encoder",
        )
        self._run_as_identity = f"{run_as_uid}:{run_as_gid}"
        self._run_as_uid = run_as_uid
        self._run_as_gid = run_as_gid
        self._checked_head = checked_head
        self._storage_namespace = storage_namespace
        self._runtime_instance_id = resolved_runtime_id
        self._docker_binary = docker_binary
        self._timeout_seconds = timeout_seconds
        self._runner = runner
        self._shutdown = threading.Event()

    def close(self) -> None:
        self._shutdown.set()

    def build_command(self, job: MeetingTranscriptionJob) -> list[str]:
        return self._build_command(
            job,
            container_name=f"yap-meeting-transcription-{uuid4().hex}",
        )

    def _build_command(
        self,
        job: MeetingTranscriptionJob,
        *,
        container_name: str,
    ) -> list[str]:
        input_path = _mount_file(job.input_path, "meeting input")
        return [
            self._docker_binary,
            "run",
            "--rm",
            "--name",
            container_name,
            "--label",
            f"{OWNER_LABEL}={OWNER_VALUE}",
            "--label",
            f"{STORAGE_LABEL}={self._storage_namespace}",
            "--label",
            f"{RUNTIME_LABEL}={self._runtime_instance_id}",
            "--label",
            f"{JOB_LABEL}={job.job_id}",
            "--label",
            f"{REVISION_LABEL}={self._checked_head}",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            self._run_as_identity,
            "--pids-limit",
            "512",
            "--memory",
            _MEMORY_LIMIT,
            "--memory-swap",
            _MEMORY_LIMIT,
            "--cpus",
            _CPU_LIMIT,
            "--shm-size",
            "1g",
            "--tmpfs",
            (
                "/tmp:rw,nosuid,nodev,noexec,size=4g,mode=1777,"
                f"uid={self._run_as_uid},gid={self._run_as_gid}"
            ),
            "--device",
            "nvidia.com/gpu=all",
            "--env",
            "HF_HUB_OFFLINE=1",
            "--env",
            "TRANSFORMERS_OFFLINE=1",
            "--env",
            "HF_HUB_DISABLE_TELEMETRY=1",
            "--env",
            "DO_NOT_TRACK=1",
            "--mount",
            f"type=bind,src={self._model_dir},dst=/models/tiron,readonly",
            "--mount",
            (f"type=bind,src={self._speaker_encoder_dir},dst=/models/ecapa,readonly"),
            "--mount",
            f"type=bind,src={input_path},dst=/input/audio.wav,readonly",
            self._image,
            "--runtime-lock",
            "/opt/yap-server/meeting-transcription-runtime.lock.json",
            "--model-dir",
            "/models/tiron",
            "--speaker-encoder-dir",
            "/models/ecapa",
            "--input",
            "/input/audio.wav",
            "--input-sha256",
            job.input_sha256,
            "--capture-manifest-sha256",
            job.capture_manifest_sha256,
            "--job-id",
            job.job_id,
            "--language",
            job.language,
            "--max-speakers",
            str(job.max_speakers),
        ]

    def run(
        self,
        job: MeetingTranscriptionJob,
        cancellation: threading.Event | None = None,
    ) -> dict[str, object]:
        job_cancellation = cancellation or threading.Event()
        if self._shutdown.is_set() or job_cancellation.is_set():
            raise WorkerExecutionError("meeting transcription worker was cancelled")
        container_name = f"yap-meeting-transcription-{uuid4().hex}"
        command = self._build_command(job, container_name=container_name)
        if self._runner is None:
            try:
                completed = run_bounded_process(
                    command,
                    timeout_seconds=self._timeout_seconds,
                    output_limit_bytes=MAX_WORKER_RESULT_BYTES,
                    cancellation=(self._shutdown, job_cancellation),
                )
            finally:
                force_remove_container(self._docker_binary, container_name)
        else:
            completed = self._runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
        validate_worker_output(completed)
        if completed.returncode != 0:
            raise WorkerExecutionError(
                f"meeting transcription worker exited with status {completed.returncode}"
            )
        try:
            payload = json.loads(completed.stdout)
            result = validate_meeting_worker_result(
                payload,
                job=job,
                provenance=self._provenance,
                runtime_lock_sha256=self._runtime_lock_sha256,
            )
        except (json.JSONDecodeError, ValueError) as error:
            raise WorkerExecutionError(
                "meeting transcription worker returned an invalid result"
            ) from error
        publish_result(job.result_path, result)
        return result


def validate_meeting_worker_result(
    value: object,
    *,
    job: MeetingTranscriptionJob,
    provenance: MeetingRuntimeProvenance,
    runtime_lock_sha256: str,
) -> dict[str, object]:
    result = _exact_mapping(
        value,
        {
            "schemaVersion",
            "jobId",
            "captureManifestSha256",
            "model",
            "audio",
            "meeting",
            "runtime",
        },
        "meeting worker result",
    )
    if (
        result["schemaVersion"] != 1
        or result["jobId"] != job.job_id
        or result["captureManifestSha256"] != job.capture_manifest_sha256
    ):
        raise ValueError("meeting worker result identity is invalid")

    model = _exact_mapping(
        result["model"],
        {
            "id",
            "revision",
            "runtimeHarnessRevision",
            "speakerEncoderRevision",
            "runtimeLockSha256",
        },
        "meeting worker model",
    )
    if model != {
        "id": provenance.model.identifier,
        "revision": provenance.model.revision,
        "runtimeHarnessRevision": provenance.harness.revision,
        "speakerEncoderRevision": provenance.speaker_encoder.revision,
        "runtimeLockSha256": runtime_lock_sha256,
    }:
        raise ValueError("meeting worker model identity is invalid")

    audio = _exact_mapping(
        result["audio"],
        {"sha256", "durationMs", "sampleRateHz", "frameCount"},
        "meeting worker audio",
    )
    if audio != {
        "sha256": job.input_sha256,
        "durationMs": job.duration_ms,
        "sampleRateHz": MEETING_SAMPLE_RATE_HZ,
        "frameCount": job.frame_count,
    }:
        raise ValueError("meeting worker audio identity is invalid")

    meeting = _exact_mapping(
        result["meeting"],
        {"language", "speakers", "segments", "numWindows", "sourceTimeUnit"},
        "meeting worker meeting",
    )
    language = meeting["language"]
    if (
        not isinstance(language, str)
        or _LANGUAGE.fullmatch(language) is None
        or (job.language != "auto" and language != job.language)
    ):
        raise ValueError("meeting worker language is invalid")
    speakers = meeting["speakers"]
    if (
        not isinstance(speakers, list)
        or len(speakers) > job.max_speakers
        or speakers != sorted(set(speakers))
        or any(not is_meeting_speaker_id(item) for item in speakers)
    ):
        raise ValueError("meeting worker speakers are invalid")
    raw_segments = meeting["segments"]
    if (
        not isinstance(raw_segments, list)
        or len(raw_segments) > MAX_MEETING_SEGMENT_COUNT
    ):
        raise ValueError("meeting worker segments exceed the bounded contract")
    observed_speakers: set[str] = set()
    transcript_bytes = 0
    previous_start = -1
    for index, value in enumerate(raw_segments):
        segment = _exact_mapping(
            value,
            {"index", "speaker", "startSample", "endSample", "text"},
            f"meeting worker segment {index}",
        )
        speaker = segment["speaker"]
        start = segment["startSample"]
        end = segment["endSample"]
        text = canonical_transcript(segment["text"], "meeting worker segment text")
        if (
            segment["index"] != index
            or not text
            or not isinstance(speaker, str)
            or speaker not in speakers
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < previous_start
            or start < 0
            or end <= start
            or end > job.frame_count
        ):
            raise ValueError("meeting worker segment is invalid")
        previous_start = start
        observed_speakers.add(speaker)
        transcript_bytes += len(text.encode("utf-8"))
        if transcript_bytes > MAX_TRANSCRIPT_BYTES:
            raise ValueError("meeting worker transcript exceeds the byte bound")
    if observed_speakers != set(speakers):
        raise ValueError("meeting worker speaker inventory differs from its segments")
    maximum_windows = maximum_upstream_window_count(
        job.frame_count / MEETING_SAMPLE_RATE_HZ
    )
    num_windows = meeting["numWindows"]
    if (
        not isinstance(num_windows, int)
        or isinstance(num_windows, bool)
        or not 1 <= num_windows <= maximum_windows
        or meeting["sourceTimeUnit"] != "samples"
    ):
        raise ValueError("meeting worker window identity is invalid")

    runtime = _exact_mapping(
        result["runtime"],
        {"device", "dtype", "constrainedDecoding", "twoPass"},
        "meeting worker runtime",
    )
    if runtime != {
        "device": "cuda:0",
        "dtype": "bfloat16",
        "constrainedDecoding": True,
        "twoPass": True,
    }:
        raise ValueError("meeting worker runtime identity is invalid")
    return dict(result)


def _exact_mapping(value: object, keys: set[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{field} fields are invalid")
    return value


def _mount_directory(path: Path, field: str) -> Path:
    resolved = _safe_mount_path(path.resolve(strict=True))
    if not resolved.is_dir():
        raise ValueError(f"{field} must be a directory")
    return resolved


def _mount_file(path: Path, field: str) -> Path:
    resolved = _safe_mount_path(path.resolve(strict=True))
    if not resolved.is_file():
        raise ValueError(f"{field} must be a regular file")
    return resolved


def _safe_mount_path(path: Path) -> Path:
    if any(character in str(path) for character in (",", "\n", "\r")):
        raise ValueError("container mount paths cannot contain commas or newlines")
    return path
