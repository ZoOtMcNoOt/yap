from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .analyst_answer_service import AnalystAnswerService
from .analyst_runtime import build_analyst_runtime


@dataclass(slots=True)
class AnalystProductRuntime:
    service: AnalystAnswerService

    def close(self) -> None:
        self.service.close()


def build_analyst_product_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
) -> AnalystProductRuntime | None:
    core = build_analyst_runtime(
        environ,
        authenticated_team_mode=authenticated_team_mode,
    )
    if core is None:
        return None
    return AnalystProductRuntime(
        service=AnalystAnswerService(analyst=core.service),
    )


__all__ = [
    "AnalystProductRuntime",
    "build_analyst_product_runtime",
]
