use time::{format_description::well_known::Rfc3339, OffsetDateTime};

use crate::server_connector::batch::{ApiError, CreateRecordingJobRequest, RecordingJob};

pub(in crate::jobs) fn validate_job_projection(
    projection: &RecordingJob,
    request: &CreateRecordingJobRequest,
    expected_job_id: Option<&str>,
    allowed_statuses: &[&str],
) -> Result<(), String> {
    let manifest = &projection.capture_manifest;
    let error_is_valid = match (projection.status.as_str(), projection.error.as_ref()) {
        ("failed", Some(error)) => valid_server_job_error(error),
        ("failed", None) => false,
        (_, None) => true,
        (_, Some(_)) => false,
    };
    if expected_job_id.is_some_and(|expected| projection.job_id != expected)
        || projection.job_id.is_empty()
        || projection.session_id != request.metadata.session_id.as_str()
        || projection.display_name != request.display_name
        || projection.session_mode != "meeting"
        || projection.session_origin != "imported_file"
        || projection.route.as_deref() != Some("server_batch")
        || manifest.schema_version != request.capture_manifest.schema_version
        || manifest.session_id != request.capture_manifest.session_id
        || manifest.sha256 != request.capture_manifest.sha256
        || manifest.byte_length != request.capture_manifest.byte_length
        || !allowed_statuses.contains(&projection.status.as_str())
        || !error_is_valid
        || projection.created_at_utc.is_empty()
        || projection.updated_at_utc.is_empty()
    {
        return Err("server job projection conflicts with the prepared recording".into());
    }
    Ok(())
}

fn valid_server_job_error(error: &ApiError) -> bool {
    error.is_valid()
}

pub(super) fn result_retention_expiry_ms(
    request: &CreateRecordingJobRequest,
) -> Result<u64, String> {
    let encoded = request
        .metadata
        .retention_expires_at_utc
        .as_deref()
        .filter(|value| value.ends_with('Z'))
        .ok_or_else(|| "prepared meeting job has no UTC result retention expiry".to_string())?;
    let parsed = OffsetDateTime::parse(encoded, &Rfc3339)
        .map_err(|_| "prepared meeting job has an invalid result retention expiry".to_string())?;
    let milliseconds = parsed.unix_timestamp_nanos().div_euclid(1_000_000);
    u64::try_from(milliseconds)
        .map_err(|_| "prepared meeting result retention expiry is out of range".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::jobs::RecordingLanguageDecision;

    #[test]
    fn remote_lifecycle_status_rejects_a_mismatched_server_job_identity() {
        let request = CreateRecordingJobRequest::for_test_single_chunk(
            "meeting.wav",
            "session-remote-lifecycle",
            "track-1",
            &"a".repeat(64),
            2,
            &"b".repeat(64),
            320,
            RecordingLanguageDecision::primary("en-US".into()).unwrap(),
            &"c".repeat(64),
        );
        let projection: RecordingJob = serde_json::from_value(serde_json::json!({
            "jobId": format!("job-{}", "d".repeat(32)),
            "sessionId": request.metadata.session_id.as_str(),
            "displayName": request.display_name,
            "sessionMode": "meeting",
            "sessionOrigin": "imported_file",
            "status": "server_processing",
            "route": "server_batch",
            "captureManifest": {
                "schemaVersion": request.capture_manifest.schema_version,
                "sessionId": request.capture_manifest.session_id,
                "sha256": request.capture_manifest.sha256,
                "byteLength": request.capture_manifest.byte_length,
            },
            "progressPercent": 50.0,
            "progressMessage": "Running meeting transcription.",
            "error": null,
            "createdAtUtc": "2026-08-03T12:00:00Z",
            "updatedAtUtc": "2026-08-03T12:00:01Z",
        }))
        .unwrap();

        assert!(validate_job_projection(
            &projection,
            &request,
            Some(&format!("job-{}", "e".repeat(32))),
            &[
                "server_processing",
                "complete",
                "partial",
                "failed",
                "cancelled"
            ],
        )
        .is_err());
    }
}
