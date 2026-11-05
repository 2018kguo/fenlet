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
DESK_TIDY_PYTHON_RUNTIME="$TASK_RUNTIME" bash "$TASK_ROOT/scripts/build-app.sh" "$HOME/Applications/Desk Tidy.app"
"$TASK_RUNTIME/bin/python3" - "$TASK_ROOT" <<'PYINSTALL'
from pathlib import Path
import sys
root=Path(sys.argv[1]); app=Path.home()/'Applications/Desk Tidy.app/Contents/Resources'
cli=Path.home()/'.local/bin/desk-tidy'
if cli.is_symlink() and cli.resolve()==(root/'skills/desk-tidy/scripts/desk-tidy').resolve():cli.unlink()
destination=Path.home()/'.codex/skills/desk-tidy'
target=app/'skills/desk-tidy'
destination.parent.mkdir(parents=True,exist_ok=True)
if destination.is_symlink() and destination.resolve() in [target.resolve(),(root/'skills/desk-tidy').resolve()]:destination.unlink()
if not destination.exists() and not destination.is_symlink():destination.symlink_to(target)
else:print(f'Kept existing skill at {destination}')
PYINSTALL
"$HOME/Applications/Desk Tidy.app/Contents/Resources/bin/desk-tidy" setup --install-cli
printf '%s\n' 'Installed. Open ~/Applications/Desk Tidy.app for the setup guide, or run desk-tidy setup.'
