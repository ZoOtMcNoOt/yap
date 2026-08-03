from __future__ import annotations

from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yap_server.jobs import JobServiceError, RecordingJobService
from yap_server.jobs.result_contract import validate_result_revision
from yap_server.language_span_contract import (
    ServerUtteranceLanguageObservation,
    build_server_language_span_evidence,
)
from yap_server.pools.batch_contract import AsrRouteDecision
from yap_server.pools.pcm_audio import MAX_AUDIO_SECONDS, SAMPLE_RATE_HZ

from .service_fixtures import (
    _Processor,
    _create_request,
    _published_result,
)


class RecordingJobContractTests(unittest.TestCase):
    def test_intake_duration_limit_matches_the_isolated_worker(self) -> None:
        from yap_server.jobs.contract_values import MAX_JOB_PCM_BYTES

        self.assertEqual(
            MAX_JOB_PCM_BYTES,
            SAMPLE_RATE_HZ * 2 * MAX_AUDIO_SECONDS,
        )

    def test_meeting_intake_requires_finite_retention_after_capture_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:00:00Z",
            )

            for retention in (
                None,
                "2026-07-14T20:59:59Z",
                "2026-08-13T21:00:01Z",
            ):
                with self.subTest(retention=retention):
                    with self.assertRaises(JobServiceError) as invalid:
                        service.create(
                            _create_request(retention_expires_at_utc=retention)
                        )
                    self.assertEqual(invalid.exception.status, 400)
                    self.assertEqual(invalid.exception.code, "INVALID_JOB")

    def test_intake_rejects_retention_that_is_already_expired_by_server_time(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-15T21:00:00Z",
            )

            with self.assertRaises(JobServiceError) as invalid:
                service.create(
                    _create_request(retention_expires_at_utc="2026-07-15T20:59:59Z")
                )

            self.assertEqual(invalid.exception.status, 400)
            self.assertEqual(invalid.exception.code, "INVALID_JOB")

    def test_intake_rejects_a_sequence_range_that_does_not_cover_the_pcm_frames(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:00:00Z",
            )
            request = _create_request()
            request["chunks"][0]["replayKey"]["sequenceEnd"] = 0

            with self.assertRaises(JobServiceError) as invalid:
                service.create(request)

            self.assertEqual(invalid.exception.status, 400)
            self.assertEqual(invalid.exception.code, "INVALID_JOB")

    def test_intake_rejects_an_obsolete_replay_key_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:00:00Z",
            )
            request = _create_request()
            request["chunks"][0]["replayKey"]["schemaVersion"] = 2

            with self.assertRaises(JobServiceError) as invalid:
                service.create(request)

            self.assertEqual(invalid.exception.status, 400)
            self.assertEqual(invalid.exception.code, "INVALID_JOB")

    def test_intake_rejects_session_shapes_outside_the_imported_meeting_slice(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:00:00Z",
            )

            for field, value in (("mode", "dictation"), ("origin", "live_capture")):
                with self.subTest(field=field, value=value):
                    request = _create_request()
                    request["metadata"][field] = value
                    with self.assertRaises(JobServiceError) as invalid:
                        service.create(request)
                    self.assertEqual(invalid.exception.status, 400)
                    self.assertEqual(invalid.exception.code, "INVALID_JOB")

    def test_intake_requires_chunk_sequences_to_begin_at_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:00:00Z",
            )
            request = _create_request()
            request["chunks"][0]["replayKey"]["sequenceStart"] = 1
            request["chunks"][0]["replayKey"]["sequenceEnd"] = 160

            with self.assertRaises(JobServiceError) as invalid:
                service.create(request)

            self.assertEqual(invalid.exception.status, 400)
            self.assertEqual(invalid.exception.code, "INVALID_JOB")

    def test_intake_freezes_one_consistent_language_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_Processor(),
                supported_languages=("en", "fr"),
                now=lambda: "2026-07-14T21:00:00Z",
            )

            request = _create_request()
            request["languageDecision"] = {
                "mode": "fixed",
                "languageBcp47": "fr-FR",
                "disposition": "manualOverride",
            }
            request["metadata"]["localeHintBcp47"] = "fr-FR"
            request["metadata"]["preferredLanguagesBcp47"] = ["fr-FR"]
            created = service.create(request)
            self.assertEqual(created["status"], "accepted")

            for mutation in (
                {"languageBcp47": "fr-FR"},
                {
                    "mode": "dynamic",
                    "languageBcp47": None,
                    "disposition": "explicitDynamic",
                },
                {"disposition": "legacyImplicitEnglishDefault"},
            ):
                with self.subTest(mutation=mutation):
                    invalid_request = _create_request()
                    invalid_request["languageDecision"].update(mutation)
                    with self.assertRaises(JobServiceError) as invalid:
                        service.create(invalid_request)
                    self.assertEqual(invalid.exception.code, "INVALID_JOB")

    def test_explicit_dynamic_intake_freezes_undetermined_catalog_route(self) -> None:
        class DynamicProcessor(_Processor):
            def resolve_route(self, language_bcp47: str) -> AsrRouteDecision:
                if language_bcp47 != "und":
                    raise AssertionError("dynamic intake lost the undetermined locale")
                return AsrRouteDecision(
                    provider_id="nemotron",
                    pool_id="nemotron-batch",
                    execution_mode="dynamicBatch",
                    model_revision="d" * 40,
                    provider_language="auto",
                )

        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=DynamicProcessor(),
                supported_languages=("und",),
                now=lambda: "2026-07-14T21:00:00Z",
            )
            request = _create_request()
            request["languageDecision"] = {
                "mode": "dynamic",
                "languageBcp47": None,
                "disposition": "explicitDynamic",
            }
            request["metadata"]["localeHintBcp47"] = "und"
            request["metadata"]["preferredLanguagesBcp47"] = ["und"]

            created = service.create(request)
            routing = service._state.asr_routing[created["jobId"]]

        self.assertIsNotNone(routing)
        assert routing is not None
        self.assertEqual(routing.route.execution_mode, "dynamicBatch")
        self.assertEqual(routing.route.provider_language, "auto")

    def test_dynamic_result_segments_are_lossless_and_never_use_primary_fallback(
        self,
    ) -> None:
        projection = {
            "sessionId": "s-dynamic",
            "captureManifest": {"sha256": "a" * 64},
        }
        segments: list[dict[str, object]] = [
            {
                "index": 0,
                "sourceSpanIndex": 0,
                "text": "hello",
                "status": "detected",
                "languageBcp47": "en-US",
                "rawLanguageTag": "en-US",
                "reason": None,
            },
            {
                "index": 1,
                "sourceSpanIndex": 0,
                "text": "bonjour",
                "status": "unknown",
                "languageBcp47": None,
                "rawLanguageTag": "el-GR",
                "reason": "DISABLED_LANGUAGE_TAG",
            },
        ]
        result = {
            "sessionId": "s-dynamic",
            "revision": 1,
            "authority": "server_authoritative",
            "createdAtUtc": "2026-07-17T21:00:00Z",
            "captureManifestSha256": "a" * 64,
            "previousResultSha256": None,
            "status": "complete",
            "language": {"languageBcp47": "und", "confidence": None},
            "transcript": "hello bonjour",
            "languageSegments": segments,
            "languageSpanEvidence": build_server_language_span_evidence(
                source_end_sample=160,
                provider_id="nemotron",
                pool_id="nemotron-batch",
                model_id="nvidia/nemotron-3.5-asr-streaming-0.6b",
                model_revision="f3d333391852ba876df169dcc9ba902d25b6ab0b",
                utterance_plan_sha256="e" * 64,
                utterances=(
                    ServerUtteranceLanguageObservation(
                        start_sample=0,
                        end_sample=160,
                        language_segments=segments,
                    ),
                ),
            ),
            "alignment": {
                "status": "unavailable",
                "reason": "ALIGNMENT_RUNTIME_FAILED",
                "componentRevision": "cohere-attention-alignment-candidate-v1",
            },
            "alignedWords": [],
            "modelProvenance": [
                {
                    "modelId": "nvidia/nemotron-3.5-asr-streaming-0.6b",
                    "revision": "f3d333391852ba876df169dcc9ba902d25b6ab0b",
                    "calibrationRevision": "asr-not-applicable",
                }
            ],
        }

        validate_result_revision(result, projection)
        result["languageSegments"][1]["languageBcp47"] = "en-US"
        with self.assertRaisesRegex(ValueError, "language segments"):
            validate_result_revision(result, projection)

    def test_current_alignment_is_bounded_by_the_exact_capture_duration(self) -> None:
        projection = {
            "sessionId": "s-alignment",
            "captureManifest": {"sha256": "a" * 64},
        }
        result = {
            "sessionId": "s-alignment",
            "revision": 1,
            "authority": "server_authoritative",
            "createdAtUtc": "2026-07-18T15:00:00Z",
            "captureManifestSha256": "a" * 64,
            "previousResultSha256": None,
            "status": "complete",
            "language": {"languageBcp47": "en", "confidence": None},
            "transcript": "hello",
            "alignment": {
                "status": "available",
                "reason": None,
                "componentRevision": "cohere-attention-en-v1",
            },
            "alignedWords": [
                {
                    "wordIndex": 0,
                    "text": "hello",
                    "startMs": 0,
                    "endMs": 10,
                    "turnId": None,
                    "attribution": {"kind": "unknown"},
                    "confidence": None,
                }
            ],
            "modelProvenance": [
                {
                    "modelId": "private-asr",
                    "revision": "revision-1",
                    "calibrationRevision": "asr-not-applicable",
                }
            ],
        }

        validate_result_revision(result, projection, maximum_end_ms=10)
        result["alignedWords"][0]["endMs"] = 11
        with self.assertRaisesRegex(ValueError, "aligned word content"):
            validate_result_revision(result, projection, maximum_end_ms=10)

    def test_intake_rejects_the_obsolete_schema_one_request_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:00:00Z",
            )
            request = _create_request()
            request["captureManifest"]["schemaVersion"] = 1
            del request["languageDecision"]
            del request["asrCatalogRevision"]
            del request["preprocessingEvidence"]

            with self.assertRaises(JobServiceError) as rejected:
                service.create(request, idempotency_key="schema-one-default")
            self.assertEqual(rejected.exception.code, "INVALID_JOB")

    def test_preprocessing_evidence_is_validated_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = _create_request()
            service = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:00:00Z",
            )

            created = service.create(request, idempotency_key="route-evidence-v1")
            state_path = root / "jobs" / created["jobId"] / "state.json"
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["creation"]["preprocessingEvidence"],
                request["preprocessingEvidence"],
            )
            self.assertEqual(
                persisted["asrRouting"]["asrCatalogRevision"],
                request["asrCatalogRevision"],
            )

            restarted = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:01:00Z",
            )
            self.assertEqual(
                restarted.create(request, idempotency_key="route-evidence-v1"),
                created,
            )

            class RotatedCatalogProcessor(_Processor):
                @property
                def asr_catalog_revision(self) -> str:
                    return "d" * 64

            rotated = RecordingJobService(
                root,
                processor=RotatedCatalogProcessor(),
                supported_languages=("fr",),
                now=lambda: "2026-07-14T21:01:30Z",
            )
            self.assertEqual(
                rotated.create(request, idempotency_key="route-evidence-v1"),
                created,
            )
            with self.assertRaises(JobServiceError) as stale_new_admission:
                rotated.create(request, idempotency_key="rotated-route-evidence-v1")
            self.assertEqual(stale_new_admission.exception.status, 400)
            self.assertEqual(stale_new_admission.exception.code, "INVALID_JOB")

            persisted["asrRouting"]["asrCatalogRevision"] = "d" * 64
            state_path.write_text(json.dumps(persisted), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "catalog revision differs"):
                RecordingJobService(
                    root,
                    processor=_Processor(),
                    supported_languages=("en",),
                    now=lambda: "2026-07-14T21:02:00Z",
                )

    def test_current_manifest_and_preprocessing_evidence_are_one_contract(self) -> None:
        invalid_requests: list[dict[str, object]] = []

        schema_two_without_evidence = _create_request()
        del schema_two_without_evidence["preprocessingEvidence"]
        invalid_requests.append(schema_two_without_evidence)

        schema_one_with_evidence = _create_request()
        schema_one_with_evidence["captureManifest"]["schemaVersion"] = 1
        invalid_requests.append(schema_one_with_evidence)

        schema_two_without_language = _create_request()
        del schema_two_without_language["languageDecision"]
        invalid_requests.append(schema_two_without_language)

        schema_two_without_catalog = _create_request()
        del schema_two_without_catalog["asrCatalogRevision"]
        invalid_requests.append(schema_two_without_catalog)

        legacy_preprocessing = _create_request()
        legacy_preprocessing["preprocessingEvidence"]["schemaVersion"] = 1
        invalid_requests.append(legacy_preprocessing)

        unsupported_manifest = _create_request()
        unsupported_manifest["captureManifest"]["schemaVersion"] = 3
        invalid_requests.append(unsupported_manifest)

        for request in invalid_requests:
            with self.subTest(request=request):
                with tempfile.TemporaryDirectory() as temporary:
                    service = RecordingJobService(
                        Path(temporary),
                        processor=_Processor(),
                        supported_languages=("en",),
                        now=lambda: "2026-07-14T21:00:00Z",
                    )
                    with self.assertRaises(JobServiceError) as invalid:
                        service.create(request)
                    self.assertEqual(invalid.exception.code, "INVALID_JOB")

    def test_preprocessing_evidence_rejects_unbounded_or_incoherent_shapes(
        self,
    ) -> None:
        invalid_requests: list[dict[str, object]] = []

        output_count_mismatch = _create_request()
        output_count_mismatch["preprocessingEvidence"]["normalization"][
            "outputSampleCount"
        ] = 159
        invalid_requests.append(output_count_mismatch)

        source_count_mismatch = _create_request()
        source_count_mismatch["preprocessingEvidence"]["vad"]["sourceSampleCount"] = 159
        invalid_requests.append(source_count_mismatch)

        interval_time_mismatch = _create_request()
        interval_time_mismatch["preprocessingEvidence"]["vad"]["intervals"][0][
            "endMs"
        ] = 11
        invalid_requests.append(interval_time_mismatch)

        overlapping_intervals = _create_request()
        overlapping_intervals["preprocessingEvidence"]["vad"]["intervals"] = [
            {
                "startSample": 0,
                "endSampleExclusive": 100,
                "startMs": 0,
                "endMs": 7,
            },
            {
                "startSample": 99,
                "endSampleExclusive": 160,
                "startMs": 6,
                "endMs": 10,
            },
        ]
        invalid_requests.append(overlapping_intervals)

        excessive_intervals = _create_request()
        interval = excessive_intervals["preprocessingEvidence"]["vad"]["intervals"][0]
        excessive_intervals["preprocessingEvidence"]["vad"]["intervals"] = [
            deepcopy(interval) for _ in range(4_097)
        ]
        invalid_requests.append(excessive_intervals)

        unknown_nested_field = _create_request()
        unknown_nested_field["preprocessingEvidence"]["normalization"]["unexpected"] = (
            True
        )
        invalid_requests.append(unknown_nested_field)

        identity_with_explicit_null_provenance = _create_request()
        identity_with_explicit_null_provenance["preprocessingEvidence"]["normalization"][
            "decodedFrom"
        ] = None
        invalid_requests.append(identity_with_explicit_null_provenance)

        for request in invalid_requests:
            with self.subTest(case=len(invalid_requests)):
                with tempfile.TemporaryDirectory() as temporary:
                    service = RecordingJobService(
                        Path(temporary),
                        processor=_Processor(),
                        supported_languages=("en",),
                        now=lambda: "2026-07-14T21:00:00Z",
                    )
                    with self.assertRaises(JobServiceError) as invalid:
                        service.create(request)
                    self.assertEqual(invalid.exception.code, "INVALID_JOB")

    def test_result_model_provenance_matches_the_openapi_256_character_bound(
        self,
    ) -> None:
        from yap_server.jobs.result_contract import validate_result_revision

        projection = {
            "sessionId": "s-batch-create",
            "captureManifest": {"sha256": "a" * 64},
        }
        result = _published_result(projection)
        result["modelProvenance"][0]["modelId"] = "m" * 257

        with self.assertRaises(ValueError):
            validate_result_revision(result, projection)

    def test_partial_result_requires_a_speaker_companion_identity(self) -> None:
        projection = {
            "sessionId": "s-batch-create",
            "captureManifest": {"sha256": "a" * 64},
        }
        result = _published_result(projection)
        result["status"] = "partial"

        with self.assertRaisesRegex(ValueError, "omitted its speaker companion"):
            validate_result_revision(result, projection)

        result["speakerResultSha256"] = "d" * 64
        validate_result_revision(result, projection)

    def test_result_contract_accepts_empty_but_not_whitespace_only_transcript(
        self,
    ) -> None:
        from yap_server.jobs.result_contract import validate_result_revision

        projection = {
            "sessionId": "s-batch-create",
            "captureManifest": {"sha256": "a" * 64},
        }
        result = _published_result(projection)
        result["transcript"] = ""
        validate_result_revision(result, projection)

        result["transcript"] = "   "
        with self.assertRaises(ValueError):
            validate_result_revision(result, projection)

    def test_create_returns_and_replays_the_immutable_job_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:01:00Z",
            )

            created = service.create(_create_request())

            self.assertRegex(created["jobId"], r"^job-[0-9a-f]{32}$")
            self.assertEqual(created["sessionId"], "s-batch-create")
            self.assertEqual(
                created["displayName"], "Batch transcription vertical slice"
            )
            self.assertEqual(created["sessionMode"], "meeting")
            self.assertEqual(created["sessionOrigin"], "imported_file")
            self.assertEqual(created["status"], "accepted")
            self.assertEqual(created["route"], "server_batch")
            self.assertEqual(
                created["captureManifest"], _create_request()["captureManifest"]
            )
            self.assertEqual(created["createdAtUtc"], "2026-07-14T21:01:00Z")
            self.assertEqual(created["updatedAtUtc"], "2026-07-14T21:01:00Z")
            self.assertEqual(service.get(created["jobId"]), created)

    def test_create_idempotency_survives_restart_and_rejects_conflicting_content(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:01:00Z",
            )
            request = _create_request()

            created = service.create(request, idempotency_key="job-client-1")
            replayed = service.create(request, idempotency_key="job-client-1")

            self.assertEqual(replayed, created)
            conflicting = _create_request()
            conflicting["displayName"] = "different recording"
            with self.assertRaises(JobServiceError) as conflict:
                service.create(conflicting, idempotency_key="job-client-1")
            self.assertEqual(conflict.exception.status, 409)
            self.assertEqual(conflict.exception.code, "CREATE_IDEMPOTENCY_CONFLICT")

            restarted = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:02:00Z",
            )
            self.assertEqual(
                restarted.create(request, idempotency_key="job-client-1"),
                created,
            )
            self.assertEqual(len(list((root / "jobs").iterdir())), 1)

    def test_create_persistence_failure_rolls_back_before_retry_and_restart(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:01:00Z",
            )
            request = _create_request()

            from yap_server.jobs import job_store as store_module

            with patch.object(
                store_module,
                "publish_json",
                side_effect=OSError("private state storage unavailable"),
            ):
                with self.assertRaises(OSError):
                    service.create(request, idempotency_key="job-client-retry")

            self.assertEqual(list((root / "jobs").iterdir()), [])
            created = service.create(
                request,
                idempotency_key="job-client-retry",
            )
            restarted = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:02:00Z",
            )

            self.assertEqual(
                restarted.create(request, idempotency_key="job-client-retry"),
                created,
            )
            self.assertEqual(len(list((root / "jobs").iterdir())), 1)
