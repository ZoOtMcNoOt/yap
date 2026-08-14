from pathlib import Path
from typing import Any

SERVER_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = SERVER_ROOT / "openapi" / "openapi.json"
LIVE_EVENTS_PATH = SERVER_ROOT / "openapi" / "live-events.schema.json"
EXAMPLES_ROOT = SERVER_ROOT / "openapi" / "examples"

HTTP_OPERATIONS = {
    ("/v1/health", "get"): "getHealth",
    ("/v1/asr/capabilities", "get"): "getAsrCapabilities",
    ("/v1/lid/preflight", "post"): "runLidPreflight",
    (
        "/v1/lid/preflights/{requestId}",
        "delete",
    ): "cancelLidPreflight",
    ("/v1/transcript-corrections", "post"): "submitTranscriptCorrection",
    ("/v1/transcript-corrections/{requestId}", "get"): "getTranscriptCorrection",
    ("/v1/transcript-corrections/{requestId}", "delete"): "cancelTranscriptCorrection",
    ("/v1/librarian-queries", "post"): "submitLibrarianQuery",
    ("/v1/librarian-queries/{requestId}", "get"): "getLibrarianQuery",
    ("/v1/librarian-queries/{requestId}", "delete"): "cancelLibrarianQuery",
    ("/v1/student-questions", "post"): "submitStudentQuestion",
    ("/v1/student-questions/{requestId}", "get"): "getStudentQuestion",
    ("/v1/student-questions/{requestId}", "delete"): "cancelStudentQuestion",
    ("/v1/curator-proposals", "post"): "submitCuratorProposal",
    ("/v1/curator-proposals/{requestId}", "get"): "getCuratorProposal",
    ("/v1/curator-proposals/{requestId}", "delete"): "cancelCuratorProposal",
    ("/v1/archivist-ingestions", "post"): "submitArchivistIngestion",
    ("/v1/archivist-ingestions/{requestId}", "get"): "getArchivistIngestion",
    (
        "/v1/archivist-ingestions/{requestId}",
        "delete",
    ): "cancelArchivistIngestion",
    ("/v1/jobs", "post"): "createJob",
    ("/v1/jobs/{jobId}", "get"): "getJob",
    ("/v1/jobs/{jobId}/result", "get"): "getJobResult",
    ("/v1/jobs/{jobId}/speaker-result", "get"): "getJobSpeakerResult",
    ("/v1/jobs/{jobId}", "delete"): "cancelJob",
    (
        "/v1/jobs/{jobId}/chunks/{trackId}/{sequenceStart}-{sequenceEnd}",
        "put",
    ): "uploadJobChunk",
    ("/v1/jobs/{jobId}/commit", "post"): "commitJob",
    ("/v1/jobs/{jobId}/stages", "get"): "getJobStages",
    ("/v1/jobs/{jobId}/stages/{stage}/retry", "post"): "retryJobStage",
    ("/v1/live", "get"): "connectLive",
}

OPERATION_RUNTIME = {
    ("/v1/health", "get"): ("Implemented", "Process health"),
    ("/v1/asr/capabilities", "get"): (
        "Implemented only when locked runtime artifacts verify",
        "Verified ASR capability catalog",
    ),
    ("/v1/lid/preflight", "post"): (
        "Implemented only when the locked LID runtime verifies",
        "Bounded assistive language preflight",
    ),
    ("/v1/lid/preflights/{requestId}", "delete"): (
        "Implemented only when the locked LID runtime verifies",
        "Active language-preflight cancellation",
    ),
    ("/v1/transcript-corrections", "post"): (
        "Implemented only when the authenticated warm Scribe runtime verifies",
        "Scribe transcript correction",
    ),
    ("/v1/transcript-corrections/{requestId}", "get"): (
        "Implemented only when the authenticated warm Scribe runtime verifies",
        "Scribe transcript correction",
    ),
    ("/v1/transcript-corrections/{requestId}", "delete"): (
        "Implemented only when the authenticated warm Scribe runtime verifies",
        "Scribe transcript correction",
    ),
    ("/v1/librarian-queries", "post"): (
        "Implemented only when the authenticated Librarian runtime verifies",
        "Librarian permission-safe evidence",
    ),
    ("/v1/librarian-queries/{requestId}", "get"): (
        "Implemented only when the authenticated Librarian runtime verifies",
        "Librarian permission-safe evidence",
    ),
    ("/v1/librarian-queries/{requestId}", "delete"): (
        "Implemented only when the authenticated Librarian runtime verifies",
        "Librarian permission-safe evidence",
    ),
    ("/v1/student-questions", "post"): (
        "Implemented only when the authenticated warm Student runtime verifies",
        "Student source-cited learning questions",
    ),
    ("/v1/student-questions/{requestId}", "get"): (
        "Implemented only when the authenticated warm Student runtime verifies",
        "Student source-cited learning questions",
    ),
    ("/v1/student-questions/{requestId}", "delete"): (
        "Implemented only when the authenticated warm Student runtime verifies",
        "Student source-cited learning questions",
    ),
    ("/v1/curator-proposals", "post"): (
        "Implemented only when the authenticated warm Curator runtime verifies",
        "Curator reviewed noncanonical proposals",
    ),
    ("/v1/curator-proposals/{requestId}", "get"): (
        "Implemented only when the authenticated warm Curator runtime verifies",
        "Curator reviewed noncanonical proposals",
    ),
    ("/v1/curator-proposals/{requestId}", "delete"): (
        "Implemented only when the authenticated warm Curator runtime verifies",
        "Curator reviewed noncanonical proposals",
    ),
    ("/v1/archivist-ingestions", "post"): (
        "Implemented only when the authenticated Archivist runtime verifies",
        "Archivist reviewed-source staging",
    ),
    ("/v1/archivist-ingestions/{requestId}", "get"): (
        "Implemented only when the authenticated Archivist runtime verifies",
        "Archivist reviewed-source staging",
    ),
    ("/v1/archivist-ingestions/{requestId}", "delete"): (
        "Implemented only when the authenticated Archivist runtime verifies",
        "Archivist reviewed-source staging",
    ),
    ("/v1/jobs", "post"): (
        "Implemented in the loopback batch runtime",
        "Batch job intake",
    ),
    ("/v1/jobs/{jobId}", "get"): (
        "Implemented in the loopback batch runtime",
        "Batch job status",
    ),
    ("/v1/jobs/{jobId}", "delete"): (
        "Implemented in the loopback batch runtime",
        "Batch job cancellation",
    ),
    ("/v1/jobs/{jobId}/result", "get"): (
        "Implemented in the loopback batch runtime",
        "Transcript result retrieval",
    ),
    ("/v1/jobs/{jobId}/speaker-result", "get"): (
        "Implemented for explicitly configured joint meeting candidate routes",
        "Speaker result retrieval",
    ),
    (
        "/v1/jobs/{jobId}/chunks/{trackId}/{sequenceStart}-{sequenceEnd}",
        "put",
    ): ("Implemented in the loopback batch runtime", "Resumable chunk upload"),
    ("/v1/jobs/{jobId}/commit", "post"): (
        "Implemented in the loopback batch runtime",
        "Batch upload commit",
    ),
    ("/v1/jobs/{jobId}/stages", "get"): (
        "Implemented in the loopback batch runtime",
        "Durable server-stage projections",
    ),
    ("/v1/jobs/{jobId}/stages/{stage}/retry", "post"): (
        "ASR retry implemented in the loopback batch runtime",
        "Server-stage retry",
    ),
    ("/v1/live", "get"): (
        "Authenticated private transport implemented; live ASR inference remains false",
        "Live WebSocket transport",
    ),
}

CHUNK_PATH = "/v1/jobs/{jobId}/chunks/{trackId}/{sequenceStart}-{sequenceEnd}"

RUNTIME_PATH_EXAMPLES = {
    "/v1/health": "/v1/health",
    "/v1/asr/capabilities": "/v1/asr/capabilities",
    "/v1/lid/preflight": "/v1/lid/preflight",
    "/v1/lid/preflights/{requestId}": "/v1/lid/preflights/lid-request-01",
    "/v1/transcript-corrections": "/v1/transcript-corrections",
    "/v1/transcript-corrections/{requestId}": (
        "/v1/transcript-corrections/scribe-request-01"
    ),
    "/v1/librarian-queries": "/v1/librarian-queries",
    "/v1/librarian-queries/{requestId}": (
        "/v1/librarian-queries/librarian-query-11111111111111111111111111111111"
    ),
    "/v1/student-questions": "/v1/student-questions",
    "/v1/student-questions/{requestId}": (
        "/v1/student-questions/student-question-11111111111111111111111111111111"
    ),
    "/v1/curator-proposals": "/v1/curator-proposals",
    "/v1/curator-proposals/{requestId}": (
        "/v1/curator-proposals/curator-proposal-11111111111111111111111111111111"
    ),
    "/v1/archivist-ingestions": "/v1/archivist-ingestions",
    "/v1/archivist-ingestions/{requestId}": (
        "/v1/archivist-ingestions/archivist-ingestion-11111111111111111111111111111111"
    ),
    "/v1/jobs": "/v1/jobs",
    "/v1/jobs/{jobId}": "/v1/jobs/job-01",
    "/v1/jobs/{jobId}/result": "/v1/jobs/job-01/result",
    "/v1/jobs/{jobId}/speaker-result": "/v1/jobs/job-01/speaker-result",
    CHUNK_PATH: "/v1/jobs/job-01/chunks/mic/0-15",
    "/v1/jobs/{jobId}/commit": "/v1/jobs/job-01/commit",
    "/v1/jobs/{jobId}/stages": "/v1/jobs/job-01/stages",
    "/v1/jobs/{jobId}/stages/{stage}/retry": ("/v1/jobs/job-01/stages/asr/retry"),
    "/v1/live": "/v1/live",
}

HTTP_SCHEMA_CONTRACTS: list[dict[str, Any]] = [
    {
        "path": "/v1/health",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/HealthView"},
        "errors": ["500"],
    },
    {
        "path": "/v1/asr/capabilities",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/AsrCapabilityCatalog"},
        "errors": ["501"],
    },
    {
        "path": "/v1/lid/preflight",
        "method": "post",
        "request": (
            "application/vnd.yap.lid-preflight.v1+octet-stream",
            {
                "type": "string",
                "format": "binary",
                "minLength": 960005,
                "maxLength": 1024 * 1024,
            },
        ),
        "success": {"200": "#/components/schemas/LidPreflightResult"},
        "errors": ["400", "409", "413", "415", "429", "500", "501", "503"],
        "errorSchemas": {
            "400": "#/components/schemas/LidPreflightRequestError",
            "409": "#/components/schemas/LidPreflightConflictError",
            "413": "#/components/schemas/LidPreflightRequestTooLargeError",
            "415": "#/components/schemas/LidPreflightUnsupportedMediaTypeError",
            "429": "#/components/schemas/LidPreflightBusyError",
            "500": "#/components/schemas/LidPreflightStorageError",
            "501": "#/components/schemas/LidPreflightNotImplementedError",
            "503": "#/components/schemas/LidPreflightUnavailableError",
        },
    },
    {
        "path": "/v1/lid/preflights/{requestId}",
        "method": "delete",
        "request": None,
        "success": {"202": "#/components/schemas/LidPreflightCancellation"},
        "errors": ["404", "501"],
        "errorSchemas": {
            "404": "#/components/schemas/LidPreflightNotFoundError",
            "501": "#/components/schemas/LidPreflightNotImplementedError",
        },
    },
    {
        "path": "/v1/transcript-corrections",
        "method": "post",
        "request": (
            "application/json",
            "#/components/schemas/TranscriptCorrectionRequest",
        ),
        "success": {"202": "#/components/schemas/TranscriptCorrectionJobView"},
        "errors": ["400", "401", "403", "429", "501", "503", "504"],
    },
    {
        "path": "/v1/transcript-corrections/{requestId}",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/TranscriptCorrectionJobView"},
        "errors": ["401", "403", "404", "501", "503"],
    },
    {
        "path": "/v1/librarian-queries",
        "method": "post",
        "request": (
            "application/json",
            "#/components/schemas/LibrarianRequest",
        ),
        "success": {"202": "#/components/schemas/LibrarianQueryJobView"},
        "errors": ["400", "401", "403", "429", "501", "503"],
    },
    {
        "path": "/v1/librarian-queries/{requestId}",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/LibrarianQueryJobView"},
        "errors": ["401", "403", "404", "501", "503"],
    },
    {
        "path": "/v1/librarian-queries/{requestId}",
        "method": "delete",
        "request": None,
        "success": {"202": "#/components/schemas/LibrarianQueryJobView"},
        "errors": ["401", "403", "404", "501", "503"],
    },
    {
        "path": "/v1/student-questions",
        "method": "post",
        "request": (
            "application/json",
            "#/components/schemas/StudentRequest",
        ),
        "success": {"202": "#/components/schemas/StudentQuestionJobView"},
        "errors": ["400", "401", "403", "429", "501", "503"],
    },
    {
        "path": "/v1/student-questions/{requestId}",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/StudentQuestionJobView"},
        "errors": ["401", "403", "404", "501", "503"],
    },
    {
        "path": "/v1/student-questions/{requestId}",
        "method": "delete",
        "request": None,
        "success": {"202": "#/components/schemas/StudentQuestionJobView"},
        "errors": ["401", "403", "404", "501", "503"],
    },
    {
        "path": "/v1/curator-proposals",
        "method": "post",
        "request": (
            "application/json",
            "#/components/schemas/CuratorProposalRequest",
        ),
        "success": {"202": "#/components/schemas/CuratorProposalJobView"},
        "errors": ["400", "401", "403", "409", "429", "501", "503"],
    },
    {
        "path": "/v1/curator-proposals/{requestId}",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/CuratorProposalJobView"},
        "errors": ["401", "403", "404", "501", "503"],
    },
    {
        "path": "/v1/curator-proposals/{requestId}",
        "method": "delete",
        "request": None,
        "success": {"202": "#/components/schemas/CuratorProposalJobView"},
        "errors": ["401", "403", "404", "501", "503"],
    },
    {
        "path": "/v1/archivist-ingestions",
        "method": "post",
        "request": (
            "application/json",
            "#/components/schemas/ArchivistIngestionRequest",
        ),
        "success": {"202": "#/components/schemas/ArchivistIngestionJobView"},
        "errors": ["400", "401", "403", "404", "429", "501", "503"],
    },
    {
        "path": "/v1/archivist-ingestions/{requestId}",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/ArchivistIngestionJobView"},
        "errors": ["401", "403", "404", "501", "503"],
    },
    {
        "path": "/v1/archivist-ingestions/{requestId}",
        "method": "delete",
        "request": None,
        "success": {"202": "#/components/schemas/ArchivistIngestionJobView"},
        "errors": ["401", "403", "404", "501", "503"],
    },
    {
        "path": "/v1/transcript-corrections/{requestId}",
        "method": "delete",
        "request": None,
        "success": {"202": "#/components/schemas/TranscriptCorrectionJobView"},
        "errors": ["401", "403", "404", "501", "503"],
    },
    {
        "path": "/v1/jobs",
        "method": "post",
        "request": (
            "application/json",
            "#/components/schemas/CreateRecordingJobRequest",
        ),
        "success": {"202": "#/components/schemas/RecordingJob"},
        "errors": ["400", "429", "501", "503"],
    },
    {
        "path": "/v1/jobs/{jobId}",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/RecordingJob"},
        "errors": ["404", "501"],
    },
    {
        "path": "/v1/jobs/{jobId}",
        "method": "delete",
        "request": None,
        "success": {"202": "#/components/schemas/RecordingJob"},
        "errors": ["404", "501", "503"],
    },
    {
        "path": "/v1/jobs/{jobId}/result",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/TranscriptResultRevision"},
        "errors": ["404", "409", "501"],
    },
    {
        "path": "/v1/jobs/{jobId}/speaker-result",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/SpeakerResultRevision"},
        "errors": ["404", "409", "501"],
    },
    {
        "path": CHUNK_PATH,
        "method": "put",
        "request": (
            "application/octet-stream",
            {"type": "string", "format": "binary"},
        ),
        "success": {
            "200": "#/components/schemas/ChunkUploadReceipt",
            "201": "#/components/schemas/ChunkUploadReceipt",
        },
        "errors": ["400", "404", "409", "415", "501", "503"],
    },
    {
        "path": "/v1/jobs/{jobId}/commit",
        "method": "post",
        "request": (
            "application/json",
            "#/components/schemas/CommitRecordingJobRequest",
        ),
        "success": {"202": "#/components/schemas/RecordingJob"},
        "errors": ["400", "404", "409", "501", "503"],
    },
    {
        "path": "/v1/jobs/{jobId}/stages",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/ServerStageProjectionEnvelope"},
        "errors": ["404"],
    },
    {
        "path": "/v1/jobs/{jobId}/stages/{stage}/retry",
        "method": "post",
        "request": (
            "application/json",
            "#/components/schemas/RetryServerStageRequest",
        ),
        "success": {"202": "#/components/schemas/ServerStageProjectionEnvelope"},
        "errors": ["400", "404", "409", "429", "503"],
    },
    {
        "path": "/v1/live",
        "method": "get",
        "request": None,
        "success": {"101": None},
        "errors": ["400", "501"],
    },
]

LID_ERROR_CONTRACTS = {
    ("/v1/lid/preflight", "post", "400"): (
        "LidPreflightRequestError",
        {
            "INVALID_LID_PREFLIGHT",
            "INVALID_REQUEST_BODY",
            "INVALID_CONTENT_LENGTH",
            "CONTENT_LENGTH_REQUIRED",
            "INCOMPLETE_REQUEST_BODY",
        },
        False,
    ),
    ("/v1/lid/preflight", "post", "409"): (
        "LidPreflightConflictError",
        {
            "STALE_LID_PREFLIGHT_CONTRACT",
            "LID_PREFLIGHT_CONFLICT",
            "LID_PREFLIGHT_CANCELLED",
        },
        False,
    ),
    ("/v1/lid/preflight", "post", "413"): (
        "LidPreflightRequestTooLargeError",
        {"REQUEST_TOO_LARGE"},
        False,
    ),
    ("/v1/lid/preflight", "post", "415"): (
        "LidPreflightUnsupportedMediaTypeError",
        {"UNSUPPORTED_MEDIA_TYPE"},
        False,
    ),
    ("/v1/lid/preflight", "post", "429"): (
        "LidPreflightBusyError",
        {"LID_PREFLIGHT_BUSY"},
        True,
    ),
    ("/v1/lid/preflight", "post", "500"): (
        "LidPreflightStorageError",
        {"LID_PREFLIGHT_STORAGE_ERROR"},
        True,
    ),
    ("/v1/lid/preflight", "post", "501"): (
        "LidPreflightNotImplementedError",
        {"NOT_IMPLEMENTED"},
        False,
    ),
    ("/v1/lid/preflight", "post", "503"): (
        "LidPreflightUnavailableError",
        {"LID_PREFLIGHT_UNAVAILABLE", "LID_PREFLIGHT_TIMEOUT"},
        True,
    ),
    ("/v1/lid/preflights/{requestId}", "delete", "404"): (
        "LidPreflightNotFoundError",
        {"LID_PREFLIGHT_NOT_FOUND"},
        False,
    ),
    ("/v1/lid/preflights/{requestId}", "delete", "501"): (
        "LidPreflightNotImplementedError",
        {"NOT_IMPLEMENTED"},
        False,
    ),
}
