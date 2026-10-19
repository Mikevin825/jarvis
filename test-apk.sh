#!/usr/bin/env bash
# Test JARVIS.apk on this PC, in the Android emulator.
#
# Boots the emulator (if needed), installs the APK, points it at the local
# mobile server, and launches it. The emulator window appears on your desktop.
#
#   ./test-apk.sh            # normal — opens an emulator window
#   ./test-apk.sh --headless # no window (for screenshots / CI)
#   ./test-apk.sh --fresh    # wipe the emulator's data first
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK="${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}"
ADB="$SDK/platform-tools/adb"
EMU="$SDK/emulator/emulator"
AVD="jarvis_test"
APK="$DIR/JARVIS.apk"

# 10.0.2.2 is the emulator's alias for the host machine — "localhost" inside
# the emulator is the emulator itself, which is the usual first mistake here.
HOST_URL="http://10.0.2.2:8794/"

HEADLESS=0
FRESH=0
for arg in "$@"; do
    case "$arg" in
        --headless) HEADLESS=1 ;;
        --fresh) FRESH=1 ;;
    esac
done

[[ -x "$ADB" ]] || { echo "adb not found at $ADB — set ANDROID_SDK_ROOT" >&2; exit 1; }
[[ -x "$EMU" ]] || { echo "emulator not found at $EMU — set ANDROID_SDK_ROOT" >&2; exit 1; }
[[ -f "$APK" ]] || { echo "No APK. Build it first:  ./build-apk.sh" >&2; exit 1; }

# -- the server -------------------------------------------------------------
# The app is only a window; without the server it has nothing to show.
if ! curl -s --max-time 3 http://localhost:8794/api/health >/dev/null 2>&1; then
    echo "!! The mobile server is not running."
    echo "   Start it in another terminal:  ./jarvis-mobile"
    echo "   (continuing — the app will show its 'cannot reach JARVIS' screen)"
    echo
fi

# -- the emulator -----------------------------------------------------------
if "$ADB" devices | grep -q "emulator-.*device"; then
    echo "==> emulator already running"
else
    echo "==> booting emulator '$AVD' (this takes 1-2 minutes)"
    if [[ $HEADLESS -eq 1 ]]; then
        EXTRA=(-no-window -no-audio -no-snapshot -no-boot-anim -gpu swiftshader_indirect)
    else
        EXTRA=(-no-audio -no-snapshot -no-boot-anim -gpu swiftshader_indirect)
    fi
    if [[ $FRESH -eq 1 ]]; then EXTRA+=(-wipe-data); fi

    ANDROID_SDK_ROOT="$SDK" nohup "$EMU" -avd "$AVD" "${EXTRA[@]}" \
        > /tmp/jarvis-emulator.log 2>&1 &
    echo "    log: /tmp/jarvis-emulator.log"
fi

echo "==> waiting for boot"
for _ in $(seq 1 60); do
    if [[ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; then
        echo "    booted"
        break
    fi
    sleep 5
done

if [[ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ]]; then
    echo "!! emulator did not finish booting — see /tmp/jarvis-emulator.log" >&2
    exit 1
fi

# Give the package manager a moment; a fresh boot is still settling.
sleep 3

# -- install ----------------------------------------------------------------
echo "==> installing $APK"
"$ADB" install -r "$APK"

# -- point it at the host ---------------------------------------------------
# Written straight into the app's SharedPreferences, so you don't have to type
# an IP into the emulator on every test run.
echo "==> pointing the app at $HOST_URL"
"$ADB" root >/dev/null 2>&1 || true
sleep 2
PREFS=/data/data/com.jarvis.mobile/shared_prefs
"$ADB" shell "mkdir -p $PREFS"
"$ADB" shell "cat > $PREFS/jarvis.xml" <<EOF
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="server_url">$HOST_URL</string>
</map>
EOF
# The app runs as its own uid; root-written files need its ownership.
OWNER=$("$ADB" shell stat -c '%u:%g' /data/data/com.jarvis.mobile 2>/dev/null | tr -d '\r')
if [[ -n "$OWNER" ]]; then
    "$ADB" shell "chown $OWNER $PREFS/jarvis.xml && chmod 660 $PREFS/jarvis.xml"
fi

# -- launch -----------------------------------------------------------------
echo "==> launching"
"$ADB" shell am force-stop com.jarvis.mobile
sleep 1
"$ADB" shell am start -n com.jarvis.mobile/.MainActivity >/dev/null

echo
echo "JARVIS is running in the emulator."
echo
echo "  Pair it: the token is in state/mobile-token.txt —"
echo "    $(cat "$DIR/state/mobile-token.txt" 2>/dev/null || echo '(no token file)')"
echo
echo "  Watch the WebView:  $ADB logcat | grep chromium"
echo "  Screenshot:         $ADB shell screencap -p /sdcard/s.png && $ADB pull /sdcard/s.png ."
echo "  Stop:               $ADB emu kill"
