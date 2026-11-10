#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASK_CACHE="$TASK_ROOT/build/vendor.noindex"
TASK_ARCHIVE="$TASK_CACHE/Sparkle-2.10.1.tar.xz"
mkdir -p "$TASK_CACHE"
if [ ! -f "$TASK_ARCHIVE" ]; then
  curl --fail --silent --show-error --location https://github.com/sparkle-project/Sparkle/releases/download/2.10.1/Sparkle-2.10.1.tar.xz -o "$TASK_ARCHIVE.download"
  mv "$TASK_ARCHIVE.download" "$TASK_ARCHIVE"
fi
printf '%s  %s\n' 1a856d2a9edb8e628de88121d7be04cf0e2167f8641650b78fca00b14244cf27 "$TASK_ARCHIVE" | shasum -a 256 --check >&2
if [ ! -d "$TASK_CACHE/sparkle/Sparkle.framework" ]; then
  mkdir -p "$TASK_CACHE/sparkle"
  tar -xJf "$TASK_ARCHIVE" -C "$TASK_CACHE/sparkle"
fi
printf '%s\n' "$TASK_CACHE/sparkle"
