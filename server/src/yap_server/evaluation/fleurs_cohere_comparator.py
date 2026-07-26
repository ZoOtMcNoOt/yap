from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
from typing import Mapping, Protocol

from yap_server.evaluation.fleurs_comparator_plan import (
    FleursCohereComparatorPlan,
    FleursComparatorSelection,
    bind_fleurs_comparator_model,
    bind_fleurs_comparator_release,
    load_fleurs_cohere_comparator_plan,
    select_fleurs_comparator_run,
)
from yap_server.evaluation.fleurs_cohere_result import (
    build_fleurs_cohere_aggregate,
    score_fleurs_cohere_case,
    validate_fleurs_cohere_results,
)
from yap_server.evaluation.fleurs_corpus import (
    FleursComparatorCase,
    iter_fleurs_comparator_cases,
    load_fleurs_release_lock,
)
from yap_server.evaluation.transcript_scoring import TranscriptScore
from yap_server.pools.cohere_engine import CohereAsrEngine, CohereAsrInput
from yap_server.pools.model_lock import (
    ModelPoolLock,
    load_model_pool_lock,
    sha256_file,
    verify_model_artifacts,
)


class _CohereBatchEngine(Protocol):
    def transcribe_batch(
        self,
        requests: list[CohereAsrInput],
    ) -> list[dict[str, object]]: ...


def run_fleurs_cohere_comparator(
    *,
    plan_path: Path,
    release_lock_path: Path,
    model_lock_path: Path,
    archive_path: Path,
    metadata_path: Path,
    selection_id: str,
    result_dir: Path,
    model_dir: Path | None = None,
    engine: _CohereBatchEngine | None = None,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    """Run one locked FLEURS comparator and publish its case text privately."""

    plan = load_fleurs_cohere_comparator_plan(plan_path)
    selection = select_fleurs_comparator_run(plan, selection_id)
    target, parent = _private_result_target(result_dir, environ)
    if sha256_file(release_lock_path) != plan.source_release_lock_sha256:
        raise ValueError("FLEURS release lock differs from the comparator plan")
    if sha256_file(model_lock_path) != plan.model_lock_sha256:
        raise ValueError("Cohere model lock differs from the comparator plan")
    release_lock = load_fleurs_release_lock(release_lock_path)
    model_lock = load_model_pool_lock(model_lock_path)
    bind_fleurs_comparator_release(plan, release_lock, selection)
    bind_fleurs_comparator_model(plan, model_lock)

    active_engine = engine
    if active_engine is None:
        if model_dir is None:
            raise ValueError("the real comparator requires a Cohere model directory")
        verify_model_artifacts(model_lock, model_dir)
        active_engine = CohereAsrEngine(model_dir=model_dir, lock=model_lock)
    elif model_dir is not None:
        raise ValueError("an injected comparator engine cannot use a model directory")

    temporary: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", dir=parent)
    )
    try:
        if os.name == "posix":
            os.chmod(temporary, 0o700)
        cases = iter_fleurs_comparator_cases(
            lock=release_lock,
            archive_path=archive_path,
            metadata_path=metadata_path,
            case_count=selection.case_count,
            environ=environ,
        )
        first = next(cases)
        _warm_engine(
            active_engine,
            first,
            plan=plan,
            model_lock=model_lock,
        )

        scores: list[TranscriptScore] = []
        private_cases: list[dict[str, object]] = []
        batch_counts: dict[str, int] = {}
        total_audio_samples = 0
        batch_call_count = 0
        measured_started = time.monotonic()
        pending = [first]
        for case in cases:
            pending.append(case)
            if len(pending) == plan.batch_size:
                total_audio_samples += _run_batch(
                    pending,
                    active_engine=active_engine,
                    plan=plan,
                    model_lock=model_lock,
                    selection=selection,
                    scores=scores,
                    private_cases=private_cases,
                    batch_counts=batch_counts,
                )
                batch_call_count += 1
                pending = []
        if pending:
            total_audio_samples += _run_batch(
                pending,
                active_engine=active_engine,
                plan=plan,
                model_lock=model_lock,
                selection=selection,
                scores=scores,
                private_cases=private_cases,
                batch_counts=batch_counts,
            )
            batch_call_count += 1
        measured_ms = max(1, round((time.monotonic() - measured_started) * 1000))
        if len(scores) != selection.case_count:
            raise RuntimeError("FLEURS comparator did not complete its frozen selection")
        private_cases.sort(key=lambda item: int(item["caseIndex"]))
        aggregate = build_fleurs_cohere_aggregate(
            plan=plan,
            plan_path=plan_path,
            release_lock=release_lock,
            model_lock=model_lock,
            selection=selection,
            scores=scores,
            total_audio_samples=total_audio_samples,
            measured_ms=measured_ms,
            batch_call_count=batch_call_count,
            batch_counts=batch_counts,
        )
        _write_json(
            temporary / "case-evidence.json",
            {
                "schemaVersion": 1,
                "privacyScope": "private-case-evidence",
                "aggregate": aggregate,
                "cases": private_cases,
            },
        )
        _write_json(temporary / "aggregate.json", aggregate)
        if os.name == "posix":
            os.chmod(temporary / "case-evidence.json", 0o600)
            os.chmod(temporary / "aggregate.json", 0o600)
        os.replace(temporary, target)
        temporary = None
        return aggregate
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


def _warm_engine(
    engine: _CohereBatchEngine,
    case: FleursComparatorCase,
    *,
    plan: FleursCohereComparatorPlan,
    model_lock: ModelPoolLock,
) -> None:
    request = _request(
        case,
        job_id=f"fleurs-warmup-{case.case_index:06d}",
        plan=plan,
    )
    for _warmup_index in range(plan.warmup_cases):
        validate_fleurs_cohere_results(
            engine.transcribe_batch([request]),
            requests=[request],
            cases=[case],
            plan=plan,
            model_lock=model_lock,
        )


def _run_batch(
    cases: list[FleursComparatorCase],
    *,
    active_engine: _CohereBatchEngine,
    plan: FleursCohereComparatorPlan,
    model_lock: ModelPoolLock,
    selection: FleursComparatorSelection,
    scores: list[TranscriptScore],
    private_cases: list[dict[str, object]],
    batch_counts: dict[str, int],
) -> int:
    requests = [
        _request(
            case,
            job_id=f"fleurs-{selection.identifier}-{case.case_index:06d}",
            plan=plan,
        )
        for case in cases
    ]
    hypotheses = validate_fleurs_cohere_results(
        active_engine.transcribe_batch(requests),
        requests=requests,
        cases=cases,
        plan=plan,
        model_lock=model_lock,
    )
    batch_size = str(len(cases))
    batch_counts[batch_size] = batch_counts.get(batch_size, 0) + 1
    total_samples = 0
    for case, hypothesis in zip(cases, hypotheses, strict=True):
        score, private_evidence = score_fleurs_cohere_case(
            case,
            hypothesis,
            plan=plan,
        )
        scores.append(score)
        private_cases.append(private_evidence)
        total_samples += case.duration_samples
    return total_samples


def _request(
    case: FleursComparatorCase,
    *,
    job_id: str,
    plan: FleursCohereComparatorPlan,
) -> CohereAsrInput:
    return CohereAsrInput(
        job_id=job_id,
        audio=case.audio,
        language=plan.provider_language,
        punctuation=plan.punctuation,
    )


def _private_result_target(
    result_dir: Path,
    environ: Mapping[str, str],
) -> tuple[Path, Path]:
    raw_cache = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw_cache:
        raise ValueError("YAP_EVAL_CACHE is required for FLEURS comparator evidence")
    requested_cache = Path(raw_cache)
    if not requested_cache.is_absolute() or requested_cache.is_symlink():
        raise ValueError("YAP_EVAL_CACHE must be an absolute real directory")
    cache_root = requested_cache.resolve(strict=True)
    cache_metadata = cache_root.lstat()
    if stat.S_ISLNK(cache_metadata.st_mode) or not stat.S_ISDIR(
        cache_metadata.st_mode
    ):
        raise ValueError("YAP_EVAL_CACHE must be a real directory")
    if os.name == "posix" and stat.S_IMODE(cache_metadata.st_mode) & 0o077:
        raise ValueError("YAP_EVAL_CACHE must use private permissions")
    if not result_dir.is_absolute() or result_dir.is_symlink():
        raise ValueError("FLEURS comparator result must be an absolute real path")

    absolute_target = Path(os.path.abspath(result_dir))
    _require_inside_cache(absolute_target, cache_root, "FLEURS comparator result")
    parent = absolute_target.parent
    existing = parent
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    resolved_existing = existing.resolve(strict=True)
    if resolved_existing != cache_root:
        _require_inside_cache(
            resolved_existing,
            cache_root,
            "FLEURS comparator result parent",
        )
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved_parent = parent.resolve(strict=True)
    target = resolved_parent / absolute_target.name
    _require_inside_cache(target, cache_root, "FLEURS comparator result")
    if target.exists() or target.is_symlink():
        raise ValueError("FLEURS comparator result directory must not exist")
    if os.name == "posix" and stat.S_IMODE(resolved_parent.stat().st_mode) & 0o077:
        raise ValueError("FLEURS comparator result parent must be private")
    return target, resolved_parent


def _require_inside_cache(path: Path, cache_root: Path, field: str) -> None:
    if path == cache_root or cache_root not in path.parents:
        raise ValueError(f"{field} must remain inside YAP_EVAL_CACHE")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(
            payload,
            output,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the private locked FLEURS Cohere comparator",
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--release-lock", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--selection", choices=("screen", "full"), required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    aggregate = run_fleurs_cohere_comparator(
        plan_path=arguments.plan,
        release_lock_path=arguments.release_lock,
        model_lock_path=arguments.model_lock,
        archive_path=arguments.archive,
        metadata_path=arguments.metadata,
        model_dir=arguments.model_dir,
        selection_id=arguments.selection,
        result_dir=arguments.result_dir,
    )
    print(json.dumps(aggregate, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
