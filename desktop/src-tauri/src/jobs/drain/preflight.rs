use std::{sync::Arc, time::SystemTime};

use sha2::{Digest, Sha256};

use crate::{
    jobs::{
        language_preflight::{language_preflight_outcome, LanguagePreflightOutcome},
        remote, AsrCatalogBinding, JobLedger, JobLedgerError, LidPreflightDispatchFailure,
        LidPreflightDispatchStart, RecordingJobRecord, RecordingJobStatus,
    },
    server_connector::{
        batch::BatchApiClient, lid::LidPreflightError, AsrCapabilityCatalog,
        LidPreflightDispatchProof, ServerConnector,
    },
};

use super::{
    preparation::{prepare_client_preflight_for_resources, PreprocessingStepError},
    RemoteJobDrain,
};

const CATALOG_RETRY_DELAY_MS: u64 = 30_000;
const LID_RETRY_DELAY_MS: u64 = 2_000;
const MAX_LID_ATTEMPTS: u64 = 3;
const UNAVAILABLE_POLICY_REVISION: &str = "server-preflight-unavailable-v1";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum ClientPreflightProgress {
    Advanced,
    Idle,
    ServerUnavailable,
}

#[derive(Debug)]
pub(super) struct ClientPreflightAdvanceError {
    detail: String,
}

impl std::fmt::Display for ClientPreflightAdvanceError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.detail)
    }
}

impl From<JobLedgerError> for ClientPreflightAdvanceError {
    fn from(error: JobLedgerError) -> Self {
        Self {
            detail: error.to_string(),
        }
    }
}

enum PreflightAction {
    Prepare(RecordingJobRecord),
    Promote(RecordingJobRecord),
    Detect {
        job: Box<RecordingJobRecord>,
        artifact: crate::jobs::ClientPreflightArtifactRecord,
        outcome: LanguagePreflightOutcome,
    },
}

struct CatalogSnapshot {
    catalog: AsrCapabilityCatalog,
    binding: AsrCatalogBinding,
    lid_proof: Option<LidPreflightDispatchProof>,
}

pub(super) async fn advance_client_preflight_once(
    app: &tauri::AppHandle,
    connector: &ServerConnector,
    drain: &RemoteJobDrain,
    now_ms: u64,
) -> Result<ClientPreflightProgress, ClientPreflightAdvanceError> {
    let Some(action) = select_action(drain.resources.ledger(), now_ms)? else {
        return Ok(ClientPreflightProgress::Idle);
    };
    match action {
        PreflightAction::Prepare(job) => prepare_local(drain, job, now_ms).await,
        PreflightAction::Promote(job) => promote(app, connector, drain, job, now_ms).await,
        PreflightAction::Detect {
            job,
            artifact,
            outcome,
        } => detect(app, connector, drain, *job, artifact, outcome, now_ms).await,
    }
}

fn select_action(
    ledger: &JobLedger,
    now_ms: u64,
) -> Result<Option<PreflightAction>, JobLedgerError> {
    for job in ledger
        .list_recoverable_jobs()?
        .into_iter()
        .filter(|job| job.status == RecordingJobStatus::Preflighting && !job.cancellation_requested)
    {
        if job
            .next_attempt_at_ms
            .is_some_and(|retry_at| retry_at > now_ms)
        {
            continue;
        }
        let artifact = ledger.get_client_preflight_artifact(&job.job_id)?;
        if job.language_decision_locked {
            return Ok(Some(PreflightAction::Promote(job)));
        }
        let Some(artifact) = artifact else {
            return Ok(Some(PreflightAction::Prepare(job)));
        };
        let outcome = language_preflight_outcome(ledger, &job.job_id)?;
        if matches!(outcome, LanguagePreflightOutcome::Review { .. }) {
            continue;
        }
        return Ok(Some(PreflightAction::Detect {
            job: Box::new(job),
            artifact,
            outcome,
        }));
    }
    Ok(None)
}

async fn prepare_local(
    drain: &RemoteJobDrain,
    job: RecordingJobRecord,
    now_ms: u64,
) -> Result<ClientPreflightProgress, ClientPreflightAdvanceError> {
    let resources = Arc::clone(&drain.resources);
    let owner_namespace = drain.owner_namespace.clone();
    let job_id = job.job_id.clone();
    let prepared = tauri::async_runtime::spawn_blocking(move || {
        prepare_client_preflight_for_resources(
            &resources,
            &owner_namespace,
            &job_id,
            now_ms,
            SystemTime::now(),
        )
    })
    .await;
    match prepared {
        Ok(Ok(_)) => Ok(ClientPreflightProgress::Advanced),
        Ok(Err(error)) if error.is_cancelled() => Ok(ClientPreflightProgress::Advanced),
        Ok(Err(error)) => persist_preparation_failure(drain, &job.job_id, &error, now_ms),
        Err(error) => {
            let detail = format!("client preprocessing worker failed: {error}");
            persist_preparation_failure_message(drain, &job.job_id, &detail, now_ms)
        }
    }
}

fn persist_preparation_failure(
    drain: &RemoteJobDrain,
    job_id: &str,
    error: &PreprocessingStepError,
    now_ms: u64,
) -> Result<ClientPreflightProgress, ClientPreflightAdvanceError> {
    persist_preparation_failure_message(drain, job_id, &error.to_string(), now_ms)
}

fn persist_preparation_failure_message(
    drain: &RemoteJobDrain,
    job_id: &str,
    detail: &str,
    now_ms: u64,
) -> Result<ClientPreflightProgress, ClientPreflightAdvanceError> {
    crate::stt::log_yap(&format!(
        "client recording preflight stopped before language review: {detail}"
    ));
    match drain.resources.ledger().get_job(job_id)? {
        Some(current)
            if current.status == RecordingJobStatus::Preflighting
                && !current.cancellation_requested =>
        {
            drain.resources.ledger().fail_client_preflight(
                job_id,
                "CLIENT_PREFLIGHT_FAILED",
                "The selected recording could not be prepared safely for language review.",
                now_ms,
            )?;
            Ok(ClientPreflightProgress::Advanced)
        }
        _ => Ok(ClientPreflightProgress::Advanced),
    }
}

async fn promote(
    app: &tauri::AppHandle,
    connector: &ServerConnector,
    drain: &RemoteJobDrain,
    job: RecordingJobRecord,
    now_ms: u64,
) -> Result<ClientPreflightProgress, ClientPreflightAdvanceError> {
    let Some(snapshot) = current_catalog(app, connector).await? else {
        return Ok(ClientPreflightProgress::ServerUnavailable);
    };
    if !snapshot
        .catalog
        .supports_recording_decision(&job.language_decision)
    {
        drain.resources.ledger().defer_for_catalog_capability(
            &job.job_id,
            now_ms.saturating_add(CATALOG_RETRY_DELAY_MS),
            now_ms,
        )?;
        return Ok(ClientPreflightProgress::Advanced);
    }
    let rebound = drain.resources.ledger().rebind_unstarted_server_job(
        &job.job_id,
        &snapshot.binding,
        now_ms,
    )?;
    let Some(artifact) = drain
        .resources
        .ledger()
        .get_client_preflight_artifact(&job.job_id)?
    else {
        return persist_preparation_failure_message(
            drain,
            &job.job_id,
            "confirmed client preflight has no durable artifact",
            now_ms,
        );
    };
    let spool_root = drain.resources.remote_jobs_directory().to_path_buf();
    let job_id = job.job_id.clone();
    let language_decision = rebound.language_decision.clone();
    let catalog_revision = snapshot.binding.catalog_revision().to_owned();
    let prepared = tauri::async_runtime::spawn_blocking(move || {
        let preflight = remote::load_imported_client_preflight(
            &job_id,
            &artifact.manifest_path,
            &artifact.manifest_sha256,
            &spool_root,
        )?;
        remote::finalize_imported_client_preflight(
            &preflight,
            &spool_root,
            &language_decision,
            &catalog_revision,
        )?
        .into_ledger_state()
    })
    .await;
    match prepared {
        Ok(Ok(prepared)) => {
            drain
                .resources
                .ledger()
                .promote_client_preflight_to_remote(&job.job_id, &prepared, wall_now_ms())?;
            Ok(ClientPreflightProgress::Advanced)
        }
        Ok(Err(detail)) => {
            persist_preparation_failure_message(drain, &job.job_id, &detail, wall_now_ms())
        }
        Err(error) => persist_preparation_failure_message(
            drain,
            &job.job_id,
            &format!("client preflight finalization worker failed: {error}"),
            wall_now_ms(),
        ),
    }
}

async fn detect(
    app: &tauri::AppHandle,
    connector: &ServerConnector,
    drain: &RemoteJobDrain,
    job: RecordingJobRecord,
    artifact: crate::jobs::ClientPreflightArtifactRecord,
    outcome: LanguagePreflightOutcome,
    now_ms: u64,
) -> Result<ClientPreflightProgress, ClientPreflightAdvanceError> {
    let Some(snapshot) = current_catalog(app, connector).await? else {
        return Ok(ClientPreflightProgress::ServerUnavailable);
    };
    let Some(capability) = snapshot.catalog.lid_preflight() else {
        drain.resources.ledger().record_manual_lid_preflight(
            &job.job_id,
            "server_preflight_unavailable",
            &snapshot.catalog.catalog_revision,
            UNAVAILABLE_POLICY_REVISION,
            now_ms,
        )?;
        return Ok(ClientPreflightProgress::Advanced);
    };
    let policy_revision = capability.policy.revision.clone();
    let request_id = artifact.lid_request_id.clone().unwrap_or_else(|| {
        mint_request_id(&job.job_id, outcome.attempt().saturating_add(1), now_ms)
    });
    let spool_root = drain.resources.remote_jobs_directory().to_path_buf();
    let manifest_path = artifact.manifest_path.clone();
    let manifest_sha256 = artifact.manifest_sha256.clone();
    let catalog = snapshot.catalog.clone();
    let prepared_job_id = job.job_id.clone();
    let prepared_request_id = request_id.clone();
    let preparation = tauri::async_runtime::spawn_blocking(move || {
        let preflight = remote::load_imported_client_preflight(
            &prepared_job_id,
            &manifest_path,
            &manifest_sha256,
            &spool_root,
        )?;
        preflight.prepare_lid_request(&spool_root, &catalog, prepared_request_id)
    })
    .await;
    let preparation = match preparation {
        Ok(Ok(preparation)) => preparation,
        Ok(Err(detail)) => {
            return persist_preparation_failure_message(drain, &job.job_id, &detail, now_ms)
        }
        Err(error) => {
            return persist_preparation_failure_message(
                drain,
                &job.job_id,
                &format!("language probe preparation worker failed: {error}"),
                now_ms,
            )
        }
    };
    match preparation {
        remote::ImportedLidPreparation::Manual {
            source_samples,
            source_pcm_sha256,
            reason,
        } => {
            if source_samples != artifact.source_sample_count
                || source_pcm_sha256 != artifact.source_pcm_sha256
            {
                return persist_preparation_failure_message(
                    drain,
                    &job.job_id,
                    "manual language probe selection differs from its durable source identity",
                    now_ms,
                );
            }
            if artifact.lid_request_id.is_some() {
                return finish_dispatch_failure(
                    drain,
                    &job,
                    &artifact,
                    outcome.attempt(),
                    "lid_probe_selection_changed",
                    true,
                    now_ms,
                );
            }
            drain.resources.ledger().record_manual_lid_preflight(
                &job.job_id,
                reason.as_str(),
                &snapshot.catalog.catalog_revision,
                &policy_revision,
                now_ms,
            )?;
            if reason == crate::server_connector::lid::LidManualReason::ShortRecording
                && snapshot
                    .catalog
                    .supports_recording_decision(&job.language_decision)
            {
                confirm_short_recording(
                    drain.resources.ledger(),
                    &job,
                    &artifact.source_pcm_sha256,
                    &snapshot.binding,
                    now_ms,
                )?;
            }
            Ok(ClientPreflightProgress::Advanced)
        }
        remote::ImportedLidPreparation::Dispatch { request } => {
            dispatch(
                connector,
                drain,
                job,
                artifact,
                outcome,
                snapshot,
                policy_revision,
                *request,
                now_ms,
            )
            .await
        }
    }
}

#[allow(clippy::too_many_arguments)]
async fn dispatch(
    connector: &ServerConnector,
    drain: &RemoteJobDrain,
    job: RecordingJobRecord,
    artifact: crate::jobs::ClientPreflightArtifactRecord,
    outcome: LanguagePreflightOutcome,
    snapshot: CatalogSnapshot,
    policy_revision: String,
    request: crate::server_connector::lid::LidPreflightRequest,
    now_ms: u64,
) -> Result<ClientPreflightProgress, ClientPreflightAdvanceError> {
    let Some(lease) = connector.batch_connection_lease().ok().flatten() else {
        return Ok(ClientPreflightProgress::ServerUnavailable);
    };
    let base_url = lease.client().base_url_identity();
    let active_dispatch = artifact.lid_request_id.is_some();
    if active_dispatch
        && (artifact.lid_server_base_url.as_deref() != Some(base_url)
            || artifact.lid_catalog_revision.as_deref()
                != Some(snapshot.catalog.catalog_revision.as_str())
            || artifact.lid_policy_revision.as_deref() != Some(policy_revision.as_str()))
    {
        if !cancel_persisted_dispatch(connector, &artifact).await? {
            return Ok(ClientPreflightProgress::ServerUnavailable);
        }
        return finish_dispatch_failure(
            drain,
            &job,
            &artifact,
            outcome.attempt(),
            "lid_contract_changed",
            true,
            now_ms,
        );
    }
    let attempt = if active_dispatch {
        match outcome {
            LanguagePreflightOutcome::Running { attempt } => attempt,
            _ => {
                return persist_preparation_failure_message(
                    drain,
                    &job.job_id,
                    "durable LID request has no running stage",
                    now_ms,
                )
            }
        }
    } else {
        let proof = snapshot
            .lid_proof
            .as_ref()
            .ok_or_else(|| ClientPreflightAdvanceError {
                detail: "current LID capability has no dispatch proof".into(),
            })?;
        connector
            .with_current_lid_preflight_proof(&lease, proof, || {
                drain
                    .resources
                    .ledger()
                    .begin_lid_preflight_dispatch(LidPreflightDispatchStart {
                        job_id: &job.job_id,
                        request_id: request.request_id(),
                        server_base_url: base_url,
                        catalog_revision: &snapshot.catalog.catalog_revision,
                        component_id: request.component_id(),
                        policy_revision: &policy_revision,
                        started_at_ms: now_ms,
                    })
            })
            .map_err(|detail| ClientPreflightAdvanceError { detail })??
    };
    let submitted = submit_with_cancellation(
        drain.resources.ledger(),
        lease.client(),
        &job.job_id,
        request.request_id(),
        &request,
    )
    .await?;
    let completed_at_ms = wall_now_ms();
    let Some(submitted) = submitted else {
        return Ok(ClientPreflightProgress::Advanced);
    };
    match submitted {
        Ok(result) => match drain.resources.ledger().finish_lid_preflight_dispatch(
            &job.job_id,
            request.request_id(),
            attempt,
            &result,
            completed_at_ms,
        ) {
            Ok(_) => Ok(ClientPreflightProgress::Advanced),
            Err(_error) if job_preflight_is_inactive(drain.resources.ledger(), &job.job_id)? => {
                Ok(ClientPreflightProgress::Advanced)
            }
            Err(error) => Err(error.into()),
        },
        Err(error) => {
            if job_preflight_is_inactive(drain.resources.ledger(), &job.job_id)? {
                return Ok(ClientPreflightProgress::Advanced);
            }
            let retryable = error.is_retryable() && attempt < MAX_LID_ATTEMPTS;
            drain
                .resources
                .ledger()
                .fail_lid_preflight_dispatch(LidPreflightDispatchFailure {
                    job_id: &job.job_id,
                    request_id: request.request_id(),
                    attempt,
                    reason: lid_failure_reason(&error),
                    retryable,
                    retry_at_ms: retryable
                        .then(|| completed_at_ms.saturating_add(LID_RETRY_DELAY_MS)),
                    completed_at_ms,
                })?;
            Ok(ClientPreflightProgress::Advanced)
        }
    }
}

async fn submit_with_cancellation(
    ledger: &JobLedger,
    client: &BatchApiClient,
    job_id: &str,
    request_id: &str,
    request: &crate::server_connector::lid::LidPreflightRequest,
) -> Result<
    Option<Result<crate::server_connector::lid::LidPreflightResult, LidPreflightError>>,
    JobLedgerError,
> {
    let mut submitted = Box::pin(client.lid_preflight(request));
    let mut cancellation_check = tokio::time::interval(std::time::Duration::from_millis(100));
    cancellation_check.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            result = &mut submitted => return Ok(Some(result)),
            _ = cancellation_check.tick() => {
                if job_preflight_is_inactive(ledger, job_id)? {
                    drop(submitted);
                    let acknowledged = match client.cancel_lid_preflight(request_id).await {
                        Ok(()) => true,
                        Err(error) if error.is_not_found() => true,
                        Err(_) => {
                            crate::stt::log_yap("language preflight cancellation acknowledgement was unavailable");
                            false
                        }
                    };
                    if acknowledged {
                        match ledger.acknowledge_terminal_lid_preflight_dispatch(
                            job_id,
                            request_id,
                            wall_now_ms(),
                        ) {
                            Ok(()) | Err(JobLedgerError::NotFound(_)) => {}
                            Err(error) => return Err(error),
                        }
                    }
                    return Ok(None);
                }
            }
        }
    }
}

fn finish_dispatch_failure(
    drain: &RemoteJobDrain,
    job: &RecordingJobRecord,
    artifact: &crate::jobs::ClientPreflightArtifactRecord,
    attempt: u64,
    reason: &str,
    retryable: bool,
    now_ms: u64,
) -> Result<ClientPreflightProgress, ClientPreflightAdvanceError> {
    let request_id =
        artifact
            .lid_request_id
            .as_deref()
            .ok_or_else(|| ClientPreflightAdvanceError {
                detail: "LID failure has no durable request ID".into(),
            })?;
    drain
        .resources
        .ledger()
        .fail_lid_preflight_dispatch(LidPreflightDispatchFailure {
            job_id: &job.job_id,
            request_id,
            attempt,
            reason,
            retryable,
            retry_at_ms: retryable.then(|| now_ms.saturating_add(LID_RETRY_DELAY_MS)),
            completed_at_ms: now_ms,
        })?;
    Ok(ClientPreflightProgress::Advanced)
}

async fn cancel_persisted_dispatch(
    connector: &ServerConnector,
    artifact: &crate::jobs::ClientPreflightArtifactRecord,
) -> Result<bool, ClientPreflightAdvanceError> {
    let (Some(base_url), Some(request_id)) = (
        artifact.lid_server_base_url.as_deref(),
        artifact.lid_request_id.as_deref(),
    ) else {
        return Err(ClientPreflightAdvanceError {
            detail: "persisted LID dispatch has incomplete cancellation identity".into(),
        });
    };
    let client = connector
        .batch_client_for_persisted_origin(base_url)
        .map_err(|error| ClientPreflightAdvanceError {
            detail: error.to_string(),
        })?;
    match client.cancel_lid_preflight(request_id).await {
        Ok(()) => Ok(true),
        Err(error) if error.is_not_found() => Ok(true),
        Err(_) => {
            crate::stt::log_yap(
                "stale language preflight cancellation acknowledgement was unavailable",
            );
            Ok(false)
        }
    }
}

fn confirm_short_recording(
    ledger: &JobLedger,
    job: &RecordingJobRecord,
    source_pcm_sha256: &str,
    binding: &AsrCatalogBinding,
    now_ms: u64,
) -> Result<(), JobLedgerError> {
    ledger.confirm_language_decision(
        &job.job_id,
        &job.language_decision,
        source_pcm_sha256,
        now_ms,
        Some(serde_json::json!({
            "action": "confirmed_import_selection",
            "reason": "short_recording",
        })),
        Some(binding),
    )?;
    Ok(())
}

async fn current_catalog(
    app: &tauri::AppHandle,
    connector: &ServerConnector,
) -> Result<Option<CatalogSnapshot>, ClientPreflightAdvanceError> {
    crate::server_connector::with_current_asr_capabilities(app, connector, |current| {
        CatalogSnapshot {
            catalog: current.catalog().clone(),
            binding: current.binding().clone(),
            lid_proof: current
                .lid_preflight_dispatch()
                .map(|dispatch| dispatch.dispatch_proof()),
        }
    })
    .await
    .map_err(|detail| ClientPreflightAdvanceError { detail })
}

fn job_preflight_is_inactive(ledger: &JobLedger, job_id: &str) -> Result<bool, JobLedgerError> {
    Ok(ledger.get_job(job_id)?.is_none_or(|job| {
        job.cancellation_requested || job.status != RecordingJobStatus::Preflighting
    }))
}

fn mint_request_id(job_id: &str, attempt: u64, now_ms: u64) -> String {
    let mut hash = Sha256::new();
    hash.update(job_id.as_bytes());
    hash.update(attempt.to_le_bytes());
    hash.update(now_ms.to_le_bytes());
    let prefix = hash
        .finalize()
        .iter()
        .take(16)
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    format!("lid-{prefix}")
}

fn lid_failure_reason(error: &LidPreflightError) -> &'static str {
    match error {
        LidPreflightError::InvalidRequest(_) => "invalid_request",
        LidPreflightError::Encode(_) => "encode_failed",
        LidPreflightError::Transport(_) => "transport_failed",
        LidPreflightError::ResponseTooLarge => "response_too_large",
        LidPreflightError::MalformedResponse => "malformed_response",
        LidPreflightError::Api { .. } => "server_rejected",
    }
}

fn wall_now_ms() -> u64 {
    SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u128::from(u64::MAX)) as u64
}
