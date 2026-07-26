from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile

from yap_server.capabilities import load_asr_capability_catalog
from yap_server.pools.batch_asr import (
    AsrRouteDecision,
    BatchAsrJob,
    BatchAsrPool,
    ContainerBatchAsrWorker,
    inspect_worker_image as inspect_container_image,
)
from yap_server.transcript_metrics import word_error_rate
from yap_server.pools.model_lock import (
    load_model_pool_lock,
    sha256_file,
    verify_fixture,
    verify_model_artifacts,
)
from yap_server.workload_router import WorkloadRequest, WorkloadRouter


_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GB10_DEVICE_NAME = "NVIDIA GB10"
_GB10_COMPUTE_CAPABILITY = [12, 1]
_GB10_DTYPE = "bfloat16"


def validate_gb10_runtime(runtime: object) -> None:
    if not isinstance(runtime, dict) or runtime.get("device") != "cuda":
        raise RuntimeError("worker result did not attest CUDA execution")
    if runtime.get("deviceName") != _GB10_DEVICE_NAME:
        raise RuntimeError("worker result did not attest the NVIDIA GB10 device")
    if runtime.get("computeCapability") != _GB10_COMPUTE_CAPABILITY:
        raise RuntimeError(
            "worker result did not attest GB10 compute capability 12.1"
        )
    if runtime.get("dtype") != _GB10_DTYPE:
        raise RuntimeError("worker result did not attest BF16 model execution")


def run_gb10_asr_runtime_gate(
    *,
    checked_head: str,
    image: str,
    preparation_receipt_sha256: str,
    lock_path: Path,
    model_dir: Path,
    repo_root: Path,
    result_path: Path,
    evidence_path: Path,
    max_wer: float,
) -> dict[str, object]:
    if not _GIT_SHA.fullmatch(checked_head):
        raise ValueError("checked head must be a full lowercase Git SHA")
    if not _SHA256.fullmatch(preparation_receipt_sha256):
        raise ValueError("preparation receipt SHA-256 is invalid")
    if not 0 <= max_wer <= 1:
        raise ValueError("max WER must be between zero and one")

    lock = load_model_pool_lock(lock_path)
    verify_model_artifacts(lock, model_dir)
    asr_catalog = load_asr_capability_catalog(
        lock_path.with_name("asr-capabilities.lock.json"),
        (lock,),
    )
    providers = asr_catalog.get("providers")
    if not isinstance(providers, list) or len(providers) != 1:
        raise RuntimeError("GB10 ASR runtime gate requires one verified provider")
    provider = providers[0]
    catalog_revision = asr_catalog.get("catalogRevision")
    if (
        not isinstance(provider, dict)
        or provider.get("poolId") != lock.pool_id
        or not isinstance(provider.get("providerId"), str)
        or not isinstance(catalog_revision, str)
    ):
        raise RuntimeError("GB10 ASR runtime gate provider identity is invalid")
    provider_id = provider["providerId"]

    def resolve_route(provider_language: str) -> AsrRouteDecision:
        return AsrRouteDecision(
            provider_id=provider_id,
            pool_id=lock.pool_id,
            execution_mode="fixedBatch",
            model_revision=lock.model_revision,
            provider_language=provider_language,
        )

    fixture = verify_fixture(lock, repo_root)
    container = inspect_container_image(image, checked_head)
    inspected_image_id = container.get("id")
    if not isinstance(inspected_image_id, str):
        raise RuntimeError("worker image inspection did not return an immutable image ID")
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if not callable(getuid) or not callable(getgid):
        raise RuntimeError("the GB10 ASR runtime gate requires a POSIX service identity")
    worker = ContainerBatchAsrWorker(
        image=inspected_image_id,
        model_dir=model_dir,
        lock=lock,
        run_as_uid=getuid(),
        run_as_gid=getgid(),
        checked_head=checked_head,
        storage_namespace="gb10-asr-runtime-gate",
    )
    router = WorkloadRouter(max_pending=4, max_pending_per_owner=2)
    request = WorkloadRequest(
        "gb10-asr-runtime-gate",
        "checked-head-gate",
        "batch",
    )
    router.enqueue(request)
    dispatched = router.dispatch(available_targets={"batch-asr"})
    if dispatched is None or dispatched.request != request:
        raise RuntimeError("batch workload did not dispatch to the reference pool")

    pool = BatchAsrPool(
        worker,
        route_resolver=resolve_route,
        asr_catalog_revision=catalog_revision,
        max_workers=1,
        max_queued=0,
    )
    try:
        result = pool.submit(
            BatchAsrJob(
                request.job_id,
                fixture,
                result_path,
                language="en",
                input_sha256=lock.fixture.sha256,
                route=resolve_route("en"),
            )
        ).result(timeout=35 * 60)
    finally:
        pool.shutdown()

    model = result.get("model")
    runtime = result.get("runtime")
    transcript = result.get("transcript")
    if not isinstance(model, dict) or (
        model.get("id") != lock.model_id
        or model.get("revision") != lock.model_revision
        or model.get("poolId") != lock.pool_id
    ):
        raise RuntimeError("worker result did not attest the locked model")
    validate_gb10_runtime(runtime)
    if not isinstance(transcript, dict) or not isinstance(transcript.get("text"), str):
        raise RuntimeError("worker result did not contain a transcript")
    measured_wer = word_error_rate(lock.fixture.golden_transcript, transcript["text"])
    if measured_wer > max_wer:
        raise RuntimeError(
            f"fixture WER {measured_wer:.4f} exceeds the {max_wer:.4f} gate"
        )

    result_digest = sha256_file(result_path)
    evidence: dict[str, object] = {
        "schemaVersion": 1,
        "phase": 4,
        "checkedHead": checked_head,
        "container": container,
        "containerPreparationReceiptSha256": preparation_receipt_sha256,
        "model": model,
        "fixture": {
            "sha256": lock.fixture.sha256,
            "license": lock.fixture.license,
        },
        "wordErrorRate": measured_wer,
        "maximumWordErrorRate": max_wer,
        "resultSha256": result_digest,
        "runtime": runtime,
        "boundary": {
            "network": "none",
            "workerCount": 1,
            "hostObservation": "pending-wrapper-read-back",
        },
    }
    _write_json_atomic(evidence_path, evidence)
    return evidence


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, ensure_ascii=True, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the transient checked-head GB10 ASR runtime gate"
    )
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--preparation-receipt-sha256", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--max-wer", type=float, default=0.12)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    evidence = run_gb10_asr_runtime_gate(
        checked_head=arguments.checked_head,
        image=arguments.image,
        preparation_receipt_sha256=arguments.preparation_receipt_sha256,
        lock_path=Path(arguments.lock),
        model_dir=Path(arguments.model_dir),
        repo_root=Path(arguments.repo_root),
        result_path=Path(arguments.result),
        evidence_path=Path(arguments.evidence),
        max_wer=arguments.max_wer,
    )
    print(json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
