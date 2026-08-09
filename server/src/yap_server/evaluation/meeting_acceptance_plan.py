"""Frozen evidence and scoring boundary for meeting-runtime promotion."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Mapping

from yap_server.artifact_identity import (
    artifact_identities,
    portable_artifact_path,
    require_artifact_paths,
)
from yap_server.json_contract import (
    exact_object,
    https_uri,
    sha256,
)
from yap_server.private_artifact import (
    read_json_object_with_identity,
)


_MAX_PLAN_BYTES = 256 * 1024
_RUNTIME_LOCK_SHA256 = (
    "a5eeedf04339d3d2e53cdc1ed3e695102494a6f3fd9cb7718f2b2f0c6b5cbdd6"
)
_PUBLIC_REVISION = "500809d7e9ae643d3cc945f6c91e7ed0693456bd"
_MEETING_IDS = (
    "ES2004a",
    "IS1009a",
    "TS3003a",
    "EN2002a",
    "Bmr013",
    "Bmr018",
    "Bro021",
    "MTG_32040",
    "MTG_32063",
    "MTG_32072",
    "MTG_32074",
    "MTG_32092",
    "MTG_32179",
    "MTG_32185",
    "MTG_32256",
    "MTG_32257",
    "MTG_32322",
)
_PUBLIC_ARTIFACT_PATHS = frozenset(
    {
        ".gitattributes",
        "README.md",
        "data/ami-00000-of-00001.parquet",
        "data/icsi-00000-of-00001.parquet",
        "data/notsofar-00000-of-00001.parquet",
    }
)
_EVIDENCE_CLASSES = (
    "public-comparator",
    "independent-holdout",
    "constructed-controls",
)
_PRESSURE_AXES = {
    "acoustic": (
        "close-talk",
        "far-field",
        "room-reverb",
        "echo",
        "clipping",
        "agc",
        "noise",
        "silence",
    ),
    "speech": (
        "mumbling",
        "reduced-speech",
        "false-starts",
        "interruptions",
        "sub-1.6-second-turns",
        "short-turns",
        "long-monologues",
    ),
    "overlap": (
        "no-overlap",
        "brief-two-speaker",
        "sustained-two-speaker",
        "three-or-more-speakers",
    ),
    "attendance-roster": (
        "16-attendees-up-to-8-talkers",
        "32-attendees-up-to-8-talkers",
        "64-attendees-up-to-8-talkers",
    ),
    "speaking-roster": (
        "1-talker",
        "2-talkers",
        "4-talkers",
        "8-talkers",
        "9-talkers",
        "16-talkers",
        "32-talkers",
        "late-arrival",
        "long-gap-return",
    ),
    "window-roster": (
        "1-through-8-in-30-seconds",
        "more-than-8-in-30-seconds",
    ),
    "transport": (
        "clean-source",
        "fixed-codec",
        "fixed-sample-rate",
        "fixed-jitter",
        "fixed-drop",
        "explicit-gap",
    ),
    "duration": (
        "correction-sized",
        "15-minutes",
        "30-minutes",
        "two-hours",
        "supported-maximum",
        "four-hour-synthetic-control",
    ),
    "language": (
        "every-advertised-locale",
        "fixed-language-meeting",
        "code-switching-separate-score",
    ),
}
_METRICS = (
    "cpwer",
    "tcpwer",
    "overlap-word-deletion",
    "overlap-word-recall",
    "der",
    "jer",
    "speaker-count-error",
    "timestamp-error",
    "speaker-merge-error",
    "speaker-split-error",
    "speaker-fragmentation",
)


@dataclass(frozen=True, slots=True)
class PublicComparator:
    revision: str
    exposure_status: str
    promotion_eligible: bool
    meeting_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PrivateHoldout:
    manifest_schema_version: int
    cache_environment: str
    repository_fallback: bool
    sealed_before_hypotheses: bool
    independent_promotion_required: bool
    minimum_natural_meeting_count: int
    minimum_natural_duration_seconds: int


@dataclass(frozen=True, slots=True)
class ScoringPolicy:
    public_cpwer_scorer: str
    acceptance_cpwer_scorer: str
    diarization_scorer: str
    diarization_collar_seconds: float
    score_overlap: bool
    speaker_mapping: str
    timestamp_resolution_seconds: float


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    require_every_mandatory_slice: bool
    forbid_macro_compensation: bool
    public_reproduction_tolerance_percentage_points: float
    maximum_private_pooled_cpwer_percent: float
    maximum_mandatory_slice_cpwer_percent: float
    minimum_overlap_cpwer_improvement_percent: float
    maximum_der_percent: float
    maximum_jer_percent: float
    maximum_speaker_count_absolute_error: int
    maximum_timestamp_p95_seconds: float
    maximum_warm_single_request_realtime_factor: float
    maximum_concurrent_eight_p95_realtime_factor: float
    maximum_worker_memory_bytes: int
    maximum_cancellation_seconds: float
    require_cross_request_isolation: bool
    require_exact_teardown: bool


@dataclass(frozen=True, slots=True)
class MeetingAcceptancePlan:
    runtime_lock_sha256: str
    evidence_classes: tuple[str, ...]
    public_comparator: PublicComparator
    private_holdout: PrivateHoldout
    scoring: ScoringPolicy
    pressure_axes: Mapping[str, tuple[str, ...]]
    promotion: PromotionPolicy


def load_meeting_acceptance_plan(path: Path) -> MeetingAcceptancePlan:
    root, _identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAX_PLAN_BYTES,
        field="meeting acceptance plan",
    )
    root = exact_object(
        root,
        {
            "schemaVersion",
            "runtimeLockPath",
            "runtimeLockSha256",
            "privateCache",
            "evidenceClasses",
            "evidence",
            "scorers",
            "scoring",
            "pressureAxes",
            "promotion",
        },
        "meeting acceptance plan",
    )
    if root["schemaVersion"] != 1:
        raise ValueError("unsupported meeting acceptance-plan schema")
    if (
        portable_artifact_path(root["runtimeLockPath"], "meeting runtime lock path")
        != "server/meeting-transcription-runtime.lock.json"
    ):
        raise ValueError("meeting runtime lock path differs from the contract")
    runtime_lock_sha256 = sha256(
        root["runtimeLockSha256"], "meeting runtime lock SHA-256"
    )
    if runtime_lock_sha256 != _RUNTIME_LOCK_SHA256:
        raise ValueError("meeting runtime lock SHA-256 differs from the contract")
    _private_cache(root["privateCache"])
    evidence_classes = _exact_text_array(
        root["evidenceClasses"], _EVIDENCE_CLASSES, "meeting evidence classes"
    )
    evidence = exact_object(
        root["evidence"],
        {"publicComparator", "independentHoldout", "constructedControls"},
        "meeting evidence",
    )
    public = _public_comparator(evidence["publicComparator"])
    private = _private_holdout(evidence["independentHoldout"])
    _constructed_controls(evidence["constructedControls"])
    _scorers(root["scorers"])
    scoring = _scoring(root["scoring"])
    pressure_axes = _pressure_axes(root["pressureAxes"])
    promotion = _promotion(root["promotion"])
    return MeetingAcceptancePlan(
        runtime_lock_sha256=runtime_lock_sha256,
        evidence_classes=evidence_classes,
        public_comparator=public,
        private_holdout=private,
        scoring=scoring,
        pressure_axes=pressure_axes,
        promotion=promotion,
    )


def _private_cache(value: object) -> None:
    cache = exact_object(
        value, {"environment", "repositoryFallback"}, "meeting private cache"
    )
    if (
        cache["environment"] != "YAP_EVAL_CACHE"
        or cache["repositoryFallback"] is not False
    ):
        raise ValueError("meeting evidence must use the private cache without fallback")


def _public_comparator(value: object) -> PublicComparator:
    public = exact_object(
        value,
        {
            "id",
            "repository",
            "revision",
            "source",
            "license",
            "promotionEligible",
            "exposureStatus",
            "meetingIds",
            "artifacts",
        },
        "meeting public comparator",
    )
    if public["promotionEligible"] is not False:
        raise ValueError("public comparator must remain non-promotional")
    expected = {
        "id": "tiron-published-meeting-comparator",
        "repository": "Trelis/tiron-eval-meetings",
        "revision": _PUBLIC_REVISION,
        "source": "https://huggingface.co/datasets/Trelis/tiron-eval-meetings",
        "exposureStatus": "known-exposed",
    }
    if any(public[key] != expected_value for key, expected_value in expected.items()):
        raise ValueError(
            "public comparator identity or exposure differs from the contract"
        )
    https_uri(public["source"], "public comparator source")
    license_value = exact_object(
        public["license"],
        {"spdx", "declarationArtifact", "declarationSha256"},
        "public comparator license",
    )
    if (
        license_value["spdx"] != "CC-BY-4.0"
        or license_value["declarationArtifact"] != "README.md"
        or sha256(
            license_value["declarationSha256"],
            "public comparator license declaration SHA-256",
        )
        != "11bc8decf6e73272e935727d64b3640187c0265242289eb9c31f97aa94648b0c"
    ):
        raise ValueError("public comparator license differs from the contract")
    meetings = _exact_text_array(
        public["meetingIds"], _MEETING_IDS, "public comparator meetings"
    )
    artifacts = artifact_identities(public["artifacts"], "public comparator artifacts")
    require_artifact_paths(artifacts, _PUBLIC_ARTIFACT_PATHS, "public comparator")
    artifact_by_path = {artifact.path: artifact for artifact in artifacts}
    if artifact_by_path["data/ami-00000-of-00001.parquet"].sha256 != (
        "96422895472636f39f308010f70f814e23ca11639b4dc9474d87a663f4514531"
    ):
        raise ValueError("public comparator AMI artifact differs")
    return PublicComparator(
        revision=_PUBLIC_REVISION,
        exposure_status="known-exposed",
        promotion_eligible=False,
        meeting_ids=meetings,
    )


def _private_holdout(value: object) -> PrivateHoldout:
    holdout = exact_object(
        value,
        {
            "purpose",
            "manifestSchemaVersion",
            "manifestRelativePath",
            "trustedReviewRegistryRelativePath",
            "cacheEnvironment",
            "repositoryFallback",
            "sealedBeforeHypotheses",
            "independentPromotionRequired",
            "allowedModelExposureStatuses",
            "minimumNaturalMeetingCount",
            "minimumNaturalDurationSeconds",
            "reviewPolicy",
        },
        "independent meeting holdout",
    )
    expected_scalars = {
        "purpose": "independentPromotion",
        "manifestSchemaVersion": 2,
        "cacheEnvironment": "YAP_EVAL_CACHE",
        "repositoryFallback": False,
        "sealedBeforeHypotheses": True,
        "independentPromotionRequired": True,
        "minimumNaturalMeetingCount": 6,
        "minimumNaturalDurationSeconds": 7_200,
        "reviewPolicy": "two-independent-listeners-plus-independent-adjudicator",
    }
    if any(holdout[key] != expected for key, expected in expected_scalars.items()):
        raise ValueError("independent meeting holdout differs from the contract")
    if (
        portable_artifact_path(
            holdout["manifestRelativePath"], "independent holdout manifest path"
        )
        != "meeting-transcription/private/corpus-manifest.json"
        or portable_artifact_path(
            holdout["trustedReviewRegistryRelativePath"],
            "independent holdout review-registry path",
        )
        != "meeting-transcription/private/review-registry.json"
    ):
        raise ValueError("independent meeting holdout paths differ")
    _exact_text_array(
        holdout["allowedModelExposureStatuses"],
        ("contractually_excluded", "created_after_model_freeze"),
        "independent holdout model exposure statuses",
    )
    return PrivateHoldout(
        manifest_schema_version=2,
        cache_environment="YAP_EVAL_CACHE",
        repository_fallback=False,
        sealed_before_hypotheses=True,
        independent_promotion_required=True,
        minimum_natural_meeting_count=6,
        minimum_natural_duration_seconds=7_200,
    )


def _constructed_controls(value: object) -> None:
    controls = exact_object(
        value,
        {
            "promotionEligible",
            "purpose",
            "manifestSchemaVersion",
            "manifestRelativePath",
            "cacheEnvironment",
            "repositoryFallback",
        },
        "constructed meeting controls",
    )
    if controls != {
        "promotionEligible": False,
        "purpose": "supplemental",
        "manifestSchemaVersion": 2,
        "manifestRelativePath": "meeting-transcription/private/constructed-controls.json",
        "cacheEnvironment": "YAP_EVAL_CACHE",
        "repositoryFallback": False,
    }:
        raise ValueError("constructed meeting controls differ from the contract")


def _scorers(value: object) -> None:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("meeting scorers differ from the contract")
    by_id: dict[str, Mapping[str, object]] = {}
    for scorer_value in value:
        if not isinstance(scorer_value, Mapping) or not isinstance(
            scorer_value.get("id"), str
        ):
            raise ValueError("meeting scorer is invalid")
        scorer_id = scorer_value["id"]
        if scorer_id in by_id:
            raise ValueError("meeting scorer IDs must be unique")
        by_id[scorer_id] = scorer_value
    if set(by_id) != {
        "tiron-published-cpwer",
        "meeteval-0.4.3",
        "pyannote-metrics-4.1",
    }:
        raise ValueError("meeting scorers differ from the contract")
    _published_scorer(by_id["tiron-published-cpwer"])
    _independent_scorer(
        by_id["meeteval-0.4.3"],
        expected_id="meeteval-0.4.3",
        expected_role="independent-meeting-word-error",
        expected_repository="fgnt/meeteval",
        expected_revision="badcd3c7cf82f98d2ac1f292801fbe6e9093ee2f",
        expected_artifact_sha256=(
            "02d3a359f375d39c67dfb8fe1c061e7dac19d6fc1fb89ee72d793a5813dafeb2"
        ),
        expected_license_sha256=(
            "5515c2bdda551fa20d771e99ab31deebbb4f9626bef6f6c25f26125c964fd34c"
        ),
    )
    _independent_scorer(
        by_id["pyannote-metrics-4.1"],
        expected_id="pyannote-metrics-4.1",
        expected_role="independent-diarization-error",
        expected_repository="pyannote/pyannote-metrics",
        expected_revision="5b197b13ba39ac9baad37da66659da196090053c",
        expected_artifact_sha256=(
            "34a54b7671f61709c1865d0484843e5b46ea3c4e4e5260ab065e5b3156c733d3"
        ),
        expected_license_sha256=(
            "657c7e17d7360a3e885dc0b4d05a54bc7233222648ea4f6d347a0e516c4e9bdd"
        ),
    )


def _published_scorer(value: Mapping[str, object]) -> None:
    scorer = exact_object(
        value,
        {"id", "role", "implementation", "revision", "sha256", "dependencies"},
        "published Tiron scorer",
    )
    expected = {
        "id": "tiron-published-cpwer",
        "role": "public-comparator-reproduction",
        "implementation": "TrelisResearch/tiron/eval/scoring.py",
        "revision": "d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c",
        "sha256": "88dd4cbb67019c04fd79cba04072661084c1cb06cddfef60e86cb4b763cbd965",
    }
    if any(scorer[key] != expected_value for key, expected_value in expected.items()):
        raise ValueError("published Tiron scorer differs from the contract")
    dependencies = exact_object(
        scorer["dependencies"],
        {"jiwer", "whisper-normalizer"},
        "published Tiron scorer dependencies",
    )
    expected_dependencies = {
        "jiwer": (
            "4.0.0",
            "7efaf0bd336b095d99ddef9dd67e1ee829d75d58aa2a81d9639870b01d6d95ea",
        ),
        "whisper-normalizer": (
            "0.1.14",
            "93119c1425c6225df4ef33d071cde2f61706cab4f72bb5b4fe47c9f7cdce8747",
        ),
    }
    for name, expected_dependency in expected_dependencies.items():
        dependency = exact_object(
            dependencies[name], {"version", "sha256"}, f"{name} scorer dependency"
        )
        if (
            dependency["version"] != expected_dependency[0]
            or sha256(dependency["sha256"], f"{name} artifact SHA-256")
            != expected_dependency[1]
        ):
            raise ValueError(f"{name} scorer dependency differs")


def _independent_scorer(
    value: Mapping[str, object],
    *,
    expected_id: str,
    expected_role: str,
    expected_repository: str,
    expected_revision: str,
    expected_artifact_sha256: str,
    expected_license_sha256: str,
) -> None:
    scorer = exact_object(
        value,
        {"id", "role", "repository", "revision", "artifactSha256", "license"},
        f"{expected_id} scorer",
    )
    if (
        scorer["id"] != expected_id
        or scorer["role"] != expected_role
        or scorer["repository"] != expected_repository
        or scorer["revision"] != expected_revision
        or sha256(scorer["artifactSha256"], f"{expected_id} artifact SHA-256")
        != expected_artifact_sha256
    ):
        raise ValueError(f"{expected_id} scorer differs from the contract")
    license_value = exact_object(
        scorer["license"], {"spdx", "sha256"}, f"{expected_id} license"
    )
    if (
        license_value["spdx"] != "MIT"
        or sha256(license_value["sha256"], f"{expected_id} license SHA-256")
        != expected_license_sha256
    ):
        raise ValueError(f"{expected_id} license differs from the contract")


def _scoring(value: object) -> ScoringPolicy:
    scoring = exact_object(
        value,
        {
            "publicCpwerScorer",
            "acceptanceCpwerScorer",
            "diarizationScorer",
            "normalization",
            "diarizationCollarSeconds",
            "scoreOverlap",
            "speakerMapping",
            "timestampResolutionSeconds",
            "notsofarUnknownPolicy",
            "amiIcsiExcludedSpanPolicy",
            "metrics",
        },
        "meeting scoring policy",
    )
    if scoring["scoreOverlap"] is not True:
        raise ValueError("overlap must remain scored")
    expected = {
        "publicCpwerScorer": "tiron-published-cpwer",
        "acceptanceCpwerScorer": "meeteval-0.4.3",
        "diarizationScorer": "pyannote-metrics-4.1",
        "normalization": (
            "tiron-english-spoken-v1-for-published-comparator-and-"
            "locale-declared-v1-for-acceptance"
        ),
        "diarizationCollarSeconds": 0.0,
        "speakerMapping": "optimal-permutation",
        "timestampResolutionSeconds": 0.02,
        "notsofarUnknownPolicy": "mask-overlapping-hypothesis-words",
        "amiIcsiExcludedSpanPolicy": (
            "drop-overlapping-reference-and-hypothesis-segments"
        ),
    }
    if any(scoring[key] != expected_value for key, expected_value in expected.items()):
        raise ValueError("meeting scoring policy differs from the contract")
    _exact_text_array(scoring["metrics"], _METRICS, "meeting metrics")
    return ScoringPolicy(
        public_cpwer_scorer="tiron-published-cpwer",
        acceptance_cpwer_scorer="meeteval-0.4.3",
        diarization_scorer="pyannote-metrics-4.1",
        diarization_collar_seconds=0.0,
        score_overlap=True,
        speaker_mapping="optimal-permutation",
        timestamp_resolution_seconds=0.02,
    )


def _pressure_axes(value: object) -> Mapping[str, tuple[str, ...]]:
    axes = exact_object(value, set(_PRESSURE_AXES), "meeting pressure axes")
    result: dict[str, tuple[str, ...]] = {}
    for name, expected_values in _PRESSURE_AXES.items():
        result[name] = _exact_text_array(
            axes[name], expected_values, f"meeting {name} pressure"
        )
    return result


def _promotion(value: object) -> PromotionPolicy:
    promotion = exact_object(
        value,
        {
            "requireEveryMandatorySlice",
            "forbidMacroCompensation",
            "publicReproductionTolerancePercentagePoints",
            "maximumPrivatePooledCpwerPercent",
            "maximumMandatorySliceCpwerPercent",
            "minimumOverlapCpwerImprovementPercent",
            "maximumDerPercent",
            "maximumJerPercent",
            "maximumSpeakerCountAbsoluteError",
            "maximumTimestampP95Seconds",
            "maximumWarmSingleRequestRealtimeFactor",
            "maximumConcurrentEightP95RealtimeFactor",
            "maximumWorkerMemoryBytes",
            "maximumCancellationSeconds",
            "requireCrossRequestIsolation",
            "requireExactTeardown",
            "allowedOutcomes",
        },
        "meeting promotion policy",
    )
    expected = {
        "requireEveryMandatorySlice": True,
        "forbidMacroCompensation": True,
        "publicReproductionTolerancePercentagePoints": 1.5,
        "maximumPrivatePooledCpwerPercent": 35.0,
        "maximumMandatorySliceCpwerPercent": 45.0,
        "minimumOverlapCpwerImprovementPercent": 5.0,
        "maximumDerPercent": 35.0,
        "maximumJerPercent": 45.0,
        "maximumSpeakerCountAbsoluteError": 1,
        "maximumTimestampP95Seconds": 1.5,
        "maximumWarmSingleRequestRealtimeFactor": 0.1,
        "maximumConcurrentEightP95RealtimeFactor": 0.5,
        "maximumWorkerMemoryBytes": 17_179_869_184,
        "maximumCancellationSeconds": 2.0,
        "requireCrossRequestIsolation": True,
        "requireExactTeardown": True,
    }
    for key, expected_value in expected.items():
        actual = promotion[key]
        if isinstance(expected_value, float):
            actual = _finite_number(actual, f"meeting promotion {key}")
        if actual != expected_value:
            raise ValueError("meeting promotion thresholds differ from the contract")
    _exact_text_array(
        promotion["allowedOutcomes"],
        ("narrow-route-promotion", "unadvertised-baseline"),
        "meeting promotion outcomes",
    )
    return PromotionPolicy(
        require_every_mandatory_slice=True,
        forbid_macro_compensation=True,
        public_reproduction_tolerance_percentage_points=1.5,
        maximum_private_pooled_cpwer_percent=35.0,
        maximum_mandatory_slice_cpwer_percent=45.0,
        minimum_overlap_cpwer_improvement_percent=5.0,
        maximum_der_percent=35.0,
        maximum_jer_percent=45.0,
        maximum_speaker_count_absolute_error=1,
        maximum_timestamp_p95_seconds=1.5,
        maximum_warm_single_request_realtime_factor=0.1,
        maximum_concurrent_eight_p95_realtime_factor=0.5,
        maximum_worker_memory_bytes=17_179_869_184,
        maximum_cancellation_seconds=2.0,
        require_cross_request_isolation=True,
        require_exact_teardown=True,
    )


def _exact_text_array(
    value: object, expected: tuple[str, ...], field: str
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or tuple(value) != expected
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ValueError(f"{field} differ from the contract")
    return expected


def _finite_number(value: object, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValueError(f"{field} must be finite")
    return float(value)
