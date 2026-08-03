"""Strict provenance and shape lock for the AMI long-meeting comparator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re

from yap_server.json_contract import (
    exact_object as _object,
    https_uri as _https,
    positive_int as _positive_int,
    sha256 as _sha256,
)
from yap_server.private_artifact import (
    read_json_object_with_identity,
)
from yap_server.language_tags import canonical_bcp47


MAX_ANNOTATION_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_AUDIO_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 6_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 1024 * 1024
MAX_TRANSCRIPT_XML_BYTES = 256 * 1024
NITE_NAMESPACE = "http://nite.sourceforge.net/"
NITE_ROOT = f"{{{NITE_NAMESPACE}}}root"
FLAT_ORDERING_POLICY = "start-end-agent-source-ordinal-v1"
EVENT_NAMES = frozenset({"vocalsound", "disfmarker", "gap"})

_MAX_LOCK_BYTES = 128 * 1024
_TIMING_KIND = "manual-word-plus-forced-alignment"
_LIMITATIONS = (
    "pre-existing-public-comparator",
    "upstream-transcript-known-defects-require-review",
    "upstream-timings-include-forced-alignment",
    "overlap-has-no-unique-flat-word-order",
    "speaker-attribution-not-scored-in-phase-6",
)
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_RELEASE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,2}$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


@dataclass(frozen=True, slots=True)
class AmiArtifactLock:
    cache_path: str
    download_source: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class AmiMeetingIdentity:
    corpus_id: str
    release: str
    meeting_id: str
    language_bcp47: str
    scenario_split: str
    asr_split: str
    source: str


@dataclass(frozen=True, slots=True)
class AmiUsagePolicy:
    promotion_eligible: bool
    exposure_status: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AmiLicenseLock:
    identifier: str
    declaration_source: str
    legal_code_source: str
    legal_code_sha256: str


@dataclass(frozen=True, slots=True)
class AmiTranscriptMemberLock:
    agent_id: str
    archive_path: str
    size: int
    word_element_count: int
    vocal_sound_count: int
    disfluency_marker_count: int
    gap_count: int


@dataclass(frozen=True, slots=True)
class AmiAnnotationArchiveLock:
    artifact: AmiArtifactLock
    member_count: int
    uncompressed_bytes: int
    namespace: str
    timing_kind: str
    flat_ordering_policy: str
    transcript_members: tuple[AmiTranscriptMemberLock, ...]


@dataclass(frozen=True, slots=True)
class AmiAudioConditionLock:
    identifier: str
    capture: str
    artifact: AmiArtifactLock


@dataclass(frozen=True, slots=True)
class AmiAudioSetLock:
    sample_rate_hz: int
    channel_count: int
    sample_width_bytes: int
    frame_count: int
    conditions: tuple[AmiAudioConditionLock, ...]


@dataclass(frozen=True, slots=True)
class AmiMeetingCorpusLock:
    identity: AmiMeetingIdentity
    usage: AmiUsagePolicy
    license: AmiLicenseLock
    annotations: AmiAnnotationArchiveLock
    audio: AmiAudioSetLock


def load_ami_meeting_corpus_lock(path: Path) -> AmiMeetingCorpusLock:
    root, _identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAX_LOCK_BYTES,
        field="AMI meeting corpus lock",
    )
    root = _object(
        root,
        {
            "schemaVersion",
            "corpus",
            "purpose",
            "license",
            "annotations",
            "transcript",
            "audio",
            "limitations",
        },
        "AMI meeting corpus lock",
    )
    if root["schemaVersion"] != 1:
        raise ValueError("unsupported AMI meeting corpus-lock schema")

    identity = _meeting_identity(root["corpus"])
    usage = _usage_policy(root["purpose"], root["limitations"])
    license_lock = _license_lock(root["license"])
    annotations = _annotation_archive_lock(
        root["annotations"],
        root["transcript"],
        release=identity.release,
    )
    audio = _audio_set_lock(root["audio"], release=identity.release)
    return AmiMeetingCorpusLock(
        identity=identity,
        usage=usage,
        license=license_lock,
        annotations=annotations,
        audio=audio,
    )


def _meeting_identity(value: object) -> AmiMeetingIdentity:
    corpus = _object(
        value,
        {
            "id",
            "release",
            "meetingId",
            "languageBcp47",
            "scenarioSplit",
            "asrSplit",
            "source",
        },
        "AMI corpus",
    )
    identity = AmiMeetingIdentity(
        corpus_id=_text(corpus["id"], "AMI corpus ID", 64),
        release=_matching_text(corpus["release"], _RELEASE, "AMI release"),
        meeting_id=_text(corpus["meetingId"], "AMI meeting ID", 32),
        language_bcp47=canonical_bcp47(corpus["languageBcp47"], "AMI languageBcp47"),
        scenario_split=_text(corpus["scenarioSplit"], "AMI scenario split", 64),
        asr_split=_text(corpus["asrSplit"], "AMI ASR split", 64),
        source=_https(corpus["source"], "AMI corpus source"),
    )
    if identity != AmiMeetingIdentity(
        corpus_id="ami-meeting-corpus",
        release="1.6.2",
        meeting_id="ES2004a",
        language_bcp47="en",
        scenario_split="unseen-evaluation",
        asr_split="full-corpus-asr-eval",
        source="https://groups.inf.ed.ac.uk/ami/corpus/datasets.shtml",
    ):
        raise ValueError("AMI corpus identity differs from the comparator contract")
    return identity


def _usage_policy(purpose_value: object, limitations_value: object) -> AmiUsagePolicy:
    purpose = _object(
        purpose_value,
        {"promotionEligible", "exposureStatus"},
        "AMI comparator purpose",
    )
    if (
        purpose["promotionEligible"] is not False
        or purpose["exposureStatus"] != "unknown"
    ):
        raise ValueError(
            "AMI comparator must remain non-promotional with unknown exposure"
        )
    limitations = tuple(
        _text(item, "AMI limitation", 96)
        for item in _array(limitations_value, "AMI limitations")
    )
    if limitations != _LIMITATIONS:
        raise ValueError("AMI limitations differ from the comparator contract")
    return AmiUsagePolicy(
        promotion_eligible=False,
        exposure_status="unknown",
        limitations=limitations,
    )


def _license_lock(value: object) -> AmiLicenseLock:
    license_value = _object(
        value,
        {"id", "declarationSource", "legalCodeSource", "legalCodeSha256"},
        "AMI license",
    )
    identifier = _text(license_value["id"], "AMI license ID", 32)
    if identifier != "CC-BY-4.0":
        raise ValueError("AMI license is unsupported")
    return AmiLicenseLock(
        identifier=identifier,
        declaration_source=_https(
            license_value["declarationSource"], "AMI license declaration source"
        ),
        legal_code_source=_https(
            license_value["legalCodeSource"], "AMI license legal-code source"
        ),
        legal_code_sha256=_sha256(
            license_value["legalCodeSha256"], "AMI legal-code SHA-256"
        ),
    )


def _annotation_archive_lock(
    annotations_value: object,
    transcript_value: object,
    *,
    release: str,
) -> AmiAnnotationArchiveLock:
    annotations = _object(
        annotations_value,
        {"artifact", "memberCount", "uncompressedBytes"},
        "AMI annotations",
    )
    artifact = _artifact_lock(
        annotations["artifact"],
        "AMI annotation archive",
        maximum_bytes=MAX_ANNOTATION_ARCHIVE_BYTES,
    )
    expected_path = f"corpora/ami/{release}/ami_public_manual_{release}.zip"
    expected_source = (
        "https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/"
        f"ami_public_manual_{release}.zip"
    )
    if (
        artifact.cache_path != expected_path
        or artifact.download_source != expected_source
    ):
        raise ValueError("AMI annotation artifact differs from the exact release")

    transcript = _object(
        transcript_value,
        {"namespace", "timing", "flatOrderingPolicy", "members"},
        "AMI transcript",
    )
    if transcript["namespace"] != NITE_NAMESPACE:
        raise ValueError("AMI transcript namespace is unsupported")
    timing_kind = _text(transcript["timing"], "AMI timing kind", 64)
    ordering_policy = _text(
        transcript["flatOrderingPolicy"], "AMI flat ordering policy", 64
    )
    if timing_kind != _TIMING_KIND or ordering_policy != FLAT_ORDERING_POLICY:
        raise ValueError("AMI transcript policy differs from the comparator contract")
    members = tuple(
        _transcript_member_lock(item)
        for item in _array(transcript["members"], "AMI transcript members")
    )
    if tuple(member.agent_id for member in members) != tuple("ABCD"):
        raise ValueError("AMI transcript members must bind agents A through D")
    return AmiAnnotationArchiveLock(
        artifact=artifact,
        member_count=_bounded_positive_int(
            annotations["memberCount"],
            "AMI annotation member count",
            MAX_ARCHIVE_MEMBERS,
        ),
        uncompressed_bytes=_bounded_positive_int(
            annotations["uncompressedBytes"],
            "AMI annotation uncompressed size",
            MAX_ARCHIVE_UNCOMPRESSED_BYTES,
        ),
        namespace=NITE_NAMESPACE,
        timing_kind=timing_kind,
        flat_ordering_policy=ordering_policy,
        transcript_members=members,
    )


def _audio_set_lock(value: object, *, release: str) -> AmiAudioSetLock:
    audio = _object(
        value,
        {
            "sampleRateHz",
            "channelCount",
            "sampleWidthBytes",
            "frameCount",
            "conditions",
        },
        "AMI audio",
    )
    result = AmiAudioSetLock(
        sample_rate_hz=_positive_int(audio["sampleRateHz"], "AMI sample rate"),
        channel_count=_positive_int(audio["channelCount"], "AMI channel count"),
        sample_width_bytes=_positive_int(audio["sampleWidthBytes"], "AMI sample width"),
        frame_count=_bounded_positive_int(
            audio["frameCount"],
            "AMI frame count",
            16_000 * 4 * 60 * 60,
        ),
        conditions=tuple(
            _audio_condition_lock(item)
            for item in _array(audio["conditions"], "AMI audio conditions")
        ),
    )
    if (result.sample_rate_hz, result.channel_count, result.sample_width_bytes) != (
        16_000,
        1,
        2,
    ):
        raise ValueError("AMI comparator audio must be mono 16 kHz PCM16")
    expected_conditions = (
        ("close-mix", "mixed-close-talking-headsets"),
        ("far-field-array1-channel1", "single-distant-array-channel"),
    )
    if (
        tuple((item.identifier, item.capture) for item in result.conditions)
        != expected_conditions
    ):
        raise ValueError("AMI audio conditions differ from the comparator contract")
    _validate_audio_artifact_paths(result.conditions, release=release)
    return result


def _validate_audio_artifact_paths(
    conditions: tuple[AmiAudioConditionLock, ...],
    *,
    release: str,
) -> None:
    expected = (
        (
            f"corpora/ami/{release}/ES2004a.Mix-Headset.wav",
            "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/"
            "HeadsetAudio/ES2004a.Mix-Headset.wav",
        ),
        (
            f"corpora/ami/{release}/ES2004a.Array1-01.wav",
            "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/"
            "ES2004a/audio/ES2004a.Array1-01.wav",
        ),
    )
    actual = tuple(
        (condition.artifact.cache_path, condition.artifact.download_source)
        for condition in conditions
    )
    if actual != expected:
        raise ValueError("AMI audio artifacts differ from the exact release")


def _artifact_lock(value: object, field: str, *, maximum_bytes: int) -> AmiArtifactLock:
    artifact = _object(
        value,
        {"cachePath", "downloadSource", "size", "sha256"},
        field,
    )
    return AmiArtifactLock(
        cache_path=_portable_cache_path(artifact["cachePath"], f"{field} cache path"),
        download_source=_https(artifact["downloadSource"], f"{field} source"),
        size=_bounded_positive_int(artifact["size"], f"{field} size", maximum_bytes),
        sha256=_sha256(artifact["sha256"], f"{field} SHA-256"),
    )


def _transcript_member_lock(value: object) -> AmiTranscriptMemberLock:
    member = _object(
        value,
        {"agentId", "archivePath", "size", "counts"},
        "AMI transcript member",
    )
    agent_id = _text(member["agentId"], "AMI transcript agent", 1)
    archive_path = _portable_cache_path(
        member["archivePath"], "AMI transcript archive path"
    )
    if archive_path != f"words/ES2004a.{agent_id}.words.xml":
        raise ValueError("AMI transcript archive path is invalid")
    counts = _object(
        member["counts"],
        {"w", "vocalsound", "disfmarker", "gap"},
        "AMI transcript counts",
    )
    return AmiTranscriptMemberLock(
        agent_id=agent_id,
        archive_path=archive_path,
        size=_bounded_positive_int(
            member["size"], "AMI transcript member size", MAX_TRANSCRIPT_XML_BYTES
        ),
        word_element_count=_positive_int(counts["w"], "AMI word-element count"),
        vocal_sound_count=_nonnegative_int(
            counts["vocalsound"], "AMI vocal-sound count"
        ),
        disfluency_marker_count=_nonnegative_int(
            counts["disfmarker"], "AMI disfluency-marker count"
        ),
        gap_count=_nonnegative_int(counts["gap"], "AMI gap count"),
    )


def _audio_condition_lock(value: object) -> AmiAudioConditionLock:
    condition = _object(
        value,
        {"id", "capture", "artifact"},
        "AMI audio condition",
    )
    return AmiAudioConditionLock(
        identifier=_matching_text(
            condition["id"], _SAFE_IDENTIFIER, "AMI condition ID"
        ),
        capture=_matching_text(
            condition["capture"], _SAFE_IDENTIFIER, "AMI capture kind"
        ),
        artifact=_artifact_lock(
            condition["artifact"],
            "AMI audio artifact",
            maximum_bytes=MAX_AUDIO_BYTES,
        ),
    )


def _portable_cache_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError(f"{field} is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value:
        raise ValueError(f"{field} is invalid")
    for segment in path.parts:
        if (
            _SAFE_SEGMENT.fullmatch(segment) is None
            or segment.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
        ):
            raise ValueError(f"{field} is invalid")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{field} must be bounded text")
    return value


def _matching_text(value: object, pattern: re.Pattern[str], field: str) -> str:
    text = _text(value, field, 128)
    if pattern.fullmatch(text) is None:
        raise ValueError(f"{field} is invalid")
    return text


def _bounded_positive_int(value: object, field: str, maximum: int) -> int:
    parsed = _positive_int(value, field)
    if parsed > maximum:
        raise ValueError(f"{field} exceeds the bound")
    return parsed


def _nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value
