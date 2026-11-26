#!/usr/bin/env bash
# Install into a disposable Applications directory and launch after ejecting the image.
set -euo pipefail

if [[ $# != 1 || ! -f $1 || $1 != *.dmg ]]; then
  echo "Expected one built Yap disk image." >&2
  exit 1
fi

work=$(mktemp -d)
volume="$work/volume"
applications="$work/Applications"
mkdir "$volume" "$applications"
attached=false
cleanup() {
  if [[ $attached == true ]]; then
    hdiutil detach "$volume" || return 1
  fi
  # Never recurse into a volume if macOS refused to detach it.
  rm -rf "$applications"
  rmdir "$volume" "$work"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

hdiutil attach -readonly -nobrowse -mountpoint "$volume" "$1"
attached=true
if [[ ! -d "$volume/Yap.app" || -L "$volume/Yap.app" ]]; then
  echo "The mounted image must contain the Yap.app bundle." >&2
  exit 1
fi
ditto "$volume/Yap.app" "$applications/Yap.app"
hdiutil detach "$volume"
attached=false

python3 "$(dirname "$0")/test-desktop-package.py" --macos-app "$applications/Yap.app"
shasum -a 256 "$1"
