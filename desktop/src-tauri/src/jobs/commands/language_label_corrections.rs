use super::{JobCommandError, RecordingJobs};
use crate::jobs::{remote, LanguageLabelReview};
use std::path::Path;

impl RecordingJobs {
    pub(crate) fn language_label_review(
        &self,
        transcript_path: &str,
    ) -> Result<LanguageLabelReview, JobCommandError> {
        remote::read_language_label_review(Path::new(transcript_path), self.remote_jobs_directory())
            .map_err(language_label_correction_error)
    }

    pub(crate) fn append_language_label_correction(
        &self,
        transcript_path: &str,
        expected_revision: u64,
        segment_index: u64,
        replacement_language_bcp47: Option<String>,
    ) -> Result<LanguageLabelReview, JobCommandError> {
        let _mutation_guard = self.mutation().lock().map_err(|_| {
            JobCommandError {
                code: "RECORDING_JOB_MUTATION_UNAVAILABLE".into(),
                message: "Recording-job mutation ownership is unavailable after an internal failure. Restart Yap before trying again.".into(),
            }
        })?;
        remote::append_language_label_correction(
            Path::new(transcript_path),
            self.remote_jobs_directory(),
            expected_revision,
            segment_index,
            replacement_language_bcp47,
        )
        .map_err(language_label_correction_error)
    }
}

fn language_label_correction_error(error: remote::LanguageLabelCorrectionError) -> JobCommandError {
    JobCommandError {
        code: error.code().into(),
        message: error.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        jobs::JobLedger,
        language::span_contract::{
            LanguageSpan, LanguageSpanBoundaryAuthority, LanguageSpanDisposition,
        },
        server_connector::batch::{
            AlignmentOutcome, AlignmentStatus, AlignmentUnavailableReason, LanguageDecision,
            LanguageSegment, LanguageSegmentReason, LanguageSegmentStatus, ModelRevision,
            ServerLanguageSpanEvidence, TranscriptResultRevision,
        },
    };
    use std::sync::{Arc, Barrier};

    fn dynamic_result() -> TranscriptResultRevision {
        TranscriptResultRevision {
            session_id: "session-correction-race".into(),
            revision: 1,
            authority: "server_authoritative".into(),
            created_at_utc: "2026-07-18T12:00:00Z".into(),
            capture_manifest_sha256:
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".into(),
            previous_result_sha256: None,
            status: "complete".into(),
            language: Some(LanguageDecision {
                language_bcp47: "und".into(),
                confidence: None,
            }),
            transcript: "hello bonjour".into(),
            speaker_result_sha256: None,
            language_segments: Some(vec![
                LanguageSegment {
                    index: 0,
                    source_span_index: 0,
                    text: "hello".into(),
                    status: LanguageSegmentStatus::Detected,
                    language_bcp47: Some("en-US".into()),
                    raw_language_tag: Some("en-US".into()),
                    reason: None,
                },
                LanguageSegment {
                    index: 1,
                    source_span_index: 0,
                    text: "bonjour".into(),
                    status: LanguageSegmentStatus::Unknown,
                    language_bcp47: None,
                    raw_language_tag: Some("el-GR".into()),
                    reason: Some(LanguageSegmentReason::DisabledLanguageTag),
                },
            ]),
            language_span_evidence: Some(ServerLanguageSpanEvidence {
                schema_version: 1,
                sample_rate_hz: 16_000,
                source_end_sample: 16_000,
                boundary_authority: LanguageSpanBoundaryAuthority::ServerUtterance,
                provider_id: "nemotron".into(),
                pool_id: "nemotron-batch".into(),
                model_id: "nvidia/nemotron-3.5-asr-streaming-0.6b".into(),
                model_revision: "f3d333391852ba876df169dcc9ba902d25b6ab0b".into(),
                utterance_plan_sha256:
                    "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee".into(),
                spans: vec![LanguageSpan {
                    start_sample: 0,
                    end_sample: 16_000,
                    language_bcp47: "und".into(),
                    decision_revision: 1,
                    disposition: LanguageSpanDisposition::ServerUnknown,
                    component_revision: Some("f3d333391852ba876df169dcc9ba902d25b6ab0b".into()),
                    decision_evidence: None,
                }],
            }),
            alignment: AlignmentOutcome {
                status: AlignmentStatus::Unavailable,
                reason: Some(AlignmentUnavailableReason::RuntimeFailed),
                component_revision: "cohere-attention-alignment-candidate-v1".into(),
            },
            aligned_words: Vec::new(),
            model_provenance: vec![ModelRevision {
                model_id: "nvidia/nemotron-3.5-asr-streaming-0.6b".into(),
                revision: "f3d333391852ba876df169dcc9ba902d25b6ab0b".into(),
                calibration_revision: "asr-not-applicable".into(),
            }],
        }
    }

    #[test]
    fn concurrent_language_label_corrections_serialize_to_one_revision_and_one_conflict() {
        let root = std::env::temp_dir().join(format!(
            "yap-language-label-correction-race-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        let jobs = Arc::new(RecordingJobs::from_ledger(
            JobLedger::open_in_memory().unwrap(),
            &root,
        ));
        let spool = jobs.remote_jobs_directory().to_path_buf();
        let job_id = "job-correction-race";
        std::fs::create_dir_all(spool.join(job_id)).unwrap();
        let transcript_path =
            remote::publish_remote_result(job_id, &spool, &dynamic_result(), None).unwrap();
        let transcript_path = transcript_path.display().to_string();
        let barrier = Arc::new(Barrier::new(3));
        let attempts = [(0, "de-DE"), (1, "fr-FR")]
            .into_iter()
            .map(|(segment_index, language)| {
                let jobs = Arc::clone(&jobs);
                let barrier = Arc::clone(&barrier);
                let transcript_path = transcript_path.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    jobs.append_language_label_correction(
                        &transcript_path,
                        0,
                        segment_index,
                        Some(language.into()),
                    )
                })
            })
            .collect::<Vec<_>>();
        barrier.wait();
        let results = attempts
            .into_iter()
            .map(|attempt| attempt.join().unwrap())
            .collect::<Vec<_>>();

        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(
            results
                .iter()
                .filter_map(|result| result.as_ref().err())
                .filter(|error| error.code == "LANGUAGE_LABEL_CORRECTION_CONFLICT")
                .count(),
            1
        );
        let review = jobs.language_label_review(&transcript_path).unwrap();
        assert_eq!(review.revision, 1);
        assert_eq!(review.active_correction_count, 1);
        std::fs::remove_dir_all(root).unwrap();
    }
}
