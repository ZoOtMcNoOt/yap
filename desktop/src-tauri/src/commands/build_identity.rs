#[cfg(feature = "wdio")]
#[tauri::command]
pub(crate) fn wdio_build_git_sha() -> &'static str {
    env!("YAP_BUILD_GIT_SHA")
}
