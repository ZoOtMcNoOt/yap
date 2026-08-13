from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

from yap_server.agents.librarian import LibrarianRequest
from yap_server.agents.librarian_query_service import (
    LibrarianQueryContainmentError,
    LibrarianQueryJobView,
    LibrarianQueryServiceError,
)
from yap_server.auth import AuthenticatedPrincipal

from .routes import LIBRARIAN_QUERIES_PATH, LIBRARIAN_QUERY_PATH


class LibrarianQueryServiceProtocol(Protocol):
    def submit(
        self,
        request: LibrarianRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> LibrarianQueryJobView: ...

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> LibrarianQueryJobView | None: ...

    def cancel(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> bool: ...


class LibrarianQueryRequestMixin:
    def _dispatch_librarian_query_request(self, path: str) -> None:
        assert self._librarian_query_service is not None
        assert self._principal is not None
        try:
            if path == LIBRARIAN_QUERIES_PATH and self.command == "POST":
                request = LibrarianRequest.from_wire(self._request_body.read_json())
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    self._librarian_query_service.submit(
                        request,
                        principal=self._principal,
                    ).to_wire(),
                )
                return

            match = LIBRARIAN_QUERY_PATH.fullmatch(path)
            if match is not None:
                request_id = match.group("request_id")
                if self.command == "GET":
                    view = self._librarian_query_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        self._send_librarian_query_not_found()
                        return
                    self._send_json(HTTPStatus.OK, view.to_wire())
                    return
                if self.command == "DELETE":
                    if not self._librarian_query_service.cancel(
                        request_id,
                        principal=self._principal,
                    ):
                        self._send_librarian_query_not_found()
                        return
                    view = self._librarian_query_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        raise LibrarianQueryContainmentError(
                            "cancelled librarian product identity disappeared"
                        )
                    self._send_json(HTTPStatus.ACCEPTED, view.to_wire())
                    return
        except LibrarianQueryServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            return
        except LibrarianQueryContainmentError:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="LIBRARIAN_QUERY_UNAVAILABLE",
                message="Knowledge queries are temporarily unavailable.",
                retryable=True,
            )
            return
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_LIBRARIAN_QUERY",
                message="Knowledge query request is invalid.",
            )
            return

        self._send_error(
            HTTPStatus.NOT_IMPLEMENTED,
            code="NOT_IMPLEMENTED",
            message="This knowledge query operation is not implemented.",
        )

    def _send_librarian_query_not_found(self) -> None:
        self._send_error(
            HTTPStatus.NOT_FOUND,
            code="LIBRARIAN_QUERY_NOT_FOUND",
            message="The knowledge query does not exist.",
        )


__all__ = [
    "LibrarianQueryRequestMixin",
    "LibrarianQueryServiceProtocol",
]
