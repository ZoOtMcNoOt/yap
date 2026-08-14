from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

from yap_server.agents.analyst import AnalystRequest
from yap_server.agents.analyst_answer_service import (
    AnalystAnswerContainmentError,
    AnalystAnswerJobView,
    AnalystAnswerServiceError,
)
from yap_server.auth import AuthenticatedPrincipal

from .routes import ANALYST_ANSWER_PATH, ANALYST_ANSWERS_PATH


class AnalystAnswerServiceProtocol(Protocol):
    def submit(
        self,
        request: AnalystRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> AnalystAnswerJobView: ...

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> AnalystAnswerJobView | None: ...

    def cancel(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> bool: ...


class AnalystAnswerRequestMixin:
    def _dispatch_analyst_answer_request(self, path: str) -> None:
        assert self._analyst_answer_service is not None
        assert self._principal is not None
        try:
            if path == ANALYST_ANSWERS_PATH and self.command == "POST":
                request = AnalystRequest.from_wire(self._request_body.read_json())
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    self._analyst_answer_service.submit(
                        request,
                        principal=self._principal,
                    ).to_wire(),
                )
                return

            match = ANALYST_ANSWER_PATH.fullmatch(path)
            if match is not None:
                request_id = match.group("request_id")
                if self.command == "GET":
                    view = self._analyst_answer_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        self._send_analyst_answer_not_found()
                        return
                    self._send_json(HTTPStatus.OK, view.to_wire())
                    return
                if self.command == "DELETE":
                    if not self._analyst_answer_service.cancel(
                        request_id,
                        principal=self._principal,
                    ):
                        self._send_analyst_answer_not_found()
                        return
                    view = self._analyst_answer_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        raise AnalystAnswerContainmentError(
                            "cancelled analyst product identity disappeared"
                        )
                    self._send_json(HTTPStatus.ACCEPTED, view.to_wire())
                    return
        except AnalystAnswerServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            return
        except AnalystAnswerContainmentError:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="ANALYST_ANSWER_UNAVAILABLE",
                message="Cited answers are temporarily unavailable.",
                retryable=True,
            )
            return
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_ANALYST_ANSWER",
                message="Cited-answer request is invalid.",
            )
            return

        self._send_error(
            HTTPStatus.NOT_IMPLEMENTED,
            code="NOT_IMPLEMENTED",
            message="This cited-answer operation is not implemented.",
        )

    def _send_analyst_answer_not_found(self) -> None:
        self._send_error(
            HTTPStatus.NOT_FOUND,
            code="ANALYST_ANSWER_NOT_FOUND",
            message="The cited-answer request does not exist.",
        )


__all__ = [
    "AnalystAnswerRequestMixin",
    "AnalystAnswerServiceProtocol",
]
