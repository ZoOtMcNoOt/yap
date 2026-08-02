use tauri::Emitter;

use crate::{authorization, live};

pub(crate) fn emit_session(app: &tauri::AppHandle, view: &live::state::LiveSessionView) {
    let _ = app.emit_to(authorization::MAIN_WINDOW_LABEL, "live-session", view);
    let overlay = live::state::LiveOverlayView::from(view);
    let _ = app.emit_to(
        authorization::LIVE_OVERLAY_WINDOW_LABEL,
        "live-overlay-session",
        overlay,
    );
}

pub(crate) fn emit_level(app: &tauri::AppHandle, view: &live::state::LiveLevelView) {
    let _ = app.emit_to(authorization::LIVE_OVERLAY_WINDOW_LABEL, "live-level", view);
}

/// Whether the pill should be out of the bezel. Sent from a cursor poll rather
/// than derived in the webview, because a retracted overlay ignores cursor
/// events -- it has to, or a transparent strip across the top of every display
/// would swallow clicks meant for whatever is underneath it.
pub(crate) fn emit_overlay_reveal(app: &tauri::AppHandle, revealed: bool) {
    let _ = app.emit_to(
        authorization::LIVE_OVERLAY_WINDOW_LABEL,
        "live-overlay-reveal",
        revealed,
    );
}

pub(crate) fn emit_saved(app: &tauri::AppHandle, saved: &live::recordings::SavedLiveSession) {
    let _ = app.emit_to(
        authorization::MAIN_WINDOW_LABEL,
        "live-session-saved",
        saved,
    );
}
