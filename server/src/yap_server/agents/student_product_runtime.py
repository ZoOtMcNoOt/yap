from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .student_question_service import StudentQuestionService
from .student_runtime import build_student_runtime


@dataclass(slots=True)
class StudentProductRuntime:
    service: StudentQuestionService

    def close(self) -> None:
        self.service.close()


def build_student_product_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
) -> StudentProductRuntime | None:
    core = build_student_runtime(
        environ,
        authenticated_team_mode=authenticated_team_mode,
    )
    if core is None:
        return None
    return StudentProductRuntime(
        service=StudentQuestionService(student=core.service),
    )


__all__ = [
    "StudentProductRuntime",
    "build_student_product_runtime",
]
