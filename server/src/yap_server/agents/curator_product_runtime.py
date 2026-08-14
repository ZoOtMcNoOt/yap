from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .curator_proposal_service import CuratorProposalService
from .curator_runtime import build_curator_runtime


@dataclass(slots=True)
class CuratorProductRuntime:
    service: CuratorProposalService

    def close(self) -> None:
        self.service.close()


def build_curator_product_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
) -> CuratorProductRuntime | None:
    core = build_curator_runtime(
        environ,
        authenticated_team_mode=authenticated_team_mode,
    )
    if core is None:
        return None
    return CuratorProductRuntime(
        service=CuratorProposalService(curator=core.service),
    )


__all__ = [
    "CuratorProductRuntime",
    "build_curator_product_runtime",
]
