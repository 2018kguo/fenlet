#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASK_APP="${1:-$TASK_ROOT/build/Desk Tidy.app}"
TASK_RUNTIME="${DESK_TIDY_PYTHON_RUNTIME:-$(bash "$TASK_ROOT/scripts/prepare-runtime.sh")}"
mkdir -p "$TASK_APP/Contents/MacOS" "$TASK_APP/Contents/Resources/native"
xcrun swiftc -O -target "$(uname -m)-apple-macosx13.0" -import-objc-header "$TASK_ROOT/native/Bridge.h" "$TASK_ROOT/native/Helper.swift" -o "$TASK_APP/Contents/Resources/native/desktop-helper"
xcrun swiftc -O -target "$(uname -m)-apple-macosx13.0" -parse-as-library "$TASK_ROOT/native/MenuBar.swift" -o "$TASK_APP/Contents/MacOS/DeskTidy" -framework SwiftUI -framework Security
cp -R "$TASK_ROOT/desk_tidy" "$TASK_APP/Contents/Resources/"
mkdir -p "$TASK_APP/Contents/Resources/bin"
rm -f "$TASK_APP/Contents/MacOS/desk-tidy"
cp "$TASK_ROOT/bin/desk-tidy" "$TASK_APP/Contents/Resources/bin/desk-tidy"
chmod +x "$TASK_APP/Contents/Resources/bin/desk-tidy"
cp -R "$TASK_ROOT/skills" "$TASK_APP/Contents/Resources/"
rm -rf "$TASK_APP/Contents/Resources/runtime"
mkdir -p "$TASK_APP/Contents/Resources/runtime"
cp -cR "$TASK_RUNTIME/." "$TASK_APP/Contents/Resources/runtime/"
find "$TASK_APP/Contents/Resources/desk_tidy" -name __pycache__ -type d -exec rm -rf {} +
cat > "$TASK_APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>DeskTidy</string>
<key>CFBundleIdentifier</key><string>org.2018kguo.desk-tidy</string>
<key>CFBundleName</key><string>Desk Tidy</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$TASK_APP"
printf '%s\n' "$TASK_APP"
