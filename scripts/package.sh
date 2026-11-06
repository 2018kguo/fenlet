#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -gt 0 ]; then
  TASK_APP="$1"
else
  bash "$TASK_ROOT/scripts/build-app.sh"
  TASK_APP="$TASK_ROOT/build/Fenlet.app"
fi
codesign --verify --deep --strict "$TASK_APP"
TASK_ZIP="$TASK_ROOT/build/Fenlet-macos-$(uname -m).zip"
ditto -c -k --sequesterRsrc --keepParent "$TASK_APP" "$TASK_ZIP"
(cd "$(dirname "$TASK_ZIP")" && shasum -a 256 "$(basename "$TASK_ZIP")" > "$(basename "$TASK_ZIP").sha256")
printf '%s\n' "$TASK_ZIP"
