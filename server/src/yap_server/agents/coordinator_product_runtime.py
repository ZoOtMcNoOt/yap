from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .coordinator_bundle_service import CoordinatorBundleService
from .coordinator_runtime import build_coordinator_runtime


@dataclass(slots=True)
class CoordinatorProductRuntime:
    service: CoordinatorBundleService

    def close(self) -> None:
        self.service.close()


def build_coordinator_product_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
) -> CoordinatorProductRuntime | None:
    core = build_coordinator_runtime(
        environ,
        authenticated_team_mode=authenticated_team_mode,
    )
    if core is None:
        return None
    return CoordinatorProductRuntime(
        service=CoordinatorBundleService(coordinator=core.service),
    )


__all__ = [
    "CoordinatorProductRuntime",
    "build_coordinator_product_runtime",
]
