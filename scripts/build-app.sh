#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASK_APP="${1:-$TASK_ROOT/build/Fenlet.app}"
TASK_RUNTIME="${FENLET_PYTHON_RUNTIME:-$(bash "$TASK_ROOT/scripts/prepare-runtime.sh")}"
mkdir -p "$TASK_APP/Contents/MacOS" "$TASK_APP/Contents/Resources/native"
xcrun swiftc -O -target "$(uname -m)-apple-macosx13.0" -import-objc-header "$TASK_ROOT/native/Bridge.h" "$TASK_ROOT/native/Helper.swift" -o "$TASK_APP/Contents/Resources/native/desktop-helper"
xcrun swiftc -O -target "$(uname -m)-apple-macosx13.0" -parse-as-library "$TASK_ROOT/native/MenuBar.swift" "$TASK_ROOT/native/WindowPreviews.swift" "$TASK_ROOT/native/DraftEditing.swift" "$TASK_ROOT/native/Brand.swift" -o "$TASK_APP/Contents/MacOS/Fenlet" -framework SwiftUI -framework Security -framework ScreenCaptureKit
mkdir -p "$TASK_ROOT/build/branding"
xcrun swiftc -O -parse-as-library "$TASK_ROOT/native/Brand.swift" "$TASK_ROOT/scripts/RenderIcon.swift" -o "$TASK_ROOT/build/branding/render-icon"
"$TASK_ROOT/build/branding/render-icon" "$TASK_ROOT/build/branding/AppIcon.iconset"
iconutil -c icns "$TASK_ROOT/build/branding/AppIcon.iconset" -o "$TASK_APP/Contents/Resources/AppIcon.icns"
cp -R "$TASK_ROOT/fenlet" "$TASK_APP/Contents/Resources/"
mkdir -p "$TASK_APP/Contents/Resources/bin"
cp "$TASK_ROOT/bin/fenlet" "$TASK_APP/Contents/Resources/bin/fenlet"
chmod +x "$TASK_APP/Contents/Resources/bin/fenlet"
cp -R "$TASK_ROOT/skills" "$TASK_APP/Contents/Resources/"
rm -rf "$TASK_APP/Contents/Resources/runtime"
mkdir -p "$TASK_APP/Contents/Resources/runtime"
cp -cR "$TASK_RUNTIME/." "$TASK_APP/Contents/Resources/runtime/"
find "$TASK_APP/Contents/Resources/fenlet" -name __pycache__ -type d -exec rm -rf {} +
cat > "$TASK_APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Fenlet</string>
<key>CFBundleIdentifier</key><string>org.2018kguo.desk-tidy</string>
<key>CFBundleName</key><string>Fenlet</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.2.0</string>
<key>CFBundleVersion</key><string>2</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
test -x "$TASK_APP/Contents/MacOS/Fenlet"
codesign --force --sign - "$TASK_APP"
printf '%s\n' "$TASK_APP"
