from __future__ import annotations

import logging
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

from yap_server.api.health import health
from yap_server.auth import (
    AuthenticatedPrincipal,
    AuthenticationDisabledAuthenticator,
    AuthenticationFailure,
    DevelopmentLoopbackAuthenticator,
    RequestAuthenticator,
)
from yap_server.config import ServerSettings, ensure_private_application_bind
from yap_server.jobs import RecordingJobService

from .archivist_ingestion_requests import (
    ArchivistIngestionRequestMixin,
    ArchivistIngestionServiceProtocol,
)
from .http_server import (
    MAX_CONCURRENT_REQUEST_THREADS,
    ThreadingYapHTTPServer,
    server_type,
)
from .job_requests import JobRequestMixin
from .librarian_query_requests import (
    LibrarianQueryRequestMixin,
    LibrarianQueryServiceProtocol,
)
from .student_question_requests import (
    StudentQuestionRequestMixin,
    StudentQuestionServiceProtocol,
)
from .lid_requests import LidPreflightServiceProtocol, LidRequestMixin
from .request_io import (
    BoundedRequestBody,
    REQUEST_IO_TIMEOUT_SECONDS,
    bounded_socket_reader,
    request_deadline,
)
from .responses import ResponseMixin
from .routes import (
    ARCHIVIST_INGESTION_PATH,
    ARCHIVIST_INGESTIONS_PATH,
    LID_PREFLIGHT_CANCEL_PATH,
    LID_PREFLIGHT_PATH,
    LIBRARIAN_QUERIES_PATH,
    LIBRARIAN_QUERY_PATH,
    STUDENT_QUESTIONS_PATH,
    STUDENT_QUESTION_PATH,
    SUPPORTED_HTTP_VERSIONS,
    TRANSCRIPT_CORRECTION_PATH,
    TRANSCRIPT_CORRECTIONS_PATH,
    allowed_methods as methods_for_path,
)
from .transcript_correction_requests import (
    TranscriptCorrectionRequestMixin,
    TranscriptCorrectionServiceProtocol,
)

__all__ = ["MAX_CONCURRENT_REQUEST_THREADS", "create_server", "serve"]


_REQUEST_LOGGER = logging.getLogger("yap_server.requests")


class _HealthRequestHandler(
    ArchivistIngestionRequestMixin,
    StudentQuestionRequestMixin,
    LibrarianQueryRequestMixin,
    TranscriptCorrectionRequestMixin,
    LidRequestMixin,
    JobRequestMixin,
    ResponseMixin,
    BaseHTTPRequestHandler,
):
    server_version = "yap-server"
    sys_version = ""
    timeout = REQUEST_IO_TIMEOUT_SECONDS

    def __init__(
        self,
        *args: Any,
        request_logger: logging.Logger,
        request_authenticator: RequestAuthenticator,
        job_service: RecordingJobService | None,
        lid_preflight_service: LidPreflightServiceProtocol | None,
        librarian_query_service: LibrarianQueryServiceProtocol | None,
        student_question_service: StudentQuestionServiceProtocol | None,
        archivist_ingestion_service: ArchivistIngestionServiceProtocol | None,
        transcript_correction_service: TranscriptCorrectionServiceProtocol | None,
        asr_capabilities: Mapping[str, object] | None,
        **kwargs: Any,
    ) -> None:
        self._request_logger = request_logger
        self._request_authenticator = request_authenticator
        self._principal: AuthenticatedPrincipal | None = None
        self._job_service = job_service
        self._lid_preflight_service = lid_preflight_service
        self._librarian_query_service = librarian_query_service
        self._student_question_service = student_question_service
        self._archivist_ingestion_service = archivist_ingestion_service
        self._transcript_correction_service = transcript_correction_service
        self._asr_capabilities = asr_capabilities
        self._request_id = f"req-{uuid4().hex}"
        self._request_logged = False
        self._request_body = BoundedRequestBody(self)
        self.requestline = ""
        self.request_version = ""
        self.command = ""
        super().__init__(*args, **kwargs)

    def setup(self) -> None:
        deadline = request_deadline()
        super().setup()
        original_rfile = self.rfile
        self.rfile = bounded_socket_reader(self.connection, deadline)
        original_rfile.close()

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_CONNECT(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        self._dispatch()

    def do_TRACE(self) -> None:
        self._dispatch()

    def _dispatch(self) -> None:
        if self.request_version not in SUPPORTED_HTTP_VERSIONS:
            self._send_version_not_supported()
            return

        if not self._request_size_is_allowed():
            return

        try:
            path = urlsplit(self.path).path
        except ValueError:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_REQUEST_TARGET",
                message="Request target is invalid.",
            )
            return
        allowed_methods = methods_for_path(path)
        if allowed_methods is None:
            self._send_error(
                HTTPStatus.NOT_FOUND,
                code="NOT_FOUND",
                message="Route not found.",
            )
            return

        if self.command not in allowed_methods:
            self._send_error(
                HTTPStatus.METHOD_NOT_ALLOWED,
                code="METHOD_NOT_ALLOWED",
                message="Method not allowed for this route.",
                headers={"Allow": ", ".join(sorted(allowed_methods))},
            )
            return

        if path == "/v1/health":
            self._send_json(
                HTTPStatus.OK,
                health(
                    batch_jobs=self._job_service is not None,
                    authentication_required=(
                        self._request_authenticator.authentication_required
                    ),
                    transcript_correction=(
                        self._transcript_correction_service is not None
                    ),
                    librarian_queries=(self._librarian_query_service is not None),
                    student_questions=(self._student_question_service is not None),
                    archivist_ingestions=(
                        self._archivist_ingestion_service is not None
                    ),
                ),
            )
            return

        if not self._authenticate_request():
            return

        if path == "/v1/asr/capabilities":
            if self._asr_capabilities is None:
                self._send_error(
                    HTTPStatus.NOT_IMPLEMENTED,
                    code="NOT_IMPLEMENTED",
                    message="ASR capabilities are not configured.",
                )
                return
            self._send_json(HTTPStatus.OK, self._asr_capabilities)
            return

        is_lid_route = (
            path == LID_PREFLIGHT_PATH
            or LID_PREFLIGHT_CANCEL_PATH.fullmatch(path) is not None
        )
        if is_lid_route:
            if self._lid_preflight_service is None:
                self._send_error(
                    HTTPStatus.NOT_IMPLEMENTED,
                    code="NOT_IMPLEMENTED",
                    message="LID preflight is not configured.",
                )
                return
            self._dispatch_lid_request(path)
            return

        is_transcript_correction_route = (
            path == TRANSCRIPT_CORRECTIONS_PATH
            or TRANSCRIPT_CORRECTION_PATH.fullmatch(path) is not None
        )
        if is_transcript_correction_route:
            if self._transcript_correction_service is None:
                self._send_error(
                    HTTPStatus.NOT_IMPLEMENTED,
                    code="NOT_IMPLEMENTED",
                    message="Transcript correction is not configured.",
                )
                return
            self._dispatch_transcript_correction_request(path)
            return

        is_librarian_query_route = (
            path == LIBRARIAN_QUERIES_PATH
            or LIBRARIAN_QUERY_PATH.fullmatch(path) is not None
        )
        if is_librarian_query_route:
            if self._librarian_query_service is None:
                self._send_error(
                    HTTPStatus.NOT_IMPLEMENTED,
                    code="NOT_IMPLEMENTED",
                    message="Knowledge queries are not configured.",
                )
                return
            self._dispatch_librarian_query_request(path)
            return

        is_student_question_route = (
            path == STUDENT_QUESTIONS_PATH
            or STUDENT_QUESTION_PATH.fullmatch(path) is not None
        )
        if is_student_question_route:
            if self._student_question_service is None:
                self._send_error(
                    HTTPStatus.NOT_IMPLEMENTED,
                    code="NOT_IMPLEMENTED",
                    message="Learning questions are not configured.",
                )
                return
            self._dispatch_student_question_request(path)
            return

        is_archivist_ingestion_route = (
            path == ARCHIVIST_INGESTIONS_PATH
            or ARCHIVIST_INGESTION_PATH.fullmatch(path) is not None
        )
        if is_archivist_ingestion_route:
            if self._archivist_ingestion_service is None:
                self._send_error(
                    HTTPStatus.NOT_IMPLEMENTED,
                    code="NOT_IMPLEMENTED",
                    message="Knowledge staging is not configured.",
                )
                return
            self._dispatch_archivist_ingestion_request(path)
            return

        if self._job_service is not None and path != "/v1/live":
            self._dispatch_job_request(path)
            return

        self._send_error(
            HTTPStatus.NOT_IMPLEMENTED,
            code="NOT_IMPLEMENTED",
            message="This route is unavailable in the active runtime profile.",
        )

    def _authenticate_request(self) -> bool:
        authorization_values = self.headers.get_all("Authorization") or []
        try:
            if len(authorization_values) > 1:
                raise AuthenticationFailure.invalid()
            self._principal = self._request_authenticator.authenticate(
                authorization_values[0] if authorization_values else None
            )
        except AuthenticationFailure as error:
            headers = (
                {"WWW-Authenticate": error.challenge}
                if error.challenge is not None
                else None
            )
            self._send_error(
                error.status,
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                headers=headers,
            )
            return False
        return True


def create_server(
    settings: ServerSettings,
    *,
    logger: logging.Logger | None = None,
    request_authenticator: RequestAuthenticator | None = None,
    job_service: RecordingJobService | None = None,
    lid_preflight_service: LidPreflightServiceProtocol | None = None,
    librarian_query_service: LibrarianQueryServiceProtocol | None = None,
    student_question_service: StudentQuestionServiceProtocol | None = None,
    archivist_ingestion_service: ArchivistIngestionServiceProtocol | None = None,
    transcript_correction_service: TranscriptCorrectionServiceProtocol | None = None,
    asr_capabilities: Mapping[str, object] | None = None,
) -> HTTPServer:
    ensure_private_application_bind(settings.host)
    request_logger = logger or _REQUEST_LOGGER
    if request_authenticator is None:
        if settings.authentication.required:
            raise ValueError("authenticated team mode requires a request authenticator")
        active_authenticator: RequestAuthenticator
        if settings.authentication.development_enabled:
            active_authenticator = DevelopmentLoopbackAuthenticator()
        else:
            active_authenticator = AuthenticationDisabledAuthenticator()
    else:
        active_authenticator = request_authenticator
        if (
            active_authenticator.authentication_required
            != settings.authentication.authentication_required
        ):
            raise ValueError(
                "request authenticator does not match the server authentication mode"
            )
        if (
            settings.authentication.required
            and not active_authenticator.principal_access_enforced
        ):
            raise ValueError(
                "authenticated team mode requires principal access enforcement"
            )
    handler = partial(
        _HealthRequestHandler,
        request_logger=request_logger,
        request_authenticator=active_authenticator,
        job_service=job_service,
        lid_preflight_service=lid_preflight_service,
        librarian_query_service=librarian_query_service,
        student_question_service=student_question_service,
        archivist_ingestion_service=archivist_ingestion_service,
        transcript_correction_service=transcript_correction_service,
        asr_capabilities=asr_capabilities,
    )
    server = server_type(
        settings.host,
        threaded=(
            job_service is not None
            or lid_preflight_service is not None
            or librarian_query_service is not None
            or student_question_service is not None
            or archivist_ingestion_service is not None
            or transcript_correction_service is not None
        ),
    )((settings.host, settings.port), handler)
    server._request_error_logger = request_logger
    if isinstance(server, ThreadingYapHTTPServer):
        server._job_service_for_maintenance = job_service
    return server


def serve(
    settings: ServerSettings,
    *,
    job_service: RecordingJobService | None = None,
    request_authenticator: RequestAuthenticator | None = None,
    lid_preflight_service: LidPreflightServiceProtocol | None = None,
    librarian_query_service: LibrarianQueryServiceProtocol | None = None,
    student_question_service: StudentQuestionServiceProtocol | None = None,
    archivist_ingestion_service: ArchivistIngestionServiceProtocol | None = None,
    transcript_correction_service: TranscriptCorrectionServiceProtocol | None = None,
    asr_capabilities: Mapping[str, object] | None = None,
) -> None:
    with create_server(
        settings,
        request_authenticator=request_authenticator,
        job_service=job_service,
        lid_preflight_service=lid_preflight_service,
        librarian_query_service=librarian_query_service,
        student_question_service=student_question_service,
        archivist_ingestion_service=archivist_ingestion_service,
        transcript_correction_service=transcript_correction_service,
        asr_capabilities=asr_capabilities,
    ) as server:
        server.serve_forever()
