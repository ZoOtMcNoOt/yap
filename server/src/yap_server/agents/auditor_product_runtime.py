
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .auditor_report_service import AuditorReportService
from .auditor_runtime import build_auditor_runtime


@dataclass(slots=True)
class AuditorProductRuntime:
    service: AuditorReportService

    def close(self) -> None:
        self.service.close()


def build_auditor_product_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
) -> AuditorProductRuntime | None:
    core = build_auditor_runtime(
        environ,
        authenticated_team_mode=authenticated_team_mode,
    )
    if core is None:
        return None
    return AuditorProductRuntime(
        service=AuditorReportService(auditor=core.service),
    )


__all__ = [
    "AuditorProductRuntime",
    "build_auditor_product_runtime",
]
