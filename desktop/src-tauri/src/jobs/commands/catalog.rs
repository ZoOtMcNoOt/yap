use super::super::remote;
use super::{
    JobCommandError, PublishedRemoteTranscriptCatalog, PublishedRemoteTranscriptSummary,
    PublishedSpeakerTranscript, PublishedSpeakerTranscriptTurn, RecordingJobs,
    TranscriptLanguageStatus, TranscriptResultSummary, TranscriptTimingStatus,
};
use crate::{
    jobs::{LanguageLabelReview, RecordingJobRecord, RecordingJobStatus, RecordingRoute},
    server_connector::batch::{
        validate_speaker_result_for_recording, validate_transcript_result_for_recording,
        AlignmentStatus, AnonymousSpeakerAttribution, CreateRecordingJobRequest,
        TranscriptResultRevision,
    },
};

struct SourceBoundPublishedResult {
    bundle: remote::PublishedRemoteResultBundle,
    request: CreateRecordingJobRequest,
    source_path: String,
}

fn summarize_result(
    result: &TranscriptResultRevision,
    language_review: Option<&LanguageLabelReview>,
) -> Result<TranscriptResultSummary, ()> {
    let language = result.language.as_ref().ok_or(())?;
    let language_status = if language.language_bcp47 == "und" {
        let review = language_review.ok_or(())?;
        if review.review_required_count > 0 {
            TranscriptLanguageStatus::UnknownSegments
        } else {
            TranscriptLanguageStatus::Dynamic
        }
    } else {
        TranscriptLanguageStatus::Fixed
    };
    let timing_status = match result.alignment.status {
        AlignmentStatus::Available => TranscriptTimingStatus::Available,
        AlignmentStatus::Unavailable => TranscriptTimingStatus::Unavailable,
    };
    Ok(TranscriptResultSummary {
        language_bcp47: language.language_bcp47.clone(),
        language_status,
        timing_status,
        active_language_correction_count: language_review
            .map(|review| review.active_correction_count),
        language_review_required_count: language_review.map(|review| review.review_required_count),
    })
}

impl RecordingJobs {
    pub(crate) fn published_remote_transcript_catalog(
        &self,
    ) -> Result<PublishedRemoteTranscriptCatalog, JobCommandError> {
        let mut sessions = Vec::new();
        let mut omitted_invalid_result = false;
        for record in self.ledger().list_jobs()?.into_iter().filter(|record| {
            matches!(
                record.status,
                RecordingJobStatus::Complete | RecordingJobStatus::Partial
            ) && record.route == Some(RecordingRoute::ServerBatch)
        }) {
            let verified = (|| {
                let published = self.load_source_bound_published_result(&record)?;
                let output_path = record.output_path.as_deref().ok_or(())?;
                let language_review = (published
                    .bundle
                    .result
                    .language
                    .as_ref()
                    .is_some_and(|language| language.language_bcp47 == "und"))
                .then(|| {
                    remote::read_language_label_review(output_path, self.remote_jobs_directory())
                })
                .transpose()
                .map_err(|_| ())?;
                let result_summary =
                    summarize_result(&published.bundle.result, language_review.as_ref())?;
                let speaker_transcript_available =
                    published.bundle.result.requires_speaker_result();
                Ok(PublishedRemoteTranscriptSummary {
                    session_id: published.bundle.result.session_id,
                    name: record.display_name.clone(),
                    source_path: published.source_path,
                    output_path: output_path.display().to_string(),
                    created_at_ms: record.updated_at_ms,
                    speaker_transcript_available,
                    result_summary,
                    warning: (record.status == RecordingJobStatus::Partial).then(|| {
                        "Speaker attribution may be incomplete because the server reached its eight-speaker limit; fallback reprocessing was recommended but not run."
                            .into()
                    }),
                })
            })();
            match verified {
                Ok(session) => sessions.push(session),
                Err(()) => omitted_invalid_result = true,
            }
        }
        sessions.sort_by(|left, right| {
            right
                .created_at_ms
                .cmp(&left.created_at_ms)
                .then_with(|| left.session_id.cmp(&right.session_id))
        });
        Ok(PublishedRemoteTranscriptCatalog {
            sessions,
            maintenance_warnings: if omitted_invalid_result {
                vec!["A saved private-server transcript could not be verified and was omitted from history.".into()]
            } else {
                Vec::new()
            },
        })
    }

    pub(crate) fn published_speaker_transcript(
        &self,
        session_id: &str,
        output_path: &str,
    ) -> Result<Option<PublishedSpeakerTranscript>, JobCommandError> {
        let records = self.ledger().list_jobs()?;
        let Some(record) = records.into_iter().find(|record| {
            matches!(
                record.status,
                RecordingJobStatus::Complete | RecordingJobStatus::Partial
            ) && record.route == Some(RecordingRoute::ServerBatch)
                && record
                    .output_path
                    .as_deref()
                    .is_some_and(|path| path.display().to_string() == output_path)
        }) else {
            return Ok(None);
        };
        let published = self
            .load_source_bound_published_result(&record)
            .map_err(|()| {
                command_error(
                    "SPEAKER_TRANSCRIPT_INVALID",
                    "The saved speaker transcript could not be verified.",
                )
            })?;
        if published.bundle.result.session_id != session_id {
            return Ok(None);
        }
        let Some(speaker_result) = published.bundle.load_speaker_result().map_err(|_| {
            command_error(
                "SPEAKER_TRANSCRIPT_INVALID",
                "The saved speaker transcript could not be verified.",
            )
        })?
        else {
            return Ok(None);
        };
        validate_speaker_result_for_recording(
            &speaker_result,
            &published.bundle.result,
            &published.request,
        )
        .map_err(|_| {
            command_error(
                "SPEAKER_TRANSCRIPT_INVALID",
                "The saved speaker transcript conflicts with its source recording.",
            )
        })?;
        let turns = speaker_result
            .speaker_turns
            .into_iter()
            .map(|turn| {
                let AnonymousSpeakerAttribution::SessionSpeaker { session_speaker_id } =
                    turn.attribution;
                PublishedSpeakerTranscriptTurn {
                    turn_id: turn.turn_id,
                    speaker_id: session_speaker_id,
                    start_ms: turn.start_ms,
                    end_ms: turn.end_ms,
                    text: turn.text,
                    overlap_group_id: turn.overlap_group_id,
                }
            })
            .collect();
        Ok(Some(PublishedSpeakerTranscript {
            session_id: published.bundle.result.session_id,
            source_result_sha256: published.bundle.result_sha256,
            turns,
        }))
    }

    fn load_source_bound_published_result(
        &self,
        record: &RecordingJobRecord,
    ) -> Result<SourceBoundPublishedResult, ()> {
        let output_path = record.output_path.as_deref().ok_or(())?;
        let source_path = record.source_path.as_deref().ok_or(())?;
        let prepared = self
            .ledger()
            .get_prepared_remote_job(&record.job_id)
            .map_err(|_| ())?
            .ok_or(())?;
        let request = CreateRecordingJobRequest::decode_persisted(&prepared.create_request_json)
            .map_err(|_| ())?;
        let bundle =
            remote::read_published_remote_result_bundle(output_path, self.remote_jobs_directory())
                .map_err(|_| ())?;
        validate_transcript_result_for_recording(&bundle.result, &request).map_err(|_| ())?;
        if bundle.result.status != record.status.as_db()
            || prepared.capture_manifest_sha256 != request.capture_manifest.sha256
            || record.capture_manifest_sha256.as_deref()
                != Some(request.capture_manifest.sha256.as_str())
        {
            return Err(());
        }
        Ok(SourceBoundPublishedResult {
            bundle,
            request,
            source_path: source_path.display().to_string(),
        })
    }
}

fn command_error(code: &str, message: &str) -> JobCommandError {
    JobCommandError {
        code: code.into(),
        message: message.into(),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn result_with(
        language: serde_json::Value,
        segments: serde_json::Value,
    ) -> TranscriptResultRevision {
        serde_json::from_value(json!({
            "sessionId": "session-1",
            "revision": 1,
            "authority": "server_authoritative",
            "createdAtUtc": "2026-07-18T00:00:00Z",
            "captureManifestSha256": "a".repeat(64),
            "previousResultSha256": null,
            "status": "complete",
            "language": language,
            "transcript": "bonjour hello",
            "languageSegments": segments,
            "alignment": {
                "status": "unavailable",
                "reason": "ALIGNMENT_PROVIDER_UNSUPPORTED",
                "componentRevision": "cohere-attention-alignment-candidate-v1"
            },
            "alignedWords": [],
            "modelProvenance": []
        }))
        .expect("summary fixture must decode")
    }

    #[test]
    fn summary_exposes_dynamic_unknown_segments_and_unavailable_timing() {
        let result = result_with(
            json!({ "languageBcp47": "und", "confidence": null }),
            json!([
                {
                    "index": 0,
                    "sourceSpanIndex": 0,
                    "text": "bonjour",
                    "status": "detected",
                    "languageBcp47": "fr-FR",
                    "rawLanguageTag": "fr-FR",
                    "reason": null
                },
                {
                    "index": 1,
                    "sourceSpanIndex": 0,
                    "text": "hello",
                    "status": "unknown",
                    "languageBcp47": null,
                    "rawLanguageTag": null,
                    "reason": "MISSING_LANGUAGE_TAG"
                }
            ]),
        );

        assert_eq!(
            summarize_result(
                &result,
                Some(&LanguageLabelReview {
                    schema_version: 1,
                    session_id: "session-1".into(),
                    source_result_sha256: "a".repeat(64),
                    revision: 0,
                    active_correction_count: 0,
                    review_required_count: 1,
                    segments: Vec::new(),
                })
            ),
            Ok(TranscriptResultSummary {
                language_bcp47: "und".into(),
                language_status: TranscriptLanguageStatus::UnknownSegments,
                timing_status: TranscriptTimingStatus::Unavailable,
                active_language_correction_count: Some(0),
                language_review_required_count: Some(1),
            })
        );
    }

    #[test]
    fn summary_promotes_reviewed_dynamic_labels_without_hiding_correction_count() {
        let result = result_with(
            json!({ "languageBcp47": "und", "confidence": null }),
            json!([{
                "index": 0,
                "sourceSpanIndex": 0,
                "text": "bonjour",
                "status": "unknown",
                "languageBcp47": null,
                "rawLanguageTag": null,
                "reason": "MISSING_LANGUAGE_TAG"
            }]),
        );
        let review = LanguageLabelReview {
            schema_version: 1,
            session_id: "session-1".into(),
            source_result_sha256: "a".repeat(64),
            revision: 1,
            active_correction_count: 1,
            review_required_count: 0,
            segments: Vec::new(),
        };

        assert_eq!(
            summarize_result(&result, Some(&review)),
            Ok(TranscriptResultSummary {
                language_bcp47: "und".into(),
                language_status: TranscriptLanguageStatus::Dynamic,
                timing_status: TranscriptTimingStatus::Unavailable,
                active_language_correction_count: Some(1),
                language_review_required_count: Some(0),
            })
        );
    }
}
