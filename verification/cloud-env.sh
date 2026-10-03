#!/usr/bin/env bash
# Source this file from a shell in the managed Debian cloud workspace.
yap_dev_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$yap_dev_root/.tools/powershell:$yap_dev_root/.tools/native/usr/bin:$PATH"
export PKG_CONFIG_SYSROOT_DIR="$yap_dev_root/.tools/native"
export PKG_CONFIG_PATH="$yap_dev_root/.tools/native/usr/lib/x86_64-linux-gnu/pkgconfig:$yap_dev_root/.tools/native/usr/share/pkgconfig"
export LIBRARY_PATH="$yap_dev_root/.tools/native/usr/lib/x86_64-linux-gnu${LIBRARY_PATH:+:$LIBRARY_PATH}"
export LD_LIBRARY_PATH="$yap_dev_root/.tools/native/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export SHERPA_ONNX_ARCHIVE_DIR="$yap_dev_root/.tools/sherpa"
export PNPM_CONFIG_STORE_DIR="$yap_dev_root/.pnpm-store"
export YAP_PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium
export YAP_PLAYWRIGHT_VIDEO=off
unset yap_dev_root
