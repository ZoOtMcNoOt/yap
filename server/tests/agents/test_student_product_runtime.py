from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

from yap_server.agents.student_product_runtime import build_student_product_runtime


class StudentProductRuntimeTests(unittest.TestCase):
    def test_absent_core_keeps_product_surface_disabled(self) -> None:
        with mock.patch(
            "yap_server.agents.student_product_runtime.build_student_runtime",
            return_value=None,
        ) as build_core:
            runtime = build_student_product_runtime(
                {},
                authenticated_team_mode=True,
            )

        self.assertIsNone(runtime)
        build_core.assert_called_once_with({}, authenticated_team_mode=True)

    def test_product_runtime_wraps_and_closes_exact_core_service(self) -> None:
        core_service = object()
        core_runtime = SimpleNamespace(service=core_service)
        product_service = mock.Mock()
        with (
            mock.patch(
                "yap_server.agents.student_product_runtime.build_student_runtime",
                return_value=core_runtime,
            ),
            mock.patch(
                "yap_server.agents.student_product_runtime.StudentQuestionService",
                return_value=product_service,
            ) as product_type,
        ):
            runtime = build_student_product_runtime(
                {"YAP_STUDENT_RUNTIME": "warm_qwen"},
                authenticated_team_mode=True,
            )

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertIs(runtime.service, product_service)
        product_type.assert_called_once_with(student=core_service)
        runtime.close()
        product_service.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
