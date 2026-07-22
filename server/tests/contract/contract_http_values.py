from pathlib import Path
from typing import Any

SERVER_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = SERVER_ROOT / "openapi" / "openapi.json"
LIVE_EVENTS_PATH = SERVER_ROOT / "openapi" / "live-events.schema.json"
EXAMPLES_ROOT = SERVER_ROOT / "openapi" / "examples"

HTTP_OPERATIONS = {
    ("/v1/health", "get"): "getHealth",
    ("/v1/asr/capabilities", "get"): "getAsrCapabilities",
    ("/v1/jobs", "post"): "createJob",
    ("/v1/jobs/{jobId}", "get"): "getJob",
    ("/v1/jobs/{jobId}/result", "get"): "getJobResult",
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
        "Contract only; capability remains false",
        "Live WebSocket transport",
    ),
}

CHUNK_PATH = "/v1/jobs/{jobId}/chunks/{trackId}/{sequenceStart}-{sequenceEnd}"

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
        "path": "/v1/jobs",
        "method": "post",
        "request": (
            "application/json",
            "#/components/schemas/CreateRecordingJobRequest",
        ),
        "success": {"202": "#/components/schemas/RecordingJob"},
        "errors": ["400", "429", "501"],
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
        "errors": ["404", "501"],
    },
    {
        "path": "/v1/jobs/{jobId}/result",
        "method": "get",
        "request": None,
        "success": {"200": "#/components/schemas/TranscriptResultRevision"},
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
        "errors": ["400", "404", "409", "415", "501"],
    },
    {
        "path": "/v1/jobs/{jobId}/commit",
        "method": "post",
        "request": (
            "application/json",
            "#/components/schemas/CommitRecordingJobRequest",
        ),
        "success": {"202": "#/components/schemas/RecordingJob"},
        "errors": ["400", "404", "409", "501"],
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
        "errors": ["400", "404", "409", "429"],
    },
    {
        "path": "/v1/live",
        "method": "get",
        "request": None,
        "success": {"101": None},
        "errors": ["400", "501"],
    },
]
