# Development

The widget, CLI, and skill use one engine. Pure decisions are in
`fenlet/core.py`; exact overlap analysis is in `fenlet/overlap.py`; native
reads and effects are in `native/Helper.swift`. The widget is in
`native/MenuBar.swift`. `AGENTS.md` holds the invariants.

## Checks

```sh
python3 -m unittest discover -v
bash scripts/build-app.sh
python3 scripts/verify-bundle.py build/Fenlet.app
python3 scripts/benchmark-cpu.py
```

`build-app.sh` obtains CPython 3.14.3 through uv and bundles it. The source
version in `fenlet/__init__.py` supplies the CLI and app version. A prebuilt
app needs no external runtime. GitHub Actions checks Python 3.11 and 3.14 on
Linux, then builds and tests the ARM64 app on macOS 15.

On a Mac with Accessibility permission:

```sh
python3 scripts/verify-native.py
```

This creates and removes its own windows, checks normal Close, unsaved-work
protection, minimize/Undo, identity guards, and focus preservation. It never
arranges other apps.

With [Peekaboo](https://github.com/steipete/Peekaboo) installed and its desktop
permissions granted:

```sh
python3 scripts/verify-widget.py --output build/widget-evidence
python3 scripts/demo.py
```

The widget check exercises real drag gestures against synthetic plans, including
background restoration, filled action trays, and Cancel. It checks 1, 2, 4,
and 6 displays, including portrait. The demo renders the production widget
with generated example window images; its command wrapper refuses OS effects
and model calls. Only its own fixture window is captured. `--output DIR`
keeps demo assets outside `docs` when experimenting. `ffmpeg` creates the GIF.
These fixtures are not included in the installed app.

`--preview-window` opens a development window; `--show` opens the normal
menu-bar popover once. Neither flag applies a layout.

## Release

1. Change `__version__` in `fenlet/__init__.py` and pass local checks plus
   exact-commit GitHub Actions.
2. Build a fresh app, then sign every bundled Mach-O image with your own
   Developer ID. The signing identity stays in your Keychain:

   ```sh
   bash scripts/build-app.sh
   python3 scripts/sign-app.py build/Fenlet.app --identity 'Developer ID Application: Your Name (TEAMID)'
   python3 scripts/verify-bundle.py build/Fenlet.app
   bash scripts/package.sh build/Fenlet.app
   ```

3. If a notarization profile is available, submit the ZIP and wait for
   **Accepted**, staple the app, and repackage:

   ```sh
   xcrun notarytool submit build/Fenlet-macos-arm64.zip --keychain-profile PROFILE --wait
   xcrun stapler staple build/Fenlet.app
   xcrun stapler validate build/Fenlet.app
   bash scripts/package.sh build/Fenlet.app
   spctl --assess --type execute --verbose build/Fenlet.app
   ```

   A Developer ID signature alone is not notarization. State the actual
   notarization status in the README and release notes. Do not publish signing
   certificates, passwords, provider keys, or local desktop evidence.

4. Verify the archive's checksum and relocated install. Tag the checked commit
   and publish that ZIP and its `.sha256` file. CI artifacts are ad-hoc signed
   build checks, not the Developer ID signed release download.

The bundle/Keychain identifier stays stable across the original local rename
so existing installations retain their OS identity. Display geometry comes
from OS-reported dimensions with a logical-point fallback.
