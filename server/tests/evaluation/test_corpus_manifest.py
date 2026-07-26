from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from yap_server.evaluation import corpus_manifest as corpus_manifest_module
from yap_server.evaluation.corpus_manifest import (
    load_corpus_manifest,
    load_promotion_corpus_manifest,
    validate_corpus_manifest,
)
from yap_server.evaluation.manifest_scoring import score_manifest_case
from yap_server.evaluation.transcript_scoring import (
    critical_token_set_sha256,
)
from tests.evaluation.promotion_registry_fixture import (
    file_sha256 as _sha256,
    promotion_registry_fixture as _promotion_fixture,
    write_json as _write_json,
)


def _manifest(
    *,
    purpose: str,
    exposure: str,
    asset_kind: str = "natural",
    language_bcp47: str = "en-US",
    scoring_profile: str = "word-primary-v1",
    speaker_count: int = 1,
    critical_token_set_sha256: str | None = None,
    suite_ids: list[str] | None = None,
    condition_labels: list[str] | None = None,
) -> dict[str, object]:
    model_id = "candidate/model"
    model_revision = "revision-1"
    independent = purpose == "independentPromotion"
    return {
        "schemaVersion": 2,
        "privateCacheEnvironment": "YAP_EVAL_CACHE",
        "scorerLockSha256": "7" * 64,
        "candidateModels": [
            {
                "id": model_id,
                "revision": model_revision,
                "candidateLockSha256": "f" * 64,
                "frozenAtUtc": "2026-07-01T00:00:00Z",
                "freezeEvidenceSha256": "9" * 64,
            }
        ],
        "cases": [
            {
                "id": "case-1",
                "purpose": purpose,
                "assetKind": asset_kind,
                "suiteIds": suite_ids
                or (["asr-runtime-promotion"] if independent else ["extended"]),
                "conditionLabels": condition_labels
                or (
                    ["nonSpeech", "silence"]
                    if speaker_count == 0 or asset_kind == "generatedSilence"
                    else (
                        ["clean", "closeTalk", "levelScaled", "readSpeech"]
                        if asset_kind == "perturbed"
                        else ["clean", "closeTalk", "readSpeech"]
                    )
                ),
                "derivation": (
                    None
                    if asset_kind == "natural"
                    else {
                        "revision": "deterministic-audio-derivation-v1",
                        "operation": {
                            "concatenated": "concatenate",
                            "looped": "loop",
                            "perturbed": "scaleLevel",
                            "generatedSilence": "generateSilence",
                        }[asset_kind],
                        "sourceAudioSha256s": (
                            [] if asset_kind == "generatedSilence" else ["1" * 64]
                        ),
                        "recipeSha256": "2" * 64,
                    }
                ),
                "corpus": {
                    "id": "fixture-corpus",
                    "release": "release-1",
                    "split": "test",
                    "itemId": "item-1",
                    "sourceUri": "https://example.invalid/fixture-corpus",
                    "retrievedAtUtc": "2026-07-03T00:00:00Z",
                },
                "audio": {
                    "sha256": "a" * 64,
                    "byteLength": 32_044,
                    "decodedPcmSha256": "d" * 64,
                    "durationSamples": 16_000,
                    "sampleRateHz": 16_000,
                    "channels": 1,
                    "codec": "pcm_s16le",
                    "recordedAtUtc": (
                        "2026-07-02T00:00:00Z"
                        if exposure == "created_after_model_freeze"
                        else None
                    ),
                },
                "reference": {
                    "sha256": "b" * 64,
                    "tier": "yapAdjudicated" if independent else "upstream",
                    "revision": "reference-1",
                    "languageBcp47": language_bcp47,
                    "scoringProfile": scoring_profile,
                    "punctuationProfile": "unicode-word-boundary-v1",
                    "criticalTokenSetSha256": critical_token_set_sha256,
                    "speakerCount": speaker_count,
                    "timingKind": "none",
                    "adjudicationState": "adjudicated" if independent else "upstream",
                },
                "rights": {
                    "licenseId": "CC-BY-4.0",
                    "licenseTextSha256": "e" * 64,
                    "audioDecision": "approved",
                    "referenceDecision": "approved",
                    "commercialUse": "allowed",
                    "redistribution": "forbidden",
                    "reidentificationProhibited": True,
                },
                "knownDefects": [],
                "modelExposure": [
                    {
                        "modelId": model_id,
                        "modelRevision": model_revision,
                        "status": exposure,
                        "evidenceUri": "urn:yap:evidence:model-card-snapshot",
                        "evidenceSha256": "c" * 64,
                    }
                ],
            }
        ],
    }


def _bind_pcm16_wav(
    manifest: dict[str, object],
    path: Path,
    *,
    frame_count: int = 16_000,
) -> None:
    pcm_bytes = b"\x00\x00" * frame_count
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(pcm_bytes)
    audio = manifest["cases"][0]["audio"]  # type: ignore[index]
    audio.update(  # type: ignore[union-attr]
        {
            "sha256": _sha256(path),
            "byteLength": path.stat().st_size,
            "decodedPcmSha256": hashlib.sha256(pcm_bytes).hexdigest(),
            "durationSamples": frame_count,
            "sampleRateHz": 16_000,
            "channels": 1,
            "codec": "pcm_s16le",
        }
    )


def _inference_result_lock(
    root: Path,
    manifest: dict[str, object],
    hypothesis_path: Path,
    environ: dict[str, str],
) -> Path:
    runtime_lock_path = root / "runtime.lock.json"
    runtime_lock_path.write_bytes(b"locked-runtime-identity")
    candidate = manifest["candidateModels"][0]  # type: ignore[index]
    case = manifest["cases"][0]  # type: ignore[index]
    audio = case["audio"]
    path = root / "inference-result.lock.json"
    _write_json(
        path,
        {
            "schemaVersion": 2,
            "caseId": case["id"],
            "modelId": candidate["id"],
            "modelRevision": candidate["revision"],
            "candidateLockSha256": candidate["candidateLockSha256"],
            "audioSha256": audio["sha256"],
            "decodedPcmSha256": audio["decodedPcmSha256"],
            "durationSamples": audio["durationSamples"],
            "sampleRateHz": audio["sampleRateHz"],
            "hypothesisSha256": _sha256(hypothesis_path),
            "terminologyContext": {
                "mode": "none",
                "sourcePolicySha256": None,
                "requestPayloadSha256": None,
                "entryCount": 0,
                "requestPayloadBytes": 0,
            },
            "runtime": {
                "id": "vllm-cohere-asr",
                "revision": "26.06-py3",
                "lockPath": runtime_lock_path.name,
                "lockSha256": _sha256(runtime_lock_path),
            },
        },
    )
    environ["YAP_EVAL_INFERENCE_RESULT_LOCK_SHA256"] = _sha256(path)
    return path



def _load_promotion(
    manifest_path: Path,
    registry_path: Path,
    environ: dict[str, str],
) -> dict[str, object]:
    with patch.dict(os.environ, environ, clear=False):
        return load_promotion_corpus_manifest(manifest_path, registry_path)


class CorpusManifestExposureTests(unittest.TestCase):
    def test_manifest_loader_rejects_duplicate_json_keys(self) -> None:
        encoded = json.dumps(
            _manifest(purpose="comparator", exposure="unknown"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded = encoded.replace(
            b'"schemaVersion":2',
            b'"schemaVersion":999,"schemaVersion":2',
            1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate-key-manifest.json"
            path.write_bytes(encoded)

            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                load_corpus_manifest(path)

    def test_registry_artifact_hashing_rechecks_the_bounded_open(self) -> None:
        maximum_bytes = 16 * 1024 * 1024
        oversized = b"x" * (maximum_bytes + 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifact = root / "exposure-proof.bin"
            artifact.write_bytes(b"initial")
            original_private_file = corpus_manifest_module._private_file

            def replace_after_initial_check(*args, **kwargs):
                resolved = original_private_file(*args, **kwargs)
                resolved.write_bytes(oversized)
                return resolved

            with patch.object(
                corpus_manifest_module,
                "_private_file",
                side_effect=replace_after_initial_check,
            ):
                with self.assertRaisesRegex(ValueError, "size"):
                    corpus_manifest_module._verified_registry_artifact(
                        root,
                        root,
                        artifact.name,
                        hashlib.sha256(oversized).hexdigest(),
                        "trusted exposure evidence",
                    )

    def test_promotion_manifest_must_remain_in_the_private_cache(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, registry_path, environ = _promotion_fixture(
                root / "private-cache",
                manifest,
            )
            outside_manifest = root / "outside-manifest.json"
            outside_manifest.write_bytes(manifest_path.read_bytes())

            with self.assertRaisesRegex(ValueError, "inside YAP_EVAL_CACHE"):
                _load_promotion(outside_manifest, registry_path, environ)

    def test_registry_artifact_paths_use_a_portable_non_ads_grammar(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path, registry_path, environ = _promotion_fixture(
                Path(temporary),
                manifest,
            )
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["scorerLockPath"] = "carrier.json:hidden-review"
            _write_json(registry_path, registry)
            environ["YAP_EVAL_PROMOTION_REGISTRY_SHA256"] = _sha256(registry_path)

            with self.assertRaisesRegex(ValueError, "path is invalid"):
                _load_promotion(manifest_path, registry_path, environ)

    def test_duplicate_review_cases_fail_before_private_artifact_io(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, registry_path, environ = _promotion_fixture(root, manifest)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            review = registry["verifiedReferenceReviews"][0]
            registry["verifiedReferenceReviews"].append(deepcopy(review))
            (root / review["reviewReceiptPath"]).unlink()
            _write_json(registry_path, registry)
            environ["YAP_EVAL_PROMOTION_REGISTRY_SHA256"] = _sha256(registry_path)

            with self.assertRaisesRegex(ValueError, "case IDs must be unique"):
                _load_promotion(manifest_path, registry_path, environ)

    def test_registry_preserves_the_receipt_specific_size_bound(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, registry_path, environ = _promotion_fixture(root, manifest)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            review = registry["verifiedReferenceReviews"][0]
            review_path = root / review["reviewReceiptPath"]
            body = review_path.read_bytes()
            review_path.write_bytes(body + b" " * (512 * 1024 + 1 - len(body)))
            review["reviewReceiptSha256"] = _sha256(review_path)
            _write_json(registry_path, registry)
            environ["YAP_EVAL_PROMOTION_REGISTRY_SHA256"] = _sha256(registry_path)

            with self.assertRaisesRegex(ValueError, "review receipt size"):
                _load_promotion(manifest_path, registry_path, environ)

    def test_promotion_registry_binds_scorer_and_case_evaluation_policy(
        self,
    ) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path, registry_path, environ = _promotion_fixture(
                Path(temporary) / "private-cache",
                manifest,
            )
            changed = json.loads(manifest_path.read_text(encoding="utf-8"))
            changed["cases"][0]["reference"]["scoringProfile"] = (
                "grapheme-primary-v1"
            )
            _write_json(manifest_path, changed)
            with self.assertRaisesRegex(ValueError, "evaluation policy"):
                _load_promotion(manifest_path, registry_path, environ)

            changed = json.loads(manifest_path.read_text(encoding="utf-8"))
            changed["cases"][0]["reference"]["scoringProfile"] = (
                "word-primary-v1"
            )
            changed["scorerLockSha256"] = "0" * 64
            _write_json(manifest_path, changed)
            with self.assertRaisesRegex(ValueError, "scorer lock"):
                _load_promotion(manifest_path, registry_path, environ)

    def test_unknown_exposure_is_valid_for_a_comparator(self) -> None:
        validate_corpus_manifest(_manifest(purpose="comparator", exposure="unknown"))

    def test_manifest_freezes_suite_condition_and_derivation_metadata(self) -> None:
        natural = _manifest(purpose="comparator", exposure="unknown")
        validate_corpus_manifest(natural)

        old_schema = deepcopy(natural)
        old_schema["schemaVersion"] = 1
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_corpus_manifest(old_schema)

        duplicated_condition = deepcopy(natural)
        duplicated_condition["cases"][0]["conditionLabels"] = [  # type: ignore[index]
            "clean",
            "clean",
        ]
        with self.assertRaisesRegex(ValueError, "condition labels.*unique"):
            validate_corpus_manifest(duplicated_condition)

        unknown_suite = deepcopy(natural)
        unknown_suite["cases"][0]["suiteIds"] = ["everything"]  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "suite IDs.*invalid"):
            validate_corpus_manifest(unknown_suite)

        natural_with_derivation = deepcopy(natural)
        natural_with_derivation["cases"][0]["derivation"] = {  # type: ignore[index]
            "revision": "recipe-v1",
            "operation": "scaleLevel",
            "sourceAudioSha256s": ["1" * 64],
            "recipeSha256": "2" * 64,
        }
        with self.assertRaisesRegex(ValueError, "natural.*cannot declare"):
            validate_corpus_manifest(natural_with_derivation)

    def test_derived_audio_requires_a_matching_hash_bound_recipe(self) -> None:
        perturbed = _manifest(
            purpose="comparator",
            exposure="unknown",
            asset_kind="perturbed",
        )
        validate_corpus_manifest(perturbed)

        missing_source = deepcopy(perturbed)
        missing_source["cases"][0]["derivation"][  # type: ignore[index]
            "sourceAudioSha256s"
        ] = []
        with self.assertRaisesRegex(ValueError, "requires at least one source"):
            validate_corpus_manifest(missing_source)

        wrong_operation = deepcopy(perturbed)
        wrong_operation["cases"][0]["derivation"]["operation"] = (  # type: ignore[index]
            "concatenate"
        )
        with self.assertRaisesRegex(ValueError, "does not match the asset kind"):
            validate_corpus_manifest(wrong_operation)

        unlabelled = deepcopy(perturbed)
        unlabelled["cases"][0]["conditionLabels"] = [  # type: ignore[index]
            "clean",
            "closeTalk",
            "readSpeech",
        ]
        with self.assertRaisesRegex(ValueError, "matching condition label"):
            validate_corpus_manifest(unlabelled)

    def test_promotion_and_overlap_labels_have_structural_requirements(self) -> None:
        promotion = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )
        promotion["cases"][0]["suiteIds"] = ["extended"]  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "belong to the promotion suite"):
            validate_corpus_manifest(promotion)

        overlap = _manifest(
            purpose="comparator",
            exposure="unknown",
            condition_labels=["clean", "closeTalk", "overlap"],
        )
        with self.assertRaisesRegex(ValueError, "at least two speakers"):
            validate_corpus_manifest(overlap)

    def test_unknown_or_known_training_data_cannot_be_an_independent_gate(self) -> None:
        for exposure in (
            "unknown",
            "known_training",
            "known_evaluation",
            "likely_exposed",
        ):
            with self.subTest(exposure=exposure):
                with self.assertRaisesRegex(ValueError, "proven model exclusion"):
                    validate_corpus_manifest(
                        _manifest(
                            purpose="independentPromotion",
                            exposure=exposure,
                        )
                    )

    def test_post_freeze_or_contractually_excluded_data_can_be_independent(
        self,
    ) -> None:
        for exposure in (
            "created_after_model_freeze",
            "contractually_excluded",
        ):
            with self.subTest(exposure=exposure):
                manifest = _manifest(
                    purpose="independentPromotion",
                    exposure=exposure,
                )
                with tempfile.TemporaryDirectory() as directory:
                    manifest_path, registry_path, environ = _promotion_fixture(
                        Path(directory),
                        manifest,
                    )
                    loaded = _load_promotion(
                        manifest_path,
                        registry_path,
                        environ,
                    )
                self.assertEqual(
                    loaded["cases"][0]["purpose"], "independentPromotion"
                )

    def test_every_independent_claim_requires_a_hash_bound_human_review(self) -> None:
        for exposure in ("created_after_model_freeze", "contractually_excluded"):
            with (
                self.subTest(exposure=exposure),
                tempfile.TemporaryDirectory() as directory,
            ):
                manifest = _manifest(
                    purpose="independentPromotion",
                    exposure=exposure,
                )
                manifest_path, registry_path, environ = _promotion_fixture(
                    Path(directory),
                    manifest,
                    include_reference_review=False,
                )
                with self.assertRaisesRegex(ValueError, "review receipt"):
                    _load_promotion(manifest_path, registry_path, environ)

    def test_one_case_review_is_not_duplicated_as_model_exposure_evidence(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="created_after_model_freeze",
        )
        second_model = deepcopy(manifest["candidateModels"][0])  # type: ignore[index]
        second_model["id"] = "candidate/second-model"
        second_model["revision"] = "revision-2"
        manifest["candidateModels"].append(second_model)  # type: ignore[union-attr]
        second_exposure = deepcopy(
            manifest["cases"][0]["modelExposure"][0]  # type: ignore[index]
        )
        second_exposure["modelId"] = second_model["id"]
        second_exposure["modelRevision"] = second_model["revision"]
        manifest["cases"][0]["modelExposure"].append(  # type: ignore[index]
            second_exposure
        )

        with tempfile.TemporaryDirectory() as temporary:
            manifest_path, registry_path, environ = _promotion_fixture(
                Path(temporary),
                manifest,
            )
            registry = json.loads(registry_path.read_text(encoding="utf-8"))

            self.assertEqual(registry["schemaVersion"], 2)
            self.assertEqual(len(registry["verifiedReferenceReviews"]), 1)
            review_path = registry["verifiedReferenceReviews"][0][
                "reviewReceiptPath"
            ]
            exposure_paths = {
                exposure["evidencePath"]
                for exposure in registry["verifiedExposures"]
            }
            self.assertEqual(len(exposure_paths), 2)
            self.assertNotIn(review_path, exposure_paths)
            _load_promotion(manifest_path, registry_path, environ)

    def test_reviewed_rights_and_known_defects_bind_the_promoted_case(self) -> None:
        rights_mutations = {
            "licenseId": "different-approved-license",
            "licenseTextSha256": "1" * 64,
            "redistribution": "allowed",
            "reidentificationProhibited": False,
        }
        for field, value in rights_mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                manifest = _manifest(
                    purpose="independentPromotion",
                    exposure="created_after_model_freeze",
                )
                manifest_path, registry_path, environ = _promotion_fixture(
                    Path(temporary),
                    manifest,
                )
                changed = json.loads(manifest_path.read_text(encoding="utf-8"))
                changed["cases"][0]["rights"][field] = value
                _write_json(manifest_path, changed)

                with self.assertRaisesRegex(ValueError, "review.*rights"):
                    _load_promotion(manifest_path, registry_path, environ)

        with tempfile.TemporaryDirectory() as temporary:
            manifest = _manifest(
                purpose="independentPromotion",
                exposure="created_after_model_freeze",
            )
            manifest_path, registry_path, environ = _promotion_fixture(
                Path(temporary),
                manifest,
            )
            changed = json.loads(manifest_path.read_text(encoding="utf-8"))
            changed["cases"][0]["knownDefects"] = ["speaker-overlap-omitted"]
            _write_json(manifest_path, changed)

            with self.assertRaisesRegex(ValueError, "known defects"):
                _load_promotion(manifest_path, registry_path, environ)

    def test_independent_review_uses_known_defect_codes_without_breaking_comparators(
        self,
    ) -> None:
        for defects in (["free form defect"], ["duplicate", "duplicate"]):
            with self.subTest(defects=defects):
                comparator = _manifest(purpose="comparator", exposure="unknown")
                comparator["cases"][0]["knownDefects"] = defects  # type: ignore[index]
                validate_corpus_manifest(comparator)

                promotion = _manifest(
                    purpose="independentPromotion",
                    exposure="contractually_excluded",
                )
                promotion["cases"][0]["knownDefects"] = defects  # type: ignore[index]
                with self.assertRaisesRegex(ValueError, "known defect codes"):
                    validate_corpus_manifest(promotion)

    def test_review_binds_source_coverage_and_audio_metadata(self) -> None:
        mutations = (
            (("corpus", "sourceUri"), "https://example.invalid/other-source"),
            (("corpus", "retrievedAtUtc"), "2026-07-04T00:00:00Z"),
            (("suiteIds",), ["approved-private", "asr-runtime-promotion"]),
            (("conditionLabels",), ["clean", "farField", "readSpeech"]),
            (("audio", "byteLength"), 32_046),
            (("audio", "durationSamples"), 16_001),
            (("audio", "sampleRateHz"), 8_000),
            (("audio", "channels"), 2),
            (("audio", "codec"), "flac"),
            (("reference", "tier"), "approvedPrivate"),
            (("reference", "revision"), "reference-2"),
            (("reference", "speakerCount"), 2),
            (("reference", "timingKind"), "manual"),
        )
        for field_path, value in mutations:
            with (
                self.subTest(field_path=field_path),
                tempfile.TemporaryDirectory() as temporary,
            ):
                manifest = _manifest(
                    purpose="independentPromotion",
                    exposure="created_after_model_freeze",
                )
                manifest_path, registry_path, environ = _promotion_fixture(
                    Path(temporary),
                    manifest,
                )
                changed = json.loads(manifest_path.read_text(encoding="utf-8"))
                target = changed["cases"][0]
                for field in field_path[:-1]:
                    target = target[field]
                target[field_path[-1]] = value
                _write_json(manifest_path, changed)

                with self.assertRaisesRegex(ValueError, "human review receipt"):
                    _load_promotion(manifest_path, registry_path, environ)

    def test_review_participants_require_registry_authorization(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="created_after_model_freeze",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, registry_path, environ = _promotion_fixture(root, manifest)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            participant = next(
                item
                for item in registry["trustedReviewParticipants"]
                if item["participantId"] == "reviewer-a"
            )
            participant["roles"] = ["adjudicator"]
            authorization_path = root / participant["authorizationPath"]
            _write_json(
                authorization_path,
                {
                    "schemaVersion": 1,
                    "participantId": "reviewer-a",
                    "roles": ["adjudicator"],
                },
            )
            participant["authorizationSha256"] = _sha256(authorization_path)
            _write_json(registry_path, registry)
            environ["YAP_EVAL_PROMOTION_REGISTRY_SHA256"] = _sha256(registry_path)

            with self.assertRaisesRegex(ValueError, "authorized listener"):
                _load_promotion(manifest_path, registry_path, environ)

    def test_review_support_artifacts_are_independently_hash_bound(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="created_after_model_freeze",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, registry_path, environ = _promotion_fixture(root, manifest)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            artifact = registry["verifiedReferenceReviews"][0][
                "supportingArtifacts"
            ][0]
            (root / artifact["artifactPath"]).write_bytes(b"tampered support")

            with self.assertRaisesRegex(ValueError, "trusted registry"):
                _load_promotion(manifest_path, registry_path, environ)

    def test_blind_assignment_excludes_peer_reviews_and_model_hypotheses(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="created_after_model_freeze",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, registry_path, environ = _promotion_fixture(root, manifest)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            reference_review = registry["verifiedReferenceReviews"][0]
            assignment = next(
                artifact
                for artifact in reference_review["supportingArtifacts"]
                if artifact["kind"] == "blindAssignment"
            )
            assignment_path = root / assignment["artifactPath"]
            assignment_payload = json.loads(
                assignment_path.read_text(encoding="utf-8")
            )
            assignment_payload["excludedInputs"] = ["modelHypotheses"]
            _write_json(assignment_path, assignment_payload)
            assignment["artifactSha256"] = _sha256(assignment_path)

            review_path = root / reference_review["reviewReceiptPath"]
            review_payload = json.loads(review_path.read_text(encoding="utf-8"))
            review_payload["preparation"]["assignmentSha256"] = assignment[
                "artifactSha256"
            ]
            for listener in review_payload["reviews"]:
                listener["assignmentSha256"] = assignment["artifactSha256"]
            _write_json(review_path, review_payload)
            reference_review["reviewReceiptSha256"] = _sha256(review_path)
            _write_json(registry_path, registry)
            environ["YAP_EVAL_PROMOTION_REGISTRY_SHA256"] = _sha256(registry_path)

            with self.assertRaisesRegex(ValueError, "independent listener inputs"):
                _load_promotion(manifest_path, registry_path, environ)

    def test_listener_artifact_decision_matches_the_review_packet(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="created_after_model_freeze",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, registry_path, environ = _promotion_fixture(root, manifest)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            listener = next(
                artifact
                for artifact in registry["verifiedReferenceReviews"][0][
                    "supportingArtifacts"
                ]
                if artifact["kind"] == "listenerReview"
            )
            listener_path = root / listener["artifactPath"]
            listener_payload = json.loads(listener_path.read_text(encoding="utf-8"))
            listener_payload["decision"] = "exclude"
            _write_json(listener_path, listener_payload)
            listener["artifactSha256"] = _sha256(listener_path)

            review_entry = registry["verifiedReferenceReviews"][0]
            review_path = root / review_entry["reviewReceiptPath"]
            review_payload = json.loads(review_path.read_text(encoding="utf-8"))
            reviewer_id = listener["participantId"]
            packet_listener = next(
                item
                for item in review_payload["reviews"]
                if item["reviewerId"] == reviewer_id
            )
            previous_receipt_sha256 = packet_listener["receiptSha256"]
            packet_listener["receiptSha256"] = listener["artifactSha256"]
            review_payload["adjudication"]["reviewReceiptSha256s"] = [
                listener["artifactSha256"]
                if value == previous_receipt_sha256
                else value
                for value in review_payload["adjudication"][
                    "reviewReceiptSha256s"
                ]
            ]
            _write_json(review_path, review_payload)
            review_entry["reviewReceiptSha256"] = _sha256(review_path)
            _write_json(registry_path, registry)
            environ["YAP_EVAL_PROMOTION_REGISTRY_SHA256"] = _sha256(registry_path)

            with self.assertRaisesRegex(ValueError, "does not match the review packet"):
                _load_promotion(manifest_path, registry_path, environ)

    def test_source_identity_receipt_cannot_relabel_the_recording_time(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="created_after_model_freeze",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, registry_path, environ = _promotion_fixture(root, manifest)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            review_entry = registry["verifiedReferenceReviews"][0]
            source_identity = next(
                artifact
                for artifact in review_entry["supportingArtifacts"]
                if artifact["kind"] == "sourceIdentity"
            )
            source_path = root / source_identity["artifactPath"]
            source_payload = json.loads(source_path.read_text(encoding="utf-8"))
            source_payload["recordedAtUtc"] = "2020-01-01T00:00:00Z"
            _write_json(source_path, source_payload)
            source_identity["artifactSha256"] = _sha256(source_path)

            review_path = root / review_entry["reviewReceiptPath"]
            review_payload = json.loads(review_path.read_text(encoding="utf-8"))
            review_payload["source"]["sourceIdentityReceiptSha256"] = (
                source_identity["artifactSha256"]
            )
            _write_json(review_path, review_payload)
            review_entry["reviewReceiptSha256"] = _sha256(review_path)
            _write_json(registry_path, registry)
            environ["YAP_EVAL_PROMOTION_REGISTRY_SHA256"] = _sha256(registry_path)

            with self.assertRaisesRegex(ValueError, "source identity receipt"):
                _load_promotion(manifest_path, registry_path, environ)

    def test_matching_fractional_recording_time_remains_exact(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="created_after_model_freeze",
        )
        manifest["cases"][0]["audio"]["recordedAtUtc"] = (  # type: ignore[index]
            "2026-07-02T00:00:00.500Z"
        )
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path, registry_path, environ = _promotion_fixture(
                Path(temporary),
                manifest,
            )

            loaded = _load_promotion(manifest_path, registry_path, environ)

            self.assertEqual(
                loaded["cases"][0]["audio"]["recordedAtUtc"],
                "2026-07-02T00:00:00.500Z",
            )

    def test_independent_claim_cannot_trust_its_own_manifest_evidence(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )

        with self.assertRaisesRegex(ValueError, "trusted external"):
            validate_corpus_manifest(manifest)

        with tempfile.TemporaryDirectory() as directory:
            manifest_path, registry_path, environ = _promotion_fixture(
                Path(directory),
                manifest,
            )
            exposure = manifest["cases"][0]["modelExposure"][0]  # type: ignore[index]
            exposure["evidenceSha256"] = "8" * 64
            exposure["evidenceUri"] = "urn:yap:evidence:invented"
            _write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "trusted registry"):
                _load_promotion(
                    manifest_path,
                    registry_path,
                    environ,
                )

    def test_manifest_cannot_backdate_or_omit_the_trusted_candidate(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="created_after_model_freeze",
        )
        with tempfile.TemporaryDirectory() as directory:
            manifest_path, registry_path, environ = _promotion_fixture(
                Path(directory),
                manifest,
            )
            manifest["candidateModels"][0]["frozenAtUtc"] = (  # type: ignore[index]
                "2020-01-01T00:00:00Z"
            )
            _write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "exact trusted candidate set"):
                _load_promotion(
                    manifest_path,
                    registry_path,
                    environ,
                )

        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )
        second_model = deepcopy(manifest["candidateModels"][0])  # type: ignore[index]
        second_model["id"] = "deployed/model"
        second_model["revision"] = "revision-2"
        manifest["candidateModels"].append(second_model)  # type: ignore[union-attr]
        second_exposure = deepcopy(  # type: ignore[index]
            manifest["cases"][0]["modelExposure"][0]
        )
        second_exposure["modelId"] = "deployed/model"
        second_exposure["modelRevision"] = "revision-2"
        exposures = manifest["cases"][0]["modelExposure"]  # type: ignore[index]
        exposures.append(second_exposure)
        with tempfile.TemporaryDirectory() as directory:
            manifest_path, registry_path, environ = _promotion_fixture(
                Path(directory),
                manifest,
            )
            manifest["candidateModels"].pop()  # type: ignore[union-attr]
            manifest["cases"][0]["modelExposure"].pop()  # type: ignore[index]
            _write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "exact trusted candidate set"):
                _load_promotion(
                    manifest_path,
                    registry_path,
                    environ,
                )

    def test_registry_digest_and_evidence_artifacts_are_verified(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, registry_path, environ = _promotion_fixture(root, manifest)
            (root / "exposure-0.json").write_bytes(b"tampered exposure evidence")
            with self.assertRaisesRegex(ValueError, "trusted registry"):
                _load_promotion(
                    manifest_path,
                    registry_path,
                    environ,
                )

        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, registry_path, environ = _promotion_fixture(root, manifest)
            registry_path.write_bytes(registry_path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "out-of-band digest"):
                _load_promotion(
                    manifest_path,
                    registry_path,
                    environ,
                )

    def test_derived_assets_cannot_be_relabelled_as_post_freeze_promotion(self) -> None:
        for asset_kind in ("concatenated", "looped", "perturbed"):
            manifest = _manifest(
                purpose="independentPromotion",
                exposure="created_after_model_freeze",
                asset_kind=asset_kind,
            )
            with self.subTest(asset_kind=asset_kind):
                with self.assertRaisesRegex(ValueError, "natural source audio"):
                    validate_corpus_manifest(manifest)

    def test_identical_audio_cannot_change_exposure_or_purpose(self) -> None:
        manifest = _manifest(purpose="comparator", exposure="unknown")
        duplicate = deepcopy(manifest["cases"][0])  # type: ignore[index]
        duplicate["id"] = "case-2"
        duplicate["purpose"] = "independentPromotion"
        duplicate["reference"]["tier"] = "yapAdjudicated"
        duplicate["reference"]["adjudicationState"] = "adjudicated"
        duplicate["modelExposure"][0]["status"] = "contractually_excluded"
        manifest["cases"].append(duplicate)  # type: ignore[union-attr]

        with self.assertRaisesRegex(ValueError, "only one corpus case"):
            validate_corpus_manifest(manifest)

    def test_every_case_must_classify_every_candidate_model(self) -> None:
        manifest = _manifest(purpose="comparator", exposure="unknown")
        changed = deepcopy(manifest)
        changed["candidateModels"].append(  # type: ignore[union-attr]
            {
                "id": "second/model",
                "revision": "revision-2",
                "candidateLockSha256": "7" * 64,
                "frozenAtUtc": "2026-07-01T00:00:00Z",
                "freezeEvidenceSha256": "6" * 64,
            }
        )

        with self.assertRaisesRegex(ValueError, "classify every candidate model"):
            validate_corpus_manifest(changed)

    def test_manifest_cannot_embed_reference_text_or_a_repository_path(self) -> None:
        manifest = _manifest(purpose="comparator", exposure="unknown")
        case = manifest["cases"][0]  # type: ignore[index]
        case["referenceText"] = "private words"  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "fields differ"):
            validate_corpus_manifest(manifest)

    def test_runtime_only_cases_are_explicitly_constructed(self) -> None:
        with self.assertRaisesRegex(ValueError, "runtime-only"):
            validate_corpus_manifest(
                _manifest(purpose="runtimeOnly", exposure="unknown")
            )
        validate_corpus_manifest(
            _manifest(
                purpose="runtimeOnly",
                exposure="unknown",
                asset_kind="concatenated",
            )
        )

    def test_post_freeze_status_requires_a_later_recording_time(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="created_after_model_freeze",
        )
        manifest["cases"][0]["audio"]["recordedAtUtc"] = (  # type: ignore[index]
            "2026-06-30T23:59:59Z"
        )

        with self.assertRaisesRegex(ValueError, "later recording timestamp"):
            validate_corpus_manifest(manifest)

    def test_independent_gate_requires_approved_rights_and_adjudication(self) -> None:
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
        )
        manifest["cases"][0]["rights"]["audioDecision"] = "hold"  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "approved rights"):
            validate_corpus_manifest(manifest)

    def test_reference_language_uses_the_shared_canonical_bcp47_contract(self) -> None:
        for language in ("en_US", "en-us", "bogus", "123"):
            with self.subTest(language=language):
                with self.assertRaisesRegex(ValueError, "canonical BCP 47"):
                    validate_corpus_manifest(
                        _manifest(
                            purpose="comparator",
                            exposure="unknown",
                            language_bcp47=language,
                        )
                    )

    def test_mixed_and_silence_cases_freeze_explicit_scoring_profiles(self) -> None:
        validate_corpus_manifest(
            _manifest(
                purpose="comparator",
                exposure="unknown",
                language_bcp47="mul",
                scoring_profile="grapheme-primary-v1",
            )
        )
        with self.assertRaisesRegex(ValueError, "mixed-language"):
            validate_corpus_manifest(
                _manifest(
                    purpose="comparator",
                    exposure="unknown",
                    language_bcp47="mul",
                    scoring_profile="word-primary-v1",
                )
            )
        validate_corpus_manifest(
            _manifest(
                purpose="comparator",
                exposure="unknown",
                asset_kind="generatedSilence",
                language_bcp47="und",
                scoring_profile="silence-false-words-v1",
                speaker_count=0,
            )
        )
        with self.assertRaisesRegex(ValueError, "generated silence"):
            validate_corpus_manifest(
                _manifest(
                    purpose="comparator",
                    exposure="unknown",
                    asset_kind="generatedSilence",
                )
            )

    def test_reference_freezes_punctuation_and_critical_token_policy(self) -> None:
        validate_corpus_manifest(
            _manifest(
                purpose="comparator",
                exposure="unknown",
                critical_token_set_sha256="8" * 64,
            )
        )
        manifest = _manifest(purpose="comparator", exposure="unknown")
        reference = manifest["cases"][0]["reference"]  # type: ignore[index]
        reference["punctuationProfile"] = "automatic"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "punctuation profile"):
            validate_corpus_manifest(manifest)

        silence = _manifest(
            purpose="comparator",
            exposure="unknown",
            asset_kind="generatedSilence",
            language_bcp47="und",
            scoring_profile="silence-false-words-v1",
            speaker_count=0,
            critical_token_set_sha256="8" * 64,
        )
        with self.assertRaisesRegex(ValueError, "silence.*critical-token"):
            validate_corpus_manifest(silence)


class ManifestScoringTests(unittest.TestCase):
    def test_private_adapter_applies_manifest_policy_and_scorer_lock(self) -> None:
        policy = ["do not", "5 mg"]
        policy_sha256 = critical_token_set_sha256(policy)
        manifest = _manifest(
            purpose="independentPromotion",
            exposure="contractually_excluded",
            critical_token_set_sha256=policy_sha256,
        )
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "private-cache"
            cache.mkdir(mode=0o700)
            reference_path = cache / "reference.txt"
            hypothesis_path = cache / "hypothesis.txt"
            policy_path = cache / "critical-policy.json"
            audio_path = cache / "audio.wav"
            reference_path.write_text("Do not give 5 mg.", encoding="utf-8")
            hypothesis_path.write_text("Give 5 mg.", encoding="utf-8")
            _bind_pcm16_wav(manifest, audio_path)
            _write_json(
                policy_path,
                {"schemaVersion": 1, "criticalTokens": policy},
            )
            reference = manifest["cases"][0]["reference"]  # type: ignore[index]
            reference["sha256"] = _sha256(reference_path)  # type: ignore[index]
            manifest_path, registry_path, environ = _promotion_fixture(
                cache,
                manifest,
            )
            inference_result_lock_path = _inference_result_lock(
                cache,
                manifest,
                hypothesis_path,
                environ,
            )

            with patch.dict(os.environ, environ, clear=False):
                evidence = score_manifest_case(
                    manifest_path=manifest_path,
                    registry_path=registry_path,
                    case_id="case-1",
                    model_id="candidate/model",
                    model_revision="revision-1",
                    audio_path=audio_path,
                    reference_path=reference_path,
                    hypothesis_path=hypothesis_path,
                    inference_result_lock_path=inference_result_lock_path,
                    scorer_lock_path=cache / "scorer.lock.json",
                    critical_token_policy_path=policy_path,
                )

            self.assertEqual(evidence["caseId"], "case-1")
            self.assertEqual(evidence["schemaVersion"], 2)
            self.assertEqual(evidence["privacyScope"], "private-case")
            candidate = manifest["candidateModels"][0]  # type: ignore[index]
            self.assertEqual(
                evidence["candidateLockSha256"],
                candidate["candidateLockSha256"],
            )
            self.assertEqual(
                evidence["inferenceResultLockSha256"],
                _sha256(inference_result_lock_path),
            )
            self.assertEqual(evidence["evaluationPolicySha256"], (
                json.loads(registry_path.read_text(encoding="utf-8"))[
                    "verifiedExposures"
                ][0]["evaluationPolicySha256"]
            ))
            self.assertEqual(
                evidence["score"]["metrics"]["criticalTokens"][
                    "missedOccurrences"
                ],
                1,
            )
            self.assertEqual(
                evidence["terminologyContext"],
                {
                    "mode": "none",
                    "sourcePolicySha256": None,
                    "requestPayloadSha256": None,
                    "entryCount": 0,
                    "requestPayloadBytes": 0,
                },
            )
            self.assertNotIn("Do not give", json.dumps(evidence))

            result_lock = json.loads(
                inference_result_lock_path.read_text(encoding="utf-8")
            )
            result_lock["terminologyContext"] = {
                "mode": "provider-native",
                "sourcePolicySha256": policy_sha256,
                "requestPayloadSha256": "6" * 64,
                "entryCount": len(policy),
                "requestPayloadBytes": 64,
            }
            _write_json(inference_result_lock_path, result_lock)
            environ["YAP_EVAL_INFERENCE_RESULT_LOCK_SHA256"] = _sha256(
                inference_result_lock_path
            )
            with patch.dict(os.environ, environ, clear=False):
                assisted = score_manifest_case(
                    manifest_path=manifest_path,
                    registry_path=registry_path,
                    case_id="case-1",
                    model_id="candidate/model",
                    model_revision="revision-1",
                    audio_path=audio_path,
                    reference_path=reference_path,
                    hypothesis_path=hypothesis_path,
                    inference_result_lock_path=inference_result_lock_path,
                    scorer_lock_path=cache / "scorer.lock.json",
                    critical_token_policy_path=policy_path,
                )
            self.assertEqual(
                assisted["terminologyContext"]["mode"],
                "provider-native",
            )
            self.assertEqual(
                assisted["terminologyContext"]["sourcePolicySha256"],
                policy_sha256,
            )

            result_lock["terminologyContext"]["sourcePolicySha256"] = "5" * 64
            _write_json(inference_result_lock_path, result_lock)
            environ["YAP_EVAL_INFERENCE_RESULT_LOCK_SHA256"] = _sha256(
                inference_result_lock_path
            )
            with patch.dict(os.environ, environ, clear=False):
                with self.assertRaisesRegex(
                    ValueError,
                    "terminology context differs from the critical-token policy",
                ):
                    score_manifest_case(
                        manifest_path=manifest_path,
                        registry_path=registry_path,
                        case_id="case-1",
                        model_id="candidate/model",
                        model_revision="revision-1",
                        audio_path=audio_path,
                        reference_path=reference_path,
                        hypothesis_path=hypothesis_path,
                        inference_result_lock_path=inference_result_lock_path,
                        scorer_lock_path=cache / "scorer.lock.json",
                        critical_token_policy_path=policy_path,
                    )

            result_lock["terminologyContext"]["sourcePolicySha256"] = (
                policy_sha256
            )
            result_lock["terminologyContext"]["entryCount"] = 1
            _write_json(inference_result_lock_path, result_lock)
            environ["YAP_EVAL_INFERENCE_RESULT_LOCK_SHA256"] = _sha256(
                inference_result_lock_path
            )
            with patch.dict(os.environ, environ, clear=False):
                with self.assertRaisesRegex(
                    ValueError,
                    "terminology context entry count differs",
                ):
                    score_manifest_case(
                        manifest_path=manifest_path,
                        registry_path=registry_path,
                        case_id="case-1",
                        model_id="candidate/model",
                        model_revision="revision-1",
                        audio_path=audio_path,
                        reference_path=reference_path,
                        hypothesis_path=hypothesis_path,
                        inference_result_lock_path=inference_result_lock_path,
                        scorer_lock_path=cache / "scorer.lock.json",
                        critical_token_policy_path=policy_path,
                    )
            result_lock["terminologyContext"]["entryCount"] = len(policy)
            _write_json(inference_result_lock_path, result_lock)
            environ["YAP_EVAL_INFERENCE_RESULT_LOCK_SHA256"] = _sha256(
                inference_result_lock_path
            )

            hypothesis_path.write_text("relabelled output", encoding="utf-8")
            with patch.dict(os.environ, environ, clear=False):
                with self.assertRaisesRegex(ValueError, "hypothesis SHA-256"):
                    score_manifest_case(
                        manifest_path=manifest_path,
                        registry_path=registry_path,
                        case_id="case-1",
                        model_id="candidate/model",
                        model_revision="revision-1",
                        audio_path=audio_path,
                        reference_path=reference_path,
                        hypothesis_path=hypothesis_path,
                        inference_result_lock_path=inference_result_lock_path,
                        scorer_lock_path=cache / "scorer.lock.json",
                        critical_token_policy_path=policy_path,
                    )
            hypothesis_path.write_text("Give 5 mg.", encoding="utf-8")

            changed_manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            changed_case = changed_manifest["cases"][0]
            changed_case["audio"]["durationSamples"] = 16_000 * 60 * 60 * 4
            _write_json(manifest_path, changed_manifest)
            with patch.dict(os.environ, environ, clear=False):
                with self.assertRaisesRegex(ValueError, "human review receipt"):
                    score_manifest_case(
                        manifest_path=manifest_path,
                        registry_path=registry_path,
                        case_id="case-1",
                        model_id="candidate/model",
                        model_revision="revision-1",
                        audio_path=audio_path,
                        reference_path=reference_path,
                        hypothesis_path=hypothesis_path,
                        inference_result_lock_path=inference_result_lock_path,
                        scorer_lock_path=cache / "scorer.lock.json",
                        critical_token_policy_path=policy_path,
                    )
            _write_json(manifest_path, manifest)

            changed_inference_lock = json.loads(
                inference_result_lock_path.read_text(encoding="utf-8")
            )
            changed_inference_lock["modelRevision"] = "different-revision"
            _write_json(inference_result_lock_path, changed_inference_lock)
            environ["YAP_EVAL_INFERENCE_RESULT_LOCK_SHA256"] = _sha256(
                inference_result_lock_path
            )
            with patch.dict(os.environ, environ, clear=False):
                with self.assertRaisesRegex(ValueError, "model identity"):
                    score_manifest_case(
                        manifest_path=manifest_path,
                        registry_path=registry_path,
                        case_id="case-1",
                        model_id="candidate/model",
                        model_revision="revision-1",
                        audio_path=audio_path,
                        reference_path=reference_path,
                        hypothesis_path=hypothesis_path,
                        inference_result_lock_path=inference_result_lock_path,
                        scorer_lock_path=cache / "scorer.lock.json",
                        critical_token_policy_path=policy_path,
                    )
            changed_inference_lock["modelRevision"] = "revision-1"
            _write_json(inference_result_lock_path, changed_inference_lock)
            environ["YAP_EVAL_INFERENCE_RESULT_LOCK_SHA256"] = _sha256(
                inference_result_lock_path
            )

            reference_path.write_text("changed reference", encoding="utf-8")
            with patch.dict(os.environ, environ, clear=False):
                with self.assertRaisesRegex(ValueError, "reference SHA-256"):
                    score_manifest_case(
                        manifest_path=manifest_path,
                        registry_path=registry_path,
                        case_id="case-1",
                        model_id="candidate/model",
                        model_revision="revision-1",
                        audio_path=audio_path,
                        reference_path=reference_path,
                        hypothesis_path=hypothesis_path,
                        inference_result_lock_path=inference_result_lock_path,
                        scorer_lock_path=cache / "scorer.lock.json",
                        critical_token_policy_path=policy_path,
                    )

            reference_path.write_text("Do not give 5 mg.", encoding="utf-8")
            with patch.dict(os.environ, environ, clear=False):
                with self.assertRaisesRegex(ValueError, "distinct artifacts"):
                    score_manifest_case(
                        manifest_path=manifest_path,
                        registry_path=registry_path,
                        case_id="case-1",
                        model_id="candidate/model",
                        model_revision="revision-1",
                        audio_path=audio_path,
                        reference_path=reference_path,
                        hypothesis_path=reference_path,
                        inference_result_lock_path=inference_result_lock_path,
                        scorer_lock_path=cache / "scorer.lock.json",
                        critical_token_policy_path=policy_path,
                    )

            scorer_lock_path = cache / "scorer.lock.json"
            _write_json(
                scorer_lock_path,
                {"schemaVersion": 1, "scorer": {"id": "forged"}},
            )
            forged_sha256 = _sha256(scorer_lock_path)
            changed_manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            changed_manifest["scorerLockSha256"] = forged_sha256
            _write_json(manifest_path, changed_manifest)
            changed_registry = json.loads(
                registry_path.read_text(encoding="utf-8")
            )
            changed_registry["scorerLockSha256"] = forged_sha256
            _write_json(registry_path, changed_registry)
            environ["YAP_EVAL_PROMOTION_REGISTRY_SHA256"] = _sha256(
                registry_path
            )
            with patch.dict(os.environ, environ, clear=False):
                with self.assertRaisesRegex(ValueError, "executing scorer"):
                    score_manifest_case(
                        manifest_path=manifest_path,
                        registry_path=registry_path,
                        case_id="case-1",
                        model_id="candidate/model",
                        model_revision="revision-1",
                        audio_path=audio_path,
                        reference_path=reference_path,
                        hypothesis_path=hypothesis_path,
                        inference_result_lock_path=inference_result_lock_path,
                        scorer_lock_path=scorer_lock_path,
                        critical_token_policy_path=policy_path,
                    )


if __name__ == "__main__":
    unittest.main()
