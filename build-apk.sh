#!/usr/bin/env bash
# Build a signed, installable APK for JARVIS — without Gradle.
#
# The toolchain is already on this machine (~/Android/Sdk), so the build is
# just the four steps the SDK tools do: compile resources, compile Java, dex
# it, then zip and sign. No Gradle, no network, no dependencies.
#
#   aapt2 compile/link  -> resources + AndroidManifest + R.java
#   javac               -> .class against android.jar
#   d8                  -> classes.dex
#   zip + zipalign      -> unsigned APK
#   apksigner           -> signed APK
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK="${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}"
BT="$SDK/build-tools/36.0.0"
PLATFORM="$SDK/platforms/android-36/android.jar"
JAVA_HOME_BIN="$(dirname "$(readlink -f "$(which javac)")")"

SRC="$DIR/android"
OUT="$DIR/build/android"
KEYSTORE="$DIR/build/jarvis.keystore"
KS_PASS="jarvisdebug"
KS_ALIAS="jarvis"

for tool in "$BT/aapt2" "$BT/d8" "$BT/apksigner" "$BT/zipalign" "$PLATFORM"; do
    if [[ ! -e "$tool" ]]; then
        echo "missing toolchain piece: $tool" >&2
        echo "Set ANDROID_SDK_ROOT if your SDK lives elsewhere." >&2
        exit 1
    fi
done

echo "==> clean"
rm -rf "$OUT"
mkdir -p "$OUT/res-compiled" "$OUT/gen" "$OUT/classes" "$OUT/dex"

echo "==> aapt2 compile (resources)"
"$BT/aapt2" compile --dir "$SRC/res" -o "$OUT/res-compiled/res.zip"

echo "==> aapt2 link (manifest + resources + R.java)"
"$BT/aapt2" link \
    -o "$OUT/base.apk" \
    -I "$PLATFORM" \
    --manifest "$SRC/AndroidManifest.xml" \
    --java "$OUT/gen" \
    --min-sdk-version 24 \
    --target-sdk-version 34 \
    --version-code 1 \
    --version-name 1.0 \
    "$OUT/res-compiled/res.zip"

echo "==> javac"
find "$SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
# android.jar goes on the classpath, not the bootclasspath: modern javac
# rejects -bootclasspath alongside -target 17.
"$JAVA_HOME_BIN/javac" \
    -nowarn \
    -source 17 -target 17 \
    -classpath "$PLATFORM" \
    -d "$OUT/classes" \
    @"$OUT/sources.txt"

if ! find "$OUT/classes" -name '*.class' -print -quit | grep -q .; then
    echo "javac produced no classes — build cannot continue" >&2
    exit 1
fi

echo "==> d8 (dex)"
find "$OUT/classes" -name '*.class' > "$OUT/classes.txt"
"$BT/d8" \
    --lib "$PLATFORM" \
    --min-api 24 \
    --output "$OUT/dex" \
    @"$OUT/classes.txt"

echo "==> package"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip -q "$OUT/unsigned.apk" classes.dex)
"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

echo "==> keystore"
if [[ ! -f "$KEYSTORE" ]]; then
    mkdir -p "$(dirname "$KEYSTORE")"
    keytool -genkeypair -v \
        -keystore "$KEYSTORE" \
        -alias "$KS_ALIAS" \
        -keyalg RSA -keysize 2048 -validity 10000 \
        -storepass "$KS_PASS" -keypass "$KS_PASS" \
        -dname "CN=JARVIS, OU=Personal, O=JARVIS, L=Jos, C=NG" >/dev/null 2>&1
    echo "    created $KEYSTORE"
fi

echo "==> sign"
"$BT/apksigner" sign \
    --ks "$KEYSTORE" \
    --ks-key-alias "$KS_ALIAS" \
    --ks-pass "pass:$KS_PASS" \
    --key-pass "pass:$KS_PASS" \
    --out "$DIR/JARVIS.apk" \
    "$OUT/aligned.apk"

"$BT/apksigner" verify --print-certs "$DIR/JARVIS.apk" | head -4

echo
echo "Built: $DIR/JARVIS.apk ($(du -h "$DIR/JARVIS.apk" | cut -f1))"
