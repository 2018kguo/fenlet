#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if command -v uv >/dev/null; then TASK_UV="$(command -v uv)"; else
  mkdir -p "$TASK_ROOT/build/tools"
  curl --fail --silent --show-error --location https://astral.sh/uv/install.sh -o "$TASK_ROOT/build/uv-installer.sh"
  UV_INSTALL_DIR="$TASK_ROOT/build/tools" UV_NO_MODIFY_PATH=1 sh "$TASK_ROOT/build/uv-installer.sh" >&2
  TASK_UV="$TASK_ROOT/build/tools/uv"
fi
"$TASK_UV" python install 3.14 --no-bin --install-dir "$TASK_ROOT/build/python" >&2
TASK_PYTHON="$(UV_PYTHON_INSTALL_DIR="$TASK_ROOT/build/python" "$TASK_UV" python find --managed-python 3.14)"
cd "$(dirname "$TASK_PYTHON")/.."
pwd
