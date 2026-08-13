from __future__ import annotations

from dataclasses import replace
import json
import threading
import unittest
from unittest.mock import patch

from psycopg.errors import LockNotAvailable, QueryCanceled

from yap_server.agents import (
    AgentAdmission,
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    ExecutionRoute,
    SchedulingClass,
)
from yap_server.agents.curator import (
    CuratorEvidence,
    CuratorEvidenceItem,
    CuratorRequest,
    CuratorReviewedStudentQuestion,
    curator_request_sha256,
    curator_work_sha256,
    validate_curator_evidence,
)
from yap_server.agents.curator_model import (
    CuratorDecision,
    CuratorProposalModel,
    parse_curator_decision,
)
from yap_server.agents.curator_result_audit import CuratorStoredResult
from yap_server.agents.curator_service import (
    CuratorContainmentError,
    CuratorService,
    CuratorServiceError,
)
from yap_server.agents.student import StudentEvidenceItem
from yap_server.agents.student_model import StudentQuestion, StudentQuestionSupport
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.knowledge_proposals import KnowledgeProposal
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
    ProposalCitation,
)


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _citation(
    *,
    concept_id: str = "meetings/job-1",
    start: int = 0,
    end: int = 28,
) -> ProposalCitation:
    return ProposalCitation(
        concept_id=concept_id,
        source_revision="b" * 64,
        content_sha256="c" * 64,
        char_start=start,
        char_end=end,
    )


def _request(*, submission_id: str = "submission-1") -> CuratorRequest:
    return CuratorRequest(
        submission_id=submission_id,
        trigger="explicit-proposal",
        expected_generation_sha256="a" * 64,
        reviewed_content="The reviewed release remains blocked.",
        source_citations=(_citation(),),
    )


def _evidence() -> CuratorEvidence:
    return CuratorEvidence.create(
        generation_sha256="a" * 64,
        permission_hash="d" * 64,
        authorization_hash="e" * 64,
        items=(
            CuratorEvidenceItem(
                _citation(),
                "The release remains blocked.",
            ),
        ),
    )


def _tool_response(decision: object = "propose") -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "curator-decision-1",
                            "type": "function",
                            "function": {
                                "name": "return_curator_decision",
                                "arguments": json.dumps(
                                    {"decision": decision},
                                    separators=(",", ":"),
                                ),
                            },
                        }
                    ]
                }
            }
        ]
    }


class _Transport:
    def __init__(
        self,
        response: object,
        *,
        rendered_token_count: int = 100,
    ) -> None:
        self.response = response
        self.rendered_token_count = rendered_token_count
        self.rendered_payloads: list[dict[str, object]] = []
        self.payloads: list[dict[str, object]] = []

    def render_chat_token_count(self, payload, cancellation):
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        self.rendered_payloads.append(payload)
        return self.rendered_token_count

    def request(self, payload, cancellation, dispatched=None):
        del dispatched
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        self.payloads.append(payload)
        return self.response


class _EvidenceReader:
    def __init__(self, evidence: CuratorEvidence = _evidence()) -> None:
        self.evidence = evidence
        self.calls = 0

    def read(self, request, *, principal, cancellation):
        del request, principal
        self.calls += 1
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        return self.evidence


class _Reviewer:
    def __init__(
        self,
        decision: CuratorDecision = CuratorDecision("propose"),
        *,
        error: BaseException | None = None,
    ) -> None:
        self.decision = decision
        self.error = error
        self.calls = 0

    def review(self, request, evidence, *, cancellation):
        del request, evidence
        self.calls += 1
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        if self.error is not None:
            raise self.error
        return self.decision


class _Publisher:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.calls = 0
        self.error = error

    def publish(self, **value):
        self.calls += 1
        if self.error is not None:
            raise self.error
        request = value["request"]
        return KnowledgeProposal(
            "tenant-a",
            "f" * 64,
            request.expected_generation_sha256,
            "summary",
            request.reviewed_content,
            request.source_citations,
            "1" * 64,
            "2" * 64,
            "3" * 64,
            "proposed",
        )


class _Auditor:
    def __init__(self, stored: CuratorStoredResult | None = None) -> None:
        self.stored = stored
        self.records: list[dict[str, object]] = []

    def read(self, *, principal, submission_id):
        del principal, submission_id
        return self.stored

    def record(self, **value):
        self.records.append(value)


class _Admission:
    def __init__(
        self,
        *,
        complete_outcome: str = "completed",
        post_model_outcome: str | None = None,
        initial_outcome: str = "admitted",
        queued_status_outcome: str | None = None,
        cancel_on_complete: threading.Event | None = None,
    ) -> None:
        self.outcome = initial_outcome
        self.complete_outcome = complete_outcome
        self.post_model_outcome = post_model_outcome
        self.queued_status_outcome = queued_status_outcome
        self.cancel_on_complete = cancel_on_complete
        self.route = ExecutionRoute.COMPLEX_ORCHESTRATION
        self.generation = 9
        self.calls: list[str] = []
        self.submission: dict[str, object] | None = None

    def new_ticket(self):
        self.calls.append("new-ticket")
        return AgentAdmissionTicket("curator-1", "1" * 64)

    def submit(self, ticket, **kwargs):
        self.calls.append("submit")
        self.submission = kwargs
        return self._response(ticket)

    def status(self, ticket):
        self.calls.append("status")
        if self.outcome == "queued" and self.queued_status_outcome is not None:
            self.outcome = self.queued_status_outcome
        elif self.post_model_outcome is not None:
            self.outcome = self.post_model_outcome
        return self._response(ticket)

    def cancel(self, ticket):
        self.calls.append("cancel")
        if self.outcome == "completed":
            return AgentAdmission(ticket, "completed")
        self.outcome = "cancellation-requested"
        return AgentAdmission(
            ticket,
            "cancellation-requested",
            cancellation_reason="client-requested",
        )

    def acknowledge_cancellation(self, ticket):
        self.calls.append("acknowledge-cancellation")
        self.outcome = "cancelled"
        return AgentAdmission(ticket, "cancelled")

    def complete(self, ticket):
        self.calls.append("complete")
        if self.cancel_on_complete is not None:
            self.cancel_on_complete.set()
        self.outcome = self.complete_outcome
        if self.complete_outcome == "cancellation-requested":
            return AgentAdmission(
                ticket,
                self.complete_outcome,
                cancellation_reason="client-requested",
            )
        return AgentAdmission(ticket, self.complete_outcome)

    def _response(self, ticket):
        if self.outcome == "admitted":
            return AgentAdmission(
                ticket,
                "admitted",
                route=self.route,
                provider_generation=self.generation,
                queue_duration_ms=0,
            )
        return AgentAdmission(ticket, self.outcome)


class CuratorTests(unittest.TestCase):
    def test_request_is_exact_bounded_and_citation_owned(self) -> None:
        wire = {
            "schemaVersion": 1,
            "submissionId": "submission-1",
            "trigger": "explicit-proposal",
            "expectedGenerationSha256": "a" * 64,
            "reviewedContent": "The reviewed release remains blocked.",
            "sourceCitations": [
                {
                    "conceptId": "meetings/job-1",
                    "sourceRevision": "b" * 64,
                    "contentSha256": "c" * 64,
                    "charStart": 0,
                    "charEnd": 28,
                }
            ],
        }
        self.assertEqual(CuratorRequest.from_wire(wire), _request())
        for mutation in (
            {**wire, "schemaVersion": 2},
            {**wire, "schemaVersion": 1.0},
            {**wire, "trigger": []},
            {**wire, "trigger": {}},
            {**wire, "submissionId": True},
            {**wire, "reviewedContent": "x" * 2_049},
            {**wire, "reviewedContent": "\ud800"},
            {**wire, "reviewedContent": "\udfff"},
            {**wire, "route": "complex-orchestration"},
            {**wire, "sourceCitations": []},
            {
                **wire,
                "sourceCitations": [wire["sourceCitations"][0]] * 2,
            },
            {
                **wire,
                "sourceCitations": [wire["sourceCitations"][0]] * 9,
            },
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                CuratorRequest.from_wire(mutation)

        with self.assertRaisesRegex(ValueError, "source citations"):
            replace(
                _request(),
                source_citations=(_citation(start=0, end=20), _citation(start=10)),
            )

    def test_reviewed_student_answer_rebinds_exact_question_lineage(self) -> None:
        item = _evidence().items[0]
        student_question = StudentQuestion(
            "release remains blocked",
            "What should you remember about release remains blocked?",
            (
                StudentQuestionSupport(
                    StudentEvidenceItem(
                        item.citation.concept_id,
                        item.citation.source_revision,
                        item.citation.content_sha256,
                        item.citation.char_start,
                        item.citation.char_end,
                        item.text,
                    ),
                    "release remains blocked",
                ),
            ),
        )
        expected = CuratorReviewedStudentQuestion.from_wire(
            student_question.to_wire()
        )
        request = replace(
            _request(),
            trigger="reviewed-student-answer",
            student_question=expected,
        )
        validate_curator_evidence(request, _evidence())

        wire = {
            "schemaVersion": 1,
            "submissionId": request.submission_id,
            "trigger": request.trigger,
            "expectedGenerationSha256": request.expected_generation_sha256,
            "reviewedContent": request.reviewed_content,
            "studentQuestion": student_question.to_wire(),
        }
        parsed = CuratorRequest.from_wire(wire)
        self.assertEqual(parsed, request)
        self.assertEqual(parsed.student_question.to_wire(), student_question.to_wire())
        self.assertEqual(parsed.source_citations, (_citation(),))
        with self.assertRaisesRegex(ValueError, "Student question"):
            replace(
                expected,
                question="What should you remember about something else?",
            )
        for changed in (
            CuratorReviewedStudentQuestion(
                source_subject=expected.source_subject,
                question=expected.question,
                source_citation=expected.source_citation,
                support_quote="The release",
                support_char_start=0,
                support_char_end=11,
            ),
            replace(expected, support_char_start=3, support_char_end=26),
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_curator_evidence(
                    replace(request, student_question=changed),
                    _evidence(),
                )

        with self.assertRaisesRegex(ValueError, "trigger authority"):
            replace(_request(), student_question=expected)
        with self.assertRaisesRegex(ValueError, "request fields"):
            CuratorRequest.from_wire({**wire, "sourceCitations": []})

    def test_reviewed_student_answer_preserves_a_full_large_source_citation(self) -> None:
        text = "x" * 1_100 + "\nrelease remains blocked\n" + "y" * 1_100
        citation = _citation(start=10, end=10 + len(text))
        item = StudentEvidenceItem(
            citation.concept_id,
            citation.source_revision,
            citation.content_sha256,
            citation.char_start,
            citation.char_end,
            text,
        )
        question = StudentQuestion(
            "release remains blocked",
            "What should you remember about release remains blocked?",
            (StudentQuestionSupport(item, "release remains blocked"),),
        )
        wire = {
            "schemaVersion": 1,
            "submissionId": "submission-large-student",
            "trigger": "reviewed-student-answer",
            "expectedGenerationSha256": "a" * 64,
            "reviewedContent": "The reviewed release remains blocked.",
            "studentQuestion": question.to_wire(),
        }

        request = CuratorRequest.from_wire(wire)
        self.assertEqual(request.source_citations, (citation,))
        evidence = CuratorEvidence.create(
            generation_sha256="a" * 64,
            permission_hash="d" * 64,
            authorization_hash="e" * 64,
            items=(CuratorEvidenceItem(citation, text),),
        )
        validate_curator_evidence(
            request,
            evidence,
        )
        transport = _Transport(_tool_response(), rendered_token_count=2_000)
        self.assertEqual(
            CuratorProposalModel(
                transport=transport,
                model="gemma-complex",
                maximum_output_tokens=512,
            ).review(request, evidence, cancellation=threading.Event()),
            CuratorDecision("propose"),
        )
        self.assertEqual(len(transport.payloads), 1)

    def test_model_can_only_return_one_forced_decision(self) -> None:
        transport = _Transport(_tool_response())
        decision = CuratorProposalModel(
            transport=transport,
            model="gemma-complex",
            maximum_output_tokens=512,
        ).review(_request(), _evidence(), cancellation=threading.Event())

        self.assertEqual(decision, CuratorDecision("propose"))
        payload = transport.payloads[0]
        self.assertEqual(transport.rendered_payloads, [payload])
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["n"], 1)
        self.assertEqual(payload["parallel_tool_calls"], False)
        self.assertEqual(
            payload["tool_choice"],
            {
                "type": "function",
                "function": {"name": "return_curator_decision"},
            },
        )
        self.assertNotIn("response_format", payload)
        visible = json.loads(payload["messages"][1]["content"])
        self.assertEqual(visible["reviewedContent"], _request().reviewed_content)
        self.assertEqual(
            visible["visibleEvidence"],
            [{"text": "The release remains blocked."}],
        )
        self.assertNotIn("sourceCitations", visible)

        empty_content = _tool_response()
        empty_content["choices"][0]["message"]["content"] = ""
        self.assertEqual(
            parse_curator_decision(empty_content),
            CuratorDecision("propose"),
        )

    def test_model_rejects_wrong_or_ambiguous_tool_responses(self) -> None:
        invalid = (
            {},
            {"choices": []},
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": _tool_response()["choices"][0]["message"][
                                "tool_calls"
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "other",
                                        "arguments": '{"decision":"propose"}',
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            _tool_response("maybe"),
            _tool_response([]),
            _tool_response({}),
            _tool_response(None),
            {
                "choices": [
                    {
                        "message": {
                            "content": " ",
                            "tool_calls": _tool_response()["choices"][0]["message"][
                                "tool_calls"
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "also publish this prose",
                            "tool_calls": _tool_response()["choices"][0]["message"][
                                "tool_calls"
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "curator-decision-1",
                                    "type": "not-function",
                                    "function": {
                                        "name": "return_curator_decision",
                                        "arguments": '{"decision":"propose"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "return_curator_decision",
                                        "arguments": (
                                            '{"decision":"propose",'
                                            '"decision":"reject"}'
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )
        for response in invalid:
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_curator_decision(response)

        nested = _tool_response()
        nested["choices"][0]["message"]["tool_calls"][0]["function"][
            "arguments"
        ] = "[" * 5_000 + "]" * 5_000
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            parse_curator_decision(nested)

    def test_evidence_hash_binds_every_server_owned_identity_and_byte(self) -> None:
        evidence = _evidence()
        validate_curator_evidence(_request(), evidence)
        for changed in (
            replace(evidence, evidence_sha256="0" * 64),
            replace(evidence, permission_hash="0" * 64),
            replace(
                evidence,
                items=(replace(evidence.items[0], text="A" * 28),),
            ),
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_curator_evidence(_request(), changed)

        unicode_request = replace(_request(), reviewed_content="😀" * 2_048)
        unicode_citations = tuple(
            _citation(concept_id=f"meetings/job-{index}", end=1_024)
            for index in range(8)
        )
        unicode_evidence = CuratorEvidence.create(
            generation_sha256="a" * 64,
            permission_hash="d" * 64,
            authorization_hash="e" * 64,
            items=tuple(
                CuratorEvidenceItem(citation, "漢" * 1_024)
                for citation in unicode_citations
            ),
        )
        unicode_request = replace(
            unicode_request,
            source_citations=unicode_citations,
        )
        validate_curator_evidence(unicode_request, unicode_evidence)
        accepted_transport = _Transport(
            _tool_response(),
            rendered_token_count=7_680,
        )
        self.assertEqual(
            CuratorProposalModel(
                transport=accepted_transport,
                model="gemma-complex",
                maximum_output_tokens=512,
            ).review(
                unicode_request,
                unicode_evidence,
                cancellation=threading.Event(),
            ),
            CuratorDecision("propose"),
        )

        rejected_transport = _Transport(
            _tool_response(),
            rendered_token_count=7_681,
        )
        with self.assertRaisesRegex(ValueError, "context bound"):
            CuratorProposalModel(
                transport=rejected_transport,
                model="gemma-complex",
                maximum_output_tokens=512,
            ).review(
                unicode_request,
                unicode_evidence,
                cancellation=threading.Event(),
            )
        self.assertEqual(rejected_transport.payloads, [])

    def test_service_publishes_once_after_exact_admission_completion(self) -> None:
        admission = _Admission()
        reader = _EvidenceReader()
        reviewer = _Reviewer()
        publisher = _Publisher()
        auditor = _Auditor()
        service = CuratorService(
            admission=admission,
            evidence_reader=reader,
            reviewer=reviewer,
            publisher=publisher,
            result_auditor=auditor,
        )

        result = service.propose(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(result.status, "proposed")
        self.assertEqual(result.proposal_id, "f" * 64)
        self.assertEqual(publisher.calls, 1)
        self.assertEqual(reviewer.calls, 1)
        self.assertEqual(admission.calls[-2:], ["status", "complete"])
        self.assertEqual(admission.submission["work"].role, AgentRole.CURATOR)
        self.assertEqual(
            admission.submission["work"].purpose,
            AgentPurpose.KNOWLEDGE_PROPOSE,
        )
        self.assertEqual(
            admission.submission["work"].route,
            ExecutionRoute.COMPLEX_ORCHESTRATION,
        )
        self.assertEqual(
            admission.submission["work"].scheduling_class,
            SchedulingClass.BACKGROUND_LLM,
        )
        self.assertEqual(
            admission.submission["source_sha256"],
            curator_work_sha256(_request(), _evidence()),
        )
        self.assertEqual(auditor.records, [])

    def test_rejection_and_invalid_output_never_publish_or_retry(self) -> None:
        for reviewer, expected_status, expected_reason in (
            (_Reviewer(CuratorDecision("reject")), "rejected", "model-rejected"),
            (_Reviewer(error=ValueError("bad output")), "failed", "invalid-output"),
        ):
            with self.subTest(reason=expected_reason):
                admission = _Admission()
                publisher = _Publisher()
                auditor = _Auditor()
                result = CuratorService(
                    admission=admission,
                    evidence_reader=_EvidenceReader(),
                    reviewer=reviewer,
                    publisher=publisher,
                    result_auditor=auditor,
                ).propose(
                    _request(),
                    principal=_principal(),
                    cancellation=threading.Event(),
                )
                self.assertEqual(result.status, expected_status)
                self.assertEqual(result.reason, expected_reason)
                self.assertEqual(publisher.calls, 0)
                self.assertEqual(reviewer.calls, 1)
                self.assertEqual(auditor.records[0]["status"], expected_status)
                self.assertEqual(auditor.records[0]["reason"], expected_reason)
                self.assertEqual(admission.calls[-2:], ["status", "complete"])

    def test_stored_submission_is_replayed_without_evidence_or_model_work(self) -> None:
        stored = CuratorStoredResult(
            request_id="curator-original",
            submission_id="submission-1",
            request_sha256=curator_request_sha256(_request()),
            generation_sha256="a" * 64,
            evidence_sha256=_evidence().evidence_sha256,
            proposal_id="f" * 64,
            proposal_permission_hash="2" * 64,
            proposal_authorization_hash="3" * 64,
            provider_generation=9,
            status="proposed",
            reason=None,
        )
        reader = _EvidenceReader()
        reviewer = _Reviewer()
        publisher = _Publisher()
        result = CuratorService(
            admission=_Admission(),
            evidence_reader=reader,
            reviewer=reviewer,
            publisher=publisher,
            result_auditor=_Auditor(stored),
        ).propose(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )
        self.assertEqual(result.request_id, "curator-original")
        self.assertEqual(result.status, "proposed")
        self.assertEqual(reader.calls, 0)
        self.assertEqual(reviewer.calls, 0)
        self.assertEqual(publisher.calls, 0)

        conflicting = replace(stored, request_sha256="0" * 64)
        with self.assertRaisesRegex(
            CuratorServiceError,
            "already belongs to other content",
        ):
            CuratorService(
                admission=_Admission(),
                evidence_reader=_EvidenceReader(),
                reviewer=_Reviewer(),
                publisher=_Publisher(),
                result_auditor=_Auditor(conflicting),
            ).propose(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )

    def test_publication_timeout_is_a_terminal_failed_result(self) -> None:
        for error in (
            QueryCanceled("statement timeout"),
            LockNotAvailable("lock timeout"),
        ):
            with self.subTest(error=type(error).__name__):
                auditor = _Auditor()
                result = CuratorService(
                    admission=_Admission(),
                    evidence_reader=_EvidenceReader(),
                    reviewer=_Reviewer(),
                    publisher=_Publisher(error=error),
                    result_auditor=auditor,
                ).propose(
                    _request(),
                    principal=_principal(),
                    cancellation=threading.Event(),
                )

                self.assertEqual(result.status, "failed")
                self.assertEqual(result.reason, "storage-timeout")
                self.assertEqual(auditor.records[0]["reason"], "storage-timeout")

    def test_completion_cancellation_race_is_acknowledged_and_never_published(self) -> None:
        admission = _Admission(complete_outcome="cancellation-requested")
        publisher = _Publisher()
        auditor = _Auditor()
        result = CuratorService(
            admission=admission,
            evidence_reader=_EvidenceReader(),
            reviewer=_Reviewer(),
            publisher=publisher,
            result_auditor=auditor,
        ).propose(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.reason, "client-cancelled")
        self.assertEqual(admission.calls[-2:], ["complete", "acknowledge-cancellation"])
        self.assertEqual(publisher.calls, 0)
        self.assertEqual(auditor.records[0]["status"], "cancelled")

    def test_caller_cancellation_before_dispatch_or_publication_never_publishes(
        self,
    ) -> None:
        for cancel_during_completion in (False, True):
            with self.subTest(cancel_during_completion=cancel_during_completion):
                cancellation = threading.Event()
                if not cancel_during_completion:
                    cancellation.set()
                publisher = _Publisher()
                auditor = _Auditor()
                result = CuratorService(
                    admission=_Admission(
                        cancel_on_complete=(
                            cancellation if cancel_during_completion else None
                        )
                    ),
                    evidence_reader=_EvidenceReader(),
                    reviewer=_Reviewer(),
                    publisher=publisher,
                    result_auditor=auditor,
                ).propose(
                    _request(),
                    principal=_principal(),
                    cancellation=cancellation,
                )

                self.assertEqual(result.status, "cancelled")
                self.assertEqual(result.reason, "client-cancelled")
                self.assertEqual(publisher.calls, 0)
                self.assertEqual(auditor.records[0]["status"], "cancelled")

    def test_terminal_status_race_records_failure_and_never_publishes(self) -> None:
        for outcome, reason in (
            ("deadline-exceeded", "deadline-exceeded"),
            ("provider-unavailable", "provider-unavailable"),
        ):
            with self.subTest(outcome=outcome):
                admission = _Admission(post_model_outcome=outcome)
                publisher = _Publisher()
                auditor = _Auditor()
                result = CuratorService(
                    admission=admission,
                    evidence_reader=_EvidenceReader(),
                    reviewer=_Reviewer(),
                    publisher=publisher,
                    result_auditor=auditor,
                ).propose(
                    _request(),
                    principal=_principal(),
                    cancellation=threading.Event(),
                )

                self.assertEqual(result.status, "cancelled")
                self.assertEqual(result.reason, reason)
                self.assertEqual(publisher.calls, 0)
                self.assertEqual(auditor.records[0]["reason"], reason)

    def test_queued_terminal_states_are_audited_and_unknown_state_is_contained(
        self,
    ) -> None:
        for outcome, reason in (
            ("deadline-exceeded", "deadline-exceeded"),
            ("provider-unavailable", "provider-unavailable"),
            ("cancelled", "client-cancelled"),
        ):
            with self.subTest(outcome=outcome):
                auditor = _Auditor()
                result = CuratorService(
                    admission=_Admission(
                        initial_outcome="queued",
                        queued_status_outcome=outcome,
                    ),
                    evidence_reader=_EvidenceReader(),
                    reviewer=_Reviewer(),
                    publisher=_Publisher(),
                    result_auditor=auditor,
                ).propose(
                    _request(),
                    principal=_principal(),
                    cancellation=threading.Event(),
                )
                self.assertEqual(result.status, "cancelled")
                self.assertEqual(result.reason, reason)
                self.assertEqual(auditor.records[0]["reason"], reason)

        admission = _Admission(
            initial_outcome="queued",
            queued_status_outcome="not-found-or-unauthorized",
        )
        with self.assertRaisesRegex(CuratorContainmentError, "unknown state"):
            CuratorService(
                admission=admission,
                evidence_reader=_EvidenceReader(),
                reviewer=_Reviewer(),
                publisher=_Publisher(),
                result_auditor=_Auditor(),
            ).propose(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )
        self.assertIn("cancel", admission.calls)

    def test_deadline_before_submit_is_durably_terminal_without_broker_work(self) -> None:
        admission = _Admission()
        auditor = _Auditor()
        with patch(
            "yap_server.agents.curator_service._remaining_deadline_ms",
            side_effect=CuratorServiceError(
                504,
                "CURATOR_DEADLINE",
                "expired",
                retryable=True,
            ),
        ):
            result = CuratorService(
                admission=admission,
                evidence_reader=_EvidenceReader(),
                reviewer=_Reviewer(),
                publisher=_Publisher(),
                result_auditor=auditor,
            ).propose(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "deadline-exceeded")
        self.assertNotIn("submit", admission.calls)
        self.assertEqual(auditor.records[0]["reason"], "deadline-exceeded")

    def test_uncontained_publication_is_never_recorded_as_an_ordinary_failure(self) -> None:
        auditor = _Auditor()
        with self.assertRaisesRegex(CuratorContainmentError, "was not contained"):
            CuratorService(
                admission=_Admission(),
                evidence_reader=_EvidenceReader(),
                reviewer=_Reviewer(),
                publisher=_Publisher(
                    error=KnowledgeToolCancellationFailed("close failed")
                ),
                result_auditor=auditor,
            ).propose(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )
        self.assertEqual(auditor.records, [])

    def test_terminal_admission_result_is_replayed_instead_of_raising_capacity(self) -> None:
        winner = CuratorStoredResult(
            request_id="curator-winner",
            submission_id="submission-1",
            request_sha256=curator_request_sha256(_request()),
            generation_sha256="a" * 64,
            evidence_sha256=_evidence().evidence_sha256,
            proposal_id="f" * 64,
            proposal_permission_hash="2" * 64,
            proposal_authorization_hash="3" * 64,
            provider_generation=9,
            status="proposed",
            reason=None,
        )

        class _RacingAuditor(_Auditor):
            def read(self, *, principal, submission_id):
                del principal, submission_id
                return winner if self.records else None

            def record(self, **value):
                self.records.append(value)
                raise ValueError("curator result audit identity conflicts")

        admission = _Admission()
        admission.outcome = "queue-full"
        result = CuratorService(
            admission=admission,
            evidence_reader=_EvidenceReader(),
            reviewer=_Reviewer(),
            publisher=_Publisher(),
            result_auditor=_RacingAuditor(),
        ).propose(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )
        self.assertEqual(result.request_id, "curator-winner")
        self.assertEqual(result.status, "proposed")

    def test_admission_capacity_returns_the_same_durable_failed_view_shape(self) -> None:
        admission = _Admission(initial_outcome="queue-full")
        auditor = _Auditor()
        publisher = _Publisher()
        result = CuratorService(
            admission=admission,
            evidence_reader=_EvidenceReader(),
            reviewer=_Reviewer(),
            publisher=publisher,
            result_auditor=auditor,
        ).propose(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "capacity-unavailable")
        self.assertEqual(result.to_wire()["reason"], "capacity-unavailable")
        self.assertEqual(auditor.records[0]["status"], "failed")
        self.assertEqual(auditor.records[0]["reason"], "capacity-unavailable")
        self.assertEqual(publisher.calls, 0)


if __name__ == "__main__":
    unittest.main()
