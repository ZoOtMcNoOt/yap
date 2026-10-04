"""A deployment-selected source snapshot; approval remains an operator prerequisite."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys

from yap_server.jobs.contract_values import identifier, valid_sha256
from yap_server.private_artifact import read_json_object_with_identity
from .knowledge_source_admission import validate_curated_source_path
from .okf_compiler import CompiledKnowledgeGeneration, compile_okf_bundle
from .okf_source import real_bundle_directory


_MANIFEST_FIELDS = {
    "schemaVersion",
    "tenantId",
    "bundleRoot",
    "repositoryRevision",
    "sourcePath",
    "generationSha256",
}
_MAX_MANIFEST_BYTES = 4096


@dataclass(frozen=True, slots=True)
class ReviewedSourceSnapshot:
    tenant_id: str
    bundle_root: Path
    repository_revision: str
    source_path: str
    generation_sha256: str

    def compile(self) -> CompiledKnowledgeGeneration:
        generation = compile_okf_bundle(
            self.bundle_root,
            tenant_id=self.tenant_id,
            source_revision=self.repository_revision,
        )
        if generation.generation_sha256 != self.generation_sha256:
            raise ValueError("configured source differs from the deployment snapshot")
        return generation


def load_reviewed_source_snapshot(
    path: str, expected_sha256: str
) -> ReviewedSourceSnapshot:
    if not valid_sha256(expected_sha256):
        raise ValueError("source deployment digest is invalid")
    requested = _absolute_path(path)
    value, _identity = read_json_object_with_identity(
        requested,
        maximum_bytes=_MAX_MANIFEST_BYTES,
        expected_sha256=expected_sha256,
        field="reviewed source deployment manifest",
    )
    if (
        set(value) != _MANIFEST_FIELDS
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or not valid_sha256(value["generationSha256"])
    ):
        raise ValueError("source deployment manifest differs from the contract")
    return ReviewedSourceSnapshot(
        tenant_id=identifier(value["tenantId"], 512, "source tenant"),
        bundle_root=real_bundle_directory(_absolute_path(value["bundleRoot"])),
        repository_revision=identifier(
            value["repositoryRevision"], 512, "source repository revision"
        ),
        source_path=validate_curated_source_path(value["sourcePath"]),
        generation_sha256=value["generationSha256"],
    )


def _absolute_path(value: object) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or not Path(value).is_absolute()
    ):
        raise ValueError("source deployment requires an absolute real path")
    return Path(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--repository-revision", required=True)
    parser.add_argument("--source-path", required=True)
    args = parser.parse_args(argv)
    try:
        tenant = identifier(args.tenant_id, 512, "source tenant")
        revision = identifier(args.repository_revision, 512, "source revision")
        source_path = validate_curated_source_path(args.source_path)
        root = real_bundle_directory(args.bundle_root)
        generation = compile_okf_bundle(
            root, tenant_id=tenant, source_revision=revision
        )
        manifest = {
            "schemaVersion": 1,
            "tenantId": tenant,
            "bundleRoot": str(root),
            "repositoryRevision": revision,
            "sourcePath": source_path,
            "generationSha256": generation.generation_sha256,
        }
        body = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(body) > _MAX_MANIFEST_BYTES:
            raise ValueError("source deployment manifest is too large")
    except (ValueError, OSError, RecursionError):
        print(
            "Source snapshot could not be described. Check the bundle, tenant, revision and repository path.",
            file=sys.stderr,
        )
        return 2
    # Exact bytes make the reported digest portable across redirected consoles.
    sys.stdout.buffer.write(body)
    print(
        f"Manifest SHA-256: {hashlib.sha256(body).hexdigest()}. "
        "This describes source bytes; it does not verify Git review or approval.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
