from __future__ import annotations

from http import HTTPStatus
from typing import Any, Protocol

from yap_server.auth import PrincipalKey
from yap_server.jobs import JobServiceError
from yap_server.lid.errors import (
    LidPreflightCancelled,
    LidPreflightConflict,
    LidPreflightUnavailable,
)
from yap_server.lid.preflight import LidPreflightBackpressure
from yap_server.lid.transport import (
    LID_PREFLIGHT_MEDIA_TYPE,
    LidTransportError,
    LidTransportStaleError,
)

from .routes import LID_PREFLIGHT_CANCEL_PATH, LID_PREFLIGHT_PATH


class LidPreflightServiceProtocol(Protocol):
    def run_envelope(
        self,
        body: bytes,
        *,
        owner: PrincipalKey,
    ) -> dict[str, Any]: ...

    def cancel(self, request_id: str, *, owner: PrincipalKey) -> bool: ...


class LidRequestMixin:
    def _dispatch_lid_request(self, path: str) -> None:
        assert self._lid_preflight_service is not None
        assert self._principal is not None
        owner = self._principal.key
        try:
            if path == LID_PREFLIGHT_PATH and self.command == "POST":
                self._require_lid_media_type()
                content_length = self._request_body.required_content_length()
                result = self._lid_preflight_service.run_envelope(
                    self._request_body.read_exact(content_length),
                    owner=owner,
                )
                self._send_json(HTTPStatus.OK, result)
                return

            cancel_match = LID_PREFLIGHT_CANCEL_PATH.fullmatch(path)
            if cancel_match is not None and self.command == "DELETE":
                request_id = cancel_match.group("request_id")
                if not self._lid_preflight_service.cancel(
                    request_id,
                    owner=owner,
                ):
                    self._send_error(
                        HTTPStatus.NOT_FOUND,
                        code="LID_PREFLIGHT_NOT_FOUND",
                        message="Active LID preflight request was not found.",
                    )
                    return
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    {
                        "schemaVersion": 1,
                        "requestId": request_id,
                        "status": "cancellation_requested",
                    },
                )
                return
        except LidTransportStaleError:
            self._send_error(
                HTTPStatus.CONFLICT,
                code="STALE_LID_PREFLIGHT_CONTRACT",
                message="LID preflight contract identity is stale.",
            )
            return
        except LidTransportError:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_LID_PREFLIGHT",
                message="LID preflight request is invalid.",
            )
            return
        except LidPreflightBackpressure:
            self._send_error(
                HTTPStatus.TOO_MANY_REQUESTS,
                code="LID_PREFLIGHT_BUSY",
                message="LID preflight capacity is temporarily full.",
                retryable=True,
                headers={"Retry-After": "1"},
            )
            return
        except LidPreflightConflict:
            self._send_error(
                HTTPStatus.CONFLICT,
                code="LID_PREFLIGHT_CONFLICT",
                message="LID preflight request conflicts with active work.",
            )
            return
        except LidPreflightCancelled:
            self._send_error(
                HTTPStatus.CONFLICT,
                code="LID_PREFLIGHT_CANCELLED",
                message="LID preflight request was cancelled.",
            )
            return
        except LidPreflightUnavailable:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="LID_PREFLIGHT_UNAVAILABLE",
                message="LID preflight is temporarily unavailable.",
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
        except TimeoutError:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="LID_PREFLIGHT_TIMEOUT",
                message="LID preflight did not finish within its bounded runtime.",
                retryable=True,
            )
            return
        except OSError:
            self._send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                code="LID_PREFLIGHT_STORAGE_ERROR",
                message="Private LID preflight storage could not complete the request.",
                retryable=True,
            )
            return
        except RuntimeError:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                code="LID_PREFLIGHT_UNAVAILABLE",
                message="LID preflight is temporarily unavailable.",
                retryable=True,
            )
            return

        self._send_error(
            HTTPStatus.NOT_IMPLEMENTED,
            code="NOT_IMPLEMENTED",
            message="This LID preflight operation is not implemented.",
        )

    def _require_lid_media_type(self) -> None:
        content_types = self.headers.get_all("Content-Type", [])
        if (
            len(content_types) != 1
            or content_types[0].strip().lower() != LID_PREFLIGHT_MEDIA_TYPE
        ):
            raise JobServiceError(
                415,
                "UNSUPPORTED_MEDIA_TYPE",
                "LID preflight requires its versioned binary media type.",
            )
