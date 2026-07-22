use std::{
    marker::PhantomData,
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
};

use crate::stt::error::SttError;

use super::DownloadOperation;

/// Serializes one explicitly installed model component without conflating the
/// state of different components in Tauri's type-indexed state registry.
pub struct ModelInstallState<Tag> {
    generation: AtomicU64,
    active: Mutex<Option<DownloadOperation>>,
    _tag: PhantomData<fn() -> Tag>,
}

impl<Tag> ModelInstallState<Tag> {
    pub fn new() -> Self {
        Self {
            generation: AtomicU64::new(0),
            active: Mutex::new(None),
            _tag: PhantomData,
        }
    }

    pub fn begin(&self) -> Result<DownloadOperation, SttError> {
        let mut active = self.active.lock().map_err(|_| SttError::Busy)?;
        if active.is_some() {
            return Err(SttError::Busy);
        }
        let generation = self.generation.fetch_add(1, Ordering::AcqRel);
        let operation = DownloadOperation::new(generation);
        *active = Some(operation.clone());
        Ok(operation)
    }

    pub fn finish(&self, operation: &DownloadOperation) {
        if let Ok(mut active) = self.active.lock() {
            if active
                .as_ref()
                .is_some_and(|current| current.generation() == operation.generation())
            {
                *active = None;
            }
        }
    }

    pub fn cancel(&self) -> bool {
        let Ok(active) = self.active.lock() else {
            return false;
        };
        active.as_ref().is_some_and(|operation| {
            operation.cancel();
            true
        })
    }

    pub fn is_active(&self) -> bool {
        self.active.lock().is_ok_and(|active| active.is_some())
    }
}

impl<Tag> Default for ModelInstallState<Tag> {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestComponent;

    #[test]
    fn install_state_serializes_mutations_and_cancels_idempotently() {
        let state = ModelInstallState::<TestComponent>::new();
        let operation = state.begin().unwrap();
        assert!(state.is_active());
        assert!(state.begin().is_err());
        assert!(state.cancel());
        assert!(state.cancel());
        assert!(operation.is_cancelled());
        state.finish(&operation);
        assert!(!state.is_active());
        assert!(state.begin().is_ok());
    }

    #[test]
    fn stale_completion_cannot_clear_a_newer_model_operation() {
        let state = ModelInstallState::<TestComponent>::new();
        let first = state.begin().unwrap();
        state.finish(&first);
        let second = state.begin().unwrap();

        state.finish(&first);

        assert!(state.is_active());
        assert!(state.cancel());
        assert!(second.is_cancelled());
        state.finish(&second);
        assert!(!state.is_active());
    }
}
