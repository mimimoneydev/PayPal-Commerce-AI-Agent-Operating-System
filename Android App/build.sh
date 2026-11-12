#!/usr/bin/env bash
# Dependency-free APK build using only the Android SDK build-tools and a JDK.
# No Gradle, no Maven, no network access required. Space-safe paths throughout.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}}"
BT="${BUILD_TOOLS:-$SDK/build-tools/35.0.0}"
PLATFORM_JAR="${PLATFORM_JAR:-$SDK/platforms/android-35/android.jar}"
SRC="$ROOT/app/src/main"
OUT="$ROOT/build"
APK="$ROOT/apk/ACME-Shop.apk"

for tool in aapt2 d8 zipalign apksigner; do
  if [ ! -x "$BT/$tool" ]; then echo "Missing $BT/$tool — set BUILD_TOOLS" >&2; exit 1; fi
done
if [ ! -f "$PLATFORM_JAR" ]; then echo "Missing $PLATFORM_JAR — set PLATFORM_JAR" >&2; exit 1; fi

echo "[1/7] Cleaning"
rm -rf "$OUT"
mkdir -p "$OUT/compiled" "$OUT/gen" "$OUT/classes" "$OUT/dex" "$ROOT/apk"

echo "[2/7] Compiling resources"
"$BT/aapt2" compile --dir "$SRC/res" -o "$OUT/compiled"
FLATS=()
while IFS= read -r f; do FLATS+=("$f"); done < <(find "$OUT/compiled" -name '*.flat' | sort)
if [ "${#FLATS[@]}" -eq 0 ]; then echo "No compiled resources" >&2; exit 1; fi

echo "[3/7] Linking resources + assets (${#FLATS[@]} files)"
"$BT/aapt2" link -o "$OUT/base.apk" \
  -I "$PLATFORM_JAR" \
  --manifest "$SRC/AndroidManifest.xml" \
  --java "$OUT/gen" \
  --auto-add-overlay \
  -A "$SRC/assets" \
  --min-sdk-version 26 --target-sdk-version 35 \
  --version-code 1 --version-name 1.0.0 \
  "${FLATS[@]}"

echo "[4/7] Compiling Java"
SOURCES=()
while IFS= read -r f; do SOURCES+=("$f"); done < <(find "$SRC/java" "$OUT/gen" -name '*.java' | sort)
javac -source 11 -target 11 -encoding UTF-8 \
  -cp "$PLATFORM_JAR" -d "$OUT/classes" "${SOURCES[@]}"

echo "[5/7] Dexing"
CLASSES=()
while IFS= read -r f; do CLASSES+=("$f"); done < <(find "$OUT/classes" -name '*.class' | sort)
"$BT/d8" --lib "$PLATFORM_JAR" --min-api 26 --output "$OUT/dex" "${CLASSES[@]}"

echo "[6/7] Packaging + aligning"
(cd "$OUT/dex" && zip -q "$OUT/base.apk" classes.dex)
"$BT/zipalign" -f -p 4 "$OUT/base.apk" "$OUT/aligned.apk"

echo "[7/7] Signing"
KS="$ROOT/debug.keystore"
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" \
    -storepass android -keypass android -alias androiddebugkey \
    -dname "CN=Android Debug,O=Android,C=US" \
    -keyalg RSA -keysize 2048 -validity 10000 >/dev/null 2>&1
fi
"$BT/apksigner" sign \
  --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --ks-key-alias androiddebugkey \
  --v1-signing-enabled true --v2-signing-enabled true \
  --out "$APK" "$OUT/aligned.apk"
"$BT/apksigner" verify --verbose "$APK" | head -8

echo
echo "Built: $APK ($(du -h "$APK" | cut -f1))"
echo "Install: adb install -r \"$APK\""
