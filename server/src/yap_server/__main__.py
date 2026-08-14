import logging
import os
import signal

from yap_server.agents.archivist_runtime import (
    ARCHIVIST_ADMISSION_SOCKET,
    ARCHIVIST_KNOWLEDGE_DSN_FILE,
    ARCHIVIST_RUNTIME,
    ArchivistRuntime,
    build_archivist_runtime,
)
from yap_server.agents.curator_product_runtime import (
    CuratorProductRuntime,
    build_curator_product_runtime,
)
from yap_server.agents.librarian_runtime import (
    LibrarianRuntime,
    build_librarian_runtime,
)
from yap_server.agents.student_product_runtime import (
    StudentProductRuntime,
    build_student_product_runtime,
)
from yap_server.agents.transcript_correction_runtime import (
    TranscriptCorrectionRuntime,
    build_transcript_correction_runtime,
)
from yap_server.api.app import serve
from yap_server.auth import (
    RequestAuthorizationRuntime,
    build_request_authenticator,
    build_request_authorization_runtime,
)
from yap_server.auth.signing_keys import SigningKeyUnavailable
from yap_server.config import ServerSettings, ensure_private_application_bind
from yap_server.jobs.runtime import (
    BatchRuntime,
    build_batch_runtime,
)
from yap_server.jobs.ownership import DEVELOPMENT_JOB_OWNER
from yap_server.live import PrivateLiveWebSocketServer, private_live_port_from_env
from yap_server.pools.batch_contract import WorkerContainmentError
from yap_server.pools.cleanup_deadline import run_cleanup_before_deadline


_SHUTDOWN_FAILURE_EXIT_CODE = 70
_RUNTIME_CLEANUP_TIMEOUT_SECONDS = 30.0
_ARCHIVIST_RUNTIME_CLEANUP_TIMEOUT_SECONDS = 66.0
_STUDENT_PRODUCT_RUNTIME_CLEANUP_TIMEOUT_SECONDS = 66.0
_CURATOR_PRODUCT_RUNTIME_CLEANUP_TIMEOUT_SECONDS = 66.0


def _fail_stop_worker_containment() -> None:
    logging.critical(
        "Yap private server shutdown could not verify worker containment; "
        "fail-stopping the service process"
    )
    os._exit(_SHUTDOWN_FAILURE_EXIT_CODE)


def _raise_keyboard_interrupt(signum: int, frame: object) -> None:
    del signum, frame
    raise KeyboardInterrupt


def _close_runtime_or_fail_stop(runtime: BatchRuntime) -> None:
    try:
        run_cleanup_before_deadline(
            runtime.close,
            timeout_seconds=_RUNTIME_CLEANUP_TIMEOUT_SECONDS,
            thread_name="yap-server-runtime-cleanup",
        )
    except BaseException:
        _fail_stop_worker_containment()


def _close_transcript_correction_runtime_or_fail_stop(
    runtime: TranscriptCorrectionRuntime,
) -> None:
    try:
        run_cleanup_before_deadline(
            runtime.close,
            timeout_seconds=_RUNTIME_CLEANUP_TIMEOUT_SECONDS,
            thread_name="yap-server-scribe-cleanup",
        )
    except BaseException:
        _fail_stop_worker_containment()


def _close_librarian_runtime_or_fail_stop(
    runtime: LibrarianRuntime,
) -> None:
    try:
        run_cleanup_before_deadline(
            runtime.close,
            timeout_seconds=_RUNTIME_CLEANUP_TIMEOUT_SECONDS,
            thread_name="yap-server-librarian-cleanup",
        )
    except BaseException:
        _fail_stop_worker_containment()


def _close_archivist_runtime_or_fail_stop(
    runtime: ArchivistRuntime,
) -> None:
    try:
        run_cleanup_before_deadline(
            runtime.close,
            timeout_seconds=_ARCHIVIST_RUNTIME_CLEANUP_TIMEOUT_SECONDS,
            thread_name="yap-server-archivist-cleanup",
        )
    except BaseException:
        _fail_stop_worker_containment()


def _close_student_product_runtime_or_fail_stop(
    runtime: StudentProductRuntime,
) -> None:
    try:
        run_cleanup_before_deadline(
            runtime.close,
            timeout_seconds=_STUDENT_PRODUCT_RUNTIME_CLEANUP_TIMEOUT_SECONDS,
            thread_name="yap-server-student-product-cleanup",
        )
    except BaseException:
        _fail_stop_worker_containment()


def _close_curator_product_runtime_or_fail_stop(
    runtime: CuratorProductRuntime,
) -> None:
    try:
        run_cleanup_before_deadline(
            runtime.close,
            timeout_seconds=_CURATOR_PRODUCT_RUNTIME_CLEANUP_TIMEOUT_SECONDS,
            thread_name="yap-server-curator-product-cleanup",
        )
    except BaseException:
        _fail_stop_worker_containment()


def _close_owned_resources(
    live_transport: PrivateLiveWebSocketServer | None,
    runtime: BatchRuntime | None,
    authorization_runtime: RequestAuthorizationRuntime | None,
    transcript_correction_runtime: TranscriptCorrectionRuntime | None = None,
    librarian_runtime: LibrarianRuntime | None = None,
    archivist_runtime: ArchivistRuntime | None = None,
    student_product_runtime: StudentProductRuntime | None = None,
    curator_product_runtime: CuratorProductRuntime | None = None,
) -> BaseException | None:
    cleanup_error: BaseException | None = None
    if live_transport is not None:
        try:
            live_transport.close()
        except BaseException as error:
            cleanup_error = error
    if transcript_correction_runtime is not None:
        _close_transcript_correction_runtime_or_fail_stop(transcript_correction_runtime)
    if librarian_runtime is not None:
        _close_librarian_runtime_or_fail_stop(librarian_runtime)
    if archivist_runtime is not None:
        _close_archivist_runtime_or_fail_stop(archivist_runtime)
    if student_product_runtime is not None:
        _close_student_product_runtime_or_fail_stop(student_product_runtime)
    if curator_product_runtime is not None:
        _close_curator_product_runtime_or_fail_stop(curator_product_runtime)
    if runtime is not None:
        _close_runtime_or_fail_stop(runtime)
    if authorization_runtime is not None:
        try:
            authorization_runtime.close()
        except BaseException as error:
            if cleanup_error is None:
                cleanup_error = error
    return cleanup_error


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _raise_keyboard_interrupt)
    runtime: BatchRuntime | None = None
    transcript_correction_runtime: TranscriptCorrectionRuntime | None = None
    librarian_runtime: LibrarianRuntime | None = None
    archivist_runtime: ArchivistRuntime | None = None
    student_product_runtime: StudentProductRuntime | None = None
    curator_product_runtime: CuratorProductRuntime | None = None
    authorization_runtime: RequestAuthorizationRuntime | None = None
    live_transport: PrivateLiveWebSocketServer | None = None
    try:
        settings = ServerSettings.from_env()
        ensure_private_application_bind(settings.host)
        token_authenticator = build_request_authenticator(settings.authentication)
        authorization_runtime = build_request_authorization_runtime(
            settings.authentication,
            token_authenticator,
        )
        request_authenticator = authorization_runtime.authenticator
        transcript_correction_runtime = build_transcript_correction_runtime(
            os.environ,
            authenticated_team_mode=settings.authentication.required,
        )
        librarian_runtime = build_librarian_runtime(
            os.environ,
            authenticated_team_mode=settings.authentication.required,
        )
        student_product_runtime = build_student_product_runtime(
            os.environ,
            authenticated_team_mode=settings.authentication.required,
        )
        curator_product_runtime = build_curator_product_runtime(
            os.environ,
            authenticated_team_mode=settings.authentication.required,
        )
        runtime = build_batch_runtime(
            development_principal=(
                DEVELOPMENT_JOB_OWNER
                if settings.authentication.development_enabled
                else None
            )
        )
        if runtime is not None:
            archivist_runtime = build_archivist_runtime(
                os.environ,
                authenticated_team_mode=settings.authentication.required,
                jobs=runtime.service,
            )
        elif any(
            variable in os.environ
            for variable in (
                ARCHIVIST_RUNTIME,
                ARCHIVIST_ADMISSION_SOCKET,
                ARCHIVIST_KNOWLEDGE_DSN_FILE,
            )
        ):
            raise ValueError("archivist requires the recording job runtime")
        if settings.authentication.required:
            live_transport = PrivateLiveWebSocketServer(
                request_authenticator,
                port=private_live_port_from_env(),
            ).start()
    except ValueError as error:
        cleanup_error = _close_owned_resources(
            live_transport,
            runtime,
            authorization_runtime,
            transcript_correction_runtime,
            librarian_runtime,
            archivist_runtime,
            student_product_runtime,
            curator_product_runtime,
        )
        if cleanup_error is not None:
            raise SystemExit("Yap private server startup cleanup failed.") from None
        raise SystemExit(str(error)) from None
    except WorkerContainmentError:
        _fail_stop_worker_containment()
    except (OSError, RuntimeError, SigningKeyUnavailable):
        _close_owned_resources(
            live_transport,
            runtime,
            authorization_runtime,
            transcript_correction_runtime,
            librarian_runtime,
            archivist_runtime,
            student_product_runtime,
            curator_product_runtime,
        )
        raise SystemExit("Yap private server startup failed.") from None

    try:
        serve(
            settings,
            request_authenticator=request_authenticator,
            job_service=runtime.service if runtime is not None else None,
            lid_preflight_service=(
                runtime.lid_preflight_service if runtime is not None else None
            ),
            asr_capabilities=(
                runtime.asr_capabilities if runtime is not None else None
            ),
            transcript_correction_service=(
                transcript_correction_runtime.service
                if transcript_correction_runtime is not None
                else None
            ),
            librarian_query_service=(
                librarian_runtime.service if librarian_runtime is not None else None
            ),
            student_question_service=(
                student_product_runtime.service
                if student_product_runtime is not None
                else None
            ),
            archivist_ingestion_service=(
                archivist_runtime.service if archivist_runtime is not None else None
            ),
            curator_proposal_service=(
                curator_product_runtime.service
                if curator_product_runtime is not None
                else None
            ),
        )
    except KeyboardInterrupt:
        return
    except OSError:
        raise SystemExit("Yap private server runtime became unavailable.") from None
    finally:
        cleanup_error = _close_owned_resources(
            live_transport,
            runtime,
            authorization_runtime,
            transcript_correction_runtime,
            librarian_runtime,
            archivist_runtime,
            student_product_runtime,
            curator_product_runtime,
        )
        if cleanup_error is not None:
            raise RuntimeError("Yap private server cleanup failed.") from cleanup_error


if __name__ == "__main__":
    main()
