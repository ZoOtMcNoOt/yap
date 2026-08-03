"""Bounded recording-job lifecycle."""

from .errors import JobServiceError

__all__ = ["JobServiceError", "RecordingJobService"]


def __getattr__(name: str) -> object:
    if name != "RecordingJobService":
        raise AttributeError(name)
    from .service import RecordingJobService

    return RecordingJobService
