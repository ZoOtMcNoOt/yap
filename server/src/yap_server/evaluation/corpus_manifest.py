from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from yap_server.language_tags import canonical_bcp47


_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_TRUST_ARTIFACT_BYTES = 16 * 1024 * 1024
_PROMOTION_REGISTRY_DIGEST_ENV = "YAP_EVAL_PROMOTION_REGISTRY_SHA256"
_PROMOTION_CONTEXT_SEAL = object()
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PURPOSES = frozenset(
    {"comparator", "regression", "independentPromotion", "runtimeOnly"}
)
_ASSET_KINDS = frozenset(
    {"natural", "concatenated", "looped", "perturbed", "generatedSilence"}
)
_SUITE_IDS = frozenset(
    {"smoke", "asr-runtime-promotion", "extended", "approved-private"}
)
_CONDITION_LABELS = frozenset(
    {
        "accentMetadata",
        "automaticGain",
        "backgroundSpeech",
        "clean",
        "clipped",
        "closeTalk",
        "codecDegraded",
        "codeSwitch",
        "conversation",
        "dictation",
        "echo",
        "entityDense",
        "farField",
        "interrupted",
        "levelScaled",
        "medicalMock",
        "multiSpeaker",
        "music",
        "noisy",
        "nonSpeech",
        "overlap",
        "packetLoss",
        "quietSpeech",
        "readSpeech",
        "reducedSpeech",
        "resampled",
        "reverberant",
        "silence",
        "spontaneousSpeech",
        "telephony",
        "virtualMeeting",
    }
)
_DERIVATION_OPERATIONS = frozenset(
    {
        "additiveNoise",
        "codecRoundTrip",
        "concatenate",
        "generateSilence",
        "loop",
        "packetLoss",
        "resample",
        "reverberate",
        "scaleLevel",
        "truncate",
    }
)
_ASSET_DERIVATION_OPERATIONS = {
    "concatenated": frozenset({"concatenate"}),
    "looped": frozenset({"loop"}),
    "perturbed": frozenset(
        {
            "additiveNoise",
            "codecRoundTrip",
            "packetLoss",
            "resample",
            "reverberate",
            "scaleLevel",
            "truncate",
        }
    ),
    "generatedSilence": frozenset({"generateSilence"}),
}
_DERIVATION_REQUIRED_CONDITIONS = {
    "additiveNoise": "noisy",
    "codecRoundTrip": "codecDegraded",
    "generateSilence": "silence",
    "packetLoss": "packetLoss",
    "resample": "resampled",
    "reverberate": "reverberant",
    "scaleLevel": "levelScaled",
    "truncate": "interrupted",
}
_EXPOSURE_STATES = frozenset(
    {
        "known_training",
        "known_evaluation",
        "likely_exposed",
        "unknown",
        "contractually_excluded",
        "created_after_model_freeze",
    }
)
_INDEPENDENT_STATES = frozenset(
    {"contractually_excluded", "created_after_model_freeze"}
)
_REFERENCE_TIERS = frozenset({"upstream", "yapAdjudicated", "approvedPrivate"})
_TIMING_KINDS = frozenset({"none", "manual", "forcedAligned", "mixed"})
_ADJUDICATION_STATES = frozenset(
    {"upstream", "unreviewed", "doubleReviewed", "adjudicated"}
)
_RIGHTS_DECISIONS = frozenset(
    {"approved", "hold", "excluded", "permissionRequired"}
)
_RIGHTS_CAPABILITIES = frozenset(
    {"allowed", "forbidden", "unknown", "permissionRequired"}
)
_SCORING_PROFILES = frozenset(
    {
        "word-primary-v1",
        "grapheme-primary-v1",
        "silence-false-words-v1",
    }
)
_PUNCTUATION_PROFILES = frozenset({"unicode-word-boundary-v1"})


@dataclass(frozen=True, slots=True)
class _TrustedCandidateModel:
    model_id: str
    model_revision: str
    candidate_lock_sha256: str
    frozen_at_utc: str
    freeze_evidence_sha256: str


@dataclass(frozen=True, slots=True)
class _TrustedCaseExposure:
    case_id: str
    corpus_id: str
    corpus_release: str
    corpus_split: str
    source_item_id: str
    audio_sha256: str
    decoded_pcm_sha256: str
    reference_sha256: str
    evaluation_policy_sha256: str
    model_id: str
    model_revision: str
    status: str
    recorded_at_utc: str | None
    evidence_uri: str
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class _TrustedPromotionContext:
    """Externally verified freezes and exposures, never derived from the manifest."""

    scorer_lock_sha256: str
    expected_models: tuple[_TrustedCandidateModel, ...]
    verified_exposures: tuple[_TrustedCaseExposure, ...]
    _seal: object


def load_corpus_manifest(path: Path) -> dict[str, object]:
    payload = _read_json_object(path, "ASR corpus manifest", _MAX_MANIFEST_BYTES)
    _validate_corpus_manifest(payload, promotion_context=None)
    return payload


def load_promotion_corpus_manifest(
    manifest_path: Path,
    registry_path: Path,
) -> dict[str, object]:
    """Load an independent manifest through the private pinned trust registry."""

    return load_promotion_corpus_manifest_with_identity(
        manifest_path,
        registry_path,
    )[0]


def load_promotion_corpus_manifest_with_identity(
    manifest_path: Path,
    registry_path: Path,
) -> tuple[dict[str, object], str]:
    """Load a private promotion manifest and its same-read SHA-256 identity."""

    cache_root = _private_cache_root(os.environ)
    private_manifest = _private_file(
        manifest_path,
        cache_root=cache_root,
        maximum_bytes=_MAX_MANIFEST_BYTES,
        field="ASR corpus manifest",
    )
    promotion_context = _load_trusted_promotion_context(registry_path, os.environ)
    payload, manifest_sha256 = _read_json_object_with_identity(
        private_manifest,
        "ASR corpus manifest",
        _MAX_MANIFEST_BYTES,
    )
    _validate_corpus_manifest(payload, promotion_context=promotion_context)
    return payload, manifest_sha256


def _read_json_object(
    path: Path,
    field: str,
    maximum_bytes: int,
    *,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    return _read_json_object_with_identity(
        path,
        field,
        maximum_bytes,
        expected_sha256=expected_sha256,
    )[0]


def _read_json_object_with_identity(
    path: Path,
    field: str,
    maximum_bytes: int,
    *,
    expected_sha256: str | None = None,
) -> tuple[dict[str, object], str]:
    if path.is_symlink():
        raise ValueError(f"{field} must be a real file")
    resolved = path.resolve(strict=True)
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{field} must be a real file")
    if not 1 <= metadata.st_size <= maximum_bytes:
        raise ValueError(f"{field} size is invalid")
    body = resolved.read_bytes()
    if len(body) != metadata.st_size:
        raise ValueError(f"{field} changed while it was read")
    if (
        expected_sha256 is not None
        and hashlib.sha256(body).hexdigest() != expected_sha256
    ):
        raise ValueError(f"{field} differs from its out-of-band digest")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{field} is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{field} must be an object")
    return dict(payload), hashlib.sha256(body).hexdigest()


def validate_corpus_manifest(value: object) -> None:
    """Validate metadata; independent claims cannot self-authorize promotion."""

    _validate_corpus_manifest(value, promotion_context=None)


def evaluation_policy_sha256(
    *,
    language_bcp47: str,
    scoring_profile: str,
    punctuation_profile: str,
    critical_token_set_sha256: str | None,
) -> str:
    """Hash the exact transcript-scoring semantics for one private case."""

    language = canonical_bcp47(language_bcp47, "evaluation policy languageBcp47")
    profile = _enum(
        scoring_profile,
        _SCORING_PROFILES,
        "evaluation policy scoring profile",
    )
    punctuation = _enum(
        punctuation_profile,
        _PUNCTUATION_PROFILES,
        "evaluation policy punctuation profile",
    )
    if critical_token_set_sha256 is not None:
        critical_token_set_sha256 = _sha256(
            critical_token_set_sha256,
            "evaluation policy critical-token set SHA-256",
        )
    payload = json.dumps(
        {
            "schemaVersion": 1,
            "languageBcp47": language,
            "scoringProfile": profile,
            "punctuationProfile": punctuation,
            "criticalTokenSetSha256": critical_token_set_sha256,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_corpus_manifest(
    value: object,
    *,
    promotion_context: _TrustedPromotionContext | None,
) -> None:
    (
        trusted_scorer_lock_sha256,
        trusted_models,
        trusted_exposures,
    ) = _trusted_context_indexes(promotion_context)
    root = _object(
        value,
        {
            "schemaVersion",
            "privateCacheEnvironment",
            "scorerLockSha256",
            "candidateModels",
            "cases",
        },
        "ASR corpus manifest",
    )
    if (
        root["schemaVersion"] != 2
        or root["privateCacheEnvironment"] != "YAP_EVAL_CACHE"
    ):
        raise ValueError("ASR corpus manifest identity is invalid")
    scorer_lock_sha256 = _sha256(
        root["scorerLockSha256"],
        "evaluation scorer lock SHA-256",
    )
    if (
        trusted_scorer_lock_sha256 is not None
        and scorer_lock_sha256 != trusted_scorer_lock_sha256
    ):
        raise ValueError("evaluation scorer lock differs from the trusted registry")

    models: dict[tuple[str, str], tuple[str, datetime, str]] = {}
    for value in _array(root["candidateModels"], "candidate models"):
        model = _object(
            value,
            {
                "id",
                "revision",
                "candidateLockSha256",
                "frozenAtUtc",
                "freezeEvidenceSha256",
            },
            "candidate model",
        )
        identity = (
            _model_id(model["id"], "candidate model ID"),
            _identifier(model["revision"], "candidate model revision"),
        )
        if identity in models:
            raise ValueError("candidate model identities must be unique")
        models[identity] = (
            _sha256(
                model["candidateLockSha256"],
                "candidate model lock SHA-256",
            ),
            _utc(model["frozenAtUtc"], "candidate model freeze time"),
            _sha256(
                model["freezeEvidenceSha256"],
                "candidate model freeze-evidence SHA-256",
            ),
        )

    case_ids: set[str] = set()
    audio_hashes: set[str] = set()
    decoded_pcm_hashes: set[str] = set()
    for value in _array(root["cases"], "corpus cases"):
        case = _object(
            value,
            {
                "id",
                "purpose",
                "assetKind",
                "suiteIds",
                "conditionLabels",
                "derivation",
                "corpus",
                "audio",
                "reference",
                "rights",
                "knownDefects",
                "modelExposure",
            },
            "corpus case",
        )
        case_id = _identifier(case["id"], "corpus case ID")
        if case_id in case_ids:
            raise ValueError("corpus case IDs must be unique")
        case_ids.add(case_id)
        purpose = _enum(case["purpose"], _PURPOSES, "corpus purpose")
        asset_kind = _enum(case["assetKind"], _ASSET_KINDS, "asset kind")
        suite_ids = _unique_enum_array(case["suiteIds"], _SUITE_IDS, "suite IDs")
        condition_labels = _unique_enum_array(
            case["conditionLabels"],
            _CONDITION_LABELS,
            "condition labels",
        )
        _validate_derivation(case["derivation"], asset_kind, condition_labels)
        corpus = _object(
            case["corpus"],
            {
                "id",
                "release",
                "split",
                "itemId",
                "sourceUri",
                "retrievedAtUtc",
            },
            "corpus source",
        )
        corpus_id = _identifier(corpus["id"], "corpus ID")
        corpus_release = _identifier(corpus["release"], "corpus release")
        corpus_split = _identifier(corpus["split"], "corpus split")
        source_item_id = _identifier(corpus["itemId"], "corpus source item ID")
        _https_uri(corpus["sourceUri"], "corpus source URI")
        retrieved_at = _utc(corpus["retrievedAtUtc"], "corpus retrieval time")

        audio = _object(
            case["audio"],
            {
                "sha256",
                "byteLength",
                "decodedPcmSha256",
                "durationSamples",
                "sampleRateHz",
                "channels",
                "codec",
                "recordedAtUtc",
            },
            "corpus audio",
        )
        audio_sha256 = _sha256(audio["sha256"], "audio SHA-256")
        if audio_sha256 in audio_hashes:
            raise ValueError("audio SHA-256 must identify only one corpus case")
        audio_hashes.add(audio_sha256)
        _positive_int(audio["byteLength"], "audio byte length")
        decoded_pcm_sha256 = _sha256(
            audio["decodedPcmSha256"],
            "decoded PCM SHA-256",
        )
        if decoded_pcm_sha256 in decoded_pcm_hashes:
            raise ValueError("decoded PCM SHA-256 must identify only one corpus case")
        decoded_pcm_hashes.add(decoded_pcm_sha256)
        _positive_int(audio["durationSamples"], "audio duration samples")
        sample_rate = _positive_int(audio["sampleRateHz"], "audio sample rate")
        channels = _positive_int(audio["channels"], "audio channels")
        if sample_rate > 384_000 or channels > 8:
            raise ValueError("corpus audio shape exceeds the evaluation bounds")
        _identifier(audio["codec"], "audio codec")
        recorded_at = (
            None
            if audio["recordedAtUtc"] is None
            else _utc(audio["recordedAtUtc"], "audio recording time")
        )
        if recorded_at is not None and recorded_at > retrieved_at:
            raise ValueError("audio recording time cannot follow corpus retrieval")

        reference = _object(
            case["reference"],
            {
                "sha256",
                "tier",
                "revision",
                "languageBcp47",
                "scoringProfile",
                "punctuationProfile",
                "criticalTokenSetSha256",
                "speakerCount",
                "timingKind",
                "adjudicationState",
            },
            "corpus reference",
        )
        reference_sha256 = _sha256(reference["sha256"], "reference SHA-256")
        _enum(reference["tier"], _REFERENCE_TIERS, "reference tier")
        _identifier(reference["revision"], "reference revision")
        language_bcp47 = canonical_bcp47(
            reference["languageBcp47"],
            "reference languageBcp47",
        )
        scoring_profile = _enum(
            reference["scoringProfile"],
            _SCORING_PROFILES,
            "reference scoring profile",
        )
        punctuation_profile = _enum(
            reference["punctuationProfile"],
            _PUNCTUATION_PROFILES,
            "reference punctuation profile",
        )
        critical_token_set_sha256 = reference["criticalTokenSetSha256"]
        if critical_token_set_sha256 is not None:
            _sha256(
                critical_token_set_sha256,
                "reference critical-token set SHA-256",
            )
        case_evaluation_policy_sha256 = evaluation_policy_sha256(
            language_bcp47=language_bcp47,
            scoring_profile=scoring_profile,
            punctuation_profile=punctuation_profile,
            critical_token_set_sha256=critical_token_set_sha256,
        )
        speaker_count = _nonnegative_int(
            reference["speakerCount"],
            "reference speaker count",
        )
        if speaker_count > 64:
            raise ValueError("reference speaker count exceeds the evaluation bound")
        if language_bcp47 == "mul" and scoring_profile != "grapheme-primary-v1":
            raise ValueError(
                "mixed-language references require grapheme-primary scoring"
            )
        if scoring_profile == "silence-false-words-v1":
            if speaker_count != 0 or language_bcp47 != "und":
                raise ValueError(
                    "silence scoring requires zero speakers and und language"
                )
            if critical_token_set_sha256 is not None:
                raise ValueError(
                    "silence scoring cannot use a critical-token policy"
                )
            if "nonSpeech" not in condition_labels:
                raise ValueError("silence scoring requires the nonSpeech condition")
        elif speaker_count == 0:
            raise ValueError("speech scoring requires at least one reference speaker")
        if (
            asset_kind == "generatedSilence"
            and scoring_profile != "silence-false-words-v1"
        ):
            raise ValueError("generated silence requires silence scoring")
        if asset_kind == "generatedSilence" and "silence" not in condition_labels:
            raise ValueError("generated silence requires the silence condition")
        if "overlap" in condition_labels and speaker_count < 2:
            raise ValueError("overlap evidence requires at least two speakers")
        if "multiSpeaker" in condition_labels and speaker_count < 2:
            raise ValueError("multi-speaker evidence requires at least two speakers")
        _enum(reference["timingKind"], _TIMING_KINDS, "reference timing kind")
        adjudication_state = _enum(
            reference["adjudicationState"],
            _ADJUDICATION_STATES,
            "reference adjudication state",
        )

        rights = _object(
            case["rights"],
            {
                "licenseId",
                "licenseTextSha256",
                "audioDecision",
                "referenceDecision",
                "commercialUse",
                "redistribution",
                "reidentificationProhibited",
            },
            "corpus rights",
        )
        _identifier(rights["licenseId"], "license ID")
        _sha256(rights["licenseTextSha256"], "license text SHA-256")
        audio_decision = _enum(
            rights["audioDecision"], _RIGHTS_DECISIONS, "audio rights decision"
        )
        reference_decision = _enum(
            rights["referenceDecision"],
            _RIGHTS_DECISIONS,
            "reference rights decision",
        )
        commercial_use = _enum(
            rights["commercialUse"],
            _RIGHTS_CAPABILITIES,
            "commercial-use decision",
        )
        _enum(
            rights["redistribution"],
            _RIGHTS_CAPABILITIES,
            "redistribution decision",
        )
        if not isinstance(rights["reidentificationProhibited"], bool):
            raise ValueError("reidentification policy must be a boolean")
        _bounded_text_array(case["knownDefects"], "known defects", allow_empty=True)

        exposures: dict[tuple[str, str], tuple[str, str, str]] = {}
        for exposure_value in _array(case["modelExposure"], "model exposure"):
            exposure = _object(
                exposure_value,
                {
                    "modelId",
                    "modelRevision",
                    "status",
                    "evidenceUri",
                    "evidenceSha256",
                },
                "model exposure",
            )
            identity = (
                _model_id(exposure["modelId"], "exposure model ID"),
                _identifier(exposure["modelRevision"], "exposure model revision"),
            )
            if identity in exposures:
                raise ValueError("model exposure identities must be unique per case")
            evidence_uri = _evidence_uri(
                exposure["evidenceUri"],
                "model exposure evidence URI",
            )
            evidence_sha256 = _sha256(
                exposure["evidenceSha256"],
                "exposure evidence SHA-256",
            )
            exposure_status = _enum(
                exposure["status"],
                _EXPOSURE_STATES,
                "model exposure status",
            )
            exposures[identity] = (
                exposure_status,
                evidence_uri,
                evidence_sha256,
            )
            if exposure_status == "created_after_model_freeze":
                if asset_kind != "natural":
                    raise ValueError(
                        "post-freeze exposure requires natural source audio"
                    )
                model_claim = models.get(identity)
                if (
                    model_claim is None
                    or recorded_at is None
                    or recorded_at <= model_claim[1]
                ):
                    raise ValueError(
                        "post-freeze exposure requires a later recording timestamp"
                    )
        if set(exposures) != set(models):
            raise ValueError("every corpus case must classify every candidate model")
        if purpose == "independentPromotion":
            if "asr-runtime-promotion" not in suite_ids:
                raise ValueError(
                    "independent promotion must belong to the promotion suite"
                )
            if asset_kind != "natural":
                raise ValueError("independent promotion requires natural source audio")
            if any(
                status not in _INDEPENDENT_STATES
                for status, _evidence_uri_value, _evidence_sha256 in exposures.values()
            ):
                raise ValueError(
                    "independent promotion requires proven model exclusion"
                )
            if (
                audio_decision != "approved"
                or reference_decision != "approved"
                or commercial_use != "allowed"
                or adjudication_state != "adjudicated"
            ):
                raise ValueError(
                    "independent promotion requires approved rights and adjudication"
                )
            _require_trusted_promotion(
                models=models,
                trusted_models=trusted_models,
                trusted_exposures=trusted_exposures,
                case_id=case_id,
                corpus_id=corpus_id,
                corpus_release=corpus_release,
                corpus_split=corpus_split,
                source_item_id=source_item_id,
                audio_sha256=audio_sha256,
                decoded_pcm_sha256=decoded_pcm_sha256,
                reference_sha256=reference_sha256,
                evaluation_policy_sha256=case_evaluation_policy_sha256,
                recorded_at=recorded_at,
                exposures=exposures,
            )
        if purpose == "runtimeOnly" and asset_kind == "natural":
            raise ValueError(
                "natural audio must not be hidden inside a runtime-only case"
            )
        if purpose == "runtimeOnly" and "asr-runtime-promotion" in suite_ids:
            raise ValueError("runtime-only cases cannot enter the promotion suite")


def _load_trusted_promotion_context(
    registry_path: Path,
    environ: Mapping[str, str],
) -> _TrustedPromotionContext:
    cache_root = _private_cache_root(environ)
    expected_registry_sha256 = _sha256(
        environ.get(_PROMOTION_REGISTRY_DIGEST_ENV, "").strip(),
        _PROMOTION_REGISTRY_DIGEST_ENV,
    )
    registry = _private_file(
        registry_path,
        cache_root=cache_root,
        maximum_bytes=_MAX_MANIFEST_BYTES,
        field="promotion registry",
    )
    root = _object(
        _read_json_object(
            registry,
            "promotion registry",
            _MAX_MANIFEST_BYTES,
            expected_sha256=expected_registry_sha256,
        ),
        {
            "schemaVersion",
            "scorerLockPath",
            "scorerLockSha256",
            "candidateModels",
            "verifiedExposures",
        },
        "promotion registry",
    )
    if root["schemaVersion"] != 1:
        raise ValueError("promotion registry schema is unsupported")
    scorer_lock_sha256 = _sha256(
        root["scorerLockSha256"],
        "trusted scorer lock SHA-256",
    )
    _verified_registry_artifact(
        registry.parent,
        cache_root,
        root["scorerLockPath"],
        scorer_lock_sha256,
        "trusted scorer lock",
    )

    candidates: list[_TrustedCandidateModel] = []
    for value in _array(root["candidateModels"], "trusted candidate models"):
        model = _object(
            value,
            {
                "id",
                "revision",
                "candidateLockPath",
                "candidateLockSha256",
                "frozenAtUtc",
                "freezeEvidencePath",
                "freezeEvidenceSha256",
            },
            "trusted candidate model",
        )
        candidate_lock_sha256 = _sha256(
            model["candidateLockSha256"],
            "trusted candidate lock SHA-256",
        )
        _verified_registry_artifact(
            registry.parent,
            cache_root,
            model["candidateLockPath"],
            candidate_lock_sha256,
            "trusted candidate lock",
        )
        freeze_evidence_sha256 = _sha256(
            model["freezeEvidenceSha256"],
            "trusted freeze-evidence SHA-256",
        )
        _verified_registry_artifact(
            registry.parent,
            cache_root,
            model["freezeEvidencePath"],
            freeze_evidence_sha256,
            "trusted freeze evidence",
        )
        candidates.append(
            _TrustedCandidateModel(
                model_id=_model_id(model["id"], "trusted candidate model ID"),
                model_revision=_identifier(
                    model["revision"],
                    "trusted candidate model revision",
                ),
                candidate_lock_sha256=candidate_lock_sha256,
                frozen_at_utc=_canonical_utc_text(
                    model["frozenAtUtc"],
                    "trusted candidate freeze time",
                ),
                freeze_evidence_sha256=freeze_evidence_sha256,
            )
        )

    exposures: list[_TrustedCaseExposure] = []
    for value in _array(root["verifiedExposures"], "trusted case exposures"):
        exposure = _object(
            value,
            {
                "caseId",
                "corpusId",
                "corpusRelease",
                "corpusSplit",
                "sourceItemId",
                "audioSha256",
                "decodedPcmSha256",
                "referenceSha256",
                "evaluationPolicySha256",
                "modelId",
                "modelRevision",
                "status",
                "recordedAtUtc",
                "evidenceUri",
                "evidencePath",
                "evidenceSha256",
            },
            "trusted case exposure",
        )
        evidence_sha256 = _sha256(
            exposure["evidenceSha256"],
            "trusted exposure evidence SHA-256",
        )
        _verified_registry_artifact(
            registry.parent,
            cache_root,
            exposure["evidencePath"],
            evidence_sha256,
            "trusted exposure evidence",
        )
        recorded_at_value = exposure["recordedAtUtc"]
        recorded_at_utc = (
            None
            if recorded_at_value is None
            else _canonical_utc_text(
                recorded_at_value,
                "trusted exposure recording time",
            )
        )
        exposures.append(
            _TrustedCaseExposure(
                case_id=_identifier(exposure["caseId"], "trusted exposure case ID"),
                corpus_id=_identifier(
                    exposure["corpusId"],
                    "trusted exposure corpus ID",
                ),
                corpus_release=_identifier(
                    exposure["corpusRelease"],
                    "trusted exposure corpus release",
                ),
                corpus_split=_identifier(
                    exposure["corpusSplit"],
                    "trusted exposure corpus split",
                ),
                source_item_id=_identifier(
                    exposure["sourceItemId"],
                    "trusted exposure source item ID",
                ),
                audio_sha256=_sha256(
                    exposure["audioSha256"],
                    "trusted exposure audio SHA-256",
                ),
                decoded_pcm_sha256=_sha256(
                    exposure["decodedPcmSha256"],
                    "trusted exposure decoded PCM SHA-256",
                ),
                reference_sha256=_sha256(
                    exposure["referenceSha256"],
                    "trusted exposure reference SHA-256",
                ),
                evaluation_policy_sha256=_sha256(
                    exposure["evaluationPolicySha256"],
                    "trusted evaluation policy SHA-256",
                ),
                model_id=_model_id(
                    exposure["modelId"],
                    "trusted exposure model ID",
                ),
                model_revision=_identifier(
                    exposure["modelRevision"],
                    "trusted exposure model revision",
                ),
                status=_enum(
                    exposure["status"],
                    _EXPOSURE_STATES,
                    "trusted exposure status",
                ),
                recorded_at_utc=recorded_at_utc,
                evidence_uri=_evidence_uri(
                    exposure["evidenceUri"],
                    "trusted exposure evidence URI",
                ),
                evidence_sha256=evidence_sha256,
            )
        )
    context = _TrustedPromotionContext(
        scorer_lock_sha256=scorer_lock_sha256,
        expected_models=tuple(candidates),
        verified_exposures=tuple(exposures),
        _seal=_PROMOTION_CONTEXT_SEAL,
    )
    _trusted_context_indexes(context)
    return context


def _private_cache_root(environ: Mapping[str, str]) -> Path:
    raw = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required for promotion evidence")
    requested = Path(raw)
    if not requested.is_absolute() or requested.is_symlink():
        raise ValueError("YAP_EVAL_CACHE must be an absolute real directory")
    repository = Path(__file__).resolve().parents[4]
    resolved = requested.resolve(strict=True)
    if resolved == repository or repository in resolved.parents:
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("YAP_EVAL_CACHE must be a real directory")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("YAP_EVAL_CACHE must use private permissions")
    return resolved


def _private_file(
    path: Path,
    *,
    cache_root: Path,
    maximum_bytes: int,
    field: str,
) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{field} must be an absolute real file")
    resolved = path.resolve(strict=True)
    if cache_root not in resolved.parents:
        raise ValueError(f"{field} must remain inside YAP_EVAL_CACHE")
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{field} must be a real file")
    if not 1 <= metadata.st_size <= maximum_bytes:
        raise ValueError(f"{field} size is invalid")
    return resolved


def _verified_registry_artifact(
    registry_root: Path,
    cache_root: Path,
    relative_value: object,
    expected_sha256: str,
    field: str,
) -> None:
    if not isinstance(relative_value, str) or not relative_value:
        raise ValueError(f"{field} path is invalid")
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field} path is invalid")
    artifact = _private_file(
        registry_root / relative,
        cache_root=cache_root,
        maximum_bytes=_MAX_TRUST_ARTIFACT_BYTES,
        field=field,
    )
    if _sha256_file(artifact) != expected_sha256:
        raise ValueError(f"{field} differs from the trusted registry")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for body in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(body)
    return digest.hexdigest()


def _trusted_context_indexes(
    context: _TrustedPromotionContext | None,
) -> tuple[
    str | None,
    dict[tuple[str, str], tuple[str, datetime, str]],
    dict[tuple[str, str, str], tuple[_TrustedCaseExposure, datetime | None]],
]:
    if context is None:
        return None, {}, {}
    if (
        not isinstance(context, _TrustedPromotionContext)
        or context._seal is not _PROMOTION_CONTEXT_SEAL
    ):
        raise ValueError("promotion context is invalid")
    if not context.expected_models or not context.verified_exposures:
        raise ValueError("promotion context must contain trusted evidence")
    scorer_lock_sha256 = _sha256(
        context.scorer_lock_sha256,
        "trusted scorer lock SHA-256",
    )

    models: dict[tuple[str, str], tuple[str, datetime, str]] = {}
    for candidate in context.expected_models:
        if not isinstance(candidate, _TrustedCandidateModel):
            raise ValueError("trusted candidate model is invalid")
        identity = (
            _model_id(candidate.model_id, "trusted candidate model ID"),
            _identifier(candidate.model_revision, "trusted candidate model revision"),
        )
        if identity in models:
            raise ValueError("trusted candidate model identities must be unique")
        models[identity] = (
            _sha256(
                candidate.candidate_lock_sha256,
                "trusted candidate lock SHA-256",
            ),
            _utc(candidate.frozen_at_utc, "trusted candidate freeze time"),
            _sha256(
                candidate.freeze_evidence_sha256,
                "trusted candidate freeze-evidence SHA-256",
            ),
        )

    exposures: dict[
        tuple[str, str, str],
        tuple[_TrustedCaseExposure, datetime | None],
    ] = {}
    for exposure in context.verified_exposures:
        if not isinstance(exposure, _TrustedCaseExposure):
            raise ValueError("trusted case exposure is invalid")
        case_id = _identifier(exposure.case_id, "trusted exposure case ID")
        model_identity = (
            _model_id(exposure.model_id, "trusted exposure model ID"),
            _identifier(
                exposure.model_revision,
                "trusted exposure model revision",
            ),
        )
        if model_identity not in models:
            raise ValueError("trusted exposure refers to an unexpected model")
        key = (case_id, *model_identity)
        if key in exposures:
            raise ValueError("trusted case exposure identities must be unique")
        _identifier(exposure.corpus_id, "trusted exposure corpus ID")
        _identifier(exposure.corpus_release, "trusted exposure corpus release")
        _identifier(exposure.corpus_split, "trusted exposure corpus split")
        _identifier(exposure.source_item_id, "trusted exposure source item ID")
        _sha256(exposure.audio_sha256, "trusted exposure audio SHA-256")
        _sha256(
            exposure.decoded_pcm_sha256,
            "trusted exposure decoded PCM SHA-256",
        )
        _sha256(exposure.reference_sha256, "trusted exposure reference SHA-256")
        _sha256(
            exposure.evaluation_policy_sha256,
            "trusted evaluation policy SHA-256",
        )
        _enum(exposure.status, _EXPOSURE_STATES, "trusted exposure status")
        _evidence_uri(exposure.evidence_uri, "trusted exposure evidence URI")
        recorded_at = (
            None
            if exposure.recorded_at_utc is None
            else _utc(
                exposure.recorded_at_utc,
                "trusted exposure recording time",
            )
        )
        _sha256(exposure.evidence_sha256, "trusted exposure evidence SHA-256")
        exposures[key] = (exposure, recorded_at)
    return scorer_lock_sha256, models, exposures


def _require_trusted_promotion(
    *,
    models: dict[tuple[str, str], tuple[str, datetime, str]],
    trusted_models: dict[tuple[str, str], tuple[str, datetime, str]],
    trusted_exposures: dict[
        tuple[str, str, str],
        tuple[_TrustedCaseExposure, datetime | None],
    ],
    case_id: str,
    corpus_id: str,
    corpus_release: str,
    corpus_split: str,
    source_item_id: str,
    audio_sha256: str,
    decoded_pcm_sha256: str,
    reference_sha256: str,
    evaluation_policy_sha256: str,
    recorded_at: datetime | None,
    exposures: dict[tuple[str, str], tuple[str, str, str]],
) -> None:
    if not trusted_models and not trusted_exposures:
        raise ValueError(
            "independent promotion requires trusted external exposure evidence"
        )
    if models != trusted_models:
        raise ValueError(
            "independent promotion requires the exact trusted candidate set"
        )
    for identity, (status, evidence_uri, evidence_sha256) in exposures.items():
        trusted_entry = trusted_exposures.get((case_id, *identity))
        if trusted_entry is None:
            raise ValueError(
                "independent promotion requires trusted external exposure evidence"
            )
        trusted, trusted_recorded_at = trusted_entry
        if (
            trusted.corpus_id != corpus_id
            or trusted.corpus_release != corpus_release
            or trusted.corpus_split != corpus_split
            or trusted.source_item_id != source_item_id
            or trusted.audio_sha256 != audio_sha256
            or trusted.decoded_pcm_sha256 != decoded_pcm_sha256
            or trusted.reference_sha256 != reference_sha256
            or trusted.evaluation_policy_sha256 != evaluation_policy_sha256
            or trusted.status != status
            or trusted.evidence_uri != evidence_uri
            or trusted.evidence_sha256 != evidence_sha256
            or trusted_recorded_at != recorded_at
        ):
            if trusted.evaluation_policy_sha256 != evaluation_policy_sha256:
                raise ValueError(
                    "evaluation policy differs from the trusted registry"
                )
            raise ValueError(
                "independent promotion evidence does not match the trusted registry"
            )
        if (
            status == "created_after_model_freeze"
            and (
                trusted_recorded_at is None
                or trusted_recorded_at <= trusted_models[identity][1]
            )
        ):
            raise ValueError(
                "trusted post-freeze evidence requires a later original recording"
            )


def _object(value: object, keys: set[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{field} fields differ from the contract")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    return value


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _model_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _MODEL_ID.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _https_uri(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://"):
        raise ValueError(f"{field} must be an HTTPS URI")
    return value


def _evidence_uri(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith(("https://", "urn:yap:")):
        raise ValueError(f"{field} is invalid")
    return value


def _canonical_utc_text(value: object, field: str) -> str:
    _utc(value, field)
    if not isinstance(value, str):
        raise ValueError(f"{field} is invalid")
    return value


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{field} is invalid") from error
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"{field} must be UTC")
    return parsed


def _bounded_text_array(value: object, field: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"{field} must be an array")
    if len(value) > 128 or any(
        not isinstance(item, str) or not item or len(item) > 512 for item in value
    ):
        raise ValueError(f"{field} entries are invalid")
    return value


def _unique_enum_array(
    value: object,
    allowed: frozenset[str],
    field: str,
) -> tuple[str, ...]:
    entries = tuple(_enum(item, allowed, field) for item in _array(value, field))
    if tuple(sorted(set(entries))) != entries:
        raise ValueError(f"{field} must be unique and sorted")
    return entries


def _validate_derivation(
    value: object,
    asset_kind: str,
    condition_labels: tuple[str, ...],
) -> None:
    if asset_kind == "natural":
        if value is not None:
            raise ValueError("natural source audio cannot declare derivation")
        return
    derivation = _object(
        value,
        {"revision", "operation", "sourceAudioSha256s", "recipeSha256"},
        "corpus derivation",
    )
    _identifier(derivation["revision"], "derivation revision")
    operation = _enum(
        derivation["operation"],
        _DERIVATION_OPERATIONS,
        "derivation operation",
    )
    if operation not in _ASSET_DERIVATION_OPERATIONS[asset_kind]:
        raise ValueError("derivation operation does not match the asset kind")
    required_condition = _DERIVATION_REQUIRED_CONDITIONS.get(operation)
    if required_condition is not None and required_condition not in condition_labels:
        raise ValueError("derivation operation requires its matching condition label")
    raw_sources = _bounded_text_array(
        derivation["sourceAudioSha256s"],
        "derivation source audio SHA-256 values",
        allow_empty=True,
    )
    sources = tuple(
        _sha256(source, "derivation source audio SHA-256") for source in raw_sources
    )
    if tuple(sorted(set(sources))) != sources:
        raise ValueError("derivation source audio SHA-256 values must be unique and sorted")
    if operation == "generateSilence":
        if sources:
            raise ValueError("generated silence cannot claim a source recording")
    elif not sources:
        raise ValueError("derived audio requires at least one source recording")
    _sha256(derivation["recipeSha256"], "derivation recipe SHA-256")


def _enum(value: object, allowed: frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field} is invalid")
    return value
