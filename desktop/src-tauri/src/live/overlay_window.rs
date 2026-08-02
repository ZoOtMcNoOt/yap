use std::sync::atomic::{AtomicBool, Ordering};

use tauri::Manager;

#[cfg(target_os = "windows")]
use windows::core::Free;
#[cfg(target_os = "windows")]
use windows::Win32::Graphics::Gdi::{
    CombineRgn, CreateRectRgn, CreateRoundRectRgn, SetWindowRgn, HRGN, RGN_ERROR, RGN_OR,
};
#[cfg(target_os = "windows")]
use windows::Win32::UI::WindowsAndMessaging::{
    GetWindowLongPtrW, SetWindowLongPtrW, SetWindowPos, GWL_EXSTYLE, SWP_FRAMECHANGED,
    SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW,
};

pub(crate) const WINDOW_LABEL: &str = crate::authorization::LIVE_OVERLAY_WINDOW_LABEL;

static IDLE_COLLAPSED_ACTIVE: AtomicBool = AtomicBool::new(true);

// Ported from FreeFlow's RecordingOverlayManager (Sources/RecordingOverlay.swift,
// MIT, revision 7427ca9). Upstream does not carry a width table: it carries rules,
// and every constant below is one of theirs. macOS has a menu bar to hide behind,
// so upstream picks between a compact strip the height of that bar and a 38pt
// drop-down pill; Windows has no menu bar, so the pill is the only form that
// applies and `notchOverlap` is zero throughout.
const PILL_HEIGHT: f64 = 38.0;
// `defaultWidth` — the bare pill, wide enough for the waveform and nothing else.
const DEFAULT_WIDTH: f64 = 92.0;
// `toggleWidth` — only while recording in toggle mode, where a stop badge appears.
const TOGGLE_WIDTH: f64 = 150.0;
// "Saved" through upstream's own text-pill arithmetic: 5 chars * 6.8 + 60 chrome.
const SUCCESS_WIDTH: f64 = 94.0;
// `maxToastMessageLength` — longer errors are ellipsised rather than widening.
const MAX_MESSAGE_CHARS: usize = 90;
// Yap-only surface: the idle island's action row. Upstream dismisses when idle,
// so there is nothing to copy here beyond the 180pt it already shares with
// upstream's command-mode pill.
const EXPANDED_WIDTH: f64 = 180.0;
const EXPANDED_HEIGHT: f64 = 96.0;
// `screenHasNotch ? 18 : 12`, and Windows never has a notch. Applied to the
// bottom two corners only — see `create_visible_region`.
const CORNER_RADIUS: f64 = 12.0;
// The window region is a 1-bit clip: GDI regions have no antialiasing, so a
// region cut along the same curve the CSS paints slices the smooth edge with a
// stair-stepped one and the corners read as gritty. Rounding the *region* less
// than the pill keeps every painted pixel strictly inside it, so what you see
// is the webview's antialiased curve and nothing clips it.
//
// The cost is a sliver of transparent corner — between the two radii — that
// still accepts clicks. Two triangles a few pixels on a side, against corners
// that otherwise look chewed.
const REGION_CORNER_SLACK: f64 = 4.0;
const TOP_BEZEL_OFFSET: f64 = 0.0;

pub(crate) fn ensure_active(app: &tauri::AppHandle) -> Result<(), String> {
    ensure_surface(app, "recording")
}

pub(crate) fn ensure_idle(app: &tauri::AppHandle) -> Result<(), String> {
    ensure_surface(app, "collapsed")
}

pub(crate) fn focus_controls(app: &tauri::AppHandle) -> Result<(), String> {
    let view = app.state::<crate::live::LiveSessionState>().snapshot();
    if view.visibility != crate::live::state::LiveOverlayVisibility::Enabled {
        return Err("Live overlay controls are hidden.".into());
    }
    if crate::live::state::is_live_session_started(view.status)
        || view.status == crate::live::state::LiveSessionStatus::Blocked
    {
        ensure_active(app)?;
    } else {
        ensure_idle(app)?;
    }
    app.get_webview_window(WINDOW_LABEL)
        .ok_or_else(|| "Live overlay window is unavailable.".to_string())?
        .set_focus()
        .map_err(|error| format!("Failed to focus live overlay controls: {error}"))
}

pub(crate) fn recover(app: &tauri::AppHandle) {
    let view = app.state::<crate::live::LiveSessionState>().snapshot();
    if view.visibility != crate::live::state::LiveOverlayVisibility::Enabled {
        return;
    }
    if app
        .get_webview_window(WINDOW_LABEL)
        .and_then(|window| window.is_visible().ok())
        .unwrap_or(false)
    {
        return;
    }
    let result = if crate::live::state::is_live_session_started(view.status)
        || view.status == crate::live::state::LiveSessionStatus::Blocked
    {
        ensure_active(app)
    } else {
        ensure_idle(app)
    };
    if let Err(error) = result {
        crate::diagnostics::log(&format!("live overlay recovery failed: {error}"));
    }
}

/// Upstream `overlayWidth`, transcribed. The two inputs it reads off its own
/// state — the trigger mode and the pending error message — are inputs Rust
/// already holds, so the webview still never gets a say in native bounds.
pub(crate) fn frame(
    surface: &str,
    trigger_mode: crate::live::state::LiveCaptureMode,
    message_chars: usize,
) -> Result<(f64, f64), String> {
    let toggle = trigger_mode == crate::live::state::LiveCaptureMode::Toggle;
    match surface {
        "collapsed" | "initializing" => Ok((DEFAULT_WIDTH, PILL_HEIGHT)),
        "expanded" => Ok((EXPANDED_WIDTH, EXPANDED_HEIGHT)),
        // Upstream widens only once recording has actually started in toggle
        // mode, then locks that width through transcription via
        // `lockedOverlayWidth` so the pill cannot snap narrow mid-job. Reading
        // the trigger mode reproduces the lock without holding the state:
        // whatever made recording wide keeps processing wide.
        "recording" | "processing" => Ok((
            if toggle { TOGGLE_WIDTH } else { DEFAULT_WIDTH },
            PILL_HEIGHT,
        )),
        "success" => Ok((SUCCESS_WIDTH, PILL_HEIGHT)),
        "feedback" => Ok((feedback_width(message_chars), PILL_HEIGHT)),
        _ => Err("Unsupported live overlay surface.".into()),
    }
}

/// Upstream sizes an error toast to its message so a four-word failure does not
/// get the same pill as a paragraph: ~6.8pt per character plus 60pt of icon and
/// padding, clamped so short messages stay readable and long ones do not stretch
/// across the display. A bare failure marker with no message keeps the 92pt pill.
fn feedback_width(message_chars: usize) -> f64 {
    if message_chars == 0 {
        return DEFAULT_WIDTH;
    }
    (message_chars.min(MAX_MESSAGE_CHARS) as f64 * 6.8 + 60.0).clamp(180.0, 420.0)
}

fn active_trigger_mode(
    view: &crate::live::state::LiveSessionView,
) -> crate::live::state::LiveCaptureMode {
    view.active_capture_mode.unwrap_or(view.capture_mode)
}

fn message_chars(view: &crate::live::state::LiveSessionView) -> usize {
    view.error
        .as_deref()
        .map(|message| message.chars().count())
        .unwrap_or(0)
}

pub(crate) fn ensure_surface(app: &tauri::AppHandle, surface: &str) -> Result<(), String> {
    let view = app.state::<crate::live::LiveSessionState>().snapshot();
    ensure_surface_for(app, surface, &view)
}

/// For callers that have already read the session state and decided against it.
/// The failure pill is sized from the error message, so a caller that validates
/// the surface against one snapshot and lets this read a second can paint a
/// 92pt window around a 180pt error toast until the next sync corrects it.
pub(crate) fn ensure_surface_for(
    app: &tauri::AppHandle,
    surface: &str,
    view: &crate::live::state::LiveSessionView,
) -> Result<(), String> {
    let (width, height) = frame(surface, active_trigger_mode(view), message_chars(view))?;
    if let Some(window) = app.get_webview_window(WINDOW_LABEL) {
        ensure_dimensions(&window, width, height)?;
        position(app, &window, width)?;
        apply_visible_region(&window, width, height)?;
        IDLE_COLLAPSED_ACTIVE.store(surface == "collapsed", Ordering::Release);
        window
            .show()
            .map_err(|err| format!("Failed to show live overlay: {err}"))?;
        return Ok(());
    }

    let (x, y) = position_for_width(app, width);
    let window = tauri::WebviewWindowBuilder::new(
        app,
        WINDOW_LABEL,
        tauri::WebviewUrl::App("index.html?window=live-overlay".into()),
    )
    .title("Yap Live")
    .inner_size(width, height)
    .position(x, y)
    .decorations(false)
    .resizable(false)
    .closable(false)
    .transparent(true)
    .shadow(false)
    .always_on_top(true)
    .skip_taskbar(true)
    .focused(false)
    .focusable(true)
    .build()
    .map_err(|err| format!("Failed to create live overlay: {err}"))?;
    window
        .set_focusable(true)
        .map_err(|err| format!("Failed to make live overlay keyboard accessible: {err}"))?;
    make_system_window(&window)?;
    apply_visible_region(&window, width, height)?;
    IDLE_COLLAPSED_ACTIVE.store(surface == "collapsed", Ordering::Release);
    position(app, &window, width)?;
    Ok(())
}

// Upstream shows its panel only while dictating and animates it down out of the
// menu bar, so at rest the screen is clean. Yap's island has no menu bar to hide
// in, so it hides in the bezel: the window stays a fixed transparent strip at the
// top edge and the pill inside it translates out of view. Reaching for where the
// pill would be brings it back.
//
// Hysteresis, not a single rectangle: the pill reveals when the cursor is inside
// its own footprint and retracts only once the cursor leaves that footprint
// grown by this margin. One rectangle would flicker on the boundary.
const REVEAL_RETRACT_MARGIN: f64 = 28.0;
// A retracted pill occupies no pixels, so the zone it reveals from has to be
// tall enough to aim at. Throwing the pointer at the top edge is the gesture.
const REVEAL_ZONE_HEIGHT: f64 = 12.0;

static OVERLAY_REVEALED: AtomicBool = AtomicBool::new(false);

/// Pure so the geometry is testable without a display. Coordinates are logical
/// and relative to the monitor's own origin.
fn cursor_reveals_pill(
    cursor_x: f64,
    cursor_y: f64,
    pill_left: f64,
    pill_width: f64,
    pill_height: f64,
    already_revealed: bool,
) -> bool {
    let margin = if already_revealed {
        REVEAL_RETRACT_MARGIN
    } else {
        0.0
    };
    // While retracted the pill draws nothing, so aim at the strip it would
    // occupy; the zone is never shorter than that strip.
    let zone_height = if already_revealed {
        pill_height
    } else {
        pill_height.max(REVEAL_ZONE_HEIGHT)
    };
    cursor_x >= pill_left - margin
        && cursor_x <= pill_left + pill_width + margin
        && cursor_y >= -margin
        && cursor_y <= zone_height + margin
}

/// Drives the reveal from the one place that can see the cursor while the
/// overlay is ignoring it. Emits only on change so the webview is not woken
/// every poll.
pub(crate) fn sync_reveal(app: &tauri::AppHandle) {
    let view = app.state::<crate::live::LiveSessionState>().snapshot();
    if view.visibility != crate::live::state::LiveOverlayVisibility::Enabled {
        return;
    }
    let Some(window) = app.get_webview_window(WINDOW_LABEL) else {
        return;
    };
    let was_revealed = OVERLAY_REVEALED.load(Ordering::Acquire);

    // Anything that is not a resting idle island holds the pill out: the user is
    // dictating, transcribing, or being told something failed.
    let revealed = view.status != crate::live::state::LiveSessionStatus::Idle
        || view.error.is_some()
        || cursor_reveals_the_pill_now(app, &window, was_revealed);

    if revealed == was_revealed {
        return;
    }
    OVERLAY_REVEALED.store(revealed, Ordering::Release);
    // A retracted strip must not eat clicks meant for the desktop beneath it.
    let _ = window.set_ignore_cursor_events(!revealed);
    crate::live::events::emit_overlay_reveal(app, revealed);
}

fn cursor_reveals_the_pill_now(
    app: &tauri::AppHandle,
    window: &tauri::WebviewWindow,
    already_revealed: bool,
) -> bool {
    let Ok(cursor) = app.cursor_position() else {
        return false;
    };
    let Ok(Some(monitor)) = app.monitor_from_point(cursor.x, cursor.y) else {
        return false;
    };
    let scale = monitor.scale_factor();
    let Ok(size) = window.inner_size() else {
        return false;
    };
    let size = size.to_logical::<f64>(scale);
    let (pill_left, _) = position_for_monitor(&monitor, size.width);
    // Everything monitor-relative, so a display at a negative origin reads the
    // same as the primary one.
    let monitor_left = f64::from(monitor.position().x) / scale;
    let monitor_top = f64::from(monitor.position().y) / scale;
    cursor_reveals_pill(
        cursor.x / scale - monitor_left,
        cursor.y / scale - monitor_top,
        pill_left - monitor_left,
        size.width,
        size.height,
        already_revealed,
    )
}

pub(crate) fn follow_cursor_if_idle(app: &tauri::AppHandle) {
    if !IDLE_COLLAPSED_ACTIVE.load(Ordering::Acquire) {
        return;
    }
    let Some(window) = app.get_webview_window(WINDOW_LABEL) else {
        return;
    };
    if !window.is_visible().unwrap_or(false) {
        return;
    }
    let Some(target_monitor) = monitor_for_cursor(app) else {
        return;
    };
    if window
        .current_monitor()
        .ok()
        .flatten()
        .is_some_and(|current| same_monitor(&current, &target_monitor))
    {
        return;
    }
    let _ = position_on_monitor(&window, &target_monitor, DEFAULT_WIDTH);
}

fn ensure_dimensions(window: &tauri::WebviewWindow, width: f64, height: f64) -> Result<(), String> {
    let scale = window
        .scale_factor()
        .map_err(|err| format!("Failed to read live overlay scale: {err}"))?;
    let current = window
        .inner_size()
        .map_err(|err| format!("Failed to read live overlay size: {err}"))?
        .to_logical::<f64>(scale);
    if (current.width - width).abs() <= 0.5 && (current.height - height).abs() <= 0.5 {
        return Ok(());
    }
    window
        .set_size(tauri::LogicalSize::new(width, height))
        .map_err(|err| format!("Failed to size live overlay: {err}"))
}

fn position(
    app: &tauri::AppHandle,
    window: &tauri::WebviewWindow,
    width: f64,
) -> Result<(), String> {
    let Some(monitor) = monitor_for_cursor(app) else {
        return window
            .set_position(tauri::LogicalPosition::new(8.0, TOP_BEZEL_OFFSET))
            .map_err(|err| format!("Failed to position live overlay: {err}"));
    };
    position_on_monitor(window, &monitor, width)
}

fn position_on_monitor(
    window: &tauri::WebviewWindow,
    monitor: &tauri::Monitor,
    width: f64,
) -> Result<(), String> {
    let (x, y) = position_for_monitor(monitor, width);
    window
        .set_position(tauri::LogicalPosition::new(x, y))
        .map_err(|err| format!("Failed to position live overlay: {err}"))
}

fn position_for_width(app: &tauri::AppHandle, width: f64) -> (f64, f64) {
    monitor_for_cursor(app)
        .map(|monitor| position_for_monitor(&monitor, width))
        .unwrap_or((8.0, TOP_BEZEL_OFFSET))
}

fn monitor_for_cursor(app: &tauri::AppHandle) -> Option<tauri::Monitor> {
    app.cursor_position()
        .ok()
        .and_then(|cursor| app.monitor_from_point(cursor.x, cursor.y).ok().flatten())
        .or_else(|| app.primary_monitor().ok().flatten())
}

fn position_for_monitor(monitor: &tauri::Monitor, width: f64) -> (f64, f64) {
    let scale = monitor.scale_factor();
    let position = monitor.position();
    let size = monitor.size();
    position_for_monitor_metrics(
        f64::from(position.x),
        f64::from(position.y),
        f64::from(size.width),
        scale,
        width,
    )
}

fn position_for_monitor_metrics(
    physical_x: f64,
    physical_y: f64,
    physical_width: f64,
    scale: f64,
    window_width: f64,
) -> (f64, f64) {
    let logical_x = physical_x / scale;
    let logical_y = physical_y / scale;
    let logical_width = physical_width / scale;
    (
        logical_x + ((logical_width - window_width) / 2.0).max(0.0),
        logical_y + TOP_BEZEL_OFFSET,
    )
}

fn same_monitor(left: &tauri::Monitor, right: &tauri::Monitor) -> bool {
    left.position() == right.position() && left.size() == right.size()
}

#[cfg(target_os = "windows")]
fn apply_visible_region(
    window: &tauri::WebviewWindow,
    window_width: f64,
    window_height: f64,
) -> Result<(), String> {
    let hwnd = window
        .hwnd()
        .map_err(|err| format!("Failed to read live overlay window handle: {err}"))?;
    let scale = window
        .scale_factor()
        .map_err(|err| format!("Failed to read live overlay scale: {err}"))?;
    let mut region = create_visible_region(window_width, window_height, scale)?;
    if unsafe { SetWindowRgn(hwnd, Some(region), true) } == 0 {
        unsafe { region.free() };
        return Err("Failed to apply live overlay interaction region.".into());
    }
    Ok(())
}

/// Upstream clips its panel with `UnevenRoundedRectangle(bottomLeadingRadius:
/// bottomTrailingRadius:)` — the bottom two corners only. The top edge is flush
/// with the top of the display, so square top corners are what make the strip
/// read as part of the bezel instead of as a pill floating under it. GDI has no
/// uneven round-rect, so square the top back in by OR-ing a rectangle over the
/// corner band.
#[cfg(target_os = "windows")]
fn create_visible_region(
    window_width: f64,
    window_height: f64,
    scale: f64,
) -> Result<HRGN, String> {
    // Deliberately squarer than the pill by `REGION_CORNER_SLACK` -- a smaller
    // radius is a larger area -- so the 1-bit region encloses every pixel the
    // webview paints and never clips its antialiased curve.
    create_region_with_corner_radius(
        window_width,
        window_height,
        scale,
        CORNER_RADIUS - REGION_CORNER_SLACK,
    )
}

#[cfg(target_os = "windows")]
fn create_region_with_corner_radius(
    window_width: f64,
    window_height: f64,
    scale: f64,
    corner_radius_points: f64,
) -> Result<HRGN, String> {
    let physical_width = (window_width * scale).round().max(1.0) as i32;
    let physical_height = (window_height * scale).round().max(1.0) as i32;
    let corner_radius = (corner_radius_points * scale).round().max(1.0) as i32;
    let mut region = unsafe {
        CreateRoundRectRgn(
            0,
            0,
            physical_width,
            physical_height,
            corner_radius * 2,
            corner_radius * 2,
        )
    };
    if region.is_invalid() {
        return Err("Failed to create live overlay interaction region.".into());
    }

    // Height from CORNER_RADIUS rather than this region's own radius: the band
    // only squares the top off, so covering more of an already-square edge costs
    // nothing, while deriving it from a smaller radius would make the clip's
    // band shorter than the pill's and cut the top corners it is meant to keep.
    let band_height = (CORNER_RADIUS * scale).round().max(1.0) as i32;
    let mut top_band =
        unsafe { CreateRectRgn(0, 0, physical_width, band_height.min(physical_height)) };
    if top_band.is_invalid() {
        unsafe { region.free() };
        return Err("Failed to create live overlay interaction region.".into());
    }
    let combined = unsafe { CombineRgn(Some(region), Some(region), Some(top_band), RGN_OR) };
    unsafe { top_band.free() };
    if combined == RGN_ERROR {
        unsafe { region.free() };
        return Err("Failed to square the live overlay top corners.".into());
    }
    Ok(region)
}

#[cfg(not(target_os = "windows"))]
fn apply_visible_region(
    _window: &tauri::WebviewWindow,
    _window_width: f64,
    _window_height: f64,
) -> Result<(), String> {
    Ok(())
}

#[cfg(target_os = "windows")]
fn make_system_window(window: &tauri::WebviewWindow) -> Result<(), String> {
    let hwnd = window
        .hwnd()
        .map_err(|err| format!("Failed to read live overlay window handle: {err}"))?;
    unsafe {
        let style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE) as u32;
        let next_style = (style | WS_EX_TOOLWINDOW.0) & !WS_EX_APPWINDOW.0;
        SetWindowLongPtrW(hwnd, GWL_EXSTYLE, next_style as isize);
        SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
        )
        .map_err(|err| format!("Failed to refresh live overlay window style: {err}"))?;
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
fn make_system_window(_window: &tauri::WebviewWindow) -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::live::state::LiveCaptureMode::{PushToTalk, Toggle};

    #[test]
    fn frame_matches_visible_surface_contract() {
        assert_eq!(frame("collapsed", PushToTalk, 0), Ok((92.0, 38.0)));
        assert_eq!(frame("expanded", PushToTalk, 0), Ok((180.0, 96.0)));
        assert_eq!(frame("initializing", PushToTalk, 0), Ok((92.0, 38.0)));
        assert_eq!(frame("success", PushToTalk, 0), Ok((94.0, 38.0)));
    }

    // Upstream widens only for the stop badge, and only once recording has
    // started: arming in toggle mode is still the bare pill.
    #[test]
    fn only_toggle_mode_recording_and_its_transcription_widen_the_pill() {
        assert_eq!(frame("recording", PushToTalk, 0), Ok((92.0, 38.0)));
        assert_eq!(frame("processing", PushToTalk, 0), Ok((92.0, 38.0)));
        assert_eq!(frame("recording", Toggle, 0), Ok((150.0, 38.0)));
        assert_eq!(frame("processing", Toggle, 0), Ok((150.0, 38.0)));
        assert_eq!(frame("initializing", Toggle, 0), Ok((92.0, 38.0)));
    }

    // The width carries the message length, so the arithmetic and both clamp
    // ends are the contract — including that a bare failure marker stays narrow.
    #[test]
    fn feedback_width_tracks_the_message_within_upstream_clamps() {
        assert_eq!(frame("feedback", PushToTalk, 0), Ok((92.0, 38.0)));
        assert_eq!(frame("feedback", PushToTalk, 1), Ok((180.0, 38.0)));
        assert_eq!(frame("feedback", PushToTalk, 40), Ok((332.0, 38.0)));
        assert_eq!(frame("feedback", PushToTalk, 90), Ok((420.0, 38.0)));
    }

    // Upstream truncates at 90 characters before the pill is ever sized, so a
    // longer message can never ask for a wider window than a 90-character one.
    #[test]
    fn an_oversized_message_cannot_stretch_the_window_past_the_clamp() {
        assert_eq!(
            frame("feedback", PushToTalk, 100_000),
            frame("feedback", PushToTalk, MAX_MESSAGE_CHARS)
        );
        assert_eq!(frame("feedback", PushToTalk, 100_000), Ok((420.0, 38.0)));
    }

    // Aiming at the top edge where the pill would be is the whole gesture, so
    // the zone has to be reachable while the pill is drawing nothing at all.
    #[test]
    fn a_retracted_pill_reveals_from_the_strip_it_would_occupy() {
        let left = 914.0;
        let reveals =
            |x: f64, y: f64| cursor_reveals_pill(x, y, left, DEFAULT_WIDTH, PILL_HEIGHT, false);

        assert!(reveals(left + 40.0, 0.0));
        assert!(reveals(left + 40.0, 11.0));
        // Off to the side of where the pill lives, at the same height.
        assert!(!reveals(left - 40.0, 4.0));
        assert!(!reveals(left + DEFAULT_WIDTH + 40.0, 4.0));
        // Below the strip: the rest of the screen stays the user's.
        assert!(!reveals(left + 40.0, 200.0));
    }

    // Without hysteresis the pill would strobe while the cursor rests on the
    // boundary, which is the difference between polished and broken.
    #[test]
    fn a_revealed_pill_holds_until_the_cursor_clears_it_by_a_margin() {
        let left = 914.0;
        let reveals = |x: f64, y: f64, already: bool| {
            cursor_reveals_pill(x, y, left, DEFAULT_WIDTH, PILL_HEIGHT, already)
        };

        // Just outside the pill: retracted stays retracted, revealed stays revealed.
        let just_outside = left + DEFAULT_WIDTH + 10.0;
        assert!(!reveals(just_outside, 10.0, false));
        assert!(reveals(just_outside, 10.0, true));

        // Past the margin it lets go, sideways or downwards.
        assert!(!reveals(
            left + DEFAULT_WIDTH + REVEAL_RETRACT_MARGIN + 1.0,
            10.0,
            true
        ));
        assert!(!reveals(
            left + 40.0,
            PILL_HEIGHT + REVEAL_RETRACT_MARGIN + 1.0,
            true
        ));
    }

    #[test]
    fn unknown_surface_cannot_allocate_an_arbitrary_native_window() {
        assert_eq!(
            frame("sensor", PushToTalk, 0),
            Err("Unsupported live overlay surface.".into())
        );
    }

    #[test]
    fn top_center_position_handles_negative_multi_monitor_origins_and_dpi() {
        let collapsed = position_for_monitor_metrics(-1920.0, 0.0, 1920.0, 1.5, DEFAULT_WIDTH);
        let expanded = position_for_monitor_metrics(-1920.0, 0.0, 1920.0, 1.5, EXPANDED_WIDTH);

        assert_eq!(collapsed, (-686.0, 0.0));
        assert_eq!(expanded, (-730.0, 0.0));
        assert_eq!(collapsed.1, expanded.1);
    }

    #[test]
    fn top_center_position_uses_target_monitor_logical_width_at_two_x_dpi() {
        assert_eq!(
            position_for_monitor_metrics(1920.0, 0.0, 3840.0, 2.0, DEFAULT_WIDTH),
            (1874.0, 0.0)
        );
    }

    // The whole point of the port's silhouette: square at the top so it reads as
    // bezel, rounded at the bottom. A four-corner region would pass an
    // "excludes rounded corners" assertion just as happily, so both ends are
    // asserted here.
    #[cfg(target_os = "windows")]
    #[test]
    fn visible_region_squares_the_top_corners_and_rounds_only_the_bottom() {
        use windows::Win32::Graphics::Gdi::PtInRegion;

        let mut region = create_visible_region(DEFAULT_WIDTH, PILL_HEIGHT, 1.0).unwrap();
        assert!(unsafe { PtInRegion(region, 46, 19) }.as_bool());
        assert!(unsafe { PtInRegion(region, 0, 0) }.as_bool());
        assert!(unsafe { PtInRegion(region, 91, 0) }.as_bool());
        assert!(!unsafe { PtInRegion(region, 0, 37) }.as_bool());
        assert!(!unsafe { PtInRegion(region, 91, 37) }.as_bool());
        unsafe { region.free() };
    }

    // The grit: a GDI region is 1-bit, so a region cut along the same curve the
    // webview paints slices its antialiased edge with a stair-stepped one.
    //
    // Asserted by comparing the two regions pixel by pixel rather than against
    // hand-computed points -- GDI rasterises its arcs slightly tighter than a
    // circle, so a coordinate derived from the radius is a statement about
    // GDI's algorithm and not about the property.
    #[cfg(target_os = "windows")]
    #[test]
    fn the_region_encloses_the_painted_curve_instead_of_cutting_across_it() {
        use windows::Win32::Graphics::Gdi::PtInRegion;

        let mut painted =
            create_region_with_corner_radius(DEFAULT_WIDTH, PILL_HEIGHT, 1.0, CORNER_RADIUS)
                .unwrap();
        let mut clip = create_visible_region(DEFAULT_WIDTH, PILL_HEIGHT, 1.0).unwrap();

        let mut slack_pixels = 0;
        for y in 0..PILL_HEIGHT as i32 {
            for x in 0..DEFAULT_WIDTH as i32 {
                let is_painted = unsafe { PtInRegion(painted, x, y) }.as_bool();
                let is_kept = unsafe { PtInRegion(clip, x, y) }.as_bool();
                assert!(
                    !is_painted || is_kept,
                    "the clip cuts away a pixel the pill paints at {x},{y}"
                );
                if is_kept && !is_painted {
                    slack_pixels += 1;
                }
            }
        }
        assert!(
            slack_pixels > 0,
            "the clip is no larger than the painted shape, so it still cuts across the curve"
        );

        unsafe { painted.free() };
        unsafe { clip.free() };
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn squared_top_survives_fractional_display_scaling() {
        use windows::Win32::Graphics::Gdi::PtInRegion;

        let mut region = create_visible_region(DEFAULT_WIDTH, PILL_HEIGHT, 1.5).unwrap();
        assert!(unsafe { PtInRegion(region, 0, 0) }.as_bool());
        assert!(unsafe { PtInRegion(region, 137, 0) }.as_bool());
        assert!(!unsafe { PtInRegion(region, 0, 56) }.as_bool());
        unsafe { region.free() };
    }
}
