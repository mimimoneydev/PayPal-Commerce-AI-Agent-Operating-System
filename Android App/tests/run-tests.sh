#!/usr/bin/env bash
# One-command emulator verification for the ACME Shop Android app.
# Boots an AVD (if needed), rebuilds + installs the APK, attaches WebView DevTools
# and runs the 18-check CDP suite. Results: tests/results.json + screenshots/.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}}"
ADB="$SDK/platform-tools/adb"
EMULATOR="$SDK/emulator/emulator"
AVD="${AVD_NAME:-Pixel_9_Pro}"
PORT="${CDP_PORT:-9222}"

echo "==> [1/6] Emulator"
if ! "$ADB" devices | grep -q "emulator-.*device"; then
  # A crashed prior run can leave stale snapshot locks that make the emulator refuse
  # to start. Only these specific lock files are cleared, never AVD user data.
  AVD_DIR="$HOME/.android/avd/$AVD.avd"
  if [ -d "$AVD_DIR" ]; then
    for f in snapshot.lock.lock hardware-qemu.ini.lock multiinstance.lock \
             bootcompleted.ini read-snapshot.txt snapshot.trace; do
      [ -e "$AVD_DIR/$f" ] && rm -f "$AVD_DIR/$f"
    done
    find "$AVD_DIR" -maxdepth 1 -name 'snapshot.lock.tmp-*' -delete 2>/dev/null || true
    find "$AVD_DIR" -maxdepth 1 -name 'hardware-qemu.ini.tmp-*' -delete 2>/dev/null || true
  fi
  "$EMULATOR" -avd "$AVD" -no-snapshot -no-audio -no-window \
    -gpu swiftshader_indirect -no-boot-anim > /tmp/acme_emulator.log 2>&1 &
  "$ADB" wait-for-device
  for _ in $(seq 1 90); do
    [ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && break
    sleep 2
  done
  [ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] \
    || { echo "Emulator did not finish booting; see /tmp/acme_emulator.log" >&2; exit 1; }
fi
"$ADB" devices -l | tail -n +2

echo "==> [2/6] Build APK"
(cd "$APP" && ANDROID_HOME="$SDK" ./build.sh | tail -12)

echo "==> [3/6] Install + launch"
"$ADB" install -r "$APP/apk/ACME-Shop.apk" | tail -2
"$ADB" shell am force-stop com.acme.shop
"$ADB" shell am start -n com.acme.shop/.MainActivity >/dev/null

echo "==> [4/6] Wait for WebView DevTools"
SOCK=""
for _ in $(seq 1 30); do
  SOCK=$("$ADB" shell cat /proc/net/unix 2>/dev/null \
    | grep -o '@webview_devtools_remote_[0-9]*' | head -1 | tr -d '@' || true)
  [ -n "$SOCK" ] && break
  sleep 1
done
[ -n "$SOCK" ] || { echo "WebView DevTools socket not found" >&2; exit 1; }
"$ADB" forward --remove "tcp:$PORT" >/dev/null 2>&1 || true
"$ADB" forward "tcp:$PORT" "localabstract:$SOCK" >/dev/null
echo "forwarded $SOCK -> tcp:$PORT"

echo "==> [5/6] Functional suite"
(cd "$APP" && CDP_PORT="$PORT" ADB="$ADB" node tests/emulator-test.mjs)

echo "==> [6/6] Results"
echo "  $APP/tests/results.json"
echo "  $APP/screenshots/"
