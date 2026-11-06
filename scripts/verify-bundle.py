#!/usr/bin/env python3
"""Check a relocated app with an empty home and no external Python or API key."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    source = args.app.resolve()
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(source)], check=True)
    with tempfile.TemporaryDirectory(prefix="fenlet-bundle-") as temporary:
        directory = Path(temporary)
        app = directory / "Portable Fenlet.app"
        subprocess.run(["cp", "-cR", str(source), str(app)], check=True)
        home = directory / "home"; home.mkdir()
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "TMPDIR": str(directory), "FENLET_STATE": str(home / "state")}
        resources = app / "Contents/Resources"
        cli = resources / "bin/fenlet"
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        version = subprocess.check_output([str(cli), "--version"], env=env, cwd=directory, text=True).strip()
        assert version == "fenlet " + info["CFBundleShortVersionString"], version
        for relative in ("LICENSE.txt", "THIRD_PARTY_NOTICES.md", "python-licenses/manifest.json", "runtime/lib/python3.14/LICENSE.txt"):
            assert (resources / relative).is_file(), relative
        doctor = json.loads(subprocess.check_output([str(cli), "doctor"], env=env, cwd=directory, text=True))
        assert doctor["ok"] and doctor["data"]["runtime_ready"], doctor
        # A clean user's permission/key state is allowed to be false. Never prompt.
        installed = json.loads(subprocess.check_output([str(cli), "setup", "--install-cli", "--install-skill"], env=env, cwd=directory, text=True))
        assert installed["ok"], installed
        assert (home / ".local/bin/fenlet").resolve() == cli.resolve()
        assert (home / ".codex/skills/fenlet").resolve() == (resources / "skills/fenlet").resolve()
        assert subprocess.check_output([str(home / ".local/bin/fenlet"), "--version"], env=env, text=True).strip() == version
    print(json.dumps({"version": version, "signature_valid": True, "relocatable": True,
                      "empty_home_setup": True, "bundled_runtime": True, "license_notices": True}))


if __name__ == "__main__":
    main()
