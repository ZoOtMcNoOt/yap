from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

from yap_server.agents.archivist_ingestion_service import (
    ArchivistIngestionContainmentError,
    ArchivistIngestionJobView,
    ArchivistIngestionRequest,
    ArchivistIngestionServiceError,
)
from yap_server.auth import AuthenticatedPrincipal

from .routes import ARCHIVIST_INGESTION_PATH, ARCHIVIST_INGESTIONS_PATH


class ArchivistIngestionServiceProtocol(Protocol):
    def submit(
        self,
        request: ArchivistIngestionRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> ArchivistIngestionJobView: ...

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> ArchivistIngestionJobView | None: ...

    def cancel(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> bool: ...


class ArchivistIngestionRequestMixin:
    def _dispatch_archivist_ingestion_request(self, path: str) -> None:
        assert self._archivist_ingestion_service is not None
        assert self._principal is not None
        try:
            if path == ARCHIVIST_INGESTIONS_PATH and self.command == "POST":
                request = ArchivistIngestionRequest.from_wire(
                    self._request_body.read_json()
                )
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    self._archivist_ingestion_service.submit(
                        request,
                        principal=self._principal,
                    ).to_wire(),
                )
                return

            match = ARCHIVIST_INGESTION_PATH.fullmatch(path)
            if match is not None:
                request_id = match.group("request_id")
                if self.command == "GET":
                    view = self._archivist_ingestion_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        self._send_archivist_ingestion_not_found()
                        return
                    self._send_json(HTTPStatus.OK, view.to_wire())
                    return
                if self.command == "DELETE":
                    if not self._archivist_ingestion_service.cancel(
                        request_id,
                        principal=self._principal,
                    ):
                        self._send_archivist_ingestion_not_found()
                        return
                    view = self._archivist_ingestion_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        raise ArchivistIngestionContainmentError(
                            "cancelled archivist product identity disappeared"
                        )
                    self._send_json(HTTPStatus.ACCEPTED, view.to_wire())
                    return
        except ArchivistIngestionServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            return
        except ArchivistIngestionContainmentError:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="ARCHIVIST_INGESTION_UNAVAILABLE",
                message="Knowledge staging is temporarily unavailable.",
                retryable=True,
            )
            return
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_ARCHIVIST_INGESTION",
                message="Knowledge staging request is invalid.",
            )
            return

        self._send_error(
            HTTPStatus.NOT_IMPLEMENTED,
            code="NOT_IMPLEMENTED",
            message="This knowledge staging operation is not implemented.",
        )

    def _send_archivist_ingestion_not_found(self) -> None:
        self._send_error(
            HTTPStatus.NOT_FOUND,
            code="ARCHIVIST_INGESTION_NOT_FOUND",
            message="The knowledge staging request does not exist.",
        )


__all__ = [
    "ArchivistIngestionRequestMixin",
    "ArchivistIngestionServiceProtocol",
]
