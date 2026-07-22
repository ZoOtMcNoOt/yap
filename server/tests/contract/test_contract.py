import json
import unittest

from . import contract_http_values as http_contract
from . import contract_identity_values as identity_contract
from . import contract_schema_support as contract_schema


class ContractTests(unittest.TestCase):
    def test_openapi_declares_each_operation_runtime_and_owner(self) -> None:
        document = contract_schema.load_json(http_contract.OPENAPI_PATH)

        self.assertEqual(document["openapi"], "3.1.0")
        self.assertEqual(set(document["paths"]), {path for path, _ in http_contract.HTTP_OPERATIONS})
        for (path, method), operation_id in http_contract.HTTP_OPERATIONS.items():
            operation = document["paths"][path][method]
            self.assertEqual(operation["operationId"], operation_id)
            runtime_status, runtime_owner = http_contract.OPERATION_RUNTIME[(path, method)]
            self.assertEqual(operation["x-yap-runtime-status"], runtime_status)
            self.assertEqual(operation["x-yap-runtime-owner"], runtime_owner)

        schemas = document["components"]["schemas"]
        expected_components = {
            "RecordingJobStatus",
            "SessionMode",
            "SessionOrigin",
            "AudioRoute",
            "SessionMetadata",
            "CaptureTrackDescriptor",
            "ChunkReplayKey",
            "ContentIdentity",
            "AudioGap",
            "CaptureManifestReference",
            "SourceVadInterval",
            "VadComponentEvidence",
            "NormalizationEvidence",
            "VadEvidence",
            "PreprocessingEvidence",
            "ResultAuthority",
            "ResultStatus",
            "LanguageSegment",
            "TranscriptResultRevision",
            "SpeakerResultRevision",
            "SpeakerTurn",
            "AlignedWord",
            "ServerCapabilities",
            "HealthView",
            "AsrExecutionMode",
            "AsrQualityTier",
            "AsrCapability",
            "AsrProviderCapabilities",
            "AsrCapabilityCatalog",
            "RecordingJob",
            "ApiError",
        }
        self.assertTrue(expected_components.issubset(schemas))
        provider_capabilities = schemas["AsrProviderCapabilities"]["properties"]
        for field in (
            "providerId",
            "poolId",
            "modelId",
            "modelLicense",
            "modelSource",
        ):
            self.assertEqual(provider_capabilities[field]["pattern"], "^[ -~]+$")
        self.assertEqual(schemas["RecordingJobStatus"]["enum"], identity_contract.RECORDING_JOB_STATUSES)
        self.assertNotIn("server_processing_cohere", json.dumps(document))
        self.assertEqual(
            [name for name in contract_schema.schema_property_names(document) if "_" in name], []
        )

        origin_projection = {
            "live_capture": "liveCapture",
            "imported_file": "importedFile",
        }
        route_projection = {
            "local_fallback": "localFallback",
            "server_batch": "serverBatch",
            "server_live": "serverLive",
        }
        self.assertEqual(schemas["SessionOrigin"]["enum"], list(origin_projection))
        self.assertEqual(
            schemas["SessionOrigin"]["x-yap-recording-job-view-projection"],
            origin_projection,
        )
        self.assertEqual(
            {react: wire for wire, react in origin_projection.items()},
            {"liveCapture": "live_capture", "importedFile": "imported_file"},
        )
        self.assertEqual(schemas["AudioRoute"]["enum"], list(route_projection))
        self.assertEqual(
            schemas["AudioRoute"]["x-yap-recording-job-view-projection"],
            route_projection,
        )
        self.assertEqual(
            {react: wire for wire, react in route_projection.items()},
            {
                "localFallback": "local_fallback",
                "serverBatch": "server_batch",
                "serverLive": "server_live",
            },
        )

        metadata = schemas["SessionMetadata"]
        self.assertEqual(metadata["properties"]["startedAtUtc"]["format"], "date-time")
        self.assertEqual(metadata["properties"]["localeHintBcp47"]["maxLength"], 35)
        self.assertEqual(
            metadata["properties"]["preferredLanguagesBcp47"]["maxItems"], 8
        )
        self.assertFalse(
            metadata["properties"]["preferredLanguagesBcp47"].get(
                "uniqueItems", False
            )
        )
        self.assertEqual(
            metadata["properties"]["countryCodeHint"]["pattern"], "^[A-Z]{2}$"
        )
        self.assertIn(
            "unconfigured",
            metadata["properties"]["privacyPolicyVersion"]["description"],
        )
        self.assertIn(
            "opaque",
            schemas["CaptureTrackDescriptor"]["properties"]["deviceId"][
                "description"
            ].lower(),
        )

        job_request = schemas["CreateRecordingJobRequest"]
        replay_key = schemas["ChunkReplayKey"]
        meeting_import_metadata = job_request["properties"]["metadata"]["allOf"][1][
            "properties"
        ]
        self.assertEqual(meeting_import_metadata["mode"]["const"], "meeting")
        self.assertEqual(meeting_import_metadata["origin"]["const"], "imported_file")
        self.assertEqual(
            meeting_import_metadata["retentionExpiresAtUtc"]["$ref"],
            "#/components/schemas/UtcDateTime",
        )
        self.assertEqual(job_request["properties"]["tracks"]["maxItems"], 1)
        self.assertEqual(job_request["properties"]["chunks"]["maxItems"], 4096)
        self.assertEqual(
            schemas["CaptureManifestReference"]["properties"]["schemaVersion"][
                "enum"
            ],
            [1, 2],
        )
        self.assertEqual(
            job_request["properties"]["preprocessingEvidence"]["$ref"],
            "#/components/schemas/PreprocessingEvidence",
        )
        self.assertEqual(len(job_request["oneOf"]), 2)
        self.assertEqual(
            job_request["oneOf"][0]["properties"]["languageDecision"]["properties"][
                "mode"
            ]["const"],
            "fixed",
        )
        self.assertIn("preprocessingEvidence", job_request["oneOf"][1]["required"])
        self.assertIn("asrCatalogRevision", job_request["oneOf"][1]["required"])
        self.assertEqual(
            job_request["properties"]["asrCatalogRevision"]["pattern"],
            "^[0-9a-f]{64}$",
        )
        self.assertEqual(
            schemas["PreprocessingEvidence"]["x-yap-maximum-encoded-bytes"],
            512 * 1024,
        )
        self.assertEqual(
            schemas["VadEvidence"]["properties"]["intervals"]["maxItems"],
            4096,
        )
        self.assertIn("languageDecision", job_request["required"])
        self.assertEqual(
            job_request["properties"]["languageDecision"]["$ref"],
            "#/components/schemas/RecordingLanguageDecision",
        )
        recording_language = schemas["RecordingLanguageDecision"]
        self.assertEqual(len(recording_language["oneOf"]), 2)
        recording_variants = {
            variant["properties"]["mode"]["const"]: variant
            for variant in recording_language["oneOf"]
        }
        self.assertEqual(set(recording_variants), {"fixed", "dynamic"})
        self.assertEqual(
            recording_variants["dynamic"]["properties"]["languageBcp47"]["type"],
            "null",
        )
        self.assertEqual(
            recording_variants["dynamic"]["properties"]["disposition"]["const"],
            "explicitDynamic",
        )
        self.assertTrue(
            recording_variants["fixed"]["properties"]["languageBcp47"]["pattern"].startswith(
                "^(?!und$)"
            )
        )

        transcript_result = schemas["TranscriptResultRevision"]
        self.assertNotIn("alignment", transcript_result["required"])
        self.assertIn("before typed alignment evidence", transcript_result["description"])
        self.assertEqual(
            transcript_result["properties"]["alignedWords"]["maxItems"],
            16_384,
        )
        self.assertEqual(
            transcript_result["properties"]["alignment"]["$ref"],
            "#/components/schemas/AlignmentOutcome",
        )
        self.assertEqual(
            schemas["AlignmentOutcome"]["properties"]["componentRevision"]["enum"],
            [
                "cohere-attention-en-v1",
                "cohere-attention-alignment-candidate-v1",
            ],
        )
        self.assertIn(
            "ALIGNMENT_PROVIDER_UNSUPPORTED",
            schemas["AlignmentUnavailableReason"]["enum"],
        )
        language_segments = transcript_result["properties"]["languageSegments"]
        self.assertEqual(language_segments["minItems"], 1)
        self.assertEqual(language_segments["maxItems"], 4096)
        self.assertEqual(
            language_segments["items"]["$ref"],
            "#/components/schemas/LanguageSegment",
        )
        self.assertEqual(
            transcript_result["allOf"][0]["then"]["required"],
            ["languageSegments", "languageSpanEvidence"],
        )
        self.assertEqual(
            transcript_result["properties"]["languageSpanEvidence"]["$ref"],
            "#/components/schemas/LanguageSpanEvidence",
        )
        language_segment = schemas["LanguageSegment"]
        self.assertEqual(
            set(language_segment["required"]),
            {
                "index",
                "sourceSpanIndex",
                "text",
                "status",
                "languageBcp47",
                "rawLanguageTag",
                "reason",
            },
        )
        self.assertEqual(
            language_segment["properties"]["status"]["enum"],
            ["detected", "unknown"],
        )
        language_span_evidence = schemas["LanguageSpanEvidence"]
        self.assertEqual(
            language_span_evidence["properties"]["boundaryAuthority"]["const"],
            "serverUtterance",
        )
        self.assertIn(
            "MUST NOT be interpreted as within-utterance language diarization",
            language_span_evidence["description"],
        )
        self.assertEqual(
            language_span_evidence["properties"]["spans"]["maxItems"],
            4096,
        )
        self.assertEqual(
            schemas["LanguageSpanBoundaryAuthority"]["enum"],
            ["clientDecision", "serverUtterance"],
        )
        forbidden_ownership_fields = {
            "tenantId",
            "tenant_id",
            "ownerSubjectId",
            "owner_subject_id",
            "ownerNamespace",
            "owner_namespace",
        }
        self.assertTrue(forbidden_ownership_fields.isdisjoint(job_request["properties"]))
        self.assertTrue(forbidden_ownership_fields.isdisjoint(replay_key["properties"]))

        api_error = schemas["ApiError"]
        self.assertEqual(
            set(api_error["required"]),
            {"code", "message", "retryable", "requestId"},
        )
        self.assertEqual(
            api_error["example"],
            {
                "code": "SERVER_BUSY",
                "message": "Server capacity is temporarily unavailable.",
                "retryable": True,
                "requestId": "req-01J...",
            },
        )
