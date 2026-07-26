use std::sync::atomic::Ordering;

use tauri::Manager;

use super::{
    session_identity::{active_session_matches, CRASH_CLAIM_BIT},
    LiveRuntime, LiveStartFailure,
};
use crate::live::state::{LiveSessionState, LiveSessionView};

impl LiveRuntime {
    pub fn handle_stream_crash(&self, app: tauri::AppHandle, session: u64, message: &str) {
        if !self.claim_stream_crash(session) {
            return;
        }
        let state = app.state::<LiveSessionState>();
        let _ = crate::live::actions::stop_live_runtime_after_crash(
            app.clone(),
            &state,
            self,
            session,
            message,
        );
    }

    pub(super) fn claim_stream_crash(&self, session: u64) -> bool {
        session != 0
            && session & CRASH_CLAIM_BIT == 0
            && self
                .active_session
                .compare_exchange(
                    session,
                    session | CRASH_CLAIM_BIT,
                    Ordering::SeqCst,
                    Ordering::SeqCst,
                )
                .is_ok()
    }

    pub(crate) fn is_session_current(&self, session: u64) -> bool {
        active_session_matches(self.active_session.load(Ordering::SeqCst), session)
    }

    fn clear_active_session_if_current(&self, session: u64) -> bool {
        self.active_session
            .compare_exchange(session, 0, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
    }

    pub(crate) fn cancel_uninstalled_capture_start(
        &self,
        state: &LiveSessionState,
        session: u64,
    ) -> Option<LiveSessionView> {
        let inner = self.inner.lock().expect("live runtime poisoned");
        if !inner.can_install_capture(session, self.active_session.load(Ordering::SeqCst))
            || !self.clear_active_session_if_current(session)
        {
            return None;
        }
        drop(inner);
        state.try_cancel_armed_local_start()
    }

    pub(crate) fn claim_start_failure(&self, failure: LiveStartFailure) -> Option<String> {
        self.clear_active_session_if_current(failure.session)
            .then_some(failure.message)
    }
}
