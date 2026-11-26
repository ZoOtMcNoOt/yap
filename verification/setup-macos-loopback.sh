#!/usr/bin/env bash
# Test dependencies for the disposable Apple silicon package runner.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted && ${RUNNER_OS:-} == macOS ]]
work=$(mktemp -d "$RUNNER_TEMP/yap-virtual-audio.XXXXXX")
cd "$work"
# Homebrew's blackhole-2ch cask and switchaudio-osx formula pin these releases.
curl -fLsS --retry 2 https://existential.audio/downloads/BlackHole2ch-0.7.1.pkg -o BlackHole.pkg
echo '57b540f27a3e29c37e310e01bee0fdfab76733087e47f997ef9dccf851400dcf  BlackHole.pkg' | shasum -a 256 -c -
pkgutil --check-signature BlackHole.pkg
sudo /usr/sbin/installer -pkg BlackHole.pkg -target /
# Reload HAL drivers on this disposable runner before starting the app.
sudo /usr/bin/killall -TERM coreaudiod
curl -fLsS --retry 2 https://github.com/deweller/switchaudio-osx/archive/refs/tags/1.2.2.tar.gz -o switchaudio.tar.gz
echo '3d12b57cbd6063a643a12f12287af99c87894c33449c6bcac0a71fd15776b3ed  switchaudio.tar.gz' | shasum -a 256 -c -
tar -xzf switchaudio.tar.gz
cd switchaudio-osx-1.2.2
xcodebuild -quiet -configuration Release -project AudioSwitcher.xcodeproj -target SwitchAudioSource \
  SYMROOT="$work/build" MACOSX_DEPLOYMENT_TARGET=15.0
switch="$work/build/Release/SwitchAudioSource"
"$switch" -a
for kind in input output; do
  for attempt in {1..30}; do
    if "$switch" -a -t "$kind" | grep -Fxq 'BlackHole 2ch'; then break; fi
    sleep 1
  done
  "$switch" -t "$kind" -s 'BlackHole 2ch'
  test "$("$switch" -c -t "$kind")" = 'BlackHole 2ch'
done
echo "YAP_TEST_AUDIO_SWITCH=$switch" >> "$GITHUB_ENV"
