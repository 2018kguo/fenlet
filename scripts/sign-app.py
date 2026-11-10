#!/usr/bin/env python3
"""Sign the app and every bundled Mach-O image with a local Developer ID."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--identity", required=True, help="Developer ID name or certificate SHA-1 in your Keychain")
    args = parser.parse_args()
    app = args.app.resolve()
    assert (app / "Contents/MacOS/Fenlet").is_file(), "Expected a built Fenlet.app"
    magic = {bytes.fromhex(value) for value in ("feedface", "cefaedfe", "feedfacf", "cffaedfe", "cafebabe", "bebafeca", "cafebabf", "bfbafeca")}
    images = []
    for path in app.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as source:
                if source.read(4) in magic: images.append(path)
    bundles = [p for p in app.rglob("*") if p.is_dir() and not p.is_symlink() and p.suffix in (".xpc", ".app", ".framework")]
    for path in sorted(images + bundles, key=lambda p: len(p.parts), reverse=True) + [app]:
        subprocess.run(["codesign", "--force", "--options", "runtime", "--timestamp", "--sign", args.identity, str(path)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    print(f"Developer ID signed {len(images)} Mach-O images and the app bundle.")


if __name__ == "__main__":
    main()
