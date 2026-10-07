#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tools_root="$repo_root/.tools"
source /etc/os-release
if [[ "$ID" != debian || "$VERSION_ID" != 13 || "$(uname -m)" != x86_64 ]]; then
  echo 'This setup targets the Debian 13 x86_64 cloud workspace.' >&2
  exit 1
fi
node -e 'if (process.versions.node.split(".")[0] !== "24") process.exit(1)'
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)'
command -v uv >/dev/null
command -v corepack >/dev/null
command -v chromium >/dev/null
mkdir -p "$tools_root/downloads" "$tools_root/powershell" "$tools_root/sherpa" "$HOME/.local/bin"

if [[ ! -x "$HOME/.cargo/bin/rustup" ]]; then
  curl -fsSL https://sh.rustup.rs -o "$tools_root/downloads/rustup-init.sh"
  bash "$tools_root/downloads/rustup-init.sh" -y --profile minimal --default-toolchain 1.96.0 --component rustfmt --component clippy
else
  "$HOME/.cargo/bin/rustup" toolchain install 1.96.0 --profile minimal --component rustfmt --component clippy
  "$HOME/.cargo/bin/rustup" default 1.96.0
fi
corepack enable --install-directory "$HOME/.local/bin"
corepack install --global pnpm@11.7.0

download_checked() {
  local url="$1" destination="$2" checksum="$3"
  if [[ ! -f "$destination" ]]; then
    curl -fsSL "$url" -o "$destination.part"
    mv "$destination.part" "$destination"
  fi
  printf '%s  %s\n' "$checksum" "$destination" | sha256sum --check
}
download_checked \
  https://github.com/PowerShell/PowerShell/releases/download/v7.6.0/powershell-7.6.0-linux-x64.tar.gz \
  "$tools_root/downloads/powershell-7.6.0-linux-x64.tar.gz" \
  04517472cf57d7f9cbd93897da9bed467c73ca6063c29d7655ebc20aa1d6023f
tar -xzf "$tools_root/downloads/powershell-7.6.0-linux-x64.tar.gz" -C "$tools_root/powershell"
chmod +x "$tools_root/powershell/pwsh"
download_checked \
  https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.8/sherpa-onnx-v1.13.8-linux-x64-static-lib.tar.bz2 \
  "$tools_root/sherpa/sherpa-onnx-v1.13.8-linux-x64-static-lib.tar.bz2" \
  e1fdc5b67530e15741ef897fa5ffff297056f3bf0c6d829a27af9225a4c4b5a6

# A user-owned prefix supplies native headers/libraries without administrator
# access. Package signatures and the session's proxy/TLS trust remain enabled.
mkdir -p "$tools_root/apt/lists/partial" "$tools_root/apt/archives/partial"
printf 'deb https://deb.debian.org/debian trixie main\n' > "$tools_root/apt/sources.list"
apt_options=(
  -o "Dir::Etc::sourcelist=$tools_root/apt/sources.list"
  -o Dir::Etc::sourceparts=-
  -o "Dir::State::lists=$tools_root/apt/lists"
  -o "Dir::Cache::archives=$tools_root/apt/archives"
  -o Debug::NoLocking=1
)
if [[ -n "${HTTPS_PROXY:-}" ]]; then
  apt_options+=(-o "Acquire::https::Proxy=$HTTPS_PROXY")
fi
/usr/bin/apt-get "${apt_options[@]}" update
/usr/bin/apt-get "${apt_options[@]}" --download-only -y --no-install-recommends install \
  libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev \
  libasound2-dev librsvg2-dev libbz2-dev cmake patchelf xvfb xauth tini
python3 - "$tools_root" <<'PY'
from pathlib import Path
import shutil
import subprocess
import sys

tools = Path(sys.argv[1])
staging = tools / "native-staging"
if staging.exists():
    shutil.rmtree(staging)
staging.mkdir()
for package in sorted((tools / "apt/archives").glob("*.deb")):
    subprocess.run(["dpkg-deb", "-x", str(package), str(staging)], check=True)

def merge_system(source, target):
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if not destination.exists() and not destination.is_symlink():
            destination.symlink_to(item, target_is_directory=item.is_dir())
        elif item.is_dir() and destination.is_dir() and not destination.is_symlink():
            merge_system(item, destination)

for name in ("include", "lib/x86_64-linux-gnu", "lib/pkgconfig", "share/pkgconfig"):
    source = Path("/usr") / name
    if source.is_dir():
        merge_system(source, staging / "usr" / name)
native = tools / "native"
if native.exists():
    shutil.rmtree(native)
staging.rename(native)
PY

source "$repo_root/verification/cloud-env.sh"
(cd "$repo_root/desktop" && pnpm install --frozen-lockfile)
(cd "$repo_root/server" && uv sync --locked --exact --extra evaluation --extra test --python 3.12 --no-python-downloads)
rustc --version
pnpm --version
pwsh --version
pkg-config --modversion gtk+-3.0 webkit2gtk-4.1 ayatana-appindicator3-0.1 alsa
printf '\nReady. In each new shell: source %s/verification/cloud-env.sh\n' "$repo_root"
