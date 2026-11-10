#!/usr/bin/env python3
"""Keep Fenlet's temporary builds out of macOS application lookup."""
import argparse
from pathlib import Path
import plistlib
import re
import subprocess

BUNDLE_ID = "org.2018kguo.desk-tidy"
LSREGISTER = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"


def registered_fenlet_paths(dump):
    # lsregister emits top-level bundle records, followed by indented dictionary
    # details. Only these exact top-level fields identify a registration. The
    # optional hex suffix is its display annotation, not part of the file path.
    record, paths = {}, set()
    def finish():
        if record.get("identifier") == BUNDLE_ID and "path" in record:
            path = re.sub(r" \(0x[0-9a-fA-F]+\)$", "", record["path"])
            if path.startswith("/") and "\0" not in path:
                paths.add(Path(path))
    for line in dump.splitlines():
        if line.startswith("bundle id:"):
            finish(); record = {}
        elif line.startswith(("path:", "identifier:")):
            key, _, value = line.partition(":")
            record[key] = value.strip()
    finish()
    return sorted(paths)


def forget(*paths):
    if not paths: return
    subprocess.run([LSREGISTER, "-u", *map(str, paths)], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


def prefer_install(destination, *, temporary_paths=()):
    destination = Path(destination).resolve()
    info = plistlib.loads((destination / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != BUNDLE_ID:
        raise ValueError("The preferred application must be an installed Fenlet bundle.")
    dump = subprocess.check_output([LSREGISTER, "-dump"], text=True, timeout=30)
    paths = sorted(set(registered_fenlet_paths(dump)) | set(map(Path, temporary_paths)))
    forget(*(path for path in paths if path.resolve() != destination))
    subprocess.run([LSREGISTER, "-f", str(destination)], check=True, timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--forget", type=Path)
    choices.add_argument("--prefer", type=Path)
    args = parser.parse_args()
    if args.forget:
        forget(args.forget)
    else:
        prefer_install(args.prefer)


if __name__ == "__main__": main()
