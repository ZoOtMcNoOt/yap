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
test_home="$work/home"
profile="$test_home/Library/Application Support/com.mcnatg1.yap"
checks=$(cd "$(dirname "$0")" && pwd)
mkdir "$volume" "$applications" "$test_home"
attached=false
cleanup() {
  if [[ $attached == true ]]; then
    hdiutil detach "$volume" || return 1
  fi
  # Never recurse into a volume if macOS refused to detach it.
  rm -rf "$applications" "$test_home"
  rmdir "$volume" "$work"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

install_copy() {
  hdiutil attach -readonly -nobrowse -mountpoint "$volume" "$1"
  attached=true
  if [[ ! -d "$volume/Yap.app" || -L "$volume/Yap.app" ]]; then
    echo "The mounted image must contain the Yap.app bundle." >&2
    exit 1
  fi
  ditto "$volume/Yap.app" "$applications/Yap.app"
  hdiutil detach "$volume"
  attached=false
}
launch() {
  python3 "$checks/test-desktop-package.py" --macos-app "$applications/Yap.app" --test-home "$test_home"
}

install_copy "$1"
launch
python3 "$checks/package-profile.py" seed "$profile"
rm -rf "$applications/Yap.app"
python3 "$checks/package-profile.py" verify "$profile"
install_copy "$1"
launch
python3 "$checks/package-profile.py" verify "$profile"
shasum -a 256 "$1"
