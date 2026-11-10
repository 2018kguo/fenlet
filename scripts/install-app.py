#!/usr/bin/env python3
"""Replace the canonical Fenlet install, keeping rollback as a ZIP, not an app."""
import argparse
from pathlib import Path
import plistlib
import os
import subprocess
import tempfile


def identity(app):
    result = subprocess.run(["codesign", "-dv", "--verbose=2", str(app)], capture_output=True, text=True, check=True)
    return next((line for line in result.stderr.splitlines() if line.startswith("TeamIdentifier=")), None)


def install(source, destination):
    source, destination = source.resolve(), destination.absolute()
    info = plistlib.loads((source / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != "org.2018kguo.desk-tidy":
        raise ValueError("Expected a Fenlet app.")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(source)], check=True)
    if destination.exists():
        current = plistlib.loads((destination / "Contents/Info.plist").read_bytes())
        if current.get("CFBundleIdentifier") != info["CFBundleIdentifier"]:
            raise ValueError("The destination belongs to another application.")
        previous_identity = identity(destination)
        if previous_identity and previous_identity != "TeamIdentifier=not set" and previous_identity != identity(source):
            raise ValueError("Keep the existing Developer ID when updating. Sign this build with that identity, or install the signed release.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fenlet-install-", suffix=".noindex", dir=destination.parent) as temporary:
        staging = Path(temporary)
        candidate, previous = staging / "Fenlet.app", staging / "Previous.app"
        subprocess.run(["ditto", str(source), str(candidate)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(candidate)], check=True)
        subprocess.run(["osascript", "-e", 'if application id "org.2018kguo.desk-tidy" is running then tell application id "org.2018kguo.desk-tidy" to quit'], check=True, timeout=15)
        if subprocess.run(["pgrep", "-x", "Fenlet"], stdout=subprocess.DEVNULL).returncode == 0:
            raise ValueError("Fenlet is still finishing an operation. Wait for it, then install again.")
        if destination.exists():
            backup = Path.home() / "Library/Application Support/Fenlet/previous-install.zip"
            backup.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(destination), str(backup)], check=True)
            destination.rename(previous)
        try:
            candidate.rename(destination)
        except OSError:
            if previous.exists(): previous.rename(destination)
            raise
    subprocess.run([str(destination / "Contents/Resources/bin/fenlet"), "setup", "--install-cli", "--install-skill"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister", "-f", str(destination)], check=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    global_app = Path("/Applications/Fenlet.app")
    user_app = Path.home() / "Applications/Fenlet.app"
    destination = args.destination or (global_app if global_app.exists() else user_app if user_app.exists() else global_app if os.access(global_app.parent, os.W_OK) else user_app)
    print(install(args.app, destination))


if __name__ == "__main__":
    main()
