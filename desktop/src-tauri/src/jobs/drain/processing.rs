use std::{path::Path, sync::Mutex};

use crate::{
    jobs::{remote, JobLedger, RecordingJobStatus, REMOTE_STAGE_RETRY_REQUESTED},
    server_connector::{
        batch::{
            validate_speaker_result_for_recording, validate_transcript_result_for_recording,
            BatchApiClient, CreateRecordingJobRequest, RetryServerStageRequest, ServerStageName,
            ServerStageProjectionEnvelope, ServerStageState,
        },
        BatchConnectionLease, ServerConnector,
    },
};

use super::{
    contract::{result_retention_expiry_ms, validate_job_projection},
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
    let publication_gate = Mutex::new(());
    advance_processing_once_guarded(
        ledger,
        remote_jobs_directory,
        client,
        updated_at_ms,
        &BatchCommitGuard::Unchecked,
        &publication_gate,
    )
    .await
}

pub(super) async fn advance_processing_with_lease(
    ledger: &JobLedger,
    remote_jobs_directory: &Path,
    connector: &ServerConnector,
    lease: &BatchConnectionLease,
    publication_gate: &Mutex<()>,
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
        publication_gate,
    )
    .await
}

pub(super) fn finalize_published_saving_result(
    ledger: &JobLedger,
    remote_jobs_directory: &Path,
    publication_gate: &Mutex<()>,
    job_id: &str,
    updated_at_ms: u64,
) -> DrainResult<bool> {
    finalize_published_saving_result_after_acquiring_mutation(
        ledger,
        remote_jobs_directory,
        publication_gate,
        job_id,
        updated_at_ms,
        || {},
    )
}

#[cfg(test)]
pub(super) fn finalize_published_saving_result_with_mutation_observer_for_test(
    ledger: &JobLedger,
    remote_jobs_directory: &Path,
    publication_gate: &Mutex<()>,
    job_id: &str,
    updated_at_ms: u64,
    after_acquiring_mutation: impl FnOnce(),
) -> DrainResult<bool> {
    finalize_published_saving_result_after_acquiring_mutation(
        ledger,
        remote_jobs_directory,
        publication_gate,
        job_id,
        updated_at_ms,
        after_acquiring_mutation,
    )
}

fn finalize_published_saving_result_after_acquiring_mutation(
    ledger: &JobLedger,
    remote_jobs_directory: &Path,
    publication_gate: &Mutex<()>,
    job_id: &str,
    updated_at_ms: u64,
    after_acquiring_mutation: impl FnOnce(),
) -> DrainResult<bool> {
    let _publication = publication_gate
        .lock()
        .map_err(|_| DrainStepError::permanent("recording job mutation gate is unavailable"))?;
    after_acquiring_mutation();
    let Some(candidate) = ledger
        .get_job(job_id)
        .map_err(|error| DrainStepError::permanent(error.to_string()))?
    else {
        return Ok(false);
    };
    if candidate.status != RecordingJobStatus::Saving {
        return Ok(false);
    }
    let prepared = ledger
        .get_prepared_remote_job(job_id)
        .map_err(|error| DrainStepError::permanent(error.to_string()))?
        .ok_or_else(|| DrainStepError::permanent("saving job has no durable remote state"))?;
    let request = CreateRecordingJobRequest::decode_persisted(&prepared.create_request_json)?;
    let chunks = ledger
        .list_chunks(job_id)
        .map_err(|error| DrainStepError::permanent(error.to_string()))?;
    validate_durable_upload_state(&candidate, &prepared, &request, &chunks)?;
    let Some(published) =
        remote::discover_published_remote_result_bundle(job_id, remote_jobs_directory)?
    else {
        return Ok(false);
    };
    validate_transcript_result_for_recording(&published.result, &request)?;
    let speaker_result = published.load_speaker_result()?;
    if published.result.requires_speaker_result() {
        validate_speaker_result_for_recording(
            speaker_result.as_ref().ok_or_else(|| {
                DrainStepError::permanent("published result omitted its speaker companion")
            })?,
            &published.result,
            &request,
        )?;
    } else if speaker_result.is_some() {
        return Err(DrainStepError::permanent(
            "published result has an unexpected speaker companion",
        ));
    }
    let terminal_status = match published.result.status.as_str() {
        "complete" => RecordingJobStatus::Complete,
        "partial" => RecordingJobStatus::Partial,
        _ => unreachable!("validated published result status is terminal"),
    };
    let output_path = published.result_directory.join("transcript.txt");
    ledger
        .finalize_remote_result(
            job_id,
            &output_path,
            result_retention_expiry_ms(&request)?,
            updated_at_ms,
            terminal_status,
        )
        .map_err(|error| DrainStepError::permanent(error.to_string()))?;
    Ok(true)
}

#[cfg(test)]
pub(super) async fn advance_processing_once_guarded(
    ledger: &JobLedger,
    remote_jobs_directory: &Path,
    client: &BatchApiClient,
    updated_at_ms: u64,
    guard: &BatchCommitGuard<'_>,
    publication_gate: &Mutex<()>,
) -> DrainResult<bool> {
    advance_processing_job_once_guarded(
        ledger,
        remote_jobs_directory,
        client,
        None,
        updated_at_ms,
        guard,
        publication_gate,
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
    let publication_gate = Mutex::new(());
    advance_processing_job_once_guarded(
        ledger,
        remote_jobs_directory,
        client,
        Some(job_id),
        updated_at_ms,
        guard,
        &publication_gate,
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
    publication_gate: &Mutex<()>,
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
        &[
            "server_processing",
            "complete",
            "partial",
            "failed",
            "cancelled",
        ],
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
    if !matches!(projection.status.as_str(), "complete" | "partial") {
        return Err(DrainStepError::permanent(format!(
            "server job entered terminal status {} before publishing a result",
            projection.status
        )));
    }

    guard.ensure_current()?;
    let result = client.result(server_job_id).await?;
    validate_transcript_result_for_recording(&result, &request)?;
    if result.status != projection.status {
        return Err(DrainStepError::permanent(
            "server result status differs from its terminal job projection",
        ));
    }
    let speaker_result = if result.requires_speaker_result() {
        guard.ensure_current()?;
        let speaker_result = client.speaker_result(server_job_id).await?;
        validate_speaker_result_for_recording(&speaker_result, &result, &request)?;
        Some(speaker_result)
    } else {
        None
    };
    guard.commit(|| {
        let _publication = publication_gate
            .lock()
            .map_err(|_| DrainStepError::permanent("recording job mutation gate is unavailable"))?;
        ledger
            .begin_remote_result_saving(&candidate.job_id, updated_at_ms)
            .map_err(|error| DrainStepError::permanent(error.to_string()))?;
        let output_path = remote::publish_remote_result(
            &candidate.job_id,
            remote_jobs_directory,
            &result,
            speaker_result.as_ref(),
        )?;
        let terminal_status = match result.status.as_str() {
            "complete" => RecordingJobStatus::Complete,
            "partial" => RecordingJobStatus::Partial,
            _ => unreachable!("validated result status is terminal"),
        };
        ledger
            .finalize_remote_result(
                &candidate.job_id,
                &output_path,
                result_expires_at_ms,
                updated_at_ms,
                terminal_status,
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
