from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ServerCapabilities:
    batch_jobs: bool
    live_streaming: bool
    job_status: bool
    transcript_correction: bool
    librarian_queries: bool
    student_questions: bool
    archivist_ingestions: bool
    curator_proposals: bool
    analyst_answers: bool
    coordinator_bundles: bool
    auditor_reports: bool

    def to_wire(self) -> dict[str, bool]:
        return {
            "batchJobs": self.batch_jobs,
            "liveStreaming": self.live_streaming,
            "jobStatus": self.job_status,
            "transcriptCorrection": self.transcript_correction,
            "librarianQueries": self.librarian_queries,
            "studentQuestions": self.student_questions,
            "archivistIngestions": self.archivist_ingestions,
            "curatorProposals": self.curator_proposals,
            "analystAnswers": self.analyst_answers,
            "coordinatorBundles": self.coordinator_bundles,
            "auditorReports": self.auditor_reports,
        }


@dataclass(frozen=True, slots=True)
class HealthView:
    service: str
    status: Literal["ok"]
    api_version: str
    auth: Literal["not_configured", "required"]
    capabilities: ServerCapabilities

    def to_wire(self) -> dict[str, object]:
        return {
            "service": self.service,
            "status": self.status,
            "apiVersion": self.api_version,
            "auth": self.auth,
            "capabilities": self.capabilities.to_wire(),
        }
