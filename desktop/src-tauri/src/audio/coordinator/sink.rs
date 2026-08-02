use std::sync::{atomic::Ordering, mpsc};
use std::time::{Duration, Instant};

#[cfg(test)]
use std::sync::Arc;

use super::sink_types::{
    BoundedSink, SinkCompletionGate, SinkDegradeResult, SinkGatePhase, SinkOutcome, SinkSendError,
};

impl<T> BoundedSink<T> {
    pub fn try_send(&self, frame: T) -> Result<(), SinkSendError> {
        let mut completion = self
            .state
            .completion
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if completion.phase != SinkGatePhase::Accepting {
            self.state.dropped_frames.fetch_add(1, Ordering::Relaxed);
            return Err(SinkSendError::Closed);
        }
        let sender = match self.state.sender.lock() {
            Ok(sender) => sender,
            Err(_) => {
                self.record_drop_locked(&mut completion, "sink state became unavailable");
                return Err(SinkSendError::Closed);
            }
        };
        let Some(sender) = sender.as_ref() else {
            self.record_drop_locked(&mut completion, "sink closed");
            return Err(SinkSendError::Closed);
        };
        if self.state.closed.load(Ordering::Acquire) {
            self.record_drop_locked(&mut completion, "sink closed");
            return Err(SinkSendError::Closed);
        }
        let Some(reserved_queued) = self.reserve_queue_slot() else {
            self.record_drop_locked(&mut completion, "sink queue is full");
            return Err(SinkSendError::Full);
        };
        match sender.try_send(frame) {
            Ok(()) => {
                self.state.published_frames.fetch_add(1, Ordering::Release);
                #[cfg(test)]
                self.run_after_publish_hook_for_test();
                self.state.accepted_frames.fetch_add(1, Ordering::Relaxed);
                self.observe_high_water_mark(reserved_queued);
                Ok(())
            }
            Err(mpsc::TrySendError::Full(_)) => {
                self.rollback_reservation();
                self.record_drop_locked(&mut completion, "sink queue is full");
                Err(SinkSendError::Full)
            }
            Err(mpsc::TrySendError::Disconnected(_)) => {
                self.state.queued_frames.store(0, Ordering::Release);
                self.state.published_frames.store(0, Ordering::Release);
                self.state.closed.store(true, Ordering::Release);
                self.record_drop_locked(&mut completion, "sink receiver disconnected");
                Err(SinkSendError::Closed)
            }
        }
    }

    /// Publishes a terminal control item without treating transient queue
    /// pressure as data loss. Capture hot paths continue to use `try_send`.
    pub(crate) fn send_control_with_timeout(
        &self,
        mut item: T,
        timeout: Duration,
    ) -> Result<(), SinkSendError> {
        let deadline = Instant::now() + timeout;
        loop {
            let mut completion = self
                .state
                .completion
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            if completion.phase != SinkGatePhase::Accepting {
                self.state.dropped_frames.fetch_add(1, Ordering::Relaxed);
                return Err(SinkSendError::Closed);
            }
            let sender_guard = match self.state.sender.lock() {
                Ok(sender) => sender,
                Err(_) => {
                    self.record_drop_locked(&mut completion, "sink state became unavailable");
                    return Err(SinkSendError::Closed);
                }
            };
            let Some(sender) = sender_guard.as_ref() else {
                self.record_drop_locked(&mut completion, "sink closed");
                return Err(SinkSendError::Closed);
            };
            if self.state.closed.load(Ordering::Acquire) {
                self.record_drop_locked(&mut completion, "sink closed");
                return Err(SinkSendError::Closed);
            }
            let Some(reserved_queued) = self.reserve_queue_slot() else {
                drop(sender_guard);
                drop(completion);
                if Instant::now() >= deadline {
                    self.record_terminal_control_drop("sink queue is full");
                    return Err(SinkSendError::Full);
                }
                std::thread::sleep(Duration::from_millis(1));
                continue;
            };
            match sender.try_send(item) {
                Ok(()) => {
                    self.state.published_frames.fetch_add(1, Ordering::Release);
                    #[cfg(test)]
                    self.run_after_publish_hook_for_test();
                    self.state.accepted_frames.fetch_add(1, Ordering::Relaxed);
                    self.observe_high_water_mark(reserved_queued);
                    return Ok(());
                }
                Err(mpsc::TrySendError::Full(returned)) => {
                    self.rollback_reservation();
                    item = returned;
                    drop(sender_guard);
                    drop(completion);
                    if Instant::now() >= deadline {
                        self.record_terminal_control_drop("sink queue is full");
                        return Err(SinkSendError::Full);
                    }
                    std::thread::sleep(Duration::from_millis(1));
                }
                Err(mpsc::TrySendError::Disconnected(_)) => {
                    self.state.queued_frames.store(0, Ordering::Release);
                    self.state.published_frames.store(0, Ordering::Release);
                    self.state.closed.store(true, Ordering::Release);
                    self.record_drop_locked(&mut completion, "sink receiver disconnected");
                    return Err(SinkSendError::Closed);
                }
            }
        }
    }

    pub fn close(&self) {
        let Ok(mut sender) = self.state.sender.lock() else {
            self.state.closed.store(true, Ordering::Release);
            return;
        };
        if sender.take().is_some() {
            self.state.close_count.fetch_add(1, Ordering::Relaxed);
            self.state.closed.store(true, Ordering::Release);
        }
    }

    pub(super) fn close_with_error(&self, error: &str) {
        self.degrade(error);
        self.close();
    }

    pub(crate) fn degrade(&self, error: &str) -> SinkDegradeResult {
        let mut completion = self
            .state
            .completion
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        match completion.phase {
            SinkGatePhase::Accepting => {
                completion
                    .degradation
                    .get_or_insert_with(|| error.to_string());
                SinkDegradeResult::Accepted
            }
            SinkGatePhase::Completing => SinkDegradeResult::CompletionInProgress,
            SinkGatePhase::Published => SinkDegradeResult::Published,
        }
    }

    pub(crate) fn begin_completion(&self) -> Option<String> {
        #[cfg(test)]
        self.run_before_completion_hook_for_test();
        let mut completion = self
            .state
            .completion
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        debug_assert_eq!(completion.phase, SinkGatePhase::Accepting);
        completion.phase = SinkGatePhase::Completing;
        completion.degradation.clone()
    }

    pub(crate) fn mark_published(&self) {
        self.state
            .completion
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .phase = SinkGatePhase::Published;
    }

    pub fn outcome(&self) -> SinkOutcome {
        let error = self
            .state
            .completion
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .degradation
            .clone();
        SinkOutcome {
            kind: self.kind,
            accepted_frames: self.state.accepted_frames.load(Ordering::Acquire),
            dropped_frames: self.state.dropped_frames.load(Ordering::Acquire),
            closed: self.state.closed.load(Ordering::Acquire),
            error,
        }
    }

    pub fn high_water_mark(&self) -> usize {
        self.state.high_water_mark.load(Ordering::Acquire)
    }

    pub fn close_count(&self) -> usize {
        self.state.close_count.load(Ordering::Acquire)
    }

    #[cfg(test)]
    pub(super) fn set_after_publish_hook_for_test(&self, hook: Arc<dyn Fn() + Send + Sync>) {
        *self.state.after_publish_hook.lock().unwrap() = Some(hook);
    }

    #[cfg(test)]
    pub(crate) fn set_before_completion_hook_for_test(&self, hook: Arc<dyn Fn() + Send + Sync>) {
        *self.state.before_completion_hook.lock().unwrap() = Some(hook);
    }

    #[cfg(test)]
    pub(super) fn queued_frames_for_test(&self) -> usize {
        self.state.queued_frames.load(Ordering::Acquire)
    }

    fn reserve_queue_slot(&self) -> Option<usize> {
        let mut queued = self.state.queued_frames.load(Ordering::Acquire);
        loop {
            if queued >= self.state.queue_capacity {
                return None;
            }
            match self.state.queued_frames.compare_exchange_weak(
                queued,
                queued + 1,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => return Some(queued + 1),
                Err(observed) => queued = observed,
            }
        }
    }

    fn rollback_reservation(&self) {
        let result =
            self.state
                .queued_frames
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |queued| {
                    queued.checked_sub(1)
                });
        debug_assert!(result.is_ok(), "a failed sink send must have a reservation");
    }

    #[cfg(test)]
    fn run_after_publish_hook_for_test(&self) {
        if let Some(hook) = self.state.after_publish_hook.lock().unwrap().as_ref() {
            hook();
        }
    }

    #[cfg(test)]
    fn run_before_completion_hook_for_test(&self) {
        if let Some(hook) = self.state.before_completion_hook.lock().unwrap().as_ref() {
            hook();
        }
    }

    fn record_drop_locked(&self, completion: &mut SinkCompletionGate, error: &str) {
        self.state.dropped_frames.fetch_add(1, Ordering::Relaxed);
        if completion.phase == SinkGatePhase::Accepting {
            completion
                .degradation
                .get_or_insert_with(|| error.to_string());
        }
    }

    fn record_terminal_control_drop(&self, error: &str) {
        let mut completion = self
            .state
            .completion
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        self.record_drop_locked(&mut completion, error);
    }

    fn observe_high_water_mark(&self, queued: usize) {
        let mut current = self.state.high_water_mark.load(Ordering::Acquire);
        while queued > current {
            match self.state.high_water_mark.compare_exchange_weak(
                current,
                queued,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    #[cfg(debug_assertions)]
                    self.log_high_water_escalation(queued);
                    break;
                }
                Err(observed) => current = observed,
            }
        }
    }

    /// Report the queue climbing, without narrating every single frame of it.
    ///
    /// Only doublings are written, so a queue reaching 1024 produces about
    /// eleven lines instead of a thousand and the shape of the climb is still
    /// legible. The exact peak is never lost -- `high_water_mark()` returns it
    /// on demand and the release-evidence path reads it from there.
    #[cfg(debug_assertions)]
    fn log_high_water_escalation(&self, queued: usize) {
        let mut reported = self.state.logged_high_water_mark.load(Ordering::Acquire);
        loop {
            if !worth_reporting(queued, reported) {
                return;
            }
            match self.state.logged_high_water_mark.compare_exchange_weak(
                reported,
                queued,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    crate::diagnostics::log(&format!(
                        "audio sink {:?} queue high-water mark={queued}",
                        self.kind
                    ));
                    return;
                }
                Err(observed) => reported = observed,
            }
        }
    }
}

/// A new peak is worth a log line only once it has doubled the last reported
/// one. Pulled out of the reporting path so the volume it produces can be
/// asserted rather than assumed.
#[cfg(debug_assertions)]
fn worth_reporting(queued: usize, reported: usize) -> bool {
    queued >= reported.saturating_mul(2).max(1)
}

#[cfg(all(test, debug_assertions))]
mod high_water_reporting_tests {
    use super::worth_reporting;

    // The queue used to write a line per frame it grew by, so a climb to 1024
    // wrote 1024 lines and the log became 99% one message across three 2 MB
    // generations. Everything else aged out before it could be read.
    #[test]
    fn a_queue_climbing_to_full_reports_a_handful_of_times_not_a_thousand() {
        let mut reported = 0;
        let mut lines = 0;
        for queued in 1..=1024 {
            if worth_reporting(queued, reported) {
                reported = queued;
                lines += 1;
            }
        }
        assert_eq!(reported, 1024, "the final peak must still be reported");
        assert!(
            lines <= 12,
            "a climb to 1024 wrote {lines} lines; the point is that it stops flooding"
        );
    }

    // Bounded above, but not silent: the first frame and every doubling still
    // get through, so the shape of the climb survives.
    #[test]
    fn the_first_peak_and_every_doubling_still_report() {
        assert!(worth_reporting(1, 0));
        assert!(worth_reporting(2, 1));
        assert!(worth_reporting(64, 32));
        assert!(!worth_reporting(63, 32));
        assert!(!worth_reporting(33, 32));
    }
}
