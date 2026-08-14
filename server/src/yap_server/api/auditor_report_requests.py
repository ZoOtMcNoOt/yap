
from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

from yap_server.agents.auditor import AuditorRequest
from yap_server.agents.auditor_report_service import (
    AuditorReportContainmentError,
    AuditorReportJobView,
    AuditorReportServiceError,
)
from yap_server.auth import AuthenticatedPrincipal

from .routes import AUDITOR_REPORT_PATH, AUDITOR_REPORTS_PATH


class AuditorReportServiceProtocol(Protocol):
    def submit(
        self,
        request: AuditorRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> AuditorReportJobView: ...

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> AuditorReportJobView | None: ...

    def cancel(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> bool: ...


class AuditorReportRequestMixin:
    def _dispatch_auditor_report_request(self, path: str) -> None:
        assert self._auditor_report_service is not None
        assert self._principal is not None
        try:
            if path == AUDITOR_REPORTS_PATH and self.command == "POST":
                request = AuditorRequest.from_wire(self._request_body.read_json())
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    self._auditor_report_service.submit(
                        request,
                        principal=self._principal,
                    ).to_wire(),
                )
                return

            match = AUDITOR_REPORT_PATH.fullmatch(path)
            if match is not None:
                request_id = match.group("request_id")
                if self.command == "GET":
                    view = self._auditor_report_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        self._send_auditor_report_not_found()
                        return
                    self._send_json(HTTPStatus.OK, view.to_wire())
                    return
                if self.command == "DELETE":
                    if not self._auditor_report_service.cancel(
                        request_id,
                        principal=self._principal,
                    ):
                        self._send_auditor_report_not_found()
                        return
                    view = self._auditor_report_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        raise AuditorReportContainmentError(
                            "cancelled auditor product identity disappeared"
                        )
                    self._send_json(HTTPStatus.ACCEPTED, view.to_wire())
                    return
        except AuditorReportServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            return
        except AuditorReportContainmentError:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="AUDITOR_REPORT_UNAVAILABLE",
                message="Audit reports are temporarily unavailable.",
                retryable=True,
            )
            return
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_AUDITOR_REPORT",
                message="Audit-report request is invalid.",
            )
            return

        self._send_error(
            HTTPStatus.NOT_IMPLEMENTED,
            code="NOT_IMPLEMENTED",
            message="This audit-report operation is not implemented.",
        )

    def _send_auditor_report_not_found(self) -> None:
        self._send_error(
            HTTPStatus.NOT_FOUND,
            code="AUDITOR_REPORT_NOT_FOUND",
            message="The audit-report request does not exist.",
        )


__all__ = [
    "AuditorReportRequestMixin",
    "AuditorReportServiceProtocol",
]
