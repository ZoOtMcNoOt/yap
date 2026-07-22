use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};

use super::{remote, JobLedger, JobLedgerError};

/// Owns the durable ledger, retention/command gate, and filesystem roots shared by job actors.
pub(crate) struct RecordingJobResources {
    ledger: JobLedger,
    mutation: Mutex<()>,
    preprocessing_cancellations: Mutex<HashMap<String, Arc<AtomicBool>>>,
    owned_live_directory: PathBuf,
    remote_jobs_directory: PathBuf,
    selection_registry_path: PathBuf,
}

pub(in crate::jobs) struct PreprocessingCancellationLease<'a> {
    resources: &'a RecordingJobResources,
    job_id: String,
    cancelled: Arc<AtomicBool>,
}

impl RecordingJobResources {
    pub(crate) fn open_default() -> Result<Self, JobLedgerError> {
        Ok(Self::from_storage(
            JobLedger::open_default()?,
            crate::live::recordings::recordings_dir(),
            crate::paths::app_data_dir().join("remote-jobs"),
            crate::recording_access::recording_job_selection_registry_path(),
        ))
    }

    pub(in crate::jobs) fn from_storage(
        ledger: JobLedger,
        owned_live_directory: PathBuf,
        remote_jobs_directory: PathBuf,
        selection_registry_path: PathBuf,
    ) -> Self {
        Self {
            ledger,
            mutation: Mutex::new(()),
            preprocessing_cancellations: Mutex::new(HashMap::new()),
            owned_live_directory,
            remote_jobs_directory,
            selection_registry_path,
        }
    }

    pub(in crate::jobs) fn ledger(&self) -> &JobLedger {
        &self.ledger
    }

    pub(in crate::jobs) fn mutation(&self) -> &Mutex<()> {
        &self.mutation
    }

    pub(in crate::jobs) fn owned_live_directory(&self) -> &Path {
        &self.owned_live_directory
    }

    pub(in crate::jobs) fn remote_jobs_directory(&self) -> &Path {
        &self.remote_jobs_directory
    }

    pub(in crate::jobs) fn selection_registry_path(&self) -> &Path {
        &self.selection_registry_path
    }

    pub(in crate::jobs) fn reset_remote_spool(&self, job_id: &str) -> Result<(), String> {
        remote::reset_unattached_spool(job_id, &self.remote_jobs_directory)
    }

    pub(in crate::jobs) fn begin_preprocessing(
        &self,
        job_id: &str,
    ) -> Result<PreprocessingCancellationLease<'_>, String> {
        let mut active = self
            .preprocessing_cancellations
            .lock()
            .map_err(|_| "preprocessing cancellation state is unavailable".to_string())?;
        if active.contains_key(job_id) {
            return Err("recording job preprocessing is already active".into());
        }
        let cancelled = Arc::new(AtomicBool::new(false));
        active.insert(job_id.to_string(), Arc::clone(&cancelled));
        Ok(PreprocessingCancellationLease {
            resources: self,
            job_id: job_id.to_string(),
            cancelled,
        })
    }

    pub(in crate::jobs) fn cancel_preprocessing(&self, job_id: &str) {
        if let Ok(active) = self.preprocessing_cancellations.lock() {
            if let Some(cancelled) = active.get(job_id) {
                cancelled.store(true, Ordering::Release);
            }
        }
    }
}

impl PreprocessingCancellationLease<'_> {
    pub(in crate::jobs) fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }

    pub(in crate::jobs) fn ensure_active(&self) -> Result<(), String> {
        if self.is_cancelled() {
            Err("recording job preprocessing was cancelled".into())
        } else {
            Ok(())
        }
    }
}

impl Drop for PreprocessingCancellationLease<'_> {
    fn drop(&mut self) {
        if let Ok(mut active) = self.resources.preprocessing_cancellations.lock() {
            if active
                .get(&self.job_id)
                .is_some_and(|cancelled| Arc::ptr_eq(cancelled, &self.cancelled))
            {
                active.remove(&self.job_id);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::{
        audio::session::OwnerNamespace,
        jobs::{commands::RecordingJobs, RemoteJobDrain},
    };

    #[test]
    fn recording_command_and_drain_share_one_resource_owner() {
        let root =
            std::env::temp_dir().join(format!("yap-shared-job-resources-{}", std::process::id()));
        std::fs::remove_dir_all(&root).ok();
        std::fs::create_dir_all(&root).unwrap();
        let resources = Arc::new(RecordingJobResources::from_storage(
            JobLedger::open_in_memory().unwrap(),
            root.join("recordings"),
            root.join("remote-jobs"),
            root.join("recording-native-selection-registry.json"),
        ));
        let commands = RecordingJobs::from_resources_for_test(Arc::clone(&resources), &root);
        let drain = RemoteJobDrain::from_resources_for_test(
            Arc::clone(&resources),
            OwnerNamespace::local("i-shared-job-resources").unwrap(),
        );

        assert!(Arc::ptr_eq(commands.resources_for_test(), &resources));
        assert!(Arc::ptr_eq(drain.resources_for_test(), &resources));
        assert!(std::ptr::eq(
            commands.resources_for_test().ledger(),
            drain.resources_for_test().ledger()
        ));
        let command_gate = commands.resources_for_test().mutation().lock().unwrap();
        assert!(drain.resources_for_test().mutation().try_lock().is_err());
        drop(command_gate);
        assert_eq!(
            commands.resources_for_test().owned_live_directory(),
            drain.resources_for_test().owned_live_directory()
        );
        assert_eq!(
            commands.resources_for_test().remote_jobs_directory(),
            drain.resources_for_test().remote_jobs_directory()
        );

        drop(commands);
        drop(drain);
        drop(resources);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn preprocessing_cancellation_is_job_scoped_and_released_with_its_lease() {
        let root = std::env::temp_dir().join(format!(
            "yap-preprocessing-cancellation-{}",
            std::process::id()
        ));
        std::fs::remove_dir_all(&root).ok();
        std::fs::create_dir_all(&root).unwrap();
        let resources = RecordingJobResources::from_storage(
            JobLedger::open_in_memory().unwrap(),
            root.join("recordings"),
            root.join("remote-jobs"),
            root.join("recording-native-selection-registry.json"),
        );

        let lease = resources.begin_preprocessing("job-a").unwrap();
        assert!(lease.ensure_active().is_ok());
        assert!(resources.begin_preprocessing("job-a").is_err());
        resources.cancel_preprocessing("job-b");
        assert!(lease.ensure_active().is_ok());
        resources.cancel_preprocessing("job-a");
        assert_eq!(
            lease.ensure_active().unwrap_err(),
            "recording job preprocessing was cancelled"
        );
        drop(lease);
        assert!(resources.begin_preprocessing("job-a").is_ok());

        drop(resources);
        std::fs::remove_dir_all(root).unwrap();
    }
}
