import re

_PATH_ID = r"[A-Za-z0-9_-]+"
_LID_REQUEST_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
LID_PREFLIGHT_PATH = "/v1/lid/preflight"
LID_PREFLIGHT_CANCEL_PATH = re.compile(
    rf"^/v1/lid/preflights/(?P<request_id>{_LID_REQUEST_ID})$"
)
JOB_PATH = re.compile(rf"^/v1/jobs/(?P<job_id>{_PATH_ID})$")
RESULT_PATH = re.compile(rf"^/v1/jobs/(?P<job_id>{_PATH_ID})/result$")
CHUNK_PATH = re.compile(
    rf"^/v1/jobs/(?P<job_id>{_PATH_ID})/chunks/"
    rf"(?P<track_id>{_PATH_ID})/(?P<sequence_start>[0-9]+)-"
    rf"(?P<sequence_end>[0-9]+)$"
)
COMMIT_PATH = re.compile(rf"^/v1/jobs/(?P<job_id>{_PATH_ID})/commit$")
STAGES_PATH = re.compile(rf"^/v1/jobs/(?P<job_id>{_PATH_ID})/stages$")
STAGE_RETRY_PATH = re.compile(
    rf"^/v1/jobs/(?P<job_id>{_PATH_ID})/stages/"
    rf"(?P<stage>asr|alignment|result_publication)/retry$"
)

SUPPORTED_HTTP_VERSIONS = frozenset({"HTTP/1.0", "HTTP/1.1"})


def allowed_methods(path: str) -> frozenset[str] | None:
    if path == "/v1/health":
        return frozenset({"GET"})
    if path == "/v1/asr/capabilities":
        return frozenset({"GET"})
    if path == LID_PREFLIGHT_PATH:
        return frozenset({"POST"})
    if LID_PREFLIGHT_CANCEL_PATH.fullmatch(path):
        return frozenset({"DELETE"})
    if path == "/v1/jobs":
        return frozenset({"POST"})
    if JOB_PATH.fullmatch(path):
        return frozenset({"DELETE", "GET"})
    if RESULT_PATH.fullmatch(path):
        return frozenset({"GET"})
    if CHUNK_PATH.fullmatch(path):
        return frozenset({"PUT"})
    if COMMIT_PATH.fullmatch(path):
        return frozenset({"POST"})
    if STAGES_PATH.fullmatch(path):
        return frozenset({"GET"})
    if STAGE_RETRY_PATH.fullmatch(path):
        return frozenset({"POST"})
    if path == "/v1/live":
        return frozenset({"GET"})
    return None
