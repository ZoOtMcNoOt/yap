from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from yap_server.lid.component_lock import LidComponentArtifactError
from yap_server.lid.worker import execute_lid_worker, main
from yap_server.lid.worker_contract import WorkerInputError


_ARGS = [
    "--lock",
    "component.json",
    "--model-dir",
    "model",
    "--request",
    "request.json",
    "--probe-dir",
    "probes",
]


class LidWorkerCliTests(unittest.TestCase):
    def test_passes_the_locked_label_count_to_the_classifier_loader(self) -> None:
        lock = SimpleNamespace(model=SimpleNamespace(label_count=107))
        request = object()
        classifier = object()
        calls: list[tuple[Path, int]] = []

        def load_classifier(model_dir: Path, label_count: int):
            calls.append((model_dir, label_count))
            return classifier

        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory).resolve()
            with (
                patch(
                    "yap_server.lid.worker.load_lid_component_lock",
                    return_value=lock,
                ),
                patch("yap_server.lid.worker.verify_lid_model_artifacts"),
                patch(
                    "yap_server.lid.worker.load_lid_worker_request",
                    return_value=request,
                ),
                patch(
                    "yap_server.lid.worker.run_lid_worker_request",
                    return_value={"schemaVersion": 1},
                ) as run_request,
            ):
                result = execute_lid_worker(
                    lock_path=Path("component.json"),
                    model_dir=model_dir,
                    request_path=Path("request.json"),
                    probe_dir=Path("probes"),
                    classifier_loader=load_classifier,
                )

        self.assertEqual(calls, [(model_dir, 107)])
        run_request.assert_called_once_with(
            lock=lock,
            request=request,
            probe_root=Path("probes"),
            classifier=classifier,
        )
        self.assertEqual(result, {"schemaVersion": 1})

    def test_prints_one_bounded_success_object(self) -> None:
        output = io.StringIO()
        result = {"schemaVersion": 1, "requestId": "request-1"}
        with (
            patch("yap_server.lid.worker.execute_lid_worker", return_value=result),
            redirect_stdout(output),
        ):
            status = main(_ARGS)

        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue()), result)

    def test_preserves_controlled_input_errors_without_paths(self) -> None:
        output = io.StringIO()
        with (
            patch(
                "yap_server.lid.worker.execute_lid_worker",
                side_effect=WorkerInputError("probe digest differs"),
            ),
            redirect_stderr(output),
        ):
            status = main(_ARGS)

        payload = json.loads(output.getvalue())
        self.assertEqual(status, 2)
        self.assertEqual(payload["code"], "LID_WORKER_INPUT_INVALID")
        self.assertEqual(payload["message"], "probe digest differs")

    def test_redacts_component_and_inference_exception_details(self) -> None:
        failures = (
            (
                LidComponentArtifactError("C:/private/model is missing"),
                2,
                "LID_WORKER_COMPONENT_INVALID",
            ),
            (
                RuntimeError("private probe contents caused a failure"),
                1,
                "LID_WORKER_INFERENCE_FAILED",
            ),
        )
        for error, expected_status, expected_code in failures:
            with self.subTest(error=error):
                output = io.StringIO()
                with (
                    patch(
                        "yap_server.lid.worker.execute_lid_worker",
                        side_effect=error,
                    ),
                    redirect_stderr(output),
                ):
                    status = main(_ARGS)
                serialized = output.getvalue()
                self.assertEqual(status, expected_status)
                self.assertEqual(json.loads(serialized)["code"], expected_code)
                self.assertNotIn("private", serialized)
                self.assertNotIn("C:/", serialized)


if __name__ == "__main__":
    unittest.main()
