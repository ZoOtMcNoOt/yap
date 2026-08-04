"""Request-scoped speaker reconciliation across bounded Tiron epochs."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Sequence

from .contract import (
    MAX_SOURCE_TIME_EPOCH_COUNT,
    MEETING_SESSION_SPEAKER_LIMIT,
    MINIMUM_STABLE_SPEAKER_EVIDENCE_SAMPLES,
    TIRON_DECODE_SPEAKER_LIMIT,
)

DEFAULT_SPEAKER_MATCH_THRESHOLD = 0.25
DEFAULT_SPEAKER_MATCH_MARGIN = 0.05

_LOCAL_SPEAKER_ID = re.compile(r"^SPEAKER_0[0-7]$")
_MAX_EMBEDDING_DIMENSIONS = 4_096


@dataclass(frozen=True, slots=True)
class EpochSpeaker:
    local_speaker_id: str
    embedding: tuple[float, ...] | None
    clean_speech_sample_count: int


@dataclass(frozen=True, slots=True)
class EpochTurn:
    local_speaker_id: str
    start_sample: int
    end_sample: int
    text: str


@dataclass(frozen=True, slots=True)
class SpeakerEpoch:
    index: int
    start_sample: int
    end_sample: int
    speakers: tuple[EpochSpeaker, ...]
    turns: tuple[EpochTurn, ...]


@dataclass(frozen=True, slots=True)
class ReconciledSpeakerTurn:
    start_sample: int
    end_sample: int
    text: str
    session_speaker_id: str | None


@dataclass(frozen=True, slots=True)
class SpeakerEpochReconciliation:
    session_speaker_ids: tuple[str, ...]
    turns: tuple[ReconciledSpeakerTurn, ...]
    unknown_turn_count: int
    session_speaker_ceiling_reached: bool


@dataclass(slots=True)
class _SessionSpeaker:
    identifier: str
    centroid: tuple[float, ...]
    evidence_sample_count: int


def reconcile_speaker_epochs(
    epochs: Sequence[SpeakerEpoch],
    *,
    similarity_threshold: float = DEFAULT_SPEAKER_MATCH_THRESHOLD,
    runner_up_margin: float = DEFAULT_SPEAKER_MATCH_MARGIN,
    session_speaker_limit: int = MEETING_SESSION_SPEAKER_LIMIT,
) -> SpeakerEpochReconciliation:
    """Link only unambiguous speakers while enforcing epoch cannot-link rules.

    Embeddings exist only in the call inputs and private cluster state. The
    returned result contains source intervals and anonymous session IDs, never
    biometric vectors or exemplars.
    """

    _validate_policy(
        similarity_threshold=similarity_threshold,
        runner_up_margin=runner_up_margin,
        session_speaker_limit=session_speaker_limit,
    )
    validated_epochs = _validated_epochs(epochs)
    clusters: list[_SessionSpeaker] = []
    reconciled_turns: list[ReconciledSpeakerTurn] = []
    unknown_turn_count = 0
    ceiling_reached = False

    for epoch in validated_epochs:
        normalized_embeddings = {
            speaker.local_speaker_id: _normalized_embedding(speaker.embedding)
            if speaker.embedding is not None
            and speaker.clean_speech_sample_count
            >= MINIMUM_STABLE_SPEAKER_EVIDENCE_SAMPLES
            else None
            for speaker in epoch.speakers
        }
        speaker_by_id = {
            speaker.local_speaker_id: speaker for speaker in epoch.speakers
        }
        proposed_matches: list[tuple[float, str, int]] = []
        for speaker in epoch.speakers:
            embedding = normalized_embeddings[speaker.local_speaker_id]
            if embedding is None or not clusters:
                continue
            similarities = sorted(
                (
                    (_cosine_similarity(embedding, cluster.centroid), index)
                    for index, cluster in enumerate(clusters)
                ),
                key=lambda item: (-item[0], item[1]),
            )
            best_score, best_index = similarities[0]
            runner_up = similarities[1][0] if len(similarities) > 1 else -1.0
            if (
                best_score >= similarity_threshold
                and best_score - runner_up >= runner_up_margin
            ):
                proposed_matches.append(
                    (best_score, speaker.local_speaker_id, best_index)
                )

        # A Tiron local label is a cannot-link witness inside its epoch. When
        # two labels select the same session cluster, only the stronger match
        # may reuse it; the other label remains independent or Unknown.
        epoch_assignments: dict[str, int | None] = {}
        used_cluster_indexes: set[int] = set()
        new_cluster_indexes: set[int] = set()
        for _score, local_id, cluster_index in sorted(
            proposed_matches,
            key=lambda item: (-item[0], item[1], item[2]),
        ):
            if cluster_index not in used_cluster_indexes:
                epoch_assignments[local_id] = cluster_index
                used_cluster_indexes.add(cluster_index)

        for speaker in epoch.speakers:
            local_id = speaker.local_speaker_id
            if local_id in epoch_assignments:
                continue
            if len(clusters) < session_speaker_limit:
                embedding = normalized_embeddings[local_id]
                if embedding is None:
                    epoch_assignments[local_id] = None
                    continue
                cluster_index = len(clusters)
                clusters.append(
                    _SessionSpeaker(
                        identifier=f"speaker-{cluster_index + 1}",
                        centroid=embedding,
                        evidence_sample_count=speaker.clean_speech_sample_count,
                    )
                )
                if len(clusters) == session_speaker_limit:
                    ceiling_reached = True
                epoch_assignments[local_id] = cluster_index
                used_cluster_indexes.add(cluster_index)
                new_cluster_indexes.add(cluster_index)
            else:
                epoch_assignments[local_id] = None
                ceiling_reached = True

        for local_id, cluster_index in epoch_assignments.items():
            if cluster_index is None or cluster_index >= len(clusters):
                continue
            speaker = speaker_by_id[local_id]
            embedding = normalized_embeddings[local_id]
            cluster = clusters[cluster_index]
            if embedding is not None and cluster_index not in new_cluster_indexes:
                _update_centroid(cluster, embedding, speaker.clean_speech_sample_count)

        for turn in epoch.turns:
            cluster_index = epoch_assignments[turn.local_speaker_id]
            session_speaker_id = (
                clusters[cluster_index].identifier
                if cluster_index is not None
                else None
            )
            if session_speaker_id is None:
                unknown_turn_count += 1
            reconciled_turns.append(
                ReconciledSpeakerTurn(
                    start_sample=turn.start_sample,
                    end_sample=turn.end_sample,
                    text=turn.text,
                    session_speaker_id=session_speaker_id,
                )
            )

    return SpeakerEpochReconciliation(
        session_speaker_ids=tuple(cluster.identifier for cluster in clusters),
        turns=tuple(reconciled_turns),
        unknown_turn_count=unknown_turn_count,
        session_speaker_ceiling_reached=ceiling_reached,
    )


def _validate_policy(
    *,
    similarity_threshold: float,
    runner_up_margin: float,
    session_speaker_limit: int,
) -> None:
    if (
        not isinstance(similarity_threshold, (int, float))
        or isinstance(similarity_threshold, bool)
        or not math.isfinite(similarity_threshold)
        or not -1.0 <= similarity_threshold <= 1.0
    ):
        raise ValueError("speaker similarity threshold is invalid")
    if (
        not isinstance(runner_up_margin, (int, float))
        or isinstance(runner_up_margin, bool)
        or not math.isfinite(runner_up_margin)
        or not 0.0 <= runner_up_margin <= 2.0
    ):
        raise ValueError("speaker runner-up margin is invalid")
    if (
        not isinstance(session_speaker_limit, int)
        or isinstance(session_speaker_limit, bool)
        or not 1 <= session_speaker_limit <= MEETING_SESSION_SPEAKER_LIMIT
    ):
        raise ValueError("meeting session speaker limit is invalid")


def _validated_epochs(epochs: Sequence[SpeakerEpoch]) -> tuple[SpeakerEpoch, ...]:
    if (
        not isinstance(epochs, Sequence)
        or isinstance(epochs, (str, bytes, bytearray))
        or len(epochs) > MAX_SOURCE_TIME_EPOCH_COUNT
    ):
        raise ValueError("speaker epochs exceed the bounded contract")
    result = tuple(epochs)
    previous_end = 0
    embedding_dimensions: int | None = None
    for expected_index, epoch in enumerate(result):
        if not isinstance(epoch, SpeakerEpoch) or epoch.index != expected_index:
            raise ValueError("speaker epoch identity is invalid")
        if (
            not isinstance(epoch.start_sample, int)
            or isinstance(epoch.start_sample, bool)
            or not isinstance(epoch.end_sample, int)
            or isinstance(epoch.end_sample, bool)
            or epoch.start_sample < previous_end
            or epoch.end_sample <= epoch.start_sample
        ):
            raise ValueError("speaker epoch bounds are invalid")
        if len(epoch.speakers) > TIRON_DECODE_SPEAKER_LIMIT:
            raise ValueError("speaker epoch roster is invalid")
        local_ids = [speaker.local_speaker_id for speaker in epoch.speakers]
        if len(set(local_ids)) != len(local_ids) or any(
            _LOCAL_SPEAKER_ID.fullmatch(value) is None for value in local_ids
        ):
            raise ValueError("speaker epoch local identities are invalid")
        for speaker in epoch.speakers:
            if (
                not isinstance(speaker.clean_speech_sample_count, int)
                or isinstance(speaker.clean_speech_sample_count, bool)
                or not 0
                <= speaker.clean_speech_sample_count
                <= epoch.end_sample - epoch.start_sample
            ):
                raise ValueError("speaker epoch clean-speech evidence is invalid")
            if speaker.embedding is not None:
                normalized = _normalized_embedding(speaker.embedding)
                if embedding_dimensions is None:
                    embedding_dimensions = len(normalized)
                elif len(normalized) != embedding_dimensions:
                    raise ValueError("speaker embedding dimensions differ")
        previous_turn_start = epoch.start_sample
        for turn_index, turn in enumerate(epoch.turns):
            if (
                not isinstance(turn, EpochTurn)
                or turn.local_speaker_id not in local_ids
                or turn.start_sample < epoch.start_sample
                or (turn_index > 0 and turn.start_sample < previous_turn_start)
                or turn.end_sample <= turn.start_sample
                or turn.end_sample > epoch.end_sample
                or not turn.text
                or " ".join(turn.text.split()) != turn.text
            ):
                raise ValueError("speaker epoch turn is invalid")
            previous_turn_start = turn.start_sample
        previous_end = epoch.end_sample
    return result


def _normalized_embedding(value: Sequence[float]) -> tuple[float, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not 1 <= len(value) <= _MAX_EMBEDDING_DIMENSIONS
    ):
        raise ValueError("speaker embedding is invalid")
    vector: list[float] = []
    for component in value:
        if (
            not isinstance(component, (int, float))
            or isinstance(component, bool)
            or not math.isfinite(component)
        ):
            raise ValueError("speaker embedding is invalid")
        vector.append(float(component))
    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude <= 1e-12:
        raise ValueError("speaker embedding magnitude is invalid")
    return tuple(component / magnitude for component in vector)


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("speaker embedding dimensions differ")
    return sum(a * b for a, b in zip(left, right, strict=True))


def _update_centroid(
    cluster: _SessionSpeaker,
    embedding: tuple[float, ...],
    evidence_sample_count: int,
) -> None:
    if evidence_sample_count <= 0:
        return
    previous_weight = cluster.evidence_sample_count
    combined_weight = previous_weight + evidence_sample_count
    combined = tuple(
        (old_value * previous_weight + new_value * evidence_sample_count)
        / combined_weight
        for old_value, new_value in zip(cluster.centroid, embedding, strict=True)
    )
    cluster.centroid = _normalized_embedding(combined)
    cluster.evidence_sample_count = combined_weight
