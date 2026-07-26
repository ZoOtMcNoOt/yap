use tauri::Manager;

use super::super::state::LiveSessionState;

/// Receives transcript-state changes from the single live inference worker.
///
/// Keeping this boundary independent of Tauri lets executable evidence drive
/// the same bounded worker without creating a second transcription path.
pub(super) trait LiveStreamEventSink: Send {
    fn publish_partial(&self, text: &str);
    fn publish_final(&self, text: &str);
    fn return_to_listening(&self);
    fn mark_language_routing_degraded(&self);
    fn mark_transcription_unavailable(&self);
}

pub(super) struct TauriLiveStreamEventSink {
    app: tauri::AppHandle,
}

impl TauriLiveStreamEventSink {
    pub(super) fn new(app: tauri::AppHandle) -> Self {
        Self { app }
    }

    fn publish_state(&self, view: &super::super::state::LiveSessionView) {
        super::super::events::emit_session(&self.app, view);
    }
}

impl LiveStreamEventSink for TauriLiveStreamEventSink {
    fn publish_partial(&self, text: &str) {
        let view = self.app.state::<LiveSessionState>().update_partial(text);
        self.publish_state(&view);
    }

    fn publish_final(&self, text: &str) {
        let view = self.app.state::<LiveSessionState>().update_final(text);
        self.publish_state(&view);
    }

    fn return_to_listening(&self) {
        let view = self.app.state::<LiveSessionState>().return_to_listening();
        self.publish_state(&view);
    }

    fn mark_language_routing_degraded(&self) {
        let view = self
            .app
            .state::<LiveSessionState>()
            .mark_language_routing_degraded();
        self.publish_state(&view);
    }

    fn mark_transcription_unavailable(&self) {
        let view = self
            .app
            .state::<LiveSessionState>()
            .mark_local_transcription_unavailable();
        self.publish_state(&view);
    }
}
