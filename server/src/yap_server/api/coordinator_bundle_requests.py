from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

from yap_server.agents.coordinator import CoordinatorRequest
from yap_server.agents.coordinator_bundle_service import (
    CoordinatorBundleContainmentError,
    CoordinatorBundleJobView,
    CoordinatorBundleServiceError,
)
from yap_server.auth import AuthenticatedPrincipal

from .routes import COORDINATOR_BUNDLE_PATH, COORDINATOR_BUNDLES_PATH


class CoordinatorBundleServiceProtocol(Protocol):
    def submit(
        self,
        request: CoordinatorRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> CoordinatorBundleJobView: ...

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> CoordinatorBundleJobView | None: ...

    def cancel(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> bool: ...


class CoordinatorBundleRequestMixin:
    def _dispatch_coordinator_bundle_request(self, path: str) -> None:
        assert self._coordinator_bundle_service is not None
        assert self._principal is not None
        try:
            if path == COORDINATOR_BUNDLES_PATH and self.command == "POST":
                request = CoordinatorRequest.from_wire(self._request_body.read_json())
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    self._coordinator_bundle_service.submit(
                        request,
                        principal=self._principal,
                    ).to_wire(),
                )
                return

            match = COORDINATOR_BUNDLE_PATH.fullmatch(path)
            if match is not None:
                request_id = match.group("request_id")
                if self.command == "GET":
                    view = self._coordinator_bundle_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        self._send_coordinator_bundle_not_found()
                        return
                    self._send_json(HTTPStatus.OK, view.to_wire())
                    return
                if self.command == "DELETE":
                    if not self._coordinator_bundle_service.cancel(
                        request_id,
                        principal=self._principal,
                    ):
                        self._send_coordinator_bundle_not_found()
                        return
                    view = self._coordinator_bundle_service.get(
                        request_id,
                        principal=self._principal,
                    )
                    if view is None:
                        raise CoordinatorBundleContainmentError(
                            "cancelled coordinator product identity disappeared"
                        )
                    self._send_json(HTTPStatus.ACCEPTED, view.to_wire())
                    return
        except CoordinatorBundleServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            return
        except CoordinatorBundleContainmentError:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="COORDINATOR_BUNDLE_UNAVAILABLE",
                message="Coordination bundles are temporarily unavailable.",
                retryable=True,
            )
            return
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_COORDINATOR_BUNDLE",
                message="Coordination-bundle request is invalid.",
            )
            return

        self._send_error(
            HTTPStatus.NOT_IMPLEMENTED,
            code="NOT_IMPLEMENTED",
            message="This coordination-bundle operation is not implemented.",
        )

    def _send_coordinator_bundle_not_found(self) -> None:
        self._send_error(
            HTTPStatus.NOT_FOUND,
            code="COORDINATOR_BUNDLE_NOT_FOUND",
            message="The coordination-bundle request does not exist.",
        )


__all__ = [
    "CoordinatorBundleRequestMixin",
    "CoordinatorBundleServiceProtocol",
]
