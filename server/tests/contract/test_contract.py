import json
import unittest

from yap_server.api.routes import allowed_methods

from . import contract_http_values as http_contract
from . import contract_identity_values as identity_contract
from . import contract_schema_support as contract_schema


class ContractTests(unittest.TestCase):
    def test_openapi_requires_yap_bearer_auth_except_exact_health(self) -> None:
        document = contract_schema.load_json(http_contract.OPENAPI_PATH)
        self.assertEqual(document["security"], [{"YapAccessToken": []}])
        self.assertEqual(
            document["components"]["securitySchemes"]["YapAccessToken"],
            {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": (
                    "Microsoft Entra access token issued for the Yap API. "
                    "The server derives tenant and owner identity from validated "
                    "claims; clients never submit owner fields."
                ),
            },
        )
        self.assertEqual(document["paths"]["/v1/health"]["get"]["security"], [])

        for path, method in http_contract.HTTP_OPERATIONS:
            if path == "/v1/health":
                continue
            operation = document["paths"][path][method]
            self.assertNotEqual(operation.get("security"), [])
            self.assertTrue(
                {"401", "403", "503"}.issubset(operation["responses"]),
                f"{method.upper()} {path} must declare stable auth failures",
            )

        responses = document["components"]["responses"]
        self.assertEqual(
            responses["AuthenticationRequiredResponse"]["content"][
                "application/json"
            ]["example"]["code"],
            "AUTHENTICATION_REQUIRED",
        )
        self.assertEqual(
            responses["AccessDeniedResponse"]["content"]["application/json"][
                "example"
            ]["code"],
            "ACCESS_DENIED",
        )
        self.assertEqual(
            responses["AuthenticationUnavailableResponse"]["content"][
                "application/json"
            ]["example"]["code"],
            "AUTHENTICATION_UNAVAILABLE",
        )

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
            "LanguagePreflightCapabilities",
            "LidPreflightRequestManifest",
            "LidPreflightResult",
            "LidPreflightCancellation",
            "LidPreflightRequestError",
            "LidPreflightConflictError",
            "LidPreflightRequestTooLargeError",
            "LidPreflightUnsupportedMediaTypeError",
            "LidPreflightBusyError",
            "LidPreflightStorageError",
            "LidPreflightNotImplementedError",
            "LidPreflightUnavailableError",
            "LidPreflightNotFoundError",
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
        self.assertEqual(
            schemas["AsrCapabilityCatalog"]["properties"]["languagePreflight"],
            {"$ref": "#/components/schemas/LanguagePreflightCapabilities"},
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
            schemas["CaptureManifestReference"]["properties"]["schemaVersion"]["const"],
            2,
        )
        self.assertEqual(
            job_request["properties"]["preprocessingEvidence"]["$ref"],
            "#/components/schemas/PreprocessingEvidence",
        )
        self.assertNotIn("oneOf", job_request)
        self.assertIn("preprocessingEvidence", job_request["required"])
        self.assertIn("asrCatalogRevision", job_request["required"])
        self.assertEqual(
            schemas["PreprocessingEvidence"]["properties"]["schemaVersion"]["const"],
            2,
        )
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
                "joint-segment-timing-v1",
            ],
        )
        speaker_result = schemas["SpeakerResultRevision"]
        self.assertIn("runtimeLockSha256", speaker_result["required"])
        self.assertEqual(
            speaker_result["properties"]["runtimeLockSha256"]["$ref"],
            "#/components/schemas/Sha256",
        )
        capacity = schemas["SpeakerCapacityDegradation"]
        self.assertEqual(
            capacity["oneOf"][0]["required"],
            [
                "code",
                "scope",
                "startSample",
                "endSample",
                "observedSpeakerCount",
                "speakerLimit",
            ],
        )
        self.assertEqual(
            [variant["properties"]["scope"]["const"] for variant in capacity["oneOf"]],
            ["decode_window", "meeting"],
        )
        self.assertEqual(
            capacity["oneOf"][1]["properties"]["speakerLimit"]["const"],
            64,
        )
        anonymous = schemas["JointAnonymousSpeakerAttribution"]
        self.assertEqual(
            anonymous["oneOf"][0]["properties"]["sessionSpeakerId"]["pattern"],
            "^speaker-(?:[1-9]|[1-5][0-9]|6[0-4])$",
        )
        self.assertEqual(
            anonymous["oneOf"][1]["properties"]["kind"]["const"],
            "unknown",
        )
        speaker_provenance = speaker_result["properties"]["modelProvenance"]
        self.assertEqual(speaker_provenance["minItems"], 4)
        self.assertEqual(speaker_provenance["maxItems"], 4)
        self.assertIs(speaker_provenance["items"], False)
        self.assertEqual(len(speaker_provenance["prefixItems"]), 4)
        self.assertEqual(
            speaker_provenance["prefixItems"][3]["allOf"][1]["properties"][
                "modelId"
            ]["const"],
            "yap/speaker-epoch-reconciliation",
        )
        self.assertIn("rejects duplicate modelId", speaker_provenance["description"])
        capacity_status_contract = speaker_result["allOf"][0]
        self.assertEqual(
            capacity_status_contract["if"]["properties"]["status"]["const"],
            "partial",
        )
        self.assertEqual(
            capacity_status_contract["then"]["properties"][
                "speakerCapacityDegradation"
            ]["$ref"],
            "#/components/schemas/SpeakerCapacityDegradation",
        )
        self.assertEqual(
            capacity_status_contract["else"]["properties"][
                "speakerCapacityDegradation"
            ]["type"],
            "null",
        )
        self.assertEqual(
            schemas["JointSpeakerTranscriptTurn"]["properties"]["overlapGroupId"],
            schemas["SpeakerTurn"]["properties"]["overlapGroupId"],
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
            transcript_result["allOf"][1]["if"]["properties"]["status"]["const"],
            "partial",
        )
        self.assertEqual(
            transcript_result["allOf"][1]["then"]["required"],
            ["speakerResultSha256"],
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

    def test_openapi_methods_and_paths_match_the_executing_router(self) -> None:
        document = contract_schema.load_json(http_contract.OPENAPI_PATH)

        self.assertEqual(
            set(http_contract.RUNTIME_PATH_EXAMPLES),
            set(document["paths"]),
        )
        for template, concrete_path in http_contract.RUNTIME_PATH_EXAMPLES.items():
            expected_methods = frozenset(
                method.upper()
                for path, method in http_contract.HTTP_OPERATIONS
                if path == template
            )
            with self.subTest(template=template, concrete_path=concrete_path):
                self.assertEqual(allowed_methods(concrete_path), expected_methods)

    def test_transcript_correction_contract_keeps_authority_server_owned(self) -> None:
        document = contract_schema.load_json(http_contract.OPENAPI_PATH)
        schemas = document["components"]["schemas"]
        request = schemas["TranscriptCorrectionRequest"]
        result = schemas["TranscriptCorrectionJobView"]

        self.assertEqual(
            set(request["required"]),
            {
                "schemaVersion",
                "sourceRevisionSha256",
                "sourceSha256",
                "segments",
            },
        )
        self.assertTrue(
            {
                "approvedTerminology",
                "terminologySnapshotSha256",
                "tenantId",
                "subjectId",
            }.isdisjoint(request["properties"])
        )
        self.assertIn("terminologySnapshotSha256", result["required"])
        self.assertEqual(
            result["properties"]["terminologySnapshotSha256"]["pattern"],
            "^[0-9a-f]{64}$",
        )

    def test_lid_openapi_freezes_executing_bounds_and_typed_errors(self) -> None:
        document = contract_schema.load_json(http_contract.OPENAPI_PATH)
        schemas = document["components"]["schemas"]
        operation = document["paths"]["/v1/lid/preflight"]["post"]
        envelope = operation["x-yap-envelope-contract"]
        request_schema = operation["requestBody"]["content"][
            "application/vnd.yap.lid-preflight.v1+octet-stream"
        ]["schema"]
        capabilities = schemas["LanguagePreflightCapabilities"]["properties"]
        transport = capabilities["transport"]["properties"]
        policy = capabilities["policy"]["properties"]
        manifest = schemas["LidPreflightRequestManifest"]["properties"]

        self.assertEqual(request_schema["minLength"], 960_005)
        self.assertEqual(
            request_schema["maxLength"],
            transport["maximumBodyBytes"]["const"],
        )
        self.assertEqual(
            envelope["maximumManifestBytes"],
            transport["maximumManifestBytes"]["const"],
        )
        self.assertEqual(envelope["manifestLengthPrefixBytes"], 4)
        self.assertEqual(
            manifest["sourceSamples"]["minimum"],
            policy["minimumSourceSamples"]["const"],
        )
        self.assertEqual(manifest["sourceSamples"]["maximum"], 230_400_000)
        self.assertEqual(
            manifest["probes"]["minItems"],
            policy["maximumWindows"]["const"],
        )
        self.assertEqual(
            manifest["probes"]["maxItems"],
            policy["maximumWindows"]["const"],
        )
        self.assertEqual(
            schemas["LidPreflightResult"]["properties"]["observations"][
                "maxItems"
            ],
            policy["maximumWindows"]["const"],
        )

        for (
            path,
            method,
            status,
        ), (
            schema_name,
            expected_codes,
            retryable,
        ) in http_contract.LID_ERROR_CONTRACTS.items():
            with self.subTest(path=path, method=method, status=status):
                actual_reference = document["paths"][path][method]["responses"][
                    status
                ]["content"]["application/json"]["schema"]
                self.assertEqual(
                    actual_reference,
                    {"$ref": f"#/components/schemas/{schema_name}"},
                )
                narrowing = schemas[schema_name]["allOf"][1]["properties"]
                code_schema = narrowing["code"]
                actual_codes = (
                    set(code_schema["enum"])
                    if "enum" in code_schema
                    else {code_schema["const"]}
                )
                self.assertEqual(actual_codes, expected_codes)
                self.assertIs(narrowing["retryable"]["const"], retryable)
