use crate::{
    jobs::{
        ClientStageFinish, ClientStageName, ClientStageStart, ClientStageState, JobLedgerError,
    },
    server_connector::batch::{CreateRecordingJobRequest, PreprocessingEvidence},
};

use super::super::{
    client_stages::{finish_client_stage_in_transaction, start_client_stage_in_transaction},
    records::ValidatedPreparedRemoteJob,
};

pub(super) fn validate_prepared_request(
    prepared: &ValidatedPreparedRemoteJob,
    request: &CreateRecordingJobRequest,
) -> Result<(), JobLedgerError> {
    if request.capture_manifest.sha256 != prepared.capture_manifest_sha256
        || request.chunks.len() != prepared.chunks.len()
    {
        return Err(JobLedgerError::InvalidRecord(
            "prepared request does not identify its durable manifest and chunks",
        ));
    }
    for (reference, chunk) in request.chunks.iter().zip(&prepared.chunks) {
        if reference.replay_key.session_id != chunk.session_id
            || reference.replay_key.track_id != chunk.track_id
            || reference.replay_key.sequence_start
                != u64::try_from(chunk.sequence_start).map_err(|_| {
                    JobLedgerError::InvalidRecord("prepared chunk sequence is negative")
                })?
            || reference.replay_key.sequence_end
                != u64::try_from(chunk.sequence_end).map_err(|_| {
                    JobLedgerError::InvalidRecord("prepared chunk sequence is negative")
                })?
            || reference.content_identity.sha256 != chunk.content_sha256
            || reference.content_identity.byte_length
                != u64::try_from(chunk.content_byte_length).map_err(|_| {
                    JobLedgerError::InvalidRecord("prepared chunk byte length is negative")
                })?
        {
            return Err(JobLedgerError::InvalidRecord(
                "prepared request and durable chunks disagree",
            ));
        }
    }
    Ok(())
}

pub(in crate::jobs::ledger) fn append_preprocessing_stages(
    transaction: &rusqlite::Transaction<'_>,
    job_id: &str,
    started_at_ms: u64,
    completed_at_ms: u64,
    preprocessing: &PreprocessingEvidence,
) -> Result<(), JobLedgerError> {
    let normalization = preprocessing.normalization();
    append_normalization_stage(
        transaction,
        job_id,
        started_at_ms,
        completed_at_ms,
        normalization,
    )?;
    append_vad_stage(
        transaction,
        job_id,
        started_at_ms,
        completed_at_ms,
        normalization,
        preprocessing.vad(),
    )
}

fn append_normalization_stage(
    transaction: &rusqlite::Transaction<'_>,
    job_id: &str,
    started_at_ms: u64,
    completed_at_ms: u64,
    normalization: &crate::server_connector::batch::NormalizationEvidence,
) -> Result<(), JobLedgerError> {
    let attempt = start_client_stage_in_transaction(
        transaction,
        job_id,
        &ClientStageStart {
            stage: ClientStageName::Normalization,
            input_fingerprint_sha256: normalization.stage_input_sha256().into(),
            component_id: normalization.stage_component_id().into(),
            component_revision: normalization.stage_component_revision().into(),
            started_at_ms,
        },
    )?;
    finish_client_stage_in_transaction(
        transaction,
        job_id,
        &ClientStageFinish {
            stage: ClientStageName::Normalization,
            attempt,
            state: ClientStageState::Succeeded,
            output_fingerprint_sha256: Some(normalization.stage_output_sha256().into()),
            completed_at_ms,
            retryable: false,
            reason: None,
            evidence: Some(normalization.stage_evidence()),
        },
    )
}

fn append_vad_stage(
    transaction: &rusqlite::Transaction<'_>,
    job_id: &str,
    started_at_ms: u64,
    completed_at_ms: u64,
    normalization: &crate::server_connector::batch::NormalizationEvidence,
    vad: &crate::server_connector::batch::VadEvidence,
) -> Result<(), JobLedgerError> {
    let attempt = start_client_stage_in_transaction(
        transaction,
        job_id,
        &ClientStageStart {
            stage: ClientStageName::Vad,
            input_fingerprint_sha256: normalization.source_pcm_sha256().into(),
            component_id: vad.stage_component_id().into(),
            component_revision: vad.stage_component_revision().into(),
            started_at_ms,
        },
    )?;
    let (state, output, retryable, reason) = vad_terminal_fields(vad)?;
    finish_client_stage_in_transaction(
        transaction,
        job_id,
        &ClientStageFinish {
            stage: ClientStageName::Vad,
            attempt,
            state,
            output_fingerprint_sha256: output,
            completed_at_ms,
            retryable,
            reason,
            evidence: Some(vad.stage_evidence()),
        },
    )
}

fn vad_terminal_fields(
    vad: &crate::server_connector::batch::VadEvidence,
) -> Result<(ClientStageState, Option<String>, bool, Option<String>), JobLedgerError> {
    if vad.stage_succeeded() {
        return Ok((
            ClientStageState::Succeeded,
            Some(vad.stage_output_sha256()),
            false,
            None,
        ));
    }
    let error_code = vad.stage_error_code().ok_or(JobLedgerError::InvalidRecord(
        "failed VAD evidence requires an error code",
    ))?;
    let state = if matches!(error_code, "artifact_unavailable" | "artifact_corrupt") {
        ClientStageState::Unavailable
    } else {
        ClientStageState::Failed
    };
    Ok((
        state,
        None,
        vad_error_is_retryable(error_code),
        Some(stage_reason(error_code)?),
    ))
}

fn vad_error_is_retryable(error_code: &str) -> bool {
    !matches!(
        error_code,
        "artifact_corrupt"
            | "segment_limit_exceeded"
            | "invalid_interval"
            | "manifest_limit_exceeded"
    )
}

fn stage_reason(error_code: &str) -> Result<String, JobLedgerError> {
    let reason = error_code
        .bytes()
        .map(|byte| match byte {
            b'a'..=b'z' => byte.to_ascii_uppercase(),
            b'A'..=b'Z' | b'0'..=b'9' | b'_' => byte,
            b'-' | b'.' => b'_',
            _ => 0,
        })
        .collect::<Vec<_>>();
    if reason.contains(&0) {
        return Err(JobLedgerError::InvalidRecord(
            "VAD error code is outside the stage reason contract",
        ));
    }
    String::from_utf8(reason)
        .map_err(|_| JobLedgerError::InvalidRecord("VAD error code is not ASCII"))
}
