use std::{sync::atomic::Ordering, time::Duration};

use super::{
    inference::LiveInferenceBundle, log_worker_shutdown_errors, LiveRuntime, ModelMutationLease,
    StartIntent,
};

const LIVE_MODEL_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);

impl LiveRuntime {
    pub fn is_active(&self) -> bool {
        self.inner
            .lock()
            .expect("live runtime poisoned")
            .is_capturing()
    }

    pub(crate) fn capture_start_intent(&self) -> StartIntent {
        StartIntent(self.start_generation.load(Ordering::Acquire))
    }

    pub(crate) fn start_intent_is_current(&self, intent: StartIntent) -> bool {
        self.start_generation.load(Ordering::Acquire) == intent.0
    }

    pub(crate) fn cancel_pending_start(&self) {
        self.start_generation.fetch_add(1, Ordering::AcqRel);
        // A normal stop invalidates only the waiting capture start. The shared
        // warmup remains reusable; mutation, idle eviction, and shutdown own
        // the explicit model-cancellation paths.
        self.model_warmup.notify_waiters();
    }

    pub(crate) fn run_start_lifecycle<T>(
        &self,
        intent: StartIntent,
        run: impl FnOnce() -> T,
    ) -> Option<T> {
        if self.model_mutation_active.load(Ordering::Acquire) {
            return None;
        }
        let _operation = self.transition.begin_start();
        self.start_intent_is_current(intent).then(run)
    }

    pub(crate) fn run_installed_capture_lifecycle<T>(
        &self,
        intent: StartIntent,
        run: impl FnOnce() -> T,
    ) -> Option<T> {
        let _operation = self.transition.begin_start();
        self.start_intent_is_current(intent).then(run)
    }

    pub(crate) fn run_stop_lifecycle<T>(&self, run: impl FnOnce() -> T) -> T {
        let _operation = self.transition.begin_stop();
        run()
    }

    pub(crate) fn begin_model_mutation(&self) -> Result<ModelMutationLease, String> {
        self.begin_local_runtime_mutation("Stop live before changing local fallback.")
    }

    pub(crate) fn begin_primary_language_mutation(&self) -> Result<ModelMutationLease, String> {
        self.begin_local_runtime_mutation("Stop live before changing the primary language.")
    }

    pub(crate) fn begin_language_support_mutation(&self) -> Result<ModelMutationLease, String> {
        self.begin_local_runtime_mutation("Stop live before changing local language support.")
    }

    fn begin_local_runtime_mutation(
        &self,
        active_message: &'static str,
    ) -> Result<ModelMutationLease, String> {
        self.model_mutation_active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| "Another local model change is already in progress.".to_string())?;
        let operation = self.transition.begin_stop_owned();
        let mut lease = ModelMutationLease {
            runtime: self.clone(),
            _operation: operation,
            cancel_pending_start_on_drop: false,
        };

        let mut inner = self.inner.lock().expect("live runtime poisoned");
        if inner.is_capturing() {
            return Err(active_message.to_string());
        }
        self.cancel_pending_start();
        lease.cancel_pending_start_on_drop = true;
        inner.retire_stream();
        drop(inner);
        self.model_warmup.clear_idle()?;
        Ok(lease)
    }

    pub fn request_warm(&self, _app: tauri::AppHandle) -> Result<bool, String> {
        if self.model_mutation_active.load(Ordering::Acquire) {
            return Ok(false);
        }
        if self
            .inner
            .lock()
            .expect("live runtime poisoned")
            .has_running_stream()
        {
            return Ok(false);
        }

        self.request_model_warmup()
    }

    pub(super) fn request_model_warmup(&self) -> Result<bool, String> {
        self.model_warmup
            .request("live-model-warmup", LiveInferenceBundle::load)
    }

    pub fn unload_if_idle(&self, threshold: Duration) {
        self.run_stop_lifecycle(|| {
            let mut inner = self.inner.lock().expect("live runtime poisoned");
            if inner.is_idle_for(threshold) {
                inner.retire_stream();
                drop(inner);
                // Periodic lifecycle work must never wait for a native model
                // loader. It requests cancellation and lets the loader retire
                // its own value when it returns.
                let _ = self.model_warmup.request_idle_clear();
            }
        });
    }

    pub fn shutdown(&self) {
        self.cancel_pending_start();
        self.run_stop_lifecycle(|| {
            let mut inner = self.inner.lock().expect("live runtime poisoned");
            let (shutdown_errors, _) = inner.stop_capture();
            inner.retire_stream();
            self.active_session.store(0, Ordering::SeqCst);
            drop(inner);
            if let Err(error) = self
                .model_warmup
                .clear_idle_for_shutdown(LIVE_MODEL_SHUTDOWN_TIMEOUT)
            {
                crate::diagnostics::log(&format!(
                    "live model shutdown continued after bounded warmup cancellation: {error}"
                ));
            }
            let _ = self.finalize_recording();
            log_worker_shutdown_errors(shutdown_errors);
        });
    }
}
