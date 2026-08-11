from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from yap_server.pools.agent_model_snapshot import verify_agent_model_snapshot
from yap_server.pools.agent_vllm_service_profile import (
    AgentVllmServiceProfile,
    load_agent_vllm_service_profile,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CANDIDATE_LOCK = REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json"
PROFILE_ROOT = REPOSITORY_ROOT / "server" / "agent-service-profiles"
PROFILE_PATHS = (
    PROFILE_ROOT / "rapid-automation.json",
    PROFILE_ROOT / "complex-orchestration.json",
)


class AgentVllmServiceProfileTests(unittest.TestCase):
    def test_profiles_bind_the_two_qualified_routes_without_shared_identity(self) -> None:
        rapid, complex_route = tuple(self._load(path) for path in PROFILE_PATHS)

        self.assertEqual(rapid.profile_id, "rapid-automation")
        self.assertEqual(rapid.candidate_id, "qwen3.6-35b-a3b-nvfp4")
        self.assertEqual(rapid.endpoint, "http://127.0.0.1:18100")
        self.assertEqual(rapid.container_name, "yap-agent-qwen-rapid")
        self.assertEqual(rapid.expected_model, "nvidia/Qwen3.6-35B-A3B-NVFP4")
        self.assertIn("--reasoning-parser", rapid.launch_arguments)
        self.assertIn("qwen3", rapid.launch_arguments)
        self.assertIn("qwen3_xml", rapid.launch_arguments)
        self.assertIn("0.40", rapid.launch_arguments)
        self.assertEqual(rapid.maximum_sequences, 4)

        self.assertEqual(complex_route.profile_id, "complex-orchestration")
        self.assertEqual(complex_route.candidate_id, "gemma-4-31b-it-nvfp4")
        self.assertEqual(complex_route.endpoint, "http://127.0.0.1:18101")
        self.assertEqual(complex_route.container_name, "yap-agent-gemma-complex")
        self.assertEqual(
            complex_route.expected_model,
            "nvidia/Gemma-4-31B-IT-NVFP4",
        )
        self.assertNotIn("--reasoning-parser", complex_route.launch_arguments)
        self.assertIn("gemma4", complex_route.launch_arguments)
        self.assertIn(
            "/opt/vllm/vllm-src/examples/tool_chat_template_gemma4.jinja",
            complex_route.launch_arguments,
        )
        self.assertIn("0.70", complex_route.launch_arguments)
        self.assertEqual(complex_route.maximum_sequences, 8)

        self.assertNotEqual(rapid.endpoint, complex_route.endpoint)
        self.assertNotEqual(rapid.container_name, complex_route.container_name)
        self.assertNotEqual(rapid.image_id, complex_route.image_id)
        self.assertNotEqual(rapid.candidate_id, complex_route.candidate_id)

    def test_profile_arguments_use_the_private_container_endpoint_and_exact_bounds(
        self,
    ) -> None:
        for path in PROFILE_PATHS:
            with self.subTest(profile=path.name):
                profile = self._load(path)
                arguments = profile.launch_arguments
                self.assertEqual(
                    arguments[:3],
                    (
                        "vllm",
                        "serve",
                        f"/model-cache/snapshots/{profile.model_revision}",
                    ),
                )
                self.assertEqual(_option(arguments, "--host"), "0.0.0.0")
                self.assertEqual(
                    _option(arguments, "--port"), str(profile.container_port)
                )
                self.assertEqual(
                    _option(arguments, "--served-model-name"),
                    profile.expected_model,
                )
                self.assertEqual(_option(arguments, "--max-model-len"), "8192")
                self.assertEqual(_option(arguments, "--tensor-parallel-size"), "1")
                self.assertEqual(_option(arguments, "--kv-cache-dtype"), "fp8")
                self.assertEqual(
                    _option(arguments, "--max-num-seqs"),
                    str(profile.maximum_sequences),
                )
                self.assertEqual(
                    _option(arguments, "--max-num-batched-tokens"), "8192"
                )
                for flag in (
                    "--enable-auto-tool-choice",
                    "--enable-prefix-caching",
                    "--enable-chunked-prefill",
                    "--async-scheduling",
                    "--language-model-only",
                ):
                    self.assertIn(flag, arguments)

                self.assertGreater(profile.resources.memory_bytes, 0)
                self.assertEqual(
                    profile.resources.memory_bytes,
                    profile.resources.memory_swap_bytes,
                )
                self.assertEqual(profile.resources.cpu_count, 16)
                self.assertEqual(profile.resources.pids_limit, 4096)
                self.assertEqual(profile.resources.shm_bytes, 17_179_869_184)
                self.assertEqual(profile.resources.tmpfs_bytes, 8_589_934_592)

    def test_profile_hash_and_candidate_lock_drift_fail_closed(self) -> None:
        profile_path = PROFILE_PATHS[0]
        profile_sha256 = _sha256(profile_path)
        with self.assertRaisesRegex(ValueError, "profile bytes differ"):
            load_agent_vllm_service_profile(
                profile_path,
                CANDIDATE_LOCK,
                expected_profile_sha256="0" * 64,
            )

        with tempfile.TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "candidate-lock.json"
            lock = json.loads(CANDIDATE_LOCK.read_text(encoding="utf-8"))
            lock["candidates"][0]["model"] = "unreviewed/model"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "candidate lock bytes differ"):
                load_agent_vllm_service_profile(
                    profile_path,
                    lock_path,
                    expected_profile_sha256=profile_sha256,
                )

    def test_profile_rejects_duplicate_keys_and_oversized_documents(self) -> None:
        original = PROFILE_PATHS[0].read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            duplicate_path = Path(temporary) / "duplicate.json"
            duplicate_path.write_bytes(
                original.replace(
                    b'"schemaVersion": 1',
                    b'"schemaVersion": 1, "schemaVersion": 1',
                    1,
                )
            )
            with self.assertRaisesRegex(ValueError, "profile is invalid"):
                load_agent_vllm_service_profile(
                    duplicate_path,
                    CANDIDATE_LOCK,
                    expected_profile_sha256=_sha256(duplicate_path),
                )

            oversized_path = Path(temporary) / "oversized.json"
            oversized_path.write_bytes(original + b" " * 1_048_576)
            with self.assertRaisesRegex(ValueError, "profile size is invalid"):
                load_agent_vllm_service_profile(
                    oversized_path,
                    CANDIDATE_LOCK,
                    expected_profile_sha256=_sha256(oversized_path),
                )

    def test_profile_semantic_mutations_fail_even_with_a_matching_new_hash(self) -> None:
        original = json.loads(PROFILE_PATHS[0].read_text(encoding="utf-8"))
        mutations = (
            ("service", "complex-orchestration"),
            ("endpoint", "http://127.0.0.1:18101"),
            ("containerName", "yap-agent-gemma-complex"),
            ("candidateId", "gemma-4-31b-it-nvfp4"),
            ("expectedModel", "unreviewed/model"),
            ("modelRevision", "0" * 40),
            ("toolCallParser", "gemma4"),
            ("finalResponseProtocol", "forced-answer-tool"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for field, value in mutations:
                with self.subTest(field=field):
                    mutated = dict(original)
                    mutated[field] = value
                    path = Path(temporary) / f"{field}.json"
                    path.write_text(
                        json.dumps(mutated, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    with self.assertRaises(ValueError):
                        load_agent_vllm_service_profile(
                            path,
                            CANDIDATE_LOCK,
                            expected_profile_sha256=_sha256(path),
                        )

    def test_runtime_result_cannot_be_relabelled_as_another_route(self) -> None:
        profile = self._load(PROFILE_PATHS[0])
        relabelled = replace(profile, service="complex-orchestration")
        self.assertNotEqual(relabelled.service, profile.service)
        with self.assertRaisesRegex(ValueError, "profile identity differs"):
            relabelled.validate_identity()

    def test_model_snapshot_is_recomputed_before_a_profile_can_launch(self) -> None:
        profile = self._load(PROFILE_PATHS[0])
        with tempfile.TemporaryDirectory() as temporary:
            model_root = Path(temporary) / "models--nvidia--Qwen"
            snapshot = model_root / "snapshots" / profile.model_revision
            blobs = model_root / "blobs"
            snapshot.mkdir(parents=True)
            blobs.mkdir()
            (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
            (snapshot / "tokenizer_config.json").write_text(
                '{"model_max_length":8192}\n',
                encoding="utf-8",
            )
            weight_sha256 = "a" * 64
            weight_blob = blobs / weight_sha256
            weight_blob.write_bytes(b"checked-weight")
            try:
                (snapshot / "model.safetensors").symlink_to(weight_blob)
            except OSError as error:
                self.skipTest(f"symbolic-link capability unavailable: {error}")

            artifacts = []
            for path in sorted(snapshot.iterdir(), key=lambda item: item.name):
                resolved = path.resolve(strict=True)
                artifacts.append(
                    {
                        "path": path.name,
                        "blobIdentity": resolved.name,
                        "size": resolved.stat().st_size,
                        "sha256": (
                            resolved.name
                            if path.name.endswith(".safetensors")
                            else hashlib.sha256(resolved.read_bytes()).hexdigest()
                        ),
                    }
                )
            identity = {
                "schemaVersion": 1,
                "model": profile.expected_model,
                "revision": profile.model_revision,
                "artifacts": artifacts,
            }
            manifest_sha256 = hashlib.sha256(
                json.dumps(
                    identity,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            synthetic = replace(
                profile,
                model_artifact_manifest_sha256=manifest_sha256,
            )
            verify_agent_model_snapshot(
                expected_model=synthetic.expected_model,
                model_revision=synthetic.model_revision,
                expected_manifest_sha256=(
                    synthetic.model_artifact_manifest_sha256
                ),
                snapshot_path=snapshot,
            )

            (snapshot / "config.json").write_text(
                '{"changed":true}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "artifacts differ"):
                verify_agent_model_snapshot(
                    expected_model=synthetic.expected_model,
                    model_revision=synthetic.model_revision,
                    expected_manifest_sha256=(
                        synthetic.model_artifact_manifest_sha256
                    ),
                    snapshot_path=snapshot,
                )

    def _load(self, path: Path) -> AgentVllmServiceProfile:
        return load_agent_vllm_service_profile(
            path,
            CANDIDATE_LOCK,
            expected_profile_sha256=_sha256(path),
        )


def _option(arguments: tuple[str, ...], name: str) -> str:
    index = arguments.index(name)
    return arguments[index + 1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
