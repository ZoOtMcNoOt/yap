use std::time::{Duration, SystemTime};

use tauri::{Emitter, Manager};

use crate::{
    jobs::{AsrCatalogBinding, JobLedger, JobLedgerError, RecordingJobRecord, RecordingJobStatus},
    server_connector::{AsrCapabilityCatalog, ServerConnector},
};

use super::{
    preflight::{advance_client_preflight_once, ClientPreflightProgress},
    preparation::prepare_job_for_resources,
    processing::advance_processing_with_lease,
    recovery::advance_persisted_cancellation_once,
    upload::advance_upload_with_lease,
    RemoteJobDrain,
};

const CATALOG_RETRY_DELAY_MS: u64 = 30_000;
const DURABLE_STATE_ERROR_BACKOFF: Duration = Duration::from_secs(2);

#[derive(Default)]
pub(super) struct DurableStateCircuit {
    open: bool,
}

impl DurableStateCircuit {
    pub(super) fn trip(&mut self) {
        self.open = true;
    }

    pub(super) fn is_open(&self) -> bool {
        self.open
    }

    pub(super) fn try_close_with<E>(
        &mut self,
        probe: impl FnOnce() -> Result<(), E>,
    ) -> Result<bool, E> {
        if !self.open {
            return Ok(false);
        }
        probe()?;
        self.open = false;
        Ok(true)
    }
}

pub(super) fn claim_preprocessing_for_catalog(
    ledger: &JobLedger,
    candidate: &RecordingJobRecord,
    catalog: &AsrCapabilityCatalog,
    binding: &AsrCatalogBinding,
    now_ms: u64,
    retry_at_ms: u64,
) -> Result<bool, JobLedgerError> {
    if !candidate.language_decision_locked {
        return Err(JobLedgerError::InvalidRecord(
            "preprocessing admission requires a confirmed language decision",
        ));
    }
    if catalog.supports_recording_decision(&candidate.language_decision) {
        ledger
            .bind_and_claim_preprocessing(&candidate.job_id, binding, now_ms)
            .map(|_| true)
    } else {
        ledger
            .defer_for_catalog_capability(&candidate.job_id, retry_at_ms, now_ms)
            .map(|_| false)
    }
}

pub(crate) fn start(
    app: &tauri::AppHandle,
    lifecycle: &crate::runtime::DesktopLifecycle,
) -> std::io::Result<()> {
    let app = app.clone();
    lifecycle.spawn_async_task("remote-job-drain", async move {
        run(app).await;
    })
}

async fn run(app: tauri::AppHandle) {
    let mut next_retention_check_ms = 0_u64;
    let mut next_pending_error_log_ms = 0_u64;
    let mut next_circuit_error_log_ms = 0_u64;
    let mut durable_state_circuit = DurableStateCircuit::default();
    loop {
        let loop_now_ms = now_ms();
        if durable_state_circuit.is_open() {
            let drain = app.state::<RemoteJobDrain>();
            match durable_state_circuit
                .try_close_with(|| drain.resources.ledger().commit_write_probe())
            {
                Ok(true) => crate::stt::log_yap(
                    "recording job durable-state circuit recovered after a committed write probe",
                ),
                Ok(false) => {}
                Err(error) => {
                    if loop_now_ms >= next_circuit_error_log_ms {
                        next_circuit_error_log_ms = loop_now_ms.saturating_add(60_000);
                        crate::stt::log_yap(&format!(
                            "recording job durable-state circuit remains open; no work will dispatch: {error}"
                        ));
                    }
                    tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                    continue;
                }
            }
        }
        if loop_now_ms >= next_retention_check_ms {
            next_retention_check_ms = loop_now_ms.saturating_add(60_000);
            match app.state::<RemoteJobDrain>().enforce_retention(loop_now_ms) {
                Ok(true) => emit_jobs_changed(&app),
                Ok(false) => {}
                Err(error) => {
                    if error.durable_state_unavailable() {
                        crate::stt::log_yap(&format!(
                            "recording job retention could not commit; opening durable-state circuit: {error}"
                        ));
                        next_retention_check_ms = loop_now_ms;
                        durable_state_circuit.trip();
                        tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                        continue;
                    }
                    crate::stt::log_yap(&format!(
                        "owned remote recording retention cleanup remains pending: {error}"
                    ));
                }
            }
        }
        let has_work = match app.state::<RemoteJobDrain>().has_pending_work() {
            Ok(has_work) => has_work,
            Err(error) => {
                if loop_now_ms >= next_pending_error_log_ms {
                    next_pending_error_log_ms = loop_now_ms.saturating_add(60_000);
                    crate::stt::log_yap(&format!(
                        "remote job drain state remains unavailable; retrying: {error}"
                    ));
                }
                tokio::time::sleep(Duration::from_secs(2)).await;
                continue;
            }
        };
        if !has_work {
            tokio::time::sleep(Duration::from_secs(2)).await;
            continue;
        }

        let connector = app.state::<ServerConnector>();
        let now = now_ms();
        let drain = app.state::<RemoteJobDrain>();
        match advance_persisted_cancellation_once(
            drain.resources.ledger(),
            drain.resources.remote_jobs_directory(),
            &connector,
            now,
        )
        .await
        {
            Ok(true) => {
                emit_jobs_changed(&app);
                continue;
            }
            Ok(false) => {}
            Err(error) => {
                crate::stt::log_yap(&format!(
                    "remote cancellation remains pending after a bounded request: {error}"
                ));
                durable_state_circuit.trip();
                tokio::time::sleep(Duration::from_secs(2)).await;
                continue;
            }
        }
        match advance_client_preflight_once(&app, &connector, &drain, now).await {
            Ok(ClientPreflightProgress::Advanced) => {
                emit_jobs_changed(&app);
                continue;
            }
            Ok(ClientPreflightProgress::Idle | ClientPreflightProgress::ServerUnavailable) => {}
            Err(error) => {
                crate::stt::log_yap(&format!(
                    "client recording preflight durable state is unavailable; backing off: {error}"
                ));
                durable_state_circuit.trip();
                tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                continue;
            }
        }
        if connector.batch_connection_lease().ok().flatten().is_none() {
            connector.refresh_for_job_drain(&app).await;
        }
        if connector.batch_connection_lease().ok().flatten().is_none() {
            tokio::time::sleep(Duration::from_secs(2)).await;
            continue;
        }

        let preprocessing_candidate = drain
            .resources
            .ledger()
            .list_recoverable_jobs()
            .ok()
            .and_then(|jobs| {
                jobs.into_iter().find(|job| {
                    matches!(
                        job.status,
                        RecordingJobStatus::QueuedServer | RecordingJobStatus::Preprocessing
                    ) && job.language_decision_locked
                        && job
                            .next_attempt_at_ms
                            .is_none_or(|retry_at| retry_at <= now)
                })
            });
        if let Some(candidate) = preprocessing_candidate {
            let job_id = candidate.job_id.clone();
            let claim = crate::server_connector::with_current_asr_capabilities(
                &app,
                &connector,
                |current| {
                    claim_preprocessing_for_catalog(
                        drain.resources.ledger(),
                        &candidate,
                        current.catalog(),
                        current.binding(),
                        now,
                        now.saturating_add(CATALOG_RETRY_DELAY_MS),
                    )
                },
            )
            .await;
            let claimed = match claim {
                Ok(Some(Ok(claimed))) => claimed,
                Ok(Some(Err(error))) => {
                    crate::stt::log_yap(&format!(
                        "remote preprocessing catalog claim could not commit; backing off: {error}"
                    ));
                    durable_state_circuit.trip();
                    emit_jobs_changed(&app);
                    tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                    continue;
                }
                Ok(None) => {
                    let deferred = drain.resources.ledger().defer_for_catalog_capability(
                        &job_id,
                        now.saturating_add(CATALOG_RETRY_DELAY_MS),
                        now,
                    );
                    if let Err(error) = deferred {
                        crate::stt::log_yap(&format!(
                            "remote preprocessing catalog deferral could not commit; backing off: {error}"
                        ));
                        durable_state_circuit.trip();
                        tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                    }
                    emit_jobs_changed(&app);
                    continue;
                }
                Err(error) => {
                    crate::stt::log_yap(&format!(
                        "current ASR catalog remains unavailable before preprocessing: {error}"
                    ));
                    let deferred = drain.resources.ledger().defer_for_catalog_capability(
                        &job_id,
                        now.saturating_add(CATALOG_RETRY_DELAY_MS),
                        now,
                    );
                    if let Err(persist_error) = deferred {
                        crate::stt::log_yap(&format!(
                            "remote preprocessing catalog outage could not be deferred; backing off: {persist_error}"
                        ));
                        durable_state_circuit.trip();
                        tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                    }
                    emit_jobs_changed(&app);
                    continue;
                }
            };
            if !claimed {
                emit_jobs_changed(&app);
                continue;
            }
            let prepare_app = app.clone();
            let worker_job_id = job_id.clone();
            let prepared = tauri::async_runtime::spawn_blocking(move || {
                let drain = prepare_app.state::<RemoteJobDrain>();
                prepare_job_for_resources(
                    &drain.resources,
                    &drain.owner_namespace,
                    &worker_job_id,
                    now,
                    SystemTime::now(),
                )
            })
            .await;
            match prepared {
                Ok(Ok(Some(_job_id))) => {
                    emit_jobs_changed(&app);
                    continue;
                }
                Ok(Ok(None)) => {}
                Ok(Err(error)) => {
                    crate::stt::log_yap(&format!("remote preprocessing stopped safely: {error}"));
                    if !error.is_cancelled() {
                        if let Some(job_id) = error.job_id() {
                            if let Err(persist_error) = app
                                .state::<RemoteJobDrain>()
                                .fail_preprocessing_job(job_id, now)
                            {
                                crate::stt::log_yap(&format!(
                                    "remote preprocessing failure could not be persisted; backing off: {persist_error}"
                                ));
                                durable_state_circuit.trip();
                                tokio::time::sleep(Duration::from_secs(2)).await;
                            }
                        }
                    }
                    emit_jobs_changed(&app);
                    continue;
                }
                Err(error) => {
                    crate::stt::log_yap(&format!("remote preprocessing worker failed: {error}"));
                    if let Err(persist_error) = app
                        .state::<RemoteJobDrain>()
                        .fail_preprocessing_job(&job_id, now)
                    {
                        crate::stt::log_yap(&format!(
                            "remote preprocessing panic could not be persisted: {persist_error}"
                        ));
                        durable_state_circuit.trip();
                    }
                    emit_jobs_changed(&app);
                    // A panicking blocking worker is always contained by a
                    // bounded delay, including when SQLite could not persist
                    // the terminal failure for this exact job.
                    tokio::time::sleep(Duration::from_secs(2)).await;
                    continue;
                }
            }
        }

        let drain = app.state::<RemoteJobDrain>();
        let upload_candidate = drain
            .resources
            .ledger()
            .list_recoverable_jobs()
            .ok()
            .and_then(|jobs| {
                jobs.into_iter().find(|job| {
                    job.status == RecordingJobStatus::Uploading
                        && job
                            .next_attempt_at_ms
                            .is_none_or(|retry_at| retry_at <= now)
                })
            });
        let mut catalog_proof = None;
        let upload_job_id = upload_candidate.as_ref().map(|job| job.job_id.clone());
        if let Some(candidate) = upload_candidate.as_ref() {
            let prepared = drain
                .resources
                .ledger()
                .get_prepared_remote_job(&candidate.job_id);
            let needs_catalog = match prepared {
                Ok(Some(prepared)) => {
                    prepared.server_job_id.is_none() && prepared.create_attempt_base_url.is_none()
                }
                Ok(None) => false,
                Err(error) => {
                    crate::stt::log_yap(&format!(
                        "remote upload catalog preflight could not read durable state; backing off: {error}"
                    ));
                    durable_state_circuit.trip();
                    tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                    continue;
                }
            };
            if needs_catalog {
                let job_id = candidate.job_id.clone();
                let validation = crate::server_connector::with_current_asr_capabilities(
                    &app,
                    &connector,
                    |current| {
                        if current
                            .catalog()
                            .supports_recording_decision(&candidate.language_decision)
                        {
                            drain.resources.ledger().rebind_unstarted_server_job(
                                &job_id,
                                current.binding(),
                                now,
                            )?;
                            Ok::<_, crate::jobs::JobLedgerError>(Some(current.dispatch_proof()))
                        } else {
                            drain.resources.ledger().defer_for_catalog_capability(
                                &job_id,
                                now.saturating_add(CATALOG_RETRY_DELAY_MS),
                                now,
                            )?;
                            Ok::<_, crate::jobs::JobLedgerError>(None)
                        }
                    },
                )
                .await;
                catalog_proof = match validation {
                    Ok(Some(Ok(Some(proof)))) => Some(proof),
                    Ok(Some(Ok(None))) => {
                        emit_jobs_changed(&app);
                        continue;
                    }
                    Ok(None) => {
                        let deferred = drain.resources.ledger().defer_for_catalog_capability(
                            &job_id,
                            now.saturating_add(CATALOG_RETRY_DELAY_MS),
                            now,
                        );
                        if let Err(error) = deferred {
                            crate::stt::log_yap(&format!(
                                "remote upload catalog deferral could not commit; backing off: {error}"
                            ));
                            durable_state_circuit.trip();
                            tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                        }
                        emit_jobs_changed(&app);
                        continue;
                    }
                    Ok(Some(Err(error))) => {
                        crate::stt::log_yap(&format!(
                            "remote upload catalog validation could not commit; backing off: {error}"
                        ));
                        durable_state_circuit.trip();
                        emit_jobs_changed(&app);
                        tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                        continue;
                    }
                    Err(error) => {
                        crate::stt::log_yap(&format!(
                            "current ASR catalog remains unavailable before upload: {error}"
                        ));
                        let deferred = drain.resources.ledger().defer_for_catalog_capability(
                            &job_id,
                            now.saturating_add(CATALOG_RETRY_DELAY_MS),
                            now,
                        );
                        if let Err(persist_error) = deferred {
                            crate::stt::log_yap(&format!(
                                "remote upload catalog outage could not be deferred; backing off: {persist_error}"
                            ));
                            durable_state_circuit.trip();
                            tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                        }
                        emit_jobs_changed(&app);
                        continue;
                    }
                };
            }
        }
        if let Some(upload_job_id) = upload_job_id.as_deref() {
            let Some(lease) = connector.batch_connection_lease().ok().flatten() else {
                tokio::time::sleep(Duration::from_secs(2)).await;
                continue;
            };
            match advance_upload_with_lease(
                drain.resources.ledger(),
                drain.resources.remote_jobs_directory(),
                &connector,
                &lease,
                upload_job_id,
                catalog_proof.as_ref(),
                now,
            )
            .await
            {
                Ok(true) => {
                    emit_jobs_changed(&app);
                    continue;
                }
                Ok(false) => {}
                Err(error) => {
                    crate::stt::log_yap(&format!("remote upload step will not commit: {error}"));
                    let persisted = drain.handle_upload_error(
                        upload_job_id,
                        &error,
                        now,
                        now.saturating_add(CATALOG_RETRY_DELAY_MS),
                    );
                    if let Err(persist_error) = persisted {
                        crate::stt::log_yap(&format!(
                            "remote upload retry state could not be persisted; backing off: {persist_error}"
                        ));
                        durable_state_circuit.trip();
                        tokio::time::sleep(DURABLE_STATE_ERROR_BACKOFF).await;
                    }
                    emit_jobs_changed(&app);
                    continue;
                }
            }
        }

        let processing_job_id = drain
            .resources
            .ledger()
            .list_recoverable_jobs()
            .ok()
            .and_then(|jobs| {
                jobs.into_iter()
                    .find(|job| {
                        matches!(
                            job.status,
                            RecordingJobStatus::ServerProcessing | RecordingJobStatus::Saving
                        ) && job
                            .next_attempt_at_ms
                            .is_none_or(|retry_at| retry_at <= now)
                    })
                    .map(|job| job.job_id)
            });
        if let Some(processing_job_id) = processing_job_id.as_deref() {
            let Some(lease) = connector.batch_connection_lease().ok().flatten() else {
                tokio::time::sleep(Duration::from_secs(2)).await;
                continue;
            };
            match advance_processing_with_lease(
                drain.resources.ledger(),
                drain.resources.remote_jobs_directory(),
                &connector,
                &lease,
                processing_job_id,
                now,
            )
            .await
            {
                Ok(true) => emit_jobs_changed(&app),
                Ok(false) => {}
                Err(error) => {
                    crate::stt::log_yap(&format!("remote result step will not commit: {error}"));
                    if let Err(persist_error) = drain.schedule_remote_retry_for_job(
                        processing_job_id,
                        &[
                            RecordingJobStatus::ServerProcessing,
                            RecordingJobStatus::Saving,
                        ],
                        &error,
                        now,
                    ) {
                        crate::stt::log_yap(&format!(
                            "remote result retry state could not be persisted; backing off: {persist_error}"
                        ));
                        durable_state_circuit.trip();
                    }
                    emit_jobs_changed(&app);
                }
            }
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}

fn emit_jobs_changed(app: &tauri::AppHandle) {
    if let Err(error) = app.emit_to(
        crate::authorization::MAIN_WINDOW_LABEL,
        "recording-jobs-changed",
        (),
    ) {
        crate::stt::log_yap(&format!(
            "recording jobs event failed after background commit: {error}"
        ));
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u128::from(u64::MAX)) as u64
}
