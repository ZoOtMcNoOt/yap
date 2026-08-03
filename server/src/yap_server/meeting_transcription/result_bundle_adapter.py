from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from yap_server.jobs.contract_values import mapping
from yap_server.jobs.result_bundle import ResultRevisionBundle
from yap_server.jobs.stage_attempts import canonical_json_sha256
from yap_server.pools.batch_contract import (
    AsrRouteDecision,
    validate_fixed_batch_route_language,
)

from .contract import (
    MEETING_TRANSCRIPTION_POOL_ID,
    validate_meeting_transcription_route,
    validate_meeting_transcription_route_identity,
)
from .result_revisions import (
    MeetingResultAuthority,
    MeetingResultContext,
    build_meeting_result_revisions,
    validate_persisted_speaker_result_revision,
)


@dataclass(frozen=True, slots=True)
class MeetingResultBundleAdapter:
    authority: MeetingResultAuthority

    @property
    def pool_id(self) -> str:
        return MEETING_TRANSCRIPTION_POOL_ID

    @property
    def requires_speaker_result(self) -> bool:
        return True

    def build_result_bundle(
        self,
        worker_result: Mapping[str, object],
        *,
        projection: Mapping[str, object],
        creation: Mapping[str, object],
        route: AsrRouteDecision,
        created_at_utc: str,
        language_bcp47: str,
        maximum_end_ms: int,
    ) -> ResultRevisionBundle:
        self._validate_publication_route(route, language_bcp47)
        context = MeetingResultContext.from_job(
            projection=projection,
            creation=creation,
            created_at_utc=created_at_utc,
            language_bcp47=language_bcp47,
            provider_language=route.provider_language,
            maximum_end_ms=maximum_end_ms,
        )
        transcript_result, speaker_result = build_meeting_result_revisions(
            worker_result,
            context=context,
            authority=self.authority,
        )
        return ResultRevisionBundle(
            transcript_result=transcript_result,
            speaker_result=speaker_result,
            created_at_utc=created_at_utc,
            worker_output_sha256=canonical_json_sha256(
                {
                    "captureManifestSha256": context.capture_manifest_sha256,
                    "model": worker_result.get("model"),
                    "audio": worker_result.get("audio"),
                    "meeting": worker_result.get("meeting"),
                }
            ),
            result_shape="joint_speaker_transcript_v1",
        )

    def validate_persisted_result_bundle(
        self,
        transcript_result: Mapping[str, object],
        speaker_result: Mapping[str, object] | None,
        *,
        projection: Mapping[str, object],
        creation: Mapping[str, object],
        route: AsrRouteDecision,
        maximum_end_ms: int,
    ) -> None:
        if speaker_result is None:
            raise ValueError("persisted meeting result omitted its speaker companion")
        language = mapping(
            transcript_result.get("language"),
            "meeting result language",
        )
        language_bcp47 = language.get("languageBcp47")
        if not isinstance(language_bcp47, str):
            raise ValueError("meeting result language is invalid")
        self._validate_persisted_route(route, creation, language_bcp47)
        context = MeetingResultContext.from_job(
            projection=projection,
            creation=creation,
            created_at_utc=str(transcript_result.get("createdAtUtc")),
            language_bcp47=language_bcp47,
            provider_language=route.provider_language,
            maximum_end_ms=maximum_end_ms,
        )
        validate_persisted_speaker_result_revision(
            speaker_result,
            transcript_result=transcript_result,
            context=context,
            route_model_revision=route.model_revision,
        )

    def _validate_publication_route(
        self,
        route: AsrRouteDecision,
        language_bcp47: str,
    ) -> None:
        validate_meeting_transcription_route(
            route,
            model_revision=self.authority.provenance.model.revision,
            has_utterance_plan=False,
        )
        if language_bcp47 == "und":
            raise ValueError("meeting result language must be fixed")

    @staticmethod
    def _validate_persisted_route(
        route: AsrRouteDecision,
        creation: Mapping[str, object],
        language_bcp47: str,
    ) -> None:
        validate_meeting_transcription_route_identity(
            route,
            has_utterance_plan=False,
        )
        if language_bcp47 == "und":
            raise ValueError("meeting result language must be fixed")
        validate_fixed_batch_route_language(route, language_bcp47)
        decision = mapping(
            creation.get("languageDecision"),
            "persisted meeting language decision",
        )
        if decision.get("languageBcp47") != language_bcp47:
            raise ValueError(
                "persisted meeting result language differs from the frozen job"
            )
