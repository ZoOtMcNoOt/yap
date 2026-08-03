use std::path::Path;

use crate::{
    jobs::{remote, JobLedger, RecordingJobStatus, REMOTE_STAGE_RETRY_REQUESTED},
    server_connector::{
        batch::{
            BatchApiClient, CreateRecordingJobRequest, RetryServerStageRequest, ServerStageName,
            ServerStageProjectionEnvelope, ServerStageState,
        },
        BatchConnectionLease, ServerConnector,
    },
};

use super::{
    contract::{
        result_retention_expiry_ms, validate_job_projection, validate_result_revision,
        validate_speaker_result_revision,
    },
    upload::validate_durable_upload_state,
    BatchCommitGuard, DrainResult, DrainStepError,
};

#[cfg(test)]
pub(super) async fn advance_processing_once(
    ledger: &JobLedger,
    remote_jobs_directory: &Path,
    client: &BatchApiClient,
    updated_at_ms: u64,
) -> DrainResult<bool> {
    advance_processing_once_guarded(
        ledger,
        remote_jobs_directory,
        client,
        updated_at_ms,
        &BatchCommitGuard::Unchecked,
    )
    .await
}

pub(super) async fn advance_processing_with_lease(
    ledger: &JobLedger,
    remote_jobs_directory: &Path,
    connector: &ServerConnector,
    lease: &BatchConnectionLease,
    job_id: &str,
    updated_at_ms: u64,
) -> DrainResult<bool> {
    advance_processing_job_once_guarded(
        ledger,
        remote_jobs_directory,
        lease.client(),
        Some(job_id),
        updated_at_ms,
        &BatchCommitGuard::Lease { connector, lease },
    )
    .await
}

#[cfg(test)]
pub(super) async fn advance_processing_once_guarded(
    ledger: &JobLedger,
    remote_jobs_directory: &Path,
    client: &BatchApiClient,
    updated_at_ms: u64,
    guard: &BatchCommitGuard<'_>,
) -> DrainResult<bool> {
    advance_processing_job_once_guarded(
        ledger,
        remote_jobs_directory,
        client,
        None,
        updated_at_ms,
        guard,
    )
    .await
}

#[cfg(test)]
pub(super) async fn advance_processing_job_once_guarded_for_test(
    ledger: &JobLedger,
    remote_jobs_directory: &Path,
    client: &BatchApiClient,
    job_id: &str,
    updated_at_ms: u64,
    guard: &BatchCommitGuard<'_>,
) -> DrainResult<bool> {
    advance_processing_job_once_guarded(
        ledger,
        remote_jobs_directory,
        client,
        Some(job_id),
        updated_at_ms,
        guard,
    )
    .await
}

async fn advance_processing_job_once_guarded(
    ledger: &JobLedger,
    remote_jobs_directory: &Path,
    client: &BatchApiClient,
    exact_job_id: Option<&str>,
    updated_at_ms: u64,
    guard: &BatchCommitGuard<'_>,
) -> DrainResult<bool> {
    let candidate = ledger
        .list_recoverable_jobs()
        .map_err(|error| error.to_string())?
        .into_iter()
        .find(|job| {
            exact_job_id.is_none_or(|job_id| job.job_id == job_id)
                && matches!(
                    job.status,
                    RecordingJobStatus::ServerProcessing | RecordingJobStatus::Saving
                )
                && job
                    .next_attempt_at_ms
                    .is_none_or(|retry_at| retry_at <= updated_at_ms)
        });
    let Some(candidate) = candidate else {
        return Ok(false);
    };
    let (pinned_client, remote_authority) = client.pin_current_authority().await?;
    ledger
        .bind_remote_authority(
            &candidate.job_id,
            remote_authority.account(),
            remote_authority.authentication(),
        )
        .map_err(|error| DrainStepError::permanent(error.to_string()))?;
    let client = &pinned_client;
    let prepared = ledger
        .get_prepared_remote_job(&candidate.job_id)
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "server-processing job has no durable remote state".to_string())?;
    let server_job_id = prepared
        .server_job_id
        .as_deref()
        .ok_or_else(|| "server-processing job has no bound server job ID".to_string())?;
    if prepared.server_base_url.as_deref() != Some(client.base_url_identity()) {
        return Err("server-processing job is bound to a different server origin".into());
    }
    let request = CreateRecordingJobRequest::decode_persisted(&prepared.create_request_json)?;
    let result_expires_at_ms = result_retention_expiry_ms(&request)?;
    let chunks = ledger
        .list_chunks(&candidate.job_id)
        .map_err(|error| error.to_string())?;
    validate_durable_upload_state(&candidate, &prepared, &request, &chunks)?;

    if candidate.error_code.as_deref() == Some(REMOTE_STAGE_RETRY_REQUESTED) {
        reconcile_requested_stage_retry(
            ledger,
            client,
            &candidate.job_id,
            server_job_id,
            &request.capture_manifest.sha256,
            updated_at_ms,
            guard,
        )
        .await?;
    }

    guard.ensure_current()?;
    let projection = client.status(server_job_id).await?;
    validate_job_projection(
        &projection,
        &request,
        Some(server_job_id),
        &["server_processing", "complete", "failed", "cancelled"],
    )?;
    guard.ensure_current()?;
    if projection.status == "server_processing" {
        return Ok(false);
    }
    if projection.status == "failed" {
        let error = projection.error.as_ref().ok_or_else(|| {
            DrainStepError::permanent("failed server projection omitted its typed error")
        })?;
        return Err(DrainStepError::terminal_server(error));
    }
    if projection.status != "complete" {
        return Err(DrainStepError::permanent(format!(
            "server job entered terminal status {} before publishing a result",
            projection.status
        )));
    }

    guard.ensure_current()?;
    let result = client.result(server_job_id).await?;
    validate_result_revision(&result, &request)?;
    let speaker_result = if result.requires_speaker_result() {
        guard.ensure_current()?;
        let speaker_result = client.speaker_result(server_job_id).await?;
        validate_speaker_result_revision(&speaker_result, &result, &request)?;
        Some(speaker_result)
    } else {
        None
    };
    guard.commit(|| {
        ledger
            .begin_remote_result_saving(&candidate.job_id, updated_at_ms)
            .map_err(|error| DrainStepError::permanent(error.to_string()))
    })?;
    let output_path = remote::publish_remote_result(
        &candidate.job_id,
        remote_jobs_directory,
        &result,
        speaker_result.as_ref(),
    )?;
    guard.commit(|| {
        ledger
            .complete_remote_result(
                &candidate.job_id,
                &output_path,
                result_expires_at_ms,
                updated_at_ms,
            )
            .map_err(|error| DrainStepError::permanent(error.to_string()))
    })?;
    Ok(true)
}

async fn reconcile_requested_stage_retry(
    ledger: &JobLedger,
    client: &BatchApiClient,
    local_job_id: &str,
    server_job_id: &str,
    capture_manifest_sha256: &str,
    updated_at_ms: u64,
    guard: &BatchCommitGuard<'_>,
) -> DrainResult<()> {
    ensure_current_for_stage_retry(guard)?;
    let stages = client
        .stages(server_job_id)
        .await
        .map_err(DrainStepError::from_stage_query_error)?;
    ensure_current_for_stage_retry(guard)?;
    require_complete_stage_history(&stages)?;
    let asr = stages
        .stages
        .iter()
        .find(|stage| stage.stage == ServerStageName::Asr)
        .ok_or_else(|| DrainStepError::permanent("server stage projection omitted ASR"))?;

    match asr.state {
        ServerStageState::Running | ServerStageState::Succeeded => {
            clear_stage_retry_signal(ledger, local_job_id, updated_at_ms, guard)?;
            return Ok(());
        }
        ServerStageState::Failed if asr.retryable == Some(true) => {}
        ServerStageState::Failed => {
            return Err(DrainStepError::permanent(
                "server ASR stage is failed but not retryable",
            ));
        }
        ServerStageState::Unavailable | ServerStageState::Cancelled => {
            return Err(DrainStepError::permanent(
                "server ASR stage cannot accept the requested retry",
            ));
        }
    }

    let next_attempt = asr
        .attempt
        .checked_add(1)
        .ok_or_else(|| DrainStepError::permanent("server ASR attempt counter overflowed"))?;
    let retry_request = RetryServerStageRequest {
        stage: ServerStageName::Asr,
        attempt: asr.attempt,
        projection_revision: stages.projection_revision,
        capture_manifest_sha256: capture_manifest_sha256.to_owned(),
    };
    let retried = client
        .retry_stage(server_job_id, ServerStageName::Asr, &retry_request)
        .await
        .map_err(DrainStepError::from_stage_retry_commit_error)?;
    ensure_current_for_stage_retry(guard)?;
    require_complete_stage_history(&retried)?;
    if retried.projection_revision <= stages.projection_revision {
        return Err(DrainStepError::stage_retry_reconciling(
            "accepted stage retry did not advance the server projection revision",
        ));
    }
    let retried_asr = retried
        .stages
        .iter()
        .find(|stage| stage.stage == ServerStageName::Asr)
        .ok_or_else(|| {
            DrainStepError::stage_retry_reconciling(
                "accepted stage retry response omitted the ASR projection",
            )
        })?;
    if retried_asr.attempt != next_attempt || retried_asr.state != ServerStageState::Running {
        return Err(DrainStepError::stage_retry_reconciling(
            "accepted stage retry response did not expose the next running ASR attempt",
        ));
    }
    clear_stage_retry_signal(ledger, local_job_id, updated_at_ms, guard)
}

fn require_complete_stage_history(stages: &ServerStageProjectionEnvelope) -> DrainResult<()> {
    if !stages.history_complete {
        return Err(DrainStepError::permanent(
            "server stage history is incomplete and cannot authorize retry",
        ));
    }
    Ok(())
}

fn ensure_current_for_stage_retry(guard: &BatchCommitGuard<'_>) -> DrainResult<()> {
    guard
        .ensure_current()
        .map_err(|error| DrainStepError::stage_retry_reconciling(error.detail))
}

fn clear_stage_retry_signal(
    ledger: &JobLedger,
    local_job_id: &str,
    updated_at_ms: u64,
    guard: &BatchCommitGuard<'_>,
) -> DrainResult<()> {
    guard.commit(|| {
        ledger
            .mark_remote_job_committed(local_job_id, updated_at_ms)
            .map(|_| ())
            .map_err(|error| DrainStepError::stage_retry_reconciling(error.to_string()))
    })
}
