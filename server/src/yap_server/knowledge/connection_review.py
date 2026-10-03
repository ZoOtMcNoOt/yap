"""Check exported review evidence against an explicit local OKF bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from yap_server.jobs.contract_values import valid_sha256
from yap_server.private_artifact import read_json_object_with_identity

from .knowledge_tool_contract import ConnectionCandidate, ProposalCitation
from .okf_compiler import compile_okf_bundle


MAX_REVIEW_PACKAGE_BYTES = 65_536


def _fields(value: object, names: tuple[str, ...]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError("review package fields differ from the supported contract")
    return value


def verify_connection_review_package(
    package_path: Path,
    bundle_root: Path,
    *,
    tenant_id: str,
    source_revision: str,
) -> dict[str, str | int]:
    """Return a source-match receipt; infer no approval or current server access."""

    package, digest = read_json_object_with_identity(
        package_path,
        maximum_bytes=MAX_REVIEW_PACKAGE_BYTES,
        field="connection review package",
    )
    _fields(
        package,
        (
            "schemaVersion",
            "kind",
            "status",
            "proposalId",
            "generationSha256",
            "candidate",
            "sources",
        ),
    )
    if (
        type(package["schemaVersion"]) is not int
        or package["schemaVersion"] != 1
        or package["kind"] != "connection-review"
        or package["status"] != "proposed"
        or not valid_sha256(package["proposalId"])
        or not valid_sha256(package["generationSha256"])
    ):
        raise ValueError("review package identity or proposed status is invalid")
    candidate = _fields(
        package["candidate"],
        (
            "schemaVersion",
            "sourceConceptId",
            "targetConceptId",
            "relationshipType",
            "rationale",
        ),
    )
    parsed = ConnectionCandidate.model_validate(
        {
            "schema_version": candidate["schemaVersion"],
            "source_concept_id": candidate["sourceConceptId"],
            "target_concept_id": candidate["targetConceptId"],
            "relationship_type": candidate["relationshipType"],
            "rationale": candidate["rationale"],
        },
        strict=True,
    )
    sources = package["sources"]
    if not isinstance(sources, list) or len(sources) != 2:
        raise ValueError("review package requires exactly two sources")

    generation = compile_okf_bundle(
        bundle_root,
        tenant_id=tenant_id,
        source_revision=source_revision,
    )
    if package["generationSha256"] != generation.generation_sha256:
        raise ValueError("review package differs from the selected source generation")
    concepts = {concept.concept_id: concept for concept in generation.concepts}
    endpoints: set[str] = set()
    for entry in sources:
        source = _fields(entry, ("node", "citation", "text"))
        node = _fields(
            source["node"],
            (
                "conceptId",
                "type",
                "title",
                "sourcePath",
                "sourceRevision",
                "contentSha256",
            ),
        )
        citation = _fields(
            source["citation"],
            (
                "conceptId",
                "sourceRevision",
                "contentSha256",
                "charStart",
                "charEnd",
            ),
        )
        proof = ProposalCitation.model_validate(
            {
                "concept_id": citation["conceptId"],
                "source_revision": citation["sourceRevision"],
                "content_sha256": citation["contentSha256"],
                "char_start": citation["charStart"],
                "char_end": citation["charEnd"],
            },
            strict=True,
        )
        concept = concepts.get(proof.concept_id)
        quote = source["text"]
        if (
            concept is None
            or proof.concept_id in endpoints
            or node
            != {
                "conceptId": concept.concept_id,
                "type": concept.frontmatter["type"],
                "title": concept.frontmatter["title"],
                "sourcePath": concept.source_path,
                "sourceRevision": generation.source_revision,
                "contentSha256": concept.content_sha256,
            }
            or proof.source_revision != generation.source_revision
            or proof.content_sha256 != concept.content_sha256
            or not isinstance(quote, str)
            or not 1 <= len(quote) <= 1_024
            or "\0" in quote
            or proof.char_end > len(concept.body)
            or concept.body[proof.char_start : proof.char_end] != quote
        ):
            raise ValueError("review source metadata, hash, span or quote differs")
        endpoints.add(proof.concept_id)
    if endpoints != {parsed.source_concept_id, parsed.target_concept_id}:
        raise ValueError("review sources differ from the candidate endpoints")
    return {
        "schemaVersion": 1,
        "kind": "connection-review-validation",
        "status": "source-matched",
        "packageSha256": digest,
        "proposalId": str(package["proposalId"]),
        "generationSha256": generation.generation_sha256,
        "sourceCount": 2,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = verify_connection_review_package(
            args.package,
            args.bundle_root,
            tenant_id=args.tenant_id,
            source_revision=args.source_revision,
        )
    except (ValueError, OSError):
        # Validation exceptions can contain source text. Keep operator output
        # content-free, including failed Pydantic/OKF validation.
        print(
            "Review package could not be matched. Check its format and the selected "
            "source bundle, tenant and revision.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
