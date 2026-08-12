from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

from yap_server.agents.transcript_correction import TranscriptCorrectionRequest
from yap_server.agents.transcript_correction_service import (
    TranscriptCorrectionContainmentError,
    TranscriptCorrectionJobView,
    TranscriptCorrectionServiceError,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.jobs import JobServiceError

from .routes import (
    TRANSCRIPT_CORRECTION_PATH,
    TRANSCRIPT_CORRECTIONS_PATH,
)


class TranscriptCorrectionServiceProtocol(Protocol):
    def submit(
        self,
        request: TranscriptCorrectionRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> TranscriptCorrectionJobView: ...

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> TranscriptCorrectionJobView | None: ...

    def cancel(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> bool: ...


class TranscriptCorrectionRequestMixin:
    def _dispatch_transcript_correction_request(self, path: str) -> None:
        assert self._transcript_correction_service is not None
        assert self._principal is not None
        try:
            if path == TRANSCRIPT_CORRECTIONS_PATH and self.command == "POST":
                request = TranscriptCorrectionRequest.from_wire(
                    self._request_body.read_json()
                )
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    self._transcript_correction_service.submit(
                        request,
                        principal=self._principal,
                    ).to_wire(),
                )
                return

            match = TRANSCRIPT_CORRECTION_PATH.fullmatch(path)
            if match is not None:
                request_id = match.group("request_id")
                if self.command == "GET":
                    view = self._transcript_correction_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        self._send_transcript_correction_not_found()
                        return
                    self._send_json(HTTPStatus.OK, view.to_wire())
                    return
                if self.command == "DELETE":
                    if not self._transcript_correction_service.cancel(
                        request_id,
                        principal=self._principal,
                    ):
                        self._send_transcript_correction_not_found()
                        return
                    view = self._transcript_correction_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        raise TranscriptCorrectionContainmentError(
                            "cancelled correction identity disappeared"
                        )
                    self._send_json(HTTPStatus.ACCEPTED, view.to_wire())
                    return
        except TranscriptCorrectionServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            return
        except TranscriptCorrectionContainmentError:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="TRANSCRIPT_CORRECTION_UNAVAILABLE",
                message="Transcript correction is temporarily unavailable.",
                retryable=True,
            )
            return
        except JobServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            return
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_TRANSCRIPT_CORRECTION",
                message="Transcript correction request is invalid.",
            )
            return

        self._send_error(
            HTTPStatus.NOT_IMPLEMENTED,
            code="NOT_IMPLEMENTED",
            message="This transcript correction operation is not implemented.",
        )

    def _send_transcript_correction_not_found(self) -> None:
        self._send_error(
            HTTPStatus.NOT_FOUND,
            code="TRANSCRIPT_CORRECTION_NOT_FOUND",
            message="The transcript correction request does not exist.",
        )


__all__ = [
    "TranscriptCorrectionRequestMixin",
    "TranscriptCorrectionServiceProtocol",
]
