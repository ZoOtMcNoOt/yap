from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any, Callable, Sequence

from yap_server.bounded_file import read_regular_file


class CheckedRuntimeImageError(RuntimeError):
    pass


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
BASE_DIGEST_LABEL = "com.mcnatg1.yap.base-platform-digest"
REVISION_LABEL = "org.opencontainers.image.revision"
RUNTIME_LABEL = "com.mcnatg1.yap.runtime"
PREPARATION_RECEIPT_SCHEMA_VERSION = 1
MAXIMUM_PREPARATION_RECEIPT_BYTES = 16 * 1024


@dataclass(frozen=True)
class CheckedRuntimeImageContract:
    runtime: str
    dockerfile: Path
    image: str
    checked_head: str
    base_digest: str


_RUNTIMES = {
    "cohere-vllm": ("runtime/cohere-vllm/Dockerfile", "yap-cohere-vllm"),
    "nemotron-nemo": ("runtime/nemotron-nemo/Dockerfile", "yap-nemotron-nemo"),
    "language-detection": ("runtime/lid/Dockerfile", "yap-lid"),
    "meeting-transcription": ("runtime/tiron/Dockerfile", "yap-tiron"),
    "reference-batch-asr": ("runtime/asr/Dockerfile", "yap-gb10-asr"),
}


def external_base_references(dockerfile: Path) -> tuple[str, ...]:
    arguments: dict[str, str] = {}
    stages: set[str] = set()
    bases: list[str] = []

    for line_number, raw_line in enumerate(
        dockerfile.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        instruction, _, value = line.partition(" ")
        instruction = instruction.upper()
        value = value.strip()
        if instruction == "ARG":
            name, separator, default = value.partition("=")
            if separator:
                arguments[name.strip()] = default.strip()
            continue
        if instruction != "FROM":
            continue

        tokens = shlex.split(value)
        while tokens and tokens[0].startswith("--"):
            tokens.pop(0)
        if not tokens:
            raise CheckedRuntimeImageError(
                f"{dockerfile}:{line_number}: FROM has no image"
            )

        def expand(match: re.Match[str]) -> str:
            name = match.group(1) or match.group(2)
            if name not in arguments:
                raise CheckedRuntimeImageError(
                    f"{dockerfile}:{line_number}: unresolved build argument {name}"
                )
            return arguments[name]

        reference = re.sub(
            r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)",
            expand,
            tokens[0],
        )
        if reference not in stages:
            if re.fullmatch(r".+@sha256:[0-9a-f]{64}", reference) is None:
                raise CheckedRuntimeImageError(
                    f"{dockerfile}:{line_number}: external base is not "
                    f"digest-pinned: {reference}"
                )
            if reference not in bases:
                bases.append(reference)

        for index, token in enumerate(tokens[1:], start=1):
            if token.upper() == "AS" and index + 1 < len(tokens):
                stages.add(tokens[index + 1])
                break

    if not bases:
        raise CheckedRuntimeImageError(
            f"{dockerfile}: no external base image was found"
        )
    return tuple(bases)


def runtime_image_contract(
    repository_root: Path,
    runtime: str,
    checked_head: str,
) -> CheckedRuntimeImageContract:
    if SHA40.fullmatch(checked_head) is None:
        raise CheckedRuntimeImageError(
            "Checked head must be one full lowercase Git SHA"
        )
    try:
        dockerfile_relative, image_name = _RUNTIMES[runtime]
    except KeyError as error:
        raise CheckedRuntimeImageError(
            f"Unsupported checked runtime: {runtime}"
        ) from error

    dockerfile = repository_root / "server" / dockerfile_relative
    bases = external_base_references(dockerfile)
    base_digests = {reference.rsplit("@", maxsplit=1)[1] for reference in bases}
    if len(base_digests) != 1:
        raise CheckedRuntimeImageError(
            f"{runtime} must resolve to one immutable base platform digest"
        )
    return CheckedRuntimeImageContract(
        runtime=runtime,
        dockerfile=dockerfile,
        image=f"{image_name}:checked-head-{checked_head}",
        checked_head=checked_head,
        base_digest=next(iter(base_digests)),
    )


def _inspect_local_image(
    reference: str,
    *,
    runner: CommandRunner,
    missing_message: str,
) -> dict[str, Any]:
    command = ["docker", "image", "inspect", reference]
    try:
        completed = runner(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CheckedRuntimeImageError(f"{missing_message}: {reference}") from error

    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise CheckedRuntimeImageError(
            f"Docker returned invalid image inspection JSON for {reference}"
        ) from error
    if not isinstance(payload, list) or len(payload) != 1:
        raise CheckedRuntimeImageError(
            f"Docker returned an ambiguous image inspection for {reference}"
        )
    image = payload[0]
    if not isinstance(image, dict) or SHA256.fullmatch(str(image.get("Id"))) is None:
        raise CheckedRuntimeImageError(
            f"Docker returned an invalid local image identity for {reference}"
        )
    return image


def verify_local_checked_image(
    contract: CheckedRuntimeImageContract,
    *,
    runner: CommandRunner = subprocess.run,
) -> dict[str, str]:
    image = _inspect_local_image(
        contract.image,
        runner=runner,
        missing_message="Prepared checked runtime image is required",
    )
    architecture = image.get("Architecture")
    configuration = image.get("Config")
    if not isinstance(configuration, dict):
        raise CheckedRuntimeImageError(
            f"Docker returned an invalid image configuration for {contract.image}"
        )
    labels = configuration.get("Labels")
    if not isinstance(labels, dict):
        raise CheckedRuntimeImageError(
            f"Docker returned invalid image labels for {contract.image}"
        )
    if architecture != "arm64":
        raise CheckedRuntimeImageError(
            f"Prepared checked runtime image is not ARM64: {contract.image}"
        )
    if labels.get(REVISION_LABEL) != contract.checked_head:
        raise CheckedRuntimeImageError(
            f"Prepared checked runtime image revision differs: {contract.image}"
        )
    if labels.get(BASE_DIGEST_LABEL) != contract.base_digest:
        raise CheckedRuntimeImageError(
            f"Prepared checked runtime image base digest differs: {contract.image}"
        )
    if labels.get(RUNTIME_LABEL) != contract.runtime:
        raise CheckedRuntimeImageError(
            f"Prepared checked runtime image runtime identity differs: {contract.image}"
        )
    return {
        "runtime": contract.runtime,
        "image": contract.image,
        "imageId": str(image["Id"]),
        "architecture": architecture,
        "revision": contract.checked_head,
        "baseDigest": contract.base_digest,
    }


def _command_stdout(
    command: Sequence[str],
    *,
    runner: CommandRunner,
) -> str:
    try:
        result = runner(
            list(command),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CheckedRuntimeImageError(
            f"Command failed: {' '.join(command)}"
        ) from error
    return result.stdout.strip()


def assert_clean_checked_head(
    repository_root: Path,
    checked_head: str,
    *,
    runner: CommandRunner = subprocess.run,
) -> None:
    actual_head = _command_stdout(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        runner=runner,
    )
    if actual_head != checked_head:
        raise CheckedRuntimeImageError(
            "Checked head does not match the repository HEAD"
        )
    # git status --porcelain=v1 --untracked-files=normal
    status = _command_stdout(
        [
            "git",
            "-C",
            str(repository_root),
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
        ],
        runner=runner,
    )
    if status:
        raise CheckedRuntimeImageError(
            "Checked runtime image operations require a clean worktree"
        )


def prepare_checked_runtime_image(
    repository_root: Path,
    contract: CheckedRuntimeImageContract,
    *,
    runner: CommandRunner = subprocess.run,
) -> dict[str, str]:
    for reference in external_base_references(contract.dockerfile):
        _inspect_local_image(
            reference,
            runner=runner,
            missing_message="Cached digest-pinned base image is required",
        )

    command = [
        "docker",
        "build",
        "--pull=false",
        "--build-arg",
        f"YAP_CHECKED_HEAD={contract.checked_head}",
        "--file",
        str(contract.dockerfile),
        "--tag",
        contract.image,
        str(repository_root / "server"),
    ]
    try:
        runner(command, check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise CheckedRuntimeImageError(
            f"Checked runtime image preparation failed: {contract.runtime}"
        ) from error
    return verify_local_checked_image(contract, runner=runner)


def preparation_receipt(
    contract: CheckedRuntimeImageContract,
    prepared_image: dict[str, str],
) -> dict[str, object]:
    return {
        "schemaVersion": PREPARATION_RECEIPT_SCHEMA_VERSION,
        "checkedHead": contract.checked_head,
        "runtime": contract.runtime,
        "dockerfileSha256": hashlib.sha256(
            contract.dockerfile.read_bytes()
        ).hexdigest(),
        "image": contract.image,
        "imageId": prepared_image["imageId"],
        "architecture": prepared_image["architecture"],
        "baseDigest": prepared_image["baseDigest"],
    }


def verify_prepared_checked_image(
    contract: CheckedRuntimeImageContract,
    *,
    receipt_path: Path,
    receipt_sha256: str,
    runner: CommandRunner = subprocess.run,
) -> dict[str, str]:
    if not receipt_path.is_absolute():
        raise CheckedRuntimeImageError(
            "Checked runtime preparation receipt must use an absolute path"
        )
    if re.fullmatch(r"[0-9a-f]{64}", receipt_sha256) is None:
        raise CheckedRuntimeImageError(
            "Checked runtime preparation receipt SHA-256 is invalid"
        )
    try:
        receipt_bytes = read_regular_file(
            receipt_path,
            MAXIMUM_PREPARATION_RECEIPT_BYTES,
        )
    except ValueError as error:
        raise CheckedRuntimeImageError(str(error)) from error
    if hashlib.sha256(receipt_bytes).hexdigest() != receipt_sha256:
        raise CheckedRuntimeImageError(
            "Checked runtime preparation receipt SHA-256 differs"
        )
    try:
        receipt = json.loads(receipt_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise CheckedRuntimeImageError(
            "Checked runtime preparation receipt is invalid JSON"
        ) from error
    if not isinstance(receipt, dict):
        raise CheckedRuntimeImageError(
            "Checked runtime preparation receipt must be an object"
        )

    inspected = verify_local_checked_image(contract, runner=runner)
    expected = preparation_receipt(contract, inspected)
    if receipt != expected:
        raise CheckedRuntimeImageError(
            "Checked runtime image differs from its frozen preparation receipt"
        )
    return inspected


def _run_cli(arguments: list[str]) -> int:
    if (
        len(arguments) == 3
        and arguments[0] in {"prepare", "verify"}
    ):
        operation, runtime, checked_head = arguments
        receipt_path = None
        receipt_sha256 = None
    elif len(arguments) == 5 and arguments[0] == "verify-prepared":
        operation, runtime, checked_head, raw_receipt_path, receipt_sha256 = arguments
        receipt_path = Path(raw_receipt_path)
    else:
        raise CheckedRuntimeImageError(
            "usage: checked_runtime_image.py prepare|verify RUNTIME CHECKED_HEAD "
            "or verify-prepared RUNTIME CHECKED_HEAD RECEIPT RECEIPT_SHA256"
        )
    repository_root = Path(__file__).resolve().parents[4]
    assert_clean_checked_head(repository_root, checked_head)
    contract = runtime_image_contract(repository_root, runtime, checked_head)
    if operation == "prepare":
        result = prepare_checked_runtime_image(repository_root, contract)
        assert_clean_checked_head(repository_root, checked_head)
        print(json.dumps(preparation_receipt(contract, result), sort_keys=True))
    elif operation == "verify":
        result = verify_local_checked_image(contract)
        print(result["imageId"])
    else:
        assert receipt_path is not None
        assert receipt_sha256 is not None
        result = verify_prepared_checked_image(
            contract,
            receipt_path=receipt_path,
            receipt_sha256=receipt_sha256,
        )
        print(result["imageId"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_run_cli(sys.argv[1:]))
    except CheckedRuntimeImageError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
