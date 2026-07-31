use super::{
    command_error, mint_job_id, source_error, JobCommandError, RecordingJobs, MAX_RECORDING_JOBS,
    PENDING_JOB_LIFETIME_MS, REMOTE_IMPORT_AUDIO_EXTENSIONS,
};
use crate::{
    jobs::{
        AsrCatalogBinding, NewRecordingJob, RecordingJobRecord, RecordingJobStatus,
        RecordingJobView, RecordingLanguageDecision, RecordingRoute, SessionMode, SessionOrigin,
        SourceOwnership,
    },
    media_protocol::MediaOwner,
    recording_access::ValidatedRecordingJobSource,
};
use std::{
    collections::{HashMap, HashSet},
    path::{Path, PathBuf},
};

/// Filesystem inspection happens before a live catalog is fetched. Keeping this
/// value independent from the connector prevents slow media inspection from
/// extending the connector generation lock.
pub(super) struct PreparedRecordingImports {
    sources: Vec<ValidatedRecordingJobSource>,
}

/// The durable catalog/language commit is complete, but playback authority has
/// not yet been projected. Projection deliberately happens after the connector
/// lock is released.
pub(super) struct CommittedRecordingImports {
    entries: Vec<(RecordingJobRecord, ValidatedRecordingJobSource)>,
}

impl RecordingJobs {
    #[cfg(test)]
    pub(super) fn create_imports<P: AsRef<Path>>(
        &self,
        media: &MediaOwner,
        paths: Vec<P>,
        now_ms: u64,
    ) -> Result<Vec<RecordingJobView>, JobCommandError> {
        self.create_imports_with_language(
            media,
            paths,
            now_ms,
            RecordingLanguageDecision::primary("en-US".into())
                .expect("test primary language is valid"),
        )
    }

    #[cfg(test)]
    pub(super) fn create_imports_with_language<P: AsRef<Path>>(
        &self,
        media: &MediaOwner,
        paths: Vec<P>,
        now_ms: u64,
        language_decision: RecordingLanguageDecision,
    ) -> Result<Vec<RecordingJobView>, JobCommandError> {
        let prepared = self.prepare_imports(paths)?;
        let binding = AsrCatalogBinding::try_new("http://127.0.0.1:18765".into(), "a".repeat(64))
            .expect("test catalog binding is valid");
        let committed =
            self.commit_prepared_imports(prepared, now_ms, language_decision, &binding)?;
        self.project_committed_imports(media, committed, now_ms)
    }

    pub(super) fn prepare_imports<P: AsRef<Path>>(
        &self,
        paths: Vec<P>,
    ) -> Result<PreparedRecordingImports, JobCommandError> {
        if paths.len() > MAX_RECORDING_JOBS {
            return Err(command_error(
                "JOB_LIMIT_EXCEEDED",
                format!("Yap accepts at most {MAX_RECORDING_JOBS} recording jobs."),
            ));
        }
        if paths.iter().any(|path| {
            path.as_ref()
                .extension()
                .and_then(|extension| extension.to_str())
                .is_none_or(|extension| {
                    !REMOTE_IMPORT_AUDIO_EXTENSIONS
                        .iter()
                        .any(|allowed| extension.eq_ignore_ascii_case(allowed))
                })
        }) {
            return Err(command_error(
                "REMOTE_MEDIA_UNSUPPORTED",
                "Private-server transcription currently accepts WAV and MP3 recordings.",
            ));
        }
        let sources = paths
            .iter()
            .map(|path| self.validate_source(path.as_ref()))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(PreparedRecordingImports { sources })
    }

    /// Performs the bounded native-selection/catalog/ledger admission commit.
    /// Slow media inspection has already completed, so callers may invoke this
    /// while holding the connector generation lock.
    pub(super) fn commit_prepared_imports(
        &self,
        prepared: PreparedRecordingImports,
        now_ms: u64,
        language_decision: RecordingLanguageDecision,
        binding: &AsrCatalogBinding,
    ) -> Result<CommittedRecordingImports, JobCommandError> {
        let _mutation = self.mutation().lock().map_err(|_| {
            command_error(
                "JOB_STATE_UNAVAILABLE",
                "Recording job state is unavailable.",
            )
        })?;
        let mut new_sources = HashSet::new();
        let mut existing_by_source = HashMap::new();
        for source in &prepared.sources {
            if let Some(existing) = self
                .ledger()
                .find_recoverable_imported_job_by_source(&source.canonical_path)?
            {
                if existing.language_decision != language_decision {
                    return Err(command_error(
                        "LANGUAGE_DECISION_CONFLICT",
                        "This recording is already queued with a different language decision. Cancel or dismiss that job before importing it with another language.",
                    ));
                }
                existing_by_source.insert(source.canonical_path.clone(), existing);
            } else {
                new_sources.insert(source.canonical_path.clone());
            }
        }
        let recoverable_count = self.ledger().list_recoverable_jobs()?.len();
        if recoverable_count.saturating_add(new_sources.len()) > MAX_RECORDING_JOBS {
            return Err(command_error(
                "JOB_LIMIT_EXCEEDED",
                format!("Yap accepts at most {MAX_RECORDING_JOBS} recording jobs."),
            ));
        }

        let mut new_jobs = Vec::new();
        let mut existing_job_ids = Vec::new();
        let mut seen_existing = HashSet::new();
        let mut planned_new_sources = HashSet::new();
        for source in &prepared.sources {
            if let Some(existing) = existing_by_source.get(&source.canonical_path) {
                if seen_existing.insert(existing.job_id.clone()) {
                    existing_job_ids.push(existing.job_id.clone());
                }
                continue;
            }
            if !planned_new_sources.insert(source.canonical_path.clone()) {
                continue;
            }
            new_jobs.push(NewRecordingJob {
                job_id: mint_job_id(&source.canonical_path, now_ms),
                session_mode: SessionMode::Meeting,
                session_origin: SessionOrigin::ImportedFile,
                source_path: Some(source.canonical_path.clone()),
                source_ownership: SourceOwnership::External,
                output_path: None,
                display_name: source
                    .canonical_path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("Recording")
                    .to_owned(),
                // Accepted rows are durable but intentionally invisible to the
                // background drain until native source authority is projected.
                status: RecordingJobStatus::Accepted,
                route: Some(RecordingRoute::ServerBatch),
                attempt_count: 0,
                next_attempt_at_ms: None,
                cancellation_requested: false,
                capture_commit_path: None,
                capture_manifest_sha256: None,
                error_code: None,
                error_message: None,
                created_at_ms: now_ms,
                updated_at_ms: now_ms,
                expires_at_ms: now_ms.checked_add(PENDING_JOB_LIFETIME_MS),
                language_decision: language_decision.clone(),
                // The setup language is provisional until the immutable owned
                // source has been measured. Short recordings reuse it; long
                // recordings require the language-detection/manual-confirmation path.
                language_decision_locked: false,
                client_stage_history_complete: false,
                asr_catalog_binding: Some(binding.clone()),
            });
        }
        // Retain native picker/drop proof before a durable Accepted row can
        // exist. Accepted is still drain-ineligible; active playback and the
        // queued transition happen only during projection below.
        let selection = crate::recording_access::retain_native_selected_recording_job_sources_at(
            &prepared.sources,
            &self.selection_registry_path,
            self.owned_dir(),
        )
        .map_err(source_error)?;
        let committed = match self.ledger().commit_catalog_imports(
            &existing_job_ids,
            &new_jobs,
            &language_decision,
            binding,
            now_ms,
            MAX_RECORDING_JOBS,
        ) {
            Ok(committed) => committed,
            Err(error) => {
                if let Err(cleanup_error) =
                    crate::recording_access::rollback_retained_native_selection_at(
                        selection,
                        &self.selection_registry_path,
                    )
                {
                    super::log_registry_cleanup_failure(
                        "rollback after rejected import commit",
                        &cleanup_error,
                    );
                }
                return Err(error.into());
            }
        };
        let mut records_by_source = HashMap::new();
        for record in committed {
            let source_path = record
                .source_path
                .clone()
                .expect("committed imported job has a source path");
            records_by_source.insert(source_path, record);
        }

        let entries = prepared
            .sources
            .into_iter()
            .map(|source| {
                let record = records_by_source
                    .get(&source.canonical_path)
                    .expect("validated source has a committed job")
                    .clone();
                (record, source)
            })
            .collect();
        Ok(CommittedRecordingImports { entries })
    }

    pub(super) fn project_committed_imports(
        &self,
        media: &MediaOwner,
        committed: CommittedRecordingImports,
        now_ms: u64,
    ) -> Result<Vec<RecordingJobView>, JobCommandError> {
        let _mutation = self.mutation().lock().map_err(|_| {
            command_error(
                "JOB_STATE_UNAVAILABLE",
                "Recording job state is unavailable.",
            )
        })?;
        let mut projected = Vec::with_capacity(committed.entries.len());
        let mut projected_by_source: HashMap<PathBuf, RecordingJobView> = HashMap::new();
        for (committed_record, source) in committed.entries {
            if let Some(existing) = projected_by_source.get(&source.canonical_path) {
                projected.push(existing.clone());
                continue;
            }
            let current = self
                .ledger()
                .get_job(&committed_record.job_id)?
                .ok_or_else(|| {
                    command_error(
                        "JOB_NOT_FOUND",
                        "A committed recording disappeared before source authority was projected.",
                    )
                })?;
            if current.source_path.as_deref() != Some(source.canonical_path.as_path())
                || current.language_decision != committed_record.language_decision
            {
                return Err(command_error(
                    "JOB_STATE_CHANGED",
                    "A committed recording changed before source authority was projected.",
                ));
            }
            let source_path = source.canonical_path.clone();
            let view = if matches!(
                current.status,
                RecordingJobStatus::Complete
                    | RecordingJobStatus::Partial
                    | RecordingJobStatus::Cancelled
            ) {
                self.release_playback(&current.job_id, media);
                RecordingJobView::from_record(&current)
            } else {
                if current.status == RecordingJobStatus::Accepted {
                    let expires_at_ms = current.expires_at_ms.ok_or_else(|| {
                        command_error(
                            "JOB_TIME_OUT_OF_RANGE",
                            "Accepted recording has no bounded retention deadline.",
                        )
                    })?;
                    self.project_and_activate_accepted_import(
                        current,
                        source,
                        media,
                        now_ms,
                        expires_at_ms,
                    )?
                } else {
                    match crate::recording_access::register_native_selected_recording_job_source_at(
                        &source,
                        &self.selection_registry_path,
                        self.owned_dir(),
                    ) {
                        Ok(()) => self.project_committed_or_fail(current, source, media, now_ms)?,
                        Err(error) => {
                            let error = source_error(error);
                            let failed = self.ledger().fail_source_validation(
                                &current.job_id,
                                &error.code,
                                now_ms,
                            )?;
                            self.project_failed_capability_free(&failed, media)
                        }
                    }
                }
            };
            projected_by_source.insert(source_path, view.clone());
            projected.push(view);
        }
        Ok(projected)
    }
}
