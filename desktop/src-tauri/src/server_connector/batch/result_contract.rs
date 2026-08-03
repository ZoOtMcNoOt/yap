use time::{format_description::well_known::Rfc3339, OffsetDateTime};

use super::{CreateRecordingJobRequest, SpeakerResultRevision, TranscriptResultRevision};

pub(crate) fn validate_transcript_result_for_recording(
    result: &TranscriptResultRevision,
    request: &CreateRecordingJobRequest,
) -> Result<(), String> {
    let expected_language = request
        .metadata
        .preferred_languages_bcp47
        .first()
        .ok_or_else(|| "prepared recording has no preferred result language".to_string())?;
    let language = result
        .language
        .as_ref()
        .ok_or_else(|| "server result omitted its language decision".to_string())?;
    let timestamp_valid = result.created_at_utc.ends_with('Z')
        && result.created_at_utc.len() <= 64
        && OffsetDateTime::parse(&result.created_at_utc, &Rfc3339).is_ok();
    let language_valid = language.language_bcp47 == *expected_language
        && language.language_bcp47.len() <= 35
        && language
            .language_bcp47
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
        && language
            .confidence
            .is_none_or(|confidence| (0.0..=1.0).contains(&confidence));
    let provenance_valid = !result.model_provenance.is_empty()
        && result.model_provenance.len() <= 8
        && result.model_provenance.iter().all(|model| {
            [
                model.model_id.as_str(),
                model.revision.as_str(),
                model.calibration_revision.as_str(),
            ]
            .iter()
            .all(|value| !value.is_empty() && value.len() <= 256)
        });
    let bounds = request.recording_bounds()?;
    if result.session_id != request.metadata.session_id.as_str()
        || result.revision != 1
        || result.authority != "server_authoritative"
        || !timestamp_valid
        || result.capture_manifest_sha256 != request.capture_manifest.sha256
        || result.previous_result_sha256.is_some()
        || !matches!(result.status.as_str(), "complete" | "partial")
        || (result.status == "partial" && !result.requires_speaker_result())
        || !language_valid
        || !result.transcript_is_canonical()
        || !result.language_evidence_is_valid(Some(bounds.end_sample), bounds.duration_ms)
        || !result.alignment_is_valid(bounds.duration_ms)
        || !provenance_valid
    {
        return Err("server result revision conflicts with the prepared recording".into());
    }
    Ok(())
}

pub(crate) fn validate_speaker_result_for_recording(
    speaker_result: &SpeakerResultRevision,
    transcript_result: &TranscriptResultRevision,
    request: &CreateRecordingJobRequest,
) -> Result<(), String> {
    if !transcript_result.requires_speaker_result() {
        return Err("server transcript does not declare a speaker result".into());
    }
    let bounds = request.recording_bounds()?;
    if !speaker_result.is_valid_for(
        transcript_result,
        bounds.duration_ms,
        Some(bounds.end_sample),
        &bounds.track_ids,
    ) {
        return Err("server speaker result conflicts with the prepared recording".into());
    }
    Ok(())
}
