from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

from yap_server.evaluation.provider_resource_observations import (
    load_private_resource_samples,
)
from yap_server.evaluation.resident_provider_resource_sampler import (
    collect_resident_provider_resource_samples,
    inspect_resident_provider_resource_boundary,
    read_resident_provider_resource_sample,
)


CHECKED_HEAD = "a" * 40


def _write_runtime_files(root: Path) -> tuple[Path, Path]:
    proc_root = root / "proc"
    cgroup_root = root / "sys" / "fs" / "cgroup"
    process_root = proc_root / "4242"
    resource_root = cgroup_root / "docker" / "yap.scope"
    process_root.mkdir(parents=True)
    resource_root.mkdir(parents=True)
    (process_root / "cgroup").write_text(
        "0::/docker/yap.scope\n",
        encoding="utf-8",
    )
    (process_root / "status").write_text(
        "\n".join(
            (
                "Name:\tpython3",
                "State:\tS (sleeping)",
                "Uid:\t10001\t10001\t10001\t10001",
                "VmRSS:\t100 kB",
                "RssAnon:\t40 kB",
                "RssFile:\t50 kB",
                "RssShmem:\t10 kB",
                "VmData:\t200 kB",
                "Threads:\t8",
                "",
            )
        ),
        encoding="utf-8",
    )
    files = {
        "memory.current": "102400\n",
        "memory.peak": "204800\n",
        "memory.stat": "anon 40960\nfile 51200\nkernel 10240\n",
        "memory.events": "low 0\nhigh 1\nmax 2\noom 0\noom_kill 0\n",
        "cpu.stat": "usage_usec 123456\nuser_usec 100000\nsystem_usec 23456\n",
        "pids.current": "8\n",
    }
    for name, body in files.items():
        (resource_root / name).write_text(body, encoding="utf-8")
    return proc_root, cgroup_root


def _docker_inspect_runner(
    *args: object,
    **kwargs: object,
) -> subprocess.CompletedProcess[str]:
    del args, kwargs
    return subprocess.CompletedProcess(
        args=["docker"],
        returncode=0,
        stdout=json.dumps(
            [
                {
                    "State": {"Running": True, "Pid": 4242},
                    "Config": {
                        "Labels": {
                            "io.yap.owner": "private-inference",
                            "io.yap.revision": CHECKED_HEAD,
                        }
                    },
                }
            ]
        ),
        stderr="",
    )


class ResidentProviderResourceSamplerTests(unittest.TestCase):
    def test_inspects_the_owned_container_and_reads_cgroup_v2_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_root, cgroup_root = _write_runtime_files(root)
            boundary = inspect_resident_provider_resource_boundary(
                container_name="yap-cohere-vllm",
                checked_head=CHECKED_HEAD,
                runner=_docker_inspect_runner,
                proc_root=proc_root,
                cgroup_root=cgroup_root,
            )
            sample = read_resident_provider_resource_sample(
                boundary,
                elapsed_ms=250,
            )

        self.assertEqual(boundary.process_id, 4242)
        self.assertEqual(sample.elapsed_ms, 250)
        self.assertEqual(sample.memory_current_bytes, 102_400)
        self.assertEqual(sample.memory_peak_bytes, 204_800)
        self.assertEqual(sample.cgroup_anon_bytes, 40_960)
        self.assertEqual(sample.process_resident_bytes, 102_400)
        self.assertEqual(sample.process_virtual_data_bytes, 204_800)
        self.assertEqual(sample.process_thread_count, 8)
        self.assertEqual(sample.memory_high_events, 1)
        self.assertEqual(sample.memory_max_events, 2)
        self.assertEqual(sample.cpu_usage_usec, 123_456)
        self.assertEqual(sample.task_count, 8)

    def test_collects_until_explicit_markers_and_writes_the_workload_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_root, cgroup_root = _write_runtime_files(root)
            boundary = inspect_resident_provider_resource_boundary(
                container_name="yap-nemotron-nemo",
                checked_head=CHECKED_HEAD,
                runner=_docker_inspect_runner,
                proc_root=proc_root,
                cgroup_root=cgroup_root,
            )
            output = root / "resources.jsonl"
            control = root / "control"
            control.mkdir()
            outcome: dict[str, object] = {}

            def collect() -> None:
                try:
                    outcome["window"] = collect_resident_provider_resource_samples(
                        boundary,
                        output_path=output,
                        control_directory=control,
                        interval_ms=10,
                    )
                except BaseException as error:  # pragma: no cover - assertion aid
                    outcome["error"] = error

            worker = threading.Thread(target=collect, daemon=True)
            worker.start()
            deadline = time.monotonic() + 2
            while not (control / "ready.json").exists():
                if "error" in outcome:
                    raise AssertionError("resource sampler failed before ready") from outcome[
                        "error"
                    ]
                if time.monotonic() >= deadline:
                    self.fail("resource sampler did not become ready")
                time.sleep(0.005)
            (control / "workload-start").touch()
            time.sleep(0.08)
            (control / "workload-end").touch()
            time.sleep(0.03)
            (control / "stop").touch()
            worker.join(timeout=2)

            self.assertFalse(worker.is_alive())
            self.assertNotIn("error", outcome)
            window = outcome["window"]
            lines = output.read_text(encoding="utf-8").splitlines()
            encoded_window = json.loads(
                (control / "workload-window.json").read_text(encoding="utf-8")
            )
            loaded = load_private_resource_samples(
                output,
                environ={"YAP_EVAL_CACHE": str(root)},
            )
            if os.name == "posix":
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)

        self.assertGreaterEqual(len(lines), 8)
        self.assertEqual(len(loaded), len(lines))
        self.assertGreater(window.workload_end_ms, window.workload_start_ms)
        self.assertEqual(encoded_window["sampleCount"], len(lines))
        self.assertEqual(
            encoded_window["workloadStartMs"],
            window.workload_start_ms,
        )
        self.assertEqual(
            encoded_window["workloadEndMs"],
            window.workload_end_ms,
        )
    def test_rejects_an_unowned_or_root_container(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_root, cgroup_root = _write_runtime_files(root)
            status = proc_root / "4242" / "status"
            status.write_text(
                status.read_text(encoding="utf-8").replace(
                    "Uid:\t10001\t10001\t10001\t10001",
                    "Uid:\t0\t0\t0\t0",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "non-root"):
                inspect_resident_provider_resource_boundary(
                    container_name="yap-cohere-vllm",
                    checked_head=CHECKED_HEAD,
                    runner=_docker_inspect_runner,
                    proc_root=proc_root,
                    cgroup_root=cgroup_root,
                )


if __name__ == "__main__":
    unittest.main()
