use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Condvar, Mutex, MutexGuard,
};
use std::thread;
use std::time::{Duration, Instant};

#[cfg(test)]
use std::sync::atomic::AtomicU64;

const CLEANUP_DEADLINE_ERROR: &str =
    "Live model cleanup did not finish before the cleanup deadline.";

pub(super) struct SharedWarmup<T> {
    state: Mutex<SharedWarmupState<T>>,
    changed: Condvar,
    retirement_active: AtomicBool,
    #[cfg(test)]
    incomplete_retirement_epoch: AtomicU64,
}

enum SharedWarmupState<T> {
    Empty,
    Loading { cancelled: Arc<AtomicBool> },
    Ready(T),
    InUse,
    Failed(String),
}

pub(super) struct SharedWarmupLease<T: Send + 'static> {
    value: Option<T>,
    warmup: Arc<SharedWarmup<T>>,
}

struct RetirementCompletion<T: Send + 'static> {
    warmup: Arc<SharedWarmup<T>>,
    completed: bool,
}

impl<T> SharedWarmup<T>
where
    T: Send + 'static,
{
    pub(super) fn new() -> Self {
        Self {
            state: Mutex::new(SharedWarmupState::Empty),
            changed: Condvar::new(),
            retirement_active: AtomicBool::new(false),
            #[cfg(test)]
            incomplete_retirement_epoch: AtomicU64::new(0),
        }
    }

    pub(super) fn request<F>(self: &Arc<Self>, worker_name: &str, load: F) -> Result<bool, String>
    where
        F: FnOnce() -> Result<T, String> + Send + 'static,
    {
        let cancelled = {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            match &*state {
                SharedWarmupState::Loading { cancelled } => {
                    cancelled.store(false, Ordering::Release);
                    return Ok(false);
                }
                SharedWarmupState::Ready(_) | SharedWarmupState::InUse => return Ok(false),
                SharedWarmupState::Empty | SharedWarmupState::Failed(_) => {}
            }
            let cancelled = Arc::new(AtomicBool::new(false));
            *state = SharedWarmupState::Loading {
                cancelled: Arc::clone(&cancelled),
            };
            self.changed.notify_all();
            cancelled
        };

        let warmup = Arc::clone(self);
        let worker_cancelled = Arc::clone(&cancelled);
        if let Err(error) = thread::Builder::new()
            .name(worker_name.to_string())
            .spawn(move || {
                let result = catch_unwind(AssertUnwindSafe(load))
                    .unwrap_or_else(|_| Err("Live model warmup panicked.".to_string()));
                warmup.complete_loading(&worker_cancelled, result);
            })
        {
            self.reset_failed_spawn(&cancelled);
            return Err(format!("Live model warmup worker could not start: {error}"));
        }
        Ok(true)
    }

    pub(super) fn wait_cancellable<F>(
        self: &Arc<Self>,
        cancelled: F,
    ) -> Result<Option<SharedWarmupLease<T>>, String>
    where
        F: Fn() -> bool,
    {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        loop {
            if cancelled() {
                return Ok(None);
            }
            match &*state {
                SharedWarmupState::Ready(_) => {
                    let SharedWarmupState::Ready(value) =
                        std::mem::replace(&mut *state, SharedWarmupState::InUse)
                    else {
                        unreachable!("ready warmup state was just matched")
                    };
                    return Ok(Some(SharedWarmupLease {
                        value: Some(value),
                        warmup: Arc::clone(self),
                    }));
                }
                SharedWarmupState::Failed(error) => return Err(error.clone()),
                SharedWarmupState::Empty => {
                    return Err("Live model warmup was not requested.".to_string())
                }
                SharedWarmupState::InUse => {
                    return Err("Live model is already owned by a stream.".to_string())
                }
                SharedWarmupState::Loading { .. } => {
                    let (next, _) = self
                        .changed
                        .wait_timeout(state, Duration::from_millis(25))
                        .unwrap_or_else(|poisoned| poisoned.into_inner());
                    state = next;
                }
            }
        }
    }

    pub(super) fn cancel_loading(&self) {
        let state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if let SharedWarmupState::Loading { cancelled } = &*state {
            cancelled.store(true, Ordering::Release);
        }
        self.changed.notify_all();
    }

    pub(super) fn notify_waiters(&self) {
        self.changed.notify_all();
    }

    fn complete_loading(&self, cancelled: &Arc<AtomicBool>, result: Result<T, String>) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let owns_load = matches!(
            &*state,
            SharedWarmupState::Loading { cancelled: current }
                if Arc::ptr_eq(current, cancelled)
        );
        if !owns_load {
            return;
        }
        *state = if cancelled.load(Ordering::Acquire) {
            SharedWarmupState::Empty
        } else {
            match result {
                Ok(value) => SharedWarmupState::Ready(value),
                Err(error) => SharedWarmupState::Failed(error),
            }
        };
        self.changed.notify_all();
    }

    fn reset_failed_spawn(&self, cancelled: &Arc<AtomicBool>) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if matches!(
            &*state,
            SharedWarmupState::Loading { cancelled: current }
                if Arc::ptr_eq(current, cancelled)
        ) {
            *state = SharedWarmupState::Empty;
        }
        self.changed.notify_all();
    }

    fn restore_ready(&self, value: T) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if matches!(*state, SharedWarmupState::InUse) {
            *state = SharedWarmupState::Ready(value);
        }
        self.changed.notify_all();
    }

    pub(super) fn release_in_use(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if matches!(*state, SharedWarmupState::InUse) {
            *state = SharedWarmupState::Empty;
        }
        self.changed.notify_all();
    }

    fn spawn_retirement(
        self: &Arc<Self>,
        retired: SharedWarmupState<T>,
    ) -> Result<(), (SharedWarmupState<T>, String)> {
        if self
            .retirement_active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err((
                retired,
                "Another live model retirement is already in progress.".to_string(),
            ));
        }
        // Keep recoverable ownership outside the closure so a failed thread
        // spawn never drops a native model on the lifecycle thread.
        let payload = Arc::new(Mutex::new(Some(retired)));
        let worker_payload = Arc::clone(&payload);
        let worker_warmup = Arc::clone(self);
        match thread::Builder::new()
            .name("live-model-retirement".to_string())
            .spawn(move || {
                let mut completion = RetirementCompletion {
                    warmup: worker_warmup,
                    completed: false,
                };
                let retired = worker_payload
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner())
                    .take()
                    .expect("live model retirement worker owns one payload");
                drop(retired);
                completion.completed = true;
            }) {
            Ok(_) => Ok(()),
            Err(error) => {
                self.retirement_active.store(false, Ordering::Release);
                let retired = payload
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner())
                    .take()
                    .expect("failed retirement spawn leaves the payload owned locally");
                Err((
                    retired,
                    format!("Live model retirement worker could not start: {error}"),
                ))
            }
        }
    }

    fn complete_retirement(&self) {
        let _state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        self.retirement_active.store(false, Ordering::Release);
        self.changed.notify_all();
    }

    fn report_incomplete_retirement(&self) {
        {
            let _state = self
                .state
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            #[cfg(test)]
            self.incomplete_retirement_epoch
                .fetch_add(1, Ordering::Release);
            self.changed.notify_all();
        }
        crate::diagnostics::log(
            "live model retirement stopped before completion; cleanup remains fenced",
        );
    }

    fn cancel_loading_state(&self, state: &SharedWarmupState<T>) {
        if let SharedWarmupState::Loading { cancelled } = state {
            cancelled.store(true, Ordering::Release);
        }
        self.changed.notify_all();
    }

    fn wait_for_cleanup_progress<'a>(
        &self,
        state: MutexGuard<'a, SharedWarmupState<T>>,
        deadline: Instant,
    ) -> Result<MutexGuard<'a, SharedWarmupState<T>>, String> {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            self.cancel_loading_state(&state);
            return Err(CLEANUP_DEADLINE_ERROR.to_string());
        }
        let (state, wait) = self
            .changed
            .wait_timeout(state, remaining)
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if wait.timed_out() {
            self.cancel_loading_state(&state);
            Err(CLEANUP_DEADLINE_ERROR.to_string())
        } else {
            Ok(state)
        }
    }

    pub(super) fn request_idle_clear(self: &Arc<Self>) -> Result<(), String> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        match &*state {
            SharedWarmupState::Empty => Ok(()),
            SharedWarmupState::InUse => Err("Live model is still owned by a stream.".to_string()),
            SharedWarmupState::Loading { cancelled } => {
                cancelled.store(true, Ordering::Release);
                self.changed.notify_all();
                Ok(())
            }
            SharedWarmupState::Ready(_) => {
                if self.retirement_active.load(Ordering::Acquire) {
                    return Ok(());
                }
                let retired = std::mem::replace(&mut *state, SharedWarmupState::Empty);
                match self.spawn_retirement(retired) {
                    Ok(()) => {
                        self.changed.notify_all();
                        Ok(())
                    }
                    Err((retired, error)) => {
                        *state = retired;
                        self.changed.notify_all();
                        Err(error)
                    }
                }
            }
            SharedWarmupState::Failed(_) => {
                let retired = std::mem::replace(&mut *state, SharedWarmupState::Empty);
                self.changed.notify_all();
                drop(retired);
                Ok(())
            }
        }
    }

    pub(super) fn clear_idle_with_timeout(
        self: &Arc<Self>,
        timeout: Duration,
    ) -> Result<(), String> {
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or_else(|| "Live model cleanup deadline overflowed.".to_string())?;
        self.clear_idle_until(deadline)
    }

    fn clear_idle_until(self: &Arc<Self>, deadline: Instant) -> Result<(), String> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        loop {
            match &*state {
                SharedWarmupState::Empty => {
                    if !self.retirement_active.load(Ordering::Acquire) {
                        return Ok(());
                    }
                    state = self.wait_for_cleanup_progress(state, deadline)?;
                }
                SharedWarmupState::InUse => {
                    return Err("Live model is still owned by a stream.".to_string())
                }
                SharedWarmupState::Loading { cancelled } => {
                    cancelled.store(true, Ordering::Release);
                    self.changed.notify_all();
                    state = self.wait_for_cleanup_progress(state, deadline)?;
                }
                SharedWarmupState::Ready(_) => {
                    if self.retirement_active.load(Ordering::Acquire) {
                        state = self.wait_for_cleanup_progress(state, deadline)?;
                        continue;
                    }
                    let retired = std::mem::replace(&mut *state, SharedWarmupState::Empty);
                    match self.spawn_retirement(retired) {
                        Ok(()) => {}
                        Err((retired, error)) => {
                            *state = retired;
                            self.changed.notify_all();
                            return Err(error);
                        }
                    }
                    self.changed.notify_all();
                    state = self.wait_for_cleanup_progress(state, deadline)?;
                }
                SharedWarmupState::Failed(_) => {
                    let retired = std::mem::replace(&mut *state, SharedWarmupState::Empty);
                    self.changed.notify_all();
                    drop(retired);
                }
            }
        }
    }

    #[cfg(test)]
    pub(super) fn is_loading_for_test(&self) -> bool {
        matches!(
            *self
                .state
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()),
            SharedWarmupState::Loading { .. }
        )
    }

    #[cfg(test)]
    pub(super) fn is_loading_cancelled_for_test(&self) -> bool {
        match &*self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
        {
            SharedWarmupState::Loading { cancelled } => cancelled.load(Ordering::Acquire),
            _ => false,
        }
    }

    #[cfg(test)]
    pub(super) fn seed_ready_for_test(&self, value: T) {
        *self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = SharedWarmupState::Ready(value);
    }

    #[cfg(test)]
    pub(super) fn seed_failed_for_test(&self, error: impl Into<String>) {
        *self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) =
            SharedWarmupState::Failed(error.into());
    }

    #[cfg(test)]
    pub(super) fn seed_in_use_for_test(&self) {
        *self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = SharedWarmupState::InUse;
    }

    #[cfg(test)]
    pub(super) fn is_empty_for_test(&self) -> bool {
        let state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        matches!(*state, SharedWarmupState::Empty)
            && !self.retirement_active.load(Ordering::Acquire)
    }

    #[cfg(test)]
    pub(super) fn is_retirement_active_for_test(&self) -> bool {
        self.retirement_active.load(Ordering::Acquire)
    }

    #[cfg(test)]
    pub(super) fn incomplete_retirement_epoch_for_test(&self) -> u64 {
        self.incomplete_retirement_epoch.load(Ordering::Acquire)
    }

    #[cfg(test)]
    pub(super) fn wait_for_incomplete_retirement_after_for_test(
        &self,
        observed_epoch: u64,
        timeout: Duration,
    ) -> bool {
        let state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let (_state, _) = self
            .changed
            .wait_timeout_while(state, timeout, |_| {
                self.incomplete_retirement_epoch.load(Ordering::Acquire) <= observed_epoch
            })
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        self.incomplete_retirement_epoch.load(Ordering::Acquire) > observed_epoch
    }
}

impl<T: Send + 'static> Drop for RetirementCompletion<T> {
    fn drop(&mut self) {
        if self.completed {
            self.warmup.complete_retirement();
        } else {
            self.warmup.report_incomplete_retirement();
        }
    }
}

impl<T> SharedWarmupLease<T>
where
    T: Send + 'static,
{
    pub(super) fn commit(mut self) -> T {
        self.value
            .take()
            .expect("warmup lease commits exactly one model")
    }
}

impl<T: Send + 'static> Drop for SharedWarmupLease<T> {
    fn drop(&mut self) {
        if let Some(value) = self.value.take() {
            self.warmup.restore_ready(value);
        }
    }
}
