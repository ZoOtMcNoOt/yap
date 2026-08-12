from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from yap_server.agents.transcript_correction import (
    TranscriptCorrectionProposedEdit,
    TranscriptCorrectionRequest,
)
from yap_server.agents.transcript_correction_service import TranscriptCorrectionJobView
from yap_server.evaluation.transcript_correction_corpus import (
    TranscriptCorrectionQualificationCase,
    TranscriptCorrectionQualificationCorpus,
    load_private_transcript_correction_corpus,
)
from yap_server.evaluation.transcript_correction_qualification import (
    TranscriptCorrectionAcceptance,
    evaluate_transcript_correction_qualification,
    load_transcript_correction_acceptance,
)
from yap_server.evaluation.transcript_correction_source_evidence import (
    TranscriptCorrectionSourceCase,
    TranscriptCorrectionSourceEvidence,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request(
    text: str,
    *,
    language_bcp47: str = "en-US",
) -> TranscriptCorrectionRequest:
    return TranscriptCorrectionRequest.from_wire(
        {
            "schemaVersion": 1,
            "sourceRevisionSha256": _sha256(f"revision:{text}"),
            "sourceSha256": _sha256(text),
            "segments": [
                {
                    "segmentId": "segment-1",
                    "startCharacter": 0,
                    "endCharacter": len(text),
                    "startMilliseconds": 0,
                    "endMilliseconds": 1_000,
                    "languageBcp47": language_bcp47,
                    "text": text,
                    "textSha256": _sha256(text),
                }
            ],
        }
    )


def _source_evidence(
    source: str,
    reference: str,
    *,
    audio_sha256: str = "e" * 64,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "privacyScope": "private-case-evidence",
        "aggregate": {},
        "cases": [
            {
                "audio": {
                    "decodedPcmSha256": audio_sha256,
                    "durationSamples": 16_000,
                    "encodedPcmWavSha256": "d" * 64,
                    "sampleRateHz": 16_000,
                },
                "caseIndex": 0,
                "hypothesis": source,
                "promptId": 1,
                "reference": reference,
                "score": {"languageBcp47": "en-US"},
                "sourceItemId": "source-case-1",
            }
        ],
    }


def _loaded_source_evidence(
    evidence_sha256: str,
    source: str,
    reference: str,
    *,
    audio_sha256: str = "e" * 64,
) -> dict[str, TranscriptCorrectionSourceEvidence]:
    return {
        evidence_sha256: TranscriptCorrectionSourceEvidence(
            evidence_sha256=evidence_sha256,
            cases={
                "source-case-1": TranscriptCorrectionSourceCase(
                    case_id="source-case-1",
                    audio_sha256=audio_sha256,
                    language_bcp47="en-US",
                    duration_milliseconds=1_000,
                    hypothesis=source,
                    reference=reference,
                )
            },
        )
    }


def _case(
    case_id: str,
    owner_id: str,
    source: str,
    reference: str,
    *,
    source_kind: str,
    disposition: str,
    critical_tokens: tuple[str, ...] = (),
    language_bcp47: str = "en-US",
) -> TranscriptCorrectionQualificationCase:
    reviewed_edits = (
        (
            TranscriptCorrectionProposedEdit(
                segment_id="segment-1",
                segment_sha256=_sha256(source),
                source_text="doasge",
                replacement_text="dosage",
            ),
        )
        if disposition == "corrected"
        else ()
    )
    basis = {
        "corrected": "reviewed-safe-correction",
        "source-preserved": "protected-reference-change",
        "uncertain": "reviewed-unsafe-ambiguity",
        "unchanged": "reference-identical",
    }[disposition]
    return TranscriptCorrectionQualificationCase(
        case_id=case_id,
        source_kind=source_kind,
        source_evidence_sha256=("f" * 64 if source_kind == "real-asr" else None),
        source_evidence_case_id=(case_id if source_kind == "real-asr" else None),
        source_audio_sha256=(
            hashlib.sha256(f"audio:{case_id}".encode()).hexdigest()
            if source_kind == "real-asr"
            else None
        ),
        owner_id=owner_id,
        expected_disposition=disposition,
        expected_disposition_basis=basis,
        request=_request(source, language_bcp47=language_bcp47),
        reference_text=reference,
        critical_tokens=critical_tokens,
        reviewed_correction_edits=reviewed_edits,
    )


def _acceptance() -> TranscriptCorrectionAcceptance:
    return TranscriptCorrectionAcceptance(
        plan_sha256="a" * 64,
        minimum_case_count=2,
        minimum_real_asr_case_count=1,
        minimum_english_real_asr_case_count=1,
        minimum_spanish_real_asr_case_count=0,
        minimum_safety_probe_case_count=1,
        minimum_corrected_case_count=1,
        minimum_source_preserved_case_count=0,
        minimum_uncertain_case_count=0,
        minimum_unchanged_case_count=1,
        minimum_owner_count=2,
        concurrent_request_count=2,
        maximum_p95_latency_milliseconds=1_000,
        minimum_relative_word_error_reduction=0.5,
        minimum_expected_disposition_rate=1.0,
        maximum_uncertain_rate=1.0,
        maximum_regressed_case_count=0,
        maximum_insertion_increase_count=0,
        maximum_deletion_increase_count=0,
        maximum_critical_token_miss_increase_count=0,
        maximum_terminal_failure_count=0,
    )


def _admission_state(process_id: int = 41) -> dict[str, object]:
    return {
        "processId": process_id,
        "processStartTicks": 17,
        "binarySha256": "9" * 64,
        "socketDevice": 1,
        "socketInode": 2,
    }


class _Service:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._views: dict[tuple[str, str], TranscriptCorrectionJobView] = {}
        self._next = 0
        self.active = 0
        self.maximum_active = 0

    def submit(self, request, *, principal):
        with self._lock:
            self._next += 1
            request_id = f"request-{self._next}"
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        time.sleep(0.04)
        corrected = request.source_text.replace("doasge", "dosage")
        view = TranscriptCorrectionJobView(
            request_id=request_id,
            status="complete",
            source_revision_sha256=request.source_revision_sha256,
            source_sha256=request.source_sha256,
            terminology_snapshot_sha256="c" * 64,
            applied=corrected != request.source_text,
            corrected_text=corrected,
            reason=None if corrected != request.source_text else "unchanged",
        )
        with self._lock:
            self.active -= 1
            self._views[(principal.subject_id, request_id)] = view
        return view

    def get(self, request_id, *, principal):
        with self._lock:
            return self._views.get((principal.subject_id, request_id))

    def cancel(self, request_id, *, principal):
        del request_id, principal
        return False


class _QueuedService:
    def __init__(self, *, contain: bool) -> None:
        self._lock = threading.Lock()
        self._contain = contain
        self._cancelled = False
        self.cancel_count = 0

    def submit(self, request, *, principal):
        del principal
        return TranscriptCorrectionJobView(
            request_id="queued-request",
            status="queued",
            source_revision_sha256=request.source_revision_sha256,
            source_sha256=request.source_sha256,
            terminology_snapshot_sha256="c" * 64,
            applied=False,
        )

    def get(self, request_id, *, principal):
        del request_id, principal
        with self._lock:
            status = "cancelled" if self._cancelled else "queued"
        return TranscriptCorrectionJobView(
            request_id="queued-request",
            status=status,
            source_revision_sha256="a" * 64,
            source_sha256="b" * 64,
            terminology_snapshot_sha256="c" * 64,
            applied=False,
            reason="client-cancelled" if status == "cancelled" else None,
        )

    def cancel(self, request_id, *, principal):
        del request_id, principal
        with self._lock:
            self.cancel_count += 1
            if self._contain:
                self._cancelled = True
        return self._contain


class _InvalidOutputService(_Service):
    def submit(self, request, *, principal):
        with self._lock:
            self._next += 1
            request_id = f"request-{self._next}"
            view = TranscriptCorrectionJobView(
                request_id=request_id,
                status="complete",
                source_revision_sha256=request.source_revision_sha256,
                source_sha256=request.source_sha256,
                terminology_snapshot_sha256="c" * 64,
                applied=False,
                corrected_text=request.source_text,
                reason="invalid-output",
            )
            self._views[(principal.subject_id, request_id)] = view
        return view


class _RegressingEditService(_Service):
    def submit(self, request, *, principal):
        with self._lock:
            self._next += 1
            request_id = f"request-{self._next}"
            corrected = f"{request.source_text} invented"
            view = TranscriptCorrectionJobView(
                request_id=request_id,
                status="complete",
                source_revision_sha256=request.source_revision_sha256,
                source_sha256=request.source_sha256,
                terminology_snapshot_sha256="c" * 64,
                applied=True,
                corrected_text=corrected,
            )
            self._views[(principal.subject_id, request_id)] = view
        return view


class TranscriptCorrectionQualificationTests(unittest.TestCase):
    def test_private_corpus_is_exact_strict_owner_private_and_source_bound(self) -> None:
        source = "The doasge is correct."
        source_evidence = _source_evidence(source, "The dosage is correct.")
        source_body = json.dumps(
            source_evidence,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        value = {
            "schemaVersion": 3,
            "corpusId": "scribe-private-v1",
            "cases": [
                {
                    "caseId": "real-1",
                    "sourceKind": "real-asr",
                    "sourceEvidenceSha256": hashlib.sha256(source_body).hexdigest(),
                    "sourceEvidenceCaseId": "source-case-1",
                    "sourceAudioSha256": "e" * 64,
                    "ownerId": "owner-1",
                    "expectedDisposition": "corrected",
                    "expectedDispositionBasis": "reviewed-safe-correction",
                    "request": _request(source).to_wire(),
                    "referenceText": "The dosage is correct.",
                    "criticalTokens": [],
                    "reviewedCorrectionEdits": [
                        {
                            "segmentId": "segment-1",
                            "segmentSha256": _sha256(source),
                            "sourceText": "doasge",
                            "replacementText": "dosage",
                        }
                    ],
                }
            ],
            "terminology": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            path = root / "corpus.json"
            body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            path.write_bytes(body)
            path.chmod(0o600)
            evidence_sha256 = hashlib.sha256(source_body).hexdigest()
            with mock.patch(
                "yap_server.evaluation.transcript_correction_corpus."
                "load_private_transcript_correction_source_evidence",
                return_value=_loaded_source_evidence(
                    evidence_sha256,
                    source,
                    "The dosage is correct.",
                ),
            ):
                loaded = load_private_transcript_correction_corpus(
                    path,
                    expected_sha256=hashlib.sha256(body).hexdigest(),
                    repository_root=REPOSITORY_ROOT,
                    source_evidence_paths=(),
                )
            self.assertEqual(loaded.corpus_id, "scribe-private-v1")
            self.assertEqual(loaded.cases[0].request.source_text, source)

            value["cases"][0]["reviewedCorrectionEdits"][0][
                "replacementText"
            ] = "dosagex"
            changed = json.dumps(
                value,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            path.write_bytes(changed)
            with (
                mock.patch(
                    "yap_server.evaluation.transcript_correction_corpus."
                    "load_private_transcript_correction_source_evidence",
                    return_value=_loaded_source_evidence(
                        evidence_sha256,
                        source,
                        "The dosage is correct.",
                    ),
                ),
                self.assertRaisesRegex(ValueError, "does not improve word error"),
            ):
                load_private_transcript_correction_corpus(
                    path,
                    expected_sha256=hashlib.sha256(changed).hexdigest(),
                    repository_root=REPOSITORY_ROOT,
                    source_evidence_paths=(),
                )
            value["cases"][0]["reviewedCorrectionEdits"][0][
                "replacementText"
            ] = "dosage"

            value["schemaVersion"] = 2
            changed = json.dumps(
                value,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            path.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "schema differs"):
                load_private_transcript_correction_corpus(
                    path,
                    expected_sha256=hashlib.sha256(changed).hexdigest(),
                    repository_root=REPOSITORY_ROOT,
                    source_evidence_paths=(),
                )
            value["schemaVersion"] = 3

            value["cases"][0]["unexpected"] = True
            changed = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            path.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "shape differs"):
                load_private_transcript_correction_corpus(
                    path,
                    expected_sha256=hashlib.sha256(changed).hexdigest(),
                    repository_root=REPOSITORY_ROOT,
                    source_evidence_paths=(),
                )

    def test_acceptance_plan_is_strict_and_hash_bound(self) -> None:
        path = REPOSITORY_ROOT / "server/transcript-correction-acceptance.json"
        acceptance = load_transcript_correction_acceptance(path)
        self.assertEqual(acceptance.concurrent_request_count, 8)
        self.assertEqual(acceptance.minimum_real_asr_case_count, 16)
        self.assertEqual(acceptance.minimum_english_real_asr_case_count, 8)
        self.assertEqual(acceptance.minimum_spanish_real_asr_case_count, 8)
        self.assertEqual(acceptance.minimum_corrected_case_count, 8)
        self.assertEqual(acceptance.minimum_source_preserved_case_count, 8)
        self.assertEqual(acceptance.minimum_uncertain_case_count, 2)
        self.assertEqual(acceptance.minimum_unchanged_case_count, 6)
        self.assertEqual(acceptance.plan_sha256, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_private_corpus_binds_safe_fallback_and_uncertainty_meanings(self) -> None:
        real_source = "Alice approved the release."
        real_reference = "Bob approved the release."
        source_body = json.dumps(
            _source_evidence(real_source, real_reference),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        uncertain_source = "The result was [inaudible]."
        value = {
            "schemaVersion": 3,
            "corpusId": "scribe-private-v3",
            "cases": [
                {
                    "caseId": "real-preserved",
                    "sourceKind": "real-asr",
                    "sourceEvidenceSha256": hashlib.sha256(source_body).hexdigest(),
                    "sourceEvidenceCaseId": "source-case-1",
                    "sourceAudioSha256": "e" * 64,
                    "ownerId": "owner-1",
                    "expectedDisposition": "source-preserved",
                    "expectedDispositionBasis": "protected-reference-change",
                    "request": _request(real_source).to_wire(),
                    "referenceText": real_reference,
                    "criticalTokens": ["Bob"],
                    "reviewedCorrectionEdits": [],
                },
                {
                    "caseId": "safety-uncertain",
                    "sourceKind": "safety-probe",
                    "sourceEvidenceSha256": None,
                    "sourceEvidenceCaseId": None,
                    "sourceAudioSha256": None,
                    "ownerId": "owner-2",
                    "expectedDisposition": "uncertain",
                    "expectedDispositionBasis": "reviewed-unsafe-ambiguity",
                    "request": _request(uncertain_source).to_wire(),
                    "referenceText": "The result was approved.",
                    "criticalTokens": [],
                    "reviewedCorrectionEdits": [],
                },
            ],
            "terminology": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            path = root / "corpus.json"
            body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            path.write_bytes(body)
            path.chmod(0o600)
            evidence_sha256 = hashlib.sha256(source_body).hexdigest()
            with mock.patch(
                "yap_server.evaluation.transcript_correction_corpus."
                "load_private_transcript_correction_source_evidence",
                return_value=_loaded_source_evidence(
                    evidence_sha256,
                    real_source,
                    real_reference,
                ),
            ):
                loaded = load_private_transcript_correction_corpus(
                    path,
                    expected_sha256=hashlib.sha256(body).hexdigest(),
                    repository_root=REPOSITORY_ROOT,
                    source_evidence_paths=(),
                )
            self.assertEqual(
                [case.expected_disposition for case in loaded.cases],
                ["source-preserved", "uncertain"],
            )

    def test_private_corpus_rejects_reused_real_audio_identity(self) -> None:
        source = "The doasge is correct."
        case = {
            "caseId": "real-1",
            "sourceKind": "real-asr",
            "sourceEvidenceSha256": "f" * 64,
            "sourceEvidenceCaseId": "source-case-1",
            "sourceAudioSha256": "e" * 64,
            "ownerId": "owner-1",
            "expectedDisposition": "corrected",
            "expectedDispositionBasis": "reviewed-safe-correction",
            "request": _request(source).to_wire(),
            "referenceText": "The dosage is correct.",
            "criticalTokens": [],
            "reviewedCorrectionEdits": [
                {
                    "segmentId": "segment-1",
                    "segmentSha256": _sha256(source),
                    "sourceText": "doasge",
                    "replacementText": "dosage",
                }
            ],
        }
        value = {
            "schemaVersion": 3,
            "corpusId": "scribe-private-v2",
            "cases": [case, {**case, "caseId": "real-2", "ownerId": "owner-2"}],
            "terminology": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            path = root / "corpus.json"
            body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            path.write_bytes(body)
            path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "audio identity is duplicated"):
                load_private_transcript_correction_corpus(
                    path,
                    expected_sha256=hashlib.sha256(body).hexdigest(),
                    repository_root=REPOSITORY_ROOT,
                    source_evidence_paths=(),
                )

    def test_private_corpus_rejects_changed_real_asr_source_binding(self) -> None:
        source = "The doasge is correct."
        source_body = json.dumps(
            _source_evidence(source, "The dosage is correct."),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        value = {
            "schemaVersion": 3,
            "corpusId": "scribe-private-v2",
            "cases": [
                {
                    "caseId": "real-1",
                    "sourceKind": "real-asr",
                    "sourceEvidenceSha256": hashlib.sha256(source_body).hexdigest(),
                    "sourceEvidenceCaseId": "source-case-1",
                    "sourceAudioSha256": "c" * 64,
                    "ownerId": "owner-1",
                    "expectedDisposition": "corrected",
                    "expectedDispositionBasis": "reviewed-safe-correction",
                    "request": _request(source).to_wire(),
                    "referenceText": "The dosage is correct.",
                    "criticalTokens": [],
                    "reviewedCorrectionEdits": [
                        {
                            "segmentId": "segment-1",
                            "segmentSha256": _sha256(source),
                            "sourceText": "doasge",
                            "replacementText": "dosage",
                        }
                    ],
                }
            ],
            "terminology": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            path = root / "corpus.json"
            body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            path.write_bytes(body)
            path.chmod(0o600)
            evidence_sha256 = hashlib.sha256(source_body).hexdigest()
            with (
                mock.patch(
                    "yap_server.evaluation.transcript_correction_corpus."
                    "load_private_transcript_correction_source_evidence",
                    return_value=_loaded_source_evidence(
                        evidence_sha256,
                        source,
                        "The dosage is correct.",
                    ),
                ),
                self.assertRaisesRegex(ValueError, "source binding differs"),
            ):
                load_private_transcript_correction_corpus(
                    path,
                    expected_sha256=hashlib.sha256(body).hexdigest(),
                    repository_root=REPOSITORY_ROOT,
                    source_evidence_paths=(),
                )

    def test_language_specific_real_asr_coverage_is_mandatory(self) -> None:
        corpus = TranscriptCorrectionQualificationCorpus(
            corpus_id="scribe-private-v2",
            corpus_sha256="b" * 64,
            cases=(
                _case(
                    "real-1",
                    "owner-1",
                    "The doasge is correct.",
                    "The dosage is correct.",
                    source_kind="real-asr",
                    disposition="corrected",
                ),
                _case(
                    "safety-1",
                    "owner-2",
                    "The dose is 25 mg.",
                    "The dose is 25 mg.",
                    source_kind="safety-probe",
                    disposition="unchanged",
                ),
            ),
            terminology=(),
        )
        acceptance = replace(
            _acceptance(),
            minimum_english_real_asr_case_count=1,
            minimum_spanish_real_asr_case_count=1,
        )
        state = {
            "state": "ready",
            "profileId": "rapid-automation",
            "profileSha256": "d" * 64,
            "candidateLockSha256": "e" * 64,
            "processGeneration": 7,
            "startCount": 1,
            "restartCount": 0,
        }
        result = evaluate_transcript_correction_qualification(
            service=_Service(),
            corpus=corpus,
            acceptance=acceptance,
            observe_warm_state=lambda: state,
            observe_admission_state=_admission_state,
        )
        self.assertEqual(result.public_evidence["outcome"], "deterministic-no-scribe")
        self.assertTrue(result.public_evidence["acceptance"]["englishCoverageMet"])
        self.assertFalse(result.public_evidence["acceptance"]["spanishCoverageMet"])

    def test_multi_owner_warm_wave_qualifies_without_public_transcript_content(self) -> None:
        corpus = TranscriptCorrectionQualificationCorpus(
            corpus_id="scribe-private-v1",
            corpus_sha256="b" * 64,
            cases=(
                _case(
                    "real-1",
                    "owner-1",
                    "The doasge is correct.",
                    "The dosage is correct.",
                    source_kind="real-asr",
                    disposition="corrected",
                ),
                _case(
                    "safety-1",
                    "owner-2",
                    "The dose is 25 mg.",
                    "The dose is 25 mg.",
                    source_kind="safety-probe",
                    disposition="unchanged",
                    critical_tokens=("25 mg",),
                ),
            ),
            terminology=(),
        )
        service = _Service()
        state = {
            "state": "ready",
            "profileId": "rapid-automation",
            "profileSha256": "d" * 64,
            "candidateLockSha256": "e" * 64,
            "processGeneration": 7,
            "startCount": 1,
            "restartCount": 0,
        }
        result = evaluate_transcript_correction_qualification(
            service=service,
            corpus=corpus,
            acceptance=_acceptance(),
            observe_warm_state=lambda: state,
            observe_admission_state=_admission_state,
        )

        self.assertEqual(
            result.public_evidence["outcome"],
            "scribe-transcript-correction-qualified",
        )
        self.assertEqual(service.maximum_active, 2)
        self.assertEqual(
            result.public_evidence["route"]["maximumConcurrentOwnerCount"],
            2,
        )
        self.assertTrue(result.public_evidence["route"]["allWaveOwnersDistinct"])
        public_text = json.dumps(result.public_evidence, sort_keys=True)
        self.assertNotIn("doasge", public_text)
        self.assertNotIn("25 mg", public_text)
        self.assertIn("doasge", json.dumps(result.private_evidence))

    def test_same_owner_concurrent_wave_is_rejected(self) -> None:
        corpus = TranscriptCorrectionQualificationCorpus(
            corpus_id="scribe-private-v1",
            corpus_sha256="b" * 64,
            cases=(
                _case(
                    "real-1",
                    "owner-1",
                    "The doasge is correct.",
                    "The dosage is correct.",
                    source_kind="real-asr",
                    disposition="corrected",
                ),
                _case(
                    "safety-1",
                    "owner-1",
                    "The dose is 25 mg.",
                    "The dose is 25 mg.",
                    source_kind="safety-probe",
                    disposition="unchanged",
                ),
            ),
            terminology=(),
        )
        acceptance = replace(_acceptance(), minimum_owner_count=1)
        warm = {
            "state": "ready",
            "profileId": "rapid-automation",
            "profileSha256": "d" * 64,
            "candidateLockSha256": "e" * 64,
            "processGeneration": 7,
            "startCount": 1,
            "restartCount": 0,
        }

        result = evaluate_transcript_correction_qualification(
            service=_Service(),
            corpus=corpus,
            acceptance=acceptance,
            observe_warm_state=lambda: warm,
            observe_admission_state=_admission_state,
        )

        self.assertEqual(result.public_evidence["outcome"], "deterministic-no-scribe")
        self.assertFalse(result.public_evidence["acceptance"]["concurrentOwnersMet"])
        self.assertFalse(result.public_evidence["route"]["allWaveOwnersDistinct"])

    def test_invalid_output_fallback_does_not_satisfy_unchanged_disposition(
        self,
    ) -> None:
        corpus = TranscriptCorrectionQualificationCorpus(
            corpus_id="scribe-private-v1",
            corpus_sha256="b" * 64,
            cases=(
                _case(
                    "safety-1",
                    "owner-1",
                    "The dose is 25 mg.",
                    "The dose is 25 mg.",
                    source_kind="safety-probe",
                    disposition="unchanged",
                ),
            ),
            terminology=(),
        )
        acceptance = replace(
            _acceptance(),
            minimum_case_count=1,
            minimum_real_asr_case_count=0,
            minimum_english_real_asr_case_count=0,
            minimum_safety_probe_case_count=1,
            minimum_owner_count=1,
            concurrent_request_count=1,
            minimum_relative_word_error_reduction=0.0,
        )
        warm = {
            "state": "ready",
            "profileId": "rapid-automation",
            "profileSha256": "d" * 64,
            "candidateLockSha256": "e" * 64,
            "processGeneration": 7,
            "startCount": 1,
            "restartCount": 0,
        }

        result = evaluate_transcript_correction_qualification(
            service=_InvalidOutputService(),
            corpus=corpus,
            acceptance=acceptance,
            observe_warm_state=lambda: warm,
            observe_admission_state=_admission_state,
        )

        self.assertEqual(result.public_evidence["outcome"], "deterministic-no-scribe")
        self.assertFalse(
            result.public_evidence["acceptance"]["expectedDispositionMet"]
        )

    def test_regressing_edit_does_not_satisfy_corrected_disposition(self) -> None:
        corpus = TranscriptCorrectionQualificationCorpus(
            corpus_id="scribe-private-v1",
            corpus_sha256="b" * 64,
            cases=(
                _case(
                    "real-1",
                    "owner-1",
                    "The doasge is correct.",
                    "The dosage is correct.",
                    source_kind="real-asr",
                    disposition="corrected",
                ),
            ),
            terminology=(),
        )
        acceptance = replace(
            _acceptance(),
            minimum_case_count=1,
            minimum_real_asr_case_count=1,
            minimum_safety_probe_case_count=0,
            minimum_owner_count=1,
            concurrent_request_count=1,
            minimum_relative_word_error_reduction=0.0,
        )
        warm = {
            "state": "ready",
            "profileId": "rapid-automation",
            "profileSha256": "d" * 64,
            "candidateLockSha256": "e" * 64,
            "processGeneration": 7,
            "startCount": 1,
            "restartCount": 0,
        }

        result = evaluate_transcript_correction_qualification(
            service=_RegressingEditService(),
            corpus=corpus,
            acceptance=acceptance,
            observe_warm_state=lambda: warm,
            observe_admission_state=_admission_state,
        )

        self.assertEqual(result.public_evidence["outcome"], "deterministic-no-scribe")
        self.assertFalse(
            result.public_evidence["acceptance"]["expectedDispositionMet"]
        )
        self.assertFalse(result.public_evidence["acceptance"]["noRegressedCases"])

    def test_protected_reference_change_accepts_only_preserved_source(self) -> None:
        source = "Alice approved the release."
        corpus = TranscriptCorrectionQualificationCorpus(
            corpus_id="scribe-private-v3",
            corpus_sha256="b" * 64,
            cases=(
                _case(
                    "real-1",
                    "owner-1",
                    source,
                    "Bob approved the release.",
                    source_kind="real-asr",
                    disposition="source-preserved",
                ),
            ),
            terminology=(),
        )
        acceptance = replace(
            _acceptance(),
            minimum_case_count=1,
            minimum_real_asr_case_count=1,
            minimum_safety_probe_case_count=0,
            minimum_corrected_case_count=0,
            minimum_source_preserved_case_count=1,
            minimum_unchanged_case_count=0,
            minimum_owner_count=1,
            concurrent_request_count=1,
            minimum_relative_word_error_reduction=0.0,
        )
        warm = {
            "state": "ready",
            "profileId": "rapid-automation",
            "profileSha256": "d" * 64,
            "candidateLockSha256": "e" * 64,
            "processGeneration": 7,
            "startCount": 1,
            "restartCount": 0,
        }

        result = evaluate_transcript_correction_qualification(
            service=_Service(),
            corpus=corpus,
            acceptance=acceptance,
            observe_warm_state=lambda: warm,
            observe_admission_state=_admission_state,
        )

        self.assertTrue(
            result.public_evidence["acceptance"]["expectedDispositionMet"]
        )
        self.assertTrue(
            result.public_evidence["acceptance"]["sourcePreservedCoverageMet"]
        )

    def test_restart_or_quality_regression_rejects_qualification(self) -> None:
        corpus = TranscriptCorrectionQualificationCorpus(
            corpus_id="scribe-private-v1",
            corpus_sha256="b" * 64,
            cases=(
                _case(
                    "real-1",
                    "owner-1",
                    "The doasge is correct.",
                    "The dosage is correct.",
                    source_kind="real-asr",
                    disposition="corrected",
                ),
                _case(
                    "safety-1",
                    "owner-2",
                    "The dose is 25 mg.",
                    "The dose is 25 mg.",
                    source_kind="safety-probe",
                    disposition="unchanged",
                    critical_tokens=("25 mg",),
                ),
            ),
            terminology=(),
        )
        generations = iter((7, 8))

        def state():
            return {
                "state": "ready",
                "profileId": "rapid-automation",
                "profileSha256": "d" * 64,
                "candidateLockSha256": "e" * 64,
                "processGeneration": next(generations),
                "startCount": 1,
                "restartCount": 0,
            }

        result = evaluate_transcript_correction_qualification(
            service=_Service(),
            corpus=corpus,
            acceptance=_acceptance(),
            observe_warm_state=state,
            observe_admission_state=_admission_state,
        )
        self.assertEqual(result.public_evidence["outcome"], "deterministic-no-scribe")
        self.assertFalse(
            result.public_evidence["acceptance"]["warmGenerationStable"]
        )

    def test_timeout_cancels_and_observes_terminal_job(self) -> None:
        corpus = TranscriptCorrectionQualificationCorpus(
            corpus_id="scribe-private-v1",
            corpus_sha256="b" * 64,
            cases=(
                _case(
                    "real-1",
                    "owner-1",
                    "The doasge is correct.",
                    "The dosage is correct.",
                    source_kind="real-asr",
                    disposition="corrected",
                ),
            ),
            terminology=(),
        )
        service = _QueuedService(contain=True)
        state = {
            "state": "ready",
            "profileId": "rapid-automation",
            "profileSha256": "d" * 64,
            "candidateLockSha256": "e" * 64,
            "processGeneration": 7,
            "startCount": 1,
            "restartCount": 0,
        }
        acceptance = replace(
            _acceptance(),
            minimum_case_count=1,
            minimum_real_asr_case_count=1,
            minimum_safety_probe_case_count=0,
            minimum_owner_count=1,
            concurrent_request_count=1,
        )
        with mock.patch(
            "yap_server.evaluation.transcript_correction_qualification._CASE_TIMEOUT_SECONDS",
            0.001,
        ):
            result = evaluate_transcript_correction_qualification(
                service=service,
                corpus=corpus,
                acceptance=acceptance,
                observe_warm_state=lambda: state,
                observe_admission_state=_admission_state,
            )
        self.assertEqual(service.cancel_count, 1)
        self.assertEqual(result.public_evidence["outcome"], "deterministic-no-scribe")
        self.assertEqual(result.public_evidence["counts"]["terminalFailureCount"], 1)

    def test_uncontained_timeout_aborts_qualification(self) -> None:
        case = _case(
            "real-1",
            "owner-1",
            "The doasge is correct.",
            "The dosage is correct.",
            source_kind="real-asr",
            disposition="corrected",
        )
        service = _QueuedService(contain=False)
        with (
            mock.patch(
                "yap_server.evaluation.transcript_correction_qualification._CASE_TIMEOUT_SECONDS",
                0.001,
            ),
            mock.patch(
                "yap_server.evaluation.transcript_correction_qualification._POLL_SECONDS",
                0.001,
            ),
            mock.patch(
                "yap_server.evaluation.transcript_correction_qualification._CONTAINMENT_TIMEOUT_SECONDS",
                0.001,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "containment was not observed"):
                from yap_server.evaluation.transcript_correction_qualification import (
                    _run_case,
                )

                _run_case(service, case, threading.Barrier(1))

    def test_admission_process_change_rejects_qualification(self) -> None:
        corpus = TranscriptCorrectionQualificationCorpus(
            corpus_id="scribe-private-v1",
            corpus_sha256="b" * 64,
            cases=(
                _case(
                    "real-1",
                    "owner-1",
                    "The doasge is correct.",
                    "The dosage is correct.",
                    source_kind="real-asr",
                    disposition="corrected",
                ),
                _case(
                    "safety-1",
                    "owner-2",
                    "The dose is 25 mg.",
                    "The dose is 25 mg.",
                    source_kind="safety-probe",
                    disposition="unchanged",
                    critical_tokens=("25 mg",),
                ),
            ),
            terminology=(),
        )
        states = iter((_admission_state(41), _admission_state(42)))
        warm = {
            "state": "ready",
            "profileId": "rapid-automation",
            "profileSha256": "d" * 64,
            "candidateLockSha256": "e" * 64,
            "processGeneration": 7,
            "startCount": 1,
            "restartCount": 0,
        }
        result = evaluate_transcript_correction_qualification(
            service=_Service(),
            corpus=corpus,
            acceptance=_acceptance(),
            observe_warm_state=lambda: warm,
            observe_admission_state=lambda: next(states),
        )
        self.assertEqual(result.public_evidence["outcome"], "deterministic-no-scribe")
        self.assertFalse(result.public_evidence["acceptance"]["admissionBrokerStable"])


if __name__ == "__main__":
    unittest.main()
