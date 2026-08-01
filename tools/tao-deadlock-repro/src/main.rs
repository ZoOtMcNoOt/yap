// Minimal reproduction for the tao 0.35.3 session-lock deadlock.
//
// The lock screen is only interesting because it delivers WM_KILLFOCUS while a
// key message is being processed. is_msg_keyboard_related treats WM_KILLFOCUS
// as keyboard-related, so it re-enters the handler that already holds the
// global KEY_EVENT_BUILDERS lock. Synthesizing that ordering reproduces the
// hang without locking anyone's workstation.
//
// Exits 0 if the loop keeps pumping, 1 if it stops responding.
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use tao::event::{Event, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tao::window::WindowBuilder;
use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
use windows::Win32::UI::WindowsAndMessaging::{PostMessageW, SendMessageW, WM_KEYDOWN, WM_KILLFOCUS};

fn main() {
    let event_loop = EventLoopBuilder::new().build();
    let window = WindowBuilder::new()
        .with_title("tao-deadlock-repro")
        .with_visible(true)
        .build(&event_loop)
        .expect("window");

    // HWND is a raw pointer and therefore not Send; move the integer instead
    // and rebuild the handle on the far side.
    let hwnd_bits = tao::platform::windows::WindowExtWindows::hwnd(&window) as usize;

    let ticks = Arc::new(AtomicU64::new(0));
    let done = Arc::new(AtomicBool::new(false));
    let watch_ticks = Arc::clone(&ticks);
    let watch_done = Arc::clone(&done);

    // Two threads on purpose. SendMessageW is synchronous: it blocks until the
    // target thread processes the message, so if the main thread deadlocks the
    // injector blocks with it. A watchdog sharing that thread would never run,
    // which is exactly what happened the first time — the harness hung instead
    // of reporting the hang it had caused.
    let injector_ticks = Arc::clone(&ticks);
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_millis(400));
        let inject = std::env::var("REPRO_INJECT").as_deref() == Ok("1");
        for round in 0..(if inject { 200u32 } else { 0 }) {
            let hwnd = HWND(hwnd_bits as *mut core::ffi::c_void);
            unsafe {
                let _ = PostMessageW(Some(hwnd), WM_KEYDOWN, WPARAM(0x41), LPARAM(0));
                let _ = SendMessageW(hwnd, WM_KILLFOCUS, None, None);
            }
            if round % 20 == 0 {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
        }
        let _ = injector_ticks.load(Ordering::Relaxed);
    });

    // Independent: touches no window handle, so nothing it does can block on
    // the message loop it is judging.
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_secs(3));
        let before = watch_ticks.load(Ordering::Relaxed);
        std::thread::sleep(std::time::Duration::from_secs(5));
        let after = watch_ticks.load(Ordering::Relaxed);
        watch_done.store(true, Ordering::Relaxed);
        if after == before {
            eprintln!("DEADLOCK: event loop stopped pumping (ticks frozen at {after})");
            std::process::exit(1);
        }
        eprintln!("OK: event loop still pumping ({before} -> {after} ticks)");
        std::process::exit(0);
    });

    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Poll;
        ticks.fetch_add(1, Ordering::Relaxed);
        if let Event::WindowEvent { event: WindowEvent::CloseRequested, .. } = event {
            *control_flow = ControlFlow::Exit;
        }
    });
}
