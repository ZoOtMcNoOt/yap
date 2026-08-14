from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

from yap_server.agents.curator import CuratorRequest
from yap_server.agents.curator_proposal_service import (
    CuratorProposalContainmentError,
    CuratorProposalJobView,
    CuratorProposalServiceError,
)
from yap_server.auth import AuthenticatedPrincipal

from .routes import CURATOR_PROPOSAL_PATH, CURATOR_PROPOSALS_PATH


class CuratorProposalServiceProtocol(Protocol):
    def submit(
        self,
        request: CuratorRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> CuratorProposalJobView: ...

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> CuratorProposalJobView | None: ...

    def cancel(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> bool: ...


class CuratorProposalRequestMixin:
    def _dispatch_curator_proposal_request(self, path: str) -> None:
        assert self._curator_proposal_service is not None
        assert self._principal is not None
        try:
            if path == CURATOR_PROPOSALS_PATH and self.command == "POST":
                request = CuratorRequest.from_wire(self._request_body.read_json())
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    self._curator_proposal_service.submit(
                        request,
                        principal=self._principal,
                    ).to_wire(),
                )
                return

            match = CURATOR_PROPOSAL_PATH.fullmatch(path)
            if match is not None:
                request_id = match.group("request_id")
                if self.command == "GET":
                    view = self._curator_proposal_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        self._send_curator_proposal_not_found()
                        return
                    self._send_json(HTTPStatus.OK, view.to_wire())
                    return
                if self.command == "DELETE":
                    if not self._curator_proposal_service.cancel(
                        request_id,
                        principal=self._principal,
                    ):
                        self._send_curator_proposal_not_found()
                        return
                    view = self._curator_proposal_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        raise CuratorProposalContainmentError(
                            "cancelled curator product identity disappeared"
                        )
                    self._send_json(HTTPStatus.ACCEPTED, view.to_wire())
                    return
        except CuratorProposalServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            return
        except CuratorProposalContainmentError:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="CURATOR_PROPOSAL_UNAVAILABLE",
                message="Knowledge proposals are temporarily unavailable.",
                retryable=True,
            )
            return
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_CURATOR_PROPOSAL",
                message="Knowledge-proposal request is invalid.",
            )
            return

        self._send_error(
            HTTPStatus.NOT_IMPLEMENTED,
            code="NOT_IMPLEMENTED",
            message="This knowledge-proposal operation is not implemented.",
        )

    def _send_curator_proposal_not_found(self) -> None:
        self._send_error(
            HTTPStatus.NOT_FOUND,
            code="CURATOR_PROPOSAL_NOT_FOUND",
            message="The knowledge-proposal request does not exist.",
        )


__all__ = [
    "CuratorProposalRequestMixin",
    "CuratorProposalServiceProtocol",
]
