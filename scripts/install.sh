#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if ! xcode-select -p >/dev/null 2>&1; then
  xcode-select --install
  printf '%s\n' 'Complete Apple’s Command Line Tools installer, then run this command again. Prebuilt app downloads do not need these tools.' >&2
  exit 1
fi
TASK_RUNTIME="$(bash "$TASK_ROOT/scripts/prepare-runtime.sh")"
"$TASK_RUNTIME/bin/python3" -m unittest discover -s "$TASK_ROOT/tests" -t "$TASK_ROOT"
TASK_APP="$TASK_ROOT/build/development.noindex/Fenlet.app"
FENLET_PYTHON_RUNTIME="$TASK_RUNTIME" bash "$TASK_ROOT/scripts/build-app.sh" "$TASK_APP"
if [ -n "${FENLET_SIGN_IDENTITY:-}" ]; then
  "$TASK_RUNTIME/bin/python3" "$TASK_ROOT/scripts/sign-app.py" "$TASK_APP" --identity "$FENLET_SIGN_IDENTITY"
fi
"$TASK_RUNTIME/bin/python3" "$TASK_ROOT/scripts/install-app.py" "$TASK_APP"
printf '%s\n' 'Installed. Open Fenlet for the setup guide, or run fenlet setup.'
