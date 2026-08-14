import re

_PATH_ID = r"[A-Za-z0-9_-]+"
_LID_REQUEST_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
_LIBRARIAN_QUERY_ID = r"librarian-query-[0-9a-f]{32}"
_STUDENT_QUESTION_ID = r"student-question-[0-9a-f]{32}"
_ARCHIVIST_INGESTION_ID = r"archivist-ingestion-[0-9a-f]{32}"
_CURATOR_PROPOSAL_ID = r"curator-proposal-[0-9a-f]{32}"
_ANALYST_ANSWER_ID = r"analyst-answer-[0-9a-f]{32}"
_COORDINATOR_BUNDLE_ID = r"coordinator-bundle-[0-9a-f]{32}"
_AUDITOR_REPORT_ID = r"auditor-report-[0-9a-f]{32}"
LID_PREFLIGHT_PATH = "/v1/lid/preflight"
LID_PREFLIGHT_CANCEL_PATH = re.compile(
    rf"^/v1/lid/preflights/(?P<request_id>{_LID_REQUEST_ID})$"
)
TRANSCRIPT_CORRECTIONS_PATH = "/v1/transcript-corrections"
TRANSCRIPT_CORRECTION_PATH = re.compile(
    rf"^/v1/transcript-corrections/(?P<request_id>{_LID_REQUEST_ID})$"
)
LIBRARIAN_QUERIES_PATH = "/v1/librarian-queries"
LIBRARIAN_QUERY_PATH = re.compile(
    rf"^/v1/librarian-queries/(?P<request_id>{_LIBRARIAN_QUERY_ID})$"
)
STUDENT_QUESTIONS_PATH = "/v1/student-questions"
STUDENT_QUESTION_PATH = re.compile(
    rf"^/v1/student-questions/(?P<request_id>{_STUDENT_QUESTION_ID})$"
)
ARCHIVIST_INGESTIONS_PATH = "/v1/archivist-ingestions"
ARCHIVIST_INGESTION_PATH = re.compile(
    rf"^/v1/archivist-ingestions/(?P<request_id>{_ARCHIVIST_INGESTION_ID})$"
)
CURATOR_PROPOSALS_PATH = "/v1/curator-proposals"
CURATOR_PROPOSAL_PATH = re.compile(
    rf"^/v1/curator-proposals/(?P<request_id>{_CURATOR_PROPOSAL_ID})$"
)
ANALYST_ANSWERS_PATH = "/v1/analyst-answers"
ANALYST_ANSWER_PATH = re.compile(
    rf"^/v1/analyst-answers/(?P<request_id>{_ANALYST_ANSWER_ID})$"
)
COORDINATOR_BUNDLES_PATH = "/v1/coordinator-bundles"
COORDINATOR_BUNDLE_PATH = re.compile(
    rf"^/v1/coordinator-bundles/(?P<request_id>{_COORDINATOR_BUNDLE_ID})$"
)
AUDITOR_REPORTS_PATH = "/v1/auditor-reports"
AUDITOR_REPORT_PATH = re.compile(
    rf"^/v1/auditor-reports/(?P<request_id>{_AUDITOR_REPORT_ID})$"
)
JOB_PATH = re.compile(rf"^/v1/jobs/(?P<job_id>{_PATH_ID})$")
RESULT_PATH = re.compile(rf"^/v1/jobs/(?P<job_id>{_PATH_ID})/result$")
SPEAKER_RESULT_PATH = re.compile(rf"^/v1/jobs/(?P<job_id>{_PATH_ID})/speaker-result$")
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
    if path == TRANSCRIPT_CORRECTIONS_PATH:
        return frozenset({"POST"})
    if TRANSCRIPT_CORRECTION_PATH.fullmatch(path):
        return frozenset({"DELETE", "GET"})
    if path == LIBRARIAN_QUERIES_PATH:
        return frozenset({"POST"})
    if LIBRARIAN_QUERY_PATH.fullmatch(path):
        return frozenset({"DELETE", "GET"})
    if path == STUDENT_QUESTIONS_PATH:
        return frozenset({"POST"})
    if STUDENT_QUESTION_PATH.fullmatch(path):
        return frozenset({"DELETE", "GET"})
    if path == ARCHIVIST_INGESTIONS_PATH:
        return frozenset({"POST"})
    if ARCHIVIST_INGESTION_PATH.fullmatch(path):
        return frozenset({"DELETE", "GET"})
    if path == CURATOR_PROPOSALS_PATH:
        return frozenset({"POST"})
    if CURATOR_PROPOSAL_PATH.fullmatch(path):
        return frozenset({"DELETE", "GET"})
    if path == ANALYST_ANSWERS_PATH:
        return frozenset({"POST"})
    if ANALYST_ANSWER_PATH.fullmatch(path):
        return frozenset({"DELETE", "GET"})
    if path == COORDINATOR_BUNDLES_PATH:
        return frozenset({"POST"})
    if COORDINATOR_BUNDLE_PATH.fullmatch(path):
        return frozenset({"DELETE", "GET"})
    if path == AUDITOR_REPORTS_PATH:
        return frozenset({"POST"})
    if AUDITOR_REPORT_PATH.fullmatch(path):
        return frozenset({"DELETE", "GET"})
    if path == "/v1/jobs":
        return frozenset({"POST"})
    if JOB_PATH.fullmatch(path):
        return frozenset({"DELETE", "GET"})
    if RESULT_PATH.fullmatch(path):
        return frozenset({"GET"})
    if SPEAKER_RESULT_PATH.fullmatch(path):
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
