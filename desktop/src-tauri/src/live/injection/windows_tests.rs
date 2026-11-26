use super::write_windows_clipboard;
use std::process::Command;
use windows::{
    core::w,
    Win32::UI::WindowsAndMessaging::{
        CreateWindowExW, DestroyWindow, HWND_MESSAGE, WINDOW_EX_STYLE, WINDOW_STYLE,
    },
};

#[test]
#[ignore = "replaces the clipboard on an opted-in disposable Windows desktop"]
fn transcript_is_available_to_an_independent_windows_reader() {
    assert_eq!(
        std::env::var("YAP_TEST_DISPOSABLE_WINDOWS_CLIPBOARD").as_deref(),
        Ok("1"),
        "Run only on a disposable Windows desktop."
    );
    let owner = unsafe {
        CreateWindowExW(
            WINDOW_EX_STYLE::default(),
            w!("STATIC"),
            w!("Yap test clipboard owner"),
            WINDOW_STYLE::default(),
            0,
            0,
            0,
            0,
            Some(HWND_MESSAGE),
            None,
            None,
            None,
        )
    }
    .expect("create clipboard owner");
    let transcript = "First line\r\n知識 • café 🦀";
    write_windows_clipboard(owner, transcript).unwrap();
    assert!(write_windows_clipboard(owner, "broken\0text").is_err());

    let read = Command::new("powershell.exe")
        .args([
            "-NoProfile", "-NonInteractive", "-STA", "-Command",
            "$ErrorActionPreference = 'Stop'; Add-Type -AssemblyName System.Windows.Forms; $text = [Windows.Forms.Clipboard]::GetText([Windows.Forms.TextDataFormat]::UnicodeText); $bytes = [Text.Encoding]::UTF8.GetBytes($text); [Console]::OpenStandardOutput().Write($bytes, 0, $bytes.Length)",
        ])
        .output()
        .expect("start independent clipboard reader");
    unsafe { DestroyWindow(owner) }.unwrap();
    assert!(
        read.status.success(),
        "clipboard reader failed: {}",
        String::from_utf8_lossy(&read.stderr)
    );
    assert_eq!(read.stdout, transcript.as_bytes());
}
