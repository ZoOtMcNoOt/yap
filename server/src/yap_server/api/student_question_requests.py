from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

from yap_server.agents.student import StudentRequest
from yap_server.agents.student_question_service import (
    StudentQuestionContainmentError,
    StudentQuestionJobView,
    StudentQuestionServiceError,
)
from yap_server.auth import AuthenticatedPrincipal

from .routes import STUDENT_QUESTION_PATH, STUDENT_QUESTIONS_PATH


class StudentQuestionServiceProtocol(Protocol):
    def submit(
        self,
        request: StudentRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> StudentQuestionJobView: ...

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> StudentQuestionJobView | None: ...

    def cancel(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> bool: ...


class StudentQuestionRequestMixin:
    def _dispatch_student_question_request(self, path: str) -> None:
        assert self._student_question_service is not None
        assert self._principal is not None
        try:
            if path == STUDENT_QUESTIONS_PATH and self.command == "POST":
                request = StudentRequest.from_wire(self._request_body.read_json())
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    self._student_question_service.submit(
                        request,
                        principal=self._principal,
                    ).to_wire(),
                )
                return

            match = STUDENT_QUESTION_PATH.fullmatch(path)
            if match is not None:
                request_id = match.group("request_id")
                if self.command == "GET":
                    view = self._student_question_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        self._send_student_question_not_found()
                        return
                    self._send_json(HTTPStatus.OK, view.to_wire())
                    return
                if self.command == "DELETE":
                    if not self._student_question_service.cancel(
                        request_id,
                        principal=self._principal,
                    ):
                        self._send_student_question_not_found()
                        return
                    view = self._student_question_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        raise StudentQuestionContainmentError(
                            "cancelled student product identity disappeared"
                        )
                    self._send_json(HTTPStatus.ACCEPTED, view.to_wire())
                    return
        except StudentQuestionServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            return
        except StudentQuestionContainmentError:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="STUDENT_QUESTION_UNAVAILABLE",
                message="Learning questions are temporarily unavailable.",
                retryable=True,
            )
            return
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_STUDENT_QUESTION",
                message="Learning-question request is invalid.",
            )
            return

        self._send_error(
            HTTPStatus.NOT_IMPLEMENTED,
            code="NOT_IMPLEMENTED",
            message="This learning-question operation is not implemented.",
        )

    def _send_student_question_not_found(self) -> None:
        self._send_error(
            HTTPStatus.NOT_FOUND,
            code="STUDENT_QUESTION_NOT_FOUND",
            message="The learning-question request does not exist.",
        )


__all__ = [
    "StudentQuestionRequestMixin",
    "StudentQuestionServiceProtocol",
]
