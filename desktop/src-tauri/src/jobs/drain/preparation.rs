use std::{path::Path, time::SystemTime};

use crate::{
    audio::session::OwnerNamespace,
    jobs::{remote, JobLedger, RecordingJobResources, RecordingJobStatus},
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum PreprocessingStepErrorKind {
    Cancelled,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct PreprocessingStepError {
    job_id: Option<String>,
    kind: PreprocessingStepErrorKind,
    detail: String,
}

impl PreprocessingStepError {
    fn unidentified(detail: impl Into<String>) -> Self {
        Self {
            job_id: None,
            kind: PreprocessingStepErrorKind::Failed,
            detail: detail.into(),
        }
    }

    fn for_job(job_id: String, detail: String, cancelled: bool) -> Self {
        Self {
            job_id: Some(job_id),
            kind: if cancelled {
                PreprocessingStepErrorKind::Cancelled
            } else {
                PreprocessingStepErrorKind::Failed
            },
            detail,
        }
    }

    pub(super) fn job_id(&self) -> Option<&str> {
        self.job_id.as_deref()
    }

    pub(super) fn is_cancelled(&self) -> bool {
        self.kind == PreprocessingStepErrorKind::Cancelled
    }

    #[cfg(test)]
    fn into_detail(self) -> String {
        self.detail
    }
}

impl std::fmt::Display for PreprocessingStepError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.detail)
    }
}

impl std::error::Error for PreprocessingStepError {}

struct QueuedJobPreparation<'a> {
    ledger: &'a JobLedger,
    owned_live_directory: &'a Path,
    remote_jobs_directory: &'a Path,
    owner_namespace: &'a OwnerNamespace,
    updated_at_ms: u64,
    started_at: SystemTime,
    resources: Option<&'a RecordingJobResources>,
    exact_job_id: Option<&'a str>,
    allow_queued_claim: bool,
}

#[cfg(test)]
pub(super) fn prepare_next_queued_job_for_resources(
    resources: &RecordingJobResources,
    owner_namespace: &OwnerNamespace,
    updated_at_ms: u64,
    started_at: SystemTime,
) -> Result<Option<String>, PreprocessingStepError> {
    prepare_next_queued_job_impl(QueuedJobPreparation {
        ledger: resources.ledger(),
        owned_live_directory: resources.owned_live_directory(),
        remote_jobs_directory: resources.remote_jobs_directory(),
        owner_namespace,
        updated_at_ms,
        started_at,
        resources: Some(resources),
        exact_job_id: None,
        allow_queued_claim: true,
    })
}

pub(super) fn prepare_job_for_resources(
    resources: &RecordingJobResources,
    owner_namespace: &OwnerNamespace,
    job_id: &str,
    updated_at_ms: u64,
    started_at: SystemTime,
) -> Result<Option<String>, PreprocessingStepError> {
    prepare_next_queued_job_impl(QueuedJobPreparation {
        ledger: resources.ledger(),
        owned_live_directory: resources.owned_live_directory(),
        remote_jobs_directory: resources.remote_jobs_directory(),
        owner_namespace,
        updated_at_ms,
        started_at,
        resources: Some(resources),
        exact_job_id: Some(job_id),
        allow_queued_claim: false,
    })
}

pub(super) fn prepare_client_preflight_for_resources(
    resources: &RecordingJobResources,
    owner_namespace: &OwnerNamespace,
    job_id: &str,
    updated_at_ms: u64,
    started_at: SystemTime,
) -> Result<bool, PreprocessingStepError> {
    let ledger = resources.ledger();
    let candidate = ledger
        .get_job(job_id)
        .map_err(|error| PreprocessingStepError::for_job(job_id.into(), error.to_string(), false))?
        .ok_or_else(|| {
            PreprocessingStepError::for_job(
                job_id.into(),
                "client preflight job no longer exists".into(),
                false,
            )
        })?;
    if candidate.status != RecordingJobStatus::Preflighting
        || candidate.language_decision_locked
        || candidate.cancellation_requested
    {
        return Err(PreprocessingStepError::for_job(
            job_id.into(),
            "client preprocessing requires an active unlocked preflight".into(),
            false,
        ));
    }
    if ledger
        .get_client_preflight_artifact(job_id)
        .map_err(|error| PreprocessingStepError::for_job(job_id.into(), error.to_string(), false))?
        .is_some()
    {
        return Ok(false);
    }

    let mut durable_cancellation_observed = false;
    let cancellation = resources
        .begin_preprocessing(job_id)
        .map_err(|detail| PreprocessingStepError::for_job(job_id.into(), detail, false))?;
    let outcome = (|| -> Result<(), String> {
        ensure_job_is_active(
            ledger,
            job_id,
            Some(&cancellation),
            &mut durable_cancellation_observed,
        )?;
        let source_path = candidate
            .source_path
            .as_deref()
            .ok_or_else(|| "imported recording has no source path".to_string())?;
        let validated = crate::recording_access::validate_registered_recording_job_source_at(
            source_path,
            resources.selection_registry_path(),
            resources.owned_live_directory(),
        )
        .map_err(|error| match error {
            crate::recording_access::RecordingJobSourceError::Missing => {
                "imported recording source is missing".to_string()
            }
            crate::recording_access::RecordingJobSourceError::Unsafe(message) => message,
        })?;
        let mut source = crate::media_protocol::open_unchanged_media_source(
            &validated.canonical_path,
            &validated.fingerprint,
        )?;
        remote::reset_unattached_spool(job_id, resources.remote_jobs_directory())?;
        let prepared = remote::prepare_imported_client_preflight_with_cancellation(
            remote::ImportedClientPreflightPreparation {
                job_id,
                display_name: &candidate.display_name,
                source: &mut source,
                spool_root: resources.remote_jobs_directory(),
                owner_namespace,
                started_at,
            },
            || cancellation.ensure_active(),
        )?;
        let (artifact, preprocessing) = prepared.into_ledger_state();
        ensure_job_is_active(
            ledger,
            job_id,
            Some(&cancellation),
            &mut durable_cancellation_observed,
        )?;
        match ledger.attach_client_preflight_artifact(
            job_id,
            &artifact,
            &preprocessing,
            updated_at_ms,
        ) {
            Ok(_) => Ok(()),
            Err(error) => {
                remote::reset_unattached_spool(job_id, resources.remote_jobs_directory())
                    .map_err(|cleanup_error| {
                        format!(
                            "durable client preflight commit failed ({error}); owned spool cleanup also failed ({cleanup_error})"
                        )
                    })?;
                Err(error.to_string())
            }
        }
    })();
    match outcome {
        Ok(()) => Ok(true),
        Err(detail) => {
            let cancelled = durable_cancellation_observed
                || cancellation.is_cancelled()
                || durable_job_is_cancelled(ledger, job_id).unwrap_or(false);
            Err(PreprocessingStepError::for_job(
                job_id.into(),
                detail,
                cancelled,
            ))
        }
    }
}

#[cfg(test)]
pub(super) fn prepare_next_queued_job(
    ledger: &JobLedger,
    owned_live_directory: &Path,
    remote_jobs_directory: &Path,
    owner_namespace: &OwnerNamespace,
    updated_at_ms: u64,
    started_at: SystemTime,
) -> Result<bool, String> {
    prepare_next_queued_job_impl(QueuedJobPreparation {
        ledger,
        owned_live_directory,
        remote_jobs_directory,
        owner_namespace,
        updated_at_ms,
        started_at,
        resources: None,
        exact_job_id: None,
        allow_queued_claim: true,
    })
    .map(|prepared| prepared.is_some())
    .map_err(PreprocessingStepError::into_detail)
}

fn prepare_next_queued_job_impl(
    request: QueuedJobPreparation<'_>,
) -> Result<Option<String>, PreprocessingStepError> {
    let QueuedJobPreparation {
        ledger,
        owned_live_directory,
        remote_jobs_directory,
        owner_namespace,
        updated_at_ms,
        started_at,
        resources,
        exact_job_id,
        allow_queued_claim,
    } = request;
    let candidate = if let Some(job_id) = exact_job_id {
        let candidate = ledger.get_job(job_id).map_err(|error| {
            PreprocessingStepError::for_job(job_id.to_owned(), error.to_string(), false)
        })?;
        match candidate {
            Some(candidate)
                if candidate.status == RecordingJobStatus::Preprocessing
                    && candidate
                        .next_attempt_at_ms
                        .is_none_or(|retry_at| retry_at <= updated_at_ms) =>
            {
                Some(candidate)
            }
            Some(_) => {
                return Err(PreprocessingStepError::for_job(
                    job_id.to_owned(),
                    "catalog-claimed preprocessing job changed before media inspection".into(),
                    false,
                ))
            }
            None => {
                return Err(PreprocessingStepError::for_job(
                    job_id.to_owned(),
                    "catalog-claimed preprocessing job no longer exists".into(),
                    false,
                ))
            }
        }
    } else {
        ledger
            .list_recoverable_jobs()
            .map_err(|error| PreprocessingStepError::unidentified(error.to_string()))?
            .into_iter()
            .find(|job| {
                matches!(
                    job.status,
                    RecordingJobStatus::QueuedServer | RecordingJobStatus::Preprocessing
                ) && job.language_decision_locked
                    && job
                        .next_attempt_at_ms
                        .is_none_or(|retry_at| retry_at <= updated_at_ms)
            })
    };
    let Some(mut candidate) = candidate else {
        return Ok(None);
    };
    let job_id = candidate.job_id.clone();
    if !candidate.language_decision_locked {
        return Err(PreprocessingStepError::for_job(
            job_id,
            "preprocessing requires a confirmed language decision".into(),
            false,
        ));
    }
    let mut cancellation = None;
    let mut durable_cancellation_observed = false;
    let outcome = (|| -> Result<(), String> {
        cancellation = resources
            .map(|resources| resources.begin_preprocessing(&job_id))
            .transpose()?;
        if candidate.status == RecordingJobStatus::QueuedServer {
            if !allow_queued_claim {
                return Err("preprocessing requires an exact live-catalog claim".into());
            }
            candidate = ledger
                .begin_remote_preprocessing(&job_id, updated_at_ms)
                .map_err(|error| error.to_string())?;
        }
        if ledger
            .get_prepared_remote_job(&job_id)
            .map_err(|error| error.to_string())?
            .is_some()
        {
            return Err("preprocessing job already has durable remote state".into());
        }
        ensure_job_is_active(
            ledger,
            &job_id,
            cancellation.as_ref(),
            &mut durable_cancellation_observed,
        )?;
        let source_path = candidate
            .source_path
            .as_deref()
            .ok_or_else(|| "imported recording has no source path".to_string())?;
        let validated = match resources {
            Some(resources) => {
                crate::recording_access::validate_registered_recording_job_source_at(
                    source_path,
                    resources.selection_registry_path(),
                    owned_live_directory,
                )
            }
            None => crate::recording_access::validate_recording_job_source_at(
                source_path,
                owned_live_directory,
            ),
        }
        .map_err(|error| match error {
            crate::recording_access::RecordingJobSourceError::Missing => {
                "imported recording source is missing".to_string()
            }
            crate::recording_access::RecordingJobSourceError::Unsafe(message) => message,
        })?;
        let mut source = crate::media_protocol::open_unchanged_media_source(
            &validated.canonical_path,
            &validated.fingerprint,
        )?;
        let asr_catalog_revision = candidate
            .asr_catalog_binding
            .as_ref()
            .ok_or_else(|| {
                "catalog-claimed preprocessing job has no ASR catalog binding".to_string()
            })?
            .catalog_revision();
        remote::reset_unattached_spool(&job_id, remote_jobs_directory)?;
        let prepared = remote::prepare_imported_pcm_wav_with_cancellation(
            remote::ImportedPcmWavPreparation {
                job_id: &job_id,
                display_name: &candidate.display_name,
                source: &mut source,
                spool_root: remote_jobs_directory,
                owner_namespace,
                started_at,
                language_decision: &candidate.language_decision,
                asr_catalog_revision,
            },
            || {
                if let Some(cancellation) = cancellation.as_ref() {
                    cancellation.ensure_active()
                } else {
                    Ok(())
                }
            },
        )?
        .into_ledger_state()?;
        ensure_job_is_active(
            ledger,
            &job_id,
            cancellation.as_ref(),
            &mut durable_cancellation_observed,
        )?;
        attach_prepared_remote_job_or_cleanup(
            ledger,
            &job_id,
            &prepared,
            remote_jobs_directory,
            updated_at_ms,
        )
    })();

    match outcome {
        Ok(()) => Ok(Some(job_id)),
        Err(detail) => {
            let cancelled = durable_cancellation_observed
                || cancellation
                    .as_ref()
                    .is_some_and(|lease| lease.is_cancelled())
                || durable_job_is_cancelled(ledger, &job_id).unwrap_or(false);
            Err(PreprocessingStepError::for_job(job_id, detail, cancelled))
        }
    }
}

fn ensure_job_is_active(
    ledger: &JobLedger,
    job_id: &str,
    cancellation: Option<&crate::jobs::resources::PreprocessingCancellationLease<'_>>,
    durable_cancellation_observed: &mut bool,
) -> Result<(), String> {
    if let Some(cancellation) = cancellation {
        cancellation.ensure_active()?;
    }
    if durable_job_is_cancelled(ledger, job_id)? {
        *durable_cancellation_observed = true;
        return Err("recording job preprocessing was cancelled".into());
    }
    Ok(())
}

fn durable_job_is_cancelled(ledger: &JobLedger, job_id: &str) -> Result<bool, String> {
    ledger
        .get_job(job_id)
        .map(|job| {
            job.is_none_or(|current| {
                current.cancellation_requested || current.status == RecordingJobStatus::Cancelled
            })
        })
        .map_err(|error| error.to_string())
}

pub(super) fn attach_prepared_remote_job_or_cleanup(
    ledger: &JobLedger,
    job_id: &str,
    prepared: &crate::jobs::NewPreparedRemoteJob,
    remote_jobs_directory: &Path,
    updated_at_ms: u64,
) -> Result<(), String> {
    match ledger.attach_prepared_remote_job(job_id, prepared, updated_at_ms) {
        Ok(_) => Ok(()),
        Err(error) => {
            remote::reset_unattached_spool(job_id, remote_jobs_directory).map_err(
                |cleanup_error| {
                    format!(
                        "durable preprocessing commit failed ({error}); owned spool cleanup also failed ({cleanup_error})"
                    )
                },
            )?;
            Err(error.to_string())
        }
    }
}
