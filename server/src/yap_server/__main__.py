import logging
import os
import signal

from yap_server.api.app import serve
from yap_server.config import ServerSettings
from yap_server.jobs.runtime import (
    BatchRuntime,
    build_batch_runtime,
    ensure_development_batch_bind,
)


_SHUTDOWN_FAILURE_EXIT_CODE = 70


def _raise_keyboard_interrupt(signum: int, frame: object) -> None:
    del signum, frame
    raise KeyboardInterrupt


def _close_runtime_or_fail_stop(runtime: BatchRuntime) -> None:
    try:
        runtime.close()
    except BaseException:
        logging.critical(
            "Yap private server shutdown could not verify worker containment; "
            "fail-stopping the service process"
        )
        os._exit(_SHUTDOWN_FAILURE_EXIT_CODE)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _raise_keyboard_interrupt)
    runtime: BatchRuntime | None = None
    try:
        settings = ServerSettings.from_env()
        runtime = build_batch_runtime()
        if runtime is not None:
            ensure_development_batch_bind(settings.host)
    except ValueError as error:
        if runtime is not None:
            _close_runtime_or_fail_stop(runtime)
        raise SystemExit(str(error)) from None
    except (OSError, RuntimeError):
        if runtime is not None:
            _close_runtime_or_fail_stop(runtime)
        raise SystemExit("Yap private server startup failed.") from None

    try:
        serve(
            settings,
            job_service=runtime.service if runtime is not None else None,
            lid_preflight_service=(
                runtime.lid_preflight_service if runtime is not None else None
            ),
            asr_capabilities=(
                runtime.asr_capabilities if runtime is not None else None
            ),
        )
    except KeyboardInterrupt:
        return
    except OSError:
        raise SystemExit("Yap private server runtime became unavailable.") from None
    finally:
        if runtime is not None:
            _close_runtime_or_fail_stop(runtime)


if __name__ == "__main__":
    main()
