#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASK_APP="${1:-$TASK_ROOT/build/development.noindex/Fenlet.app}"
TASK_RUNTIME="${FENLET_PYTHON_RUNTIME:-$(bash "$TASK_ROOT/scripts/prepare-runtime.sh")}"
TASK_SPARKLE="$(bash "$TASK_ROOT/scripts/prepare-updater.sh")"
mkdir -p "$TASK_APP/Contents/MacOS" "$TASK_APP/Contents/Resources/native"
xcrun swiftc -O -target "$(uname -m)-apple-macosx13.0" -import-objc-header "$TASK_ROOT/native/Bridge.h" "$TASK_ROOT/native/Helper.swift" -o "$TASK_APP/Contents/Resources/native/desktop-helper"
xcrun swiftc -O -target "$(uname -m)-apple-macosx13.0" -parse-as-library "$TASK_ROOT/native/Engine.swift" "$TASK_ROOT/native/Updater.swift" "$TASK_ROOT/native/MenuBar.swift" "$TASK_ROOT/native/WindowPreviews.swift" "$TASK_ROOT/native/DraftEditing.swift" "$TASK_ROOT/native/Brand.swift" -o "$TASK_APP/Contents/MacOS/Fenlet" -framework SwiftUI -framework Security -framework ScreenCaptureKit -F "$TASK_SPARKLE" -framework Sparkle -Xlinker -rpath -Xlinker @executable_path/../Frameworks
mkdir -p "$TASK_APP/Contents/Frameworks"
rm -rf "$TASK_APP/Contents/Frameworks/Sparkle.framework"
cp -cR "$TASK_SPARKLE/Sparkle.framework" "$TASK_APP/Contents/Frameworks/"
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
cp "$TASK_ROOT/LICENSE" "$TASK_APP/Contents/Resources/LICENSE.txt"
cp "$TASK_ROOT/THIRD_PARTY_NOTICES.md" "$TASK_APP/Contents/Resources/THIRD_PARTY_NOTICES.md"
cp "$TASK_SPARKLE/LICENSE" "$TASK_APP/Contents/Resources/Sparkle-LICENSE.txt"
cp -R "$TASK_ROOT/vendor/python-licenses" "$TASK_APP/Contents/Resources/"
"$TASK_RUNTIME/bin/python3" - "$TASK_ROOT" "$TASK_APP" <<'PYPLIST'
import plistlib
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from fenlet import __version__
info = {
    "CFBundleExecutable": "Fenlet", "CFBundleIdentifier": "org.2018kguo.desk-tidy",
    "CFBundleName": "Fenlet", "CFBundleIconFile": "AppIcon", "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
    "LSMinimumSystemVersion": "13.0", "LSUIElement": True, "NSHighResolutionCapable": True,
    "LSApplicationCategoryType": "public.app-category.productivity",
    "SUFeedURL": "https://raw.githubusercontent.com/2018kguo/fenlet/main/docs/appcast.xml",
    "SUPublicEDKey": "5a8Bbb6hJJR9SvjayFC9+XsgYjxMOG6Mqgh9YzVrxN0=",
    "SUEnableAutomaticChecks": True, "SUAutomaticallyUpdate": False,
}
with (Path(sys.argv[2]) / "Contents/Info.plist").open("wb") as output:
    plistlib.dump(info, output)
PYPLIST
test -x "$TASK_APP/Contents/MacOS/Fenlet"
codesign --force --sign - "$TASK_APP"
printf '%s\n' "$TASK_APP"
