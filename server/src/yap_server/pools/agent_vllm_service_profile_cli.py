from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .agent_model_snapshot import verify_agent_model_snapshot
from .agent_vllm_service_profile import load_agent_vllm_service_profile
from .numeric_loopback_endpoint import parse_numeric_loopback_http_endpoint


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read one exact Yap agent vLLM service profile.",
        allow_abbrev=False,
    )
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--candidate-lock", type=Path, required=True)
    parser.add_argument("--model-snapshot", type=Path, required=True)
    parser.add_argument("--emit-null", action="store_true", required=True)
    parsed = parser.parse_args(arguments)
    try:
        profile = load_agent_vllm_service_profile(
            parsed.profile,
            parsed.candidate_lock,
            expected_profile_sha256=parsed.profile_sha256,
        )
        verify_agent_model_snapshot(
            expected_model=profile.expected_model,
            model_revision=profile.model_revision,
            expected_manifest_sha256=profile.model_artifact_manifest_sha256,
            snapshot_path=parsed.model_snapshot,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    _, endpoint_port = parse_numeric_loopback_http_endpoint(
        profile.endpoint,
        component="agent service profile",
    )
    values = [
        profile.profile_id,
        profile.service,
        str(endpoint_port),
        profile.container_name,
        profile.image,
        profile.image_id,
        profile.expected_model,
        profile.model_revision,
        profile.model_artifact_manifest_sha256,
        str(profile.container_port),
        str(profile.resources.memory_bytes),
        str(profile.resources.memory_swap_bytes),
        str(profile.resources.cpu_count),
        str(profile.resources.pids_limit),
        str(profile.resources.shm_bytes),
        str(profile.resources.tmpfs_bytes),
        "1" if profile.batch_invariant else "0",
        str(len(profile.launch_arguments)),
        *profile.launch_arguments,
    ]
    sys.stdout.buffer.write(
        b"\0".join(value.encode("utf-8") for value in values) + b"\0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
