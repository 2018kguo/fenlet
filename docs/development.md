# Development

The widget, CLI, and skill use one engine. Pure decisions are in
`fenlet/core.py`; exact overlap analysis is in `fenlet/overlap.py`; native
reads and effects are in `native/Helper.swift`. The widget is in
`native/MenuBar.swift`. `AGENTS.md` holds the invariants.

## Checks

```sh
python3 -m unittest discover -v
bash scripts/build-app.sh
python3 scripts/verify-bundle.py build/development.noindex/Fenlet.app
python3 scripts/benchmark-cpu.py
python3 scripts/benchmark-session.py build/development.noindex/Fenlet.app/Contents/Resources/bin/fenlet
```

`build-app.sh` obtains CPython 3.14.3 through uv and bundles it. The source
version in `fenlet/__init__.py` supplies the CLI and app version. A prebuilt
app needs no external runtime. GitHub Actions checks Python 3.11 and 3.14 on
Linux, then builds and tests the ARM64 app on macOS 15.

The following native and widget checks open temporary windows and can switch
Spaces or focus. Run them in a dedicated desktop test session. Ask before using
someone's active desktop; the unit tests and build above do not open windows.

On a test Mac with Accessibility permission:

```sh
python3 scripts/verify-native.py
python3 scripts/verify-native.py --spaces
```

This creates and removes its own windows, checks normal Close, unsaved-work
protection, minimize/Undo, identity guards, and focus preservation. It never
arranges other apps. `--spaces` additionally opens two owned fullscreen Spaces,
gathers three fixture windows onto one Desktop, verifies no overlaps and stale
Space/fullscreen guards, then checks Undo. These fullscreen checks briefly
switch Spaces; closing the fixture removes only its own fullscreen Spaces.

With [Peekaboo](https://github.com/steipete/Peekaboo) installed and its desktop
permissions granted:

```sh
python3 scripts/verify-widget.py --output build/widget-evidence
python3 scripts/demo.py
```

The widget check exercises real drag gestures against synthetic plans, including
background restoration, filled action trays, and Cancel. It checks 1, 2, 4,
and 6 displays, including portrait.

The [desktop demo](../media/fenlet-demo/README.md) uses the real planner and
captures the production widget with fictional content. The surrounding desktop
is illustrated, and the animation demonstrates the workflow rather than latency.
Its command wrapper refuses OS effects and model calls. Only its own fixture
windows are captured. Node 22+, HyperFrames, and FFmpeg render the MP4, GIF, and
poster. `--prepare-only` builds an editable project under `build/fenlet-demo`;
`--render-only` preserves edits in that project. `--output DIR` keeps exports
outside `docs`. These tools and fixtures are not included in the installed app.

`--preview-window` opens a development window; `--show` opens the normal
menu-bar popover once. Neither flag applies a layout.

## Release

1. Change `__version__` in `fenlet/__init__.py` and pass local checks plus
   exact-commit GitHub Actions.
2. Build a fresh app, then sign every bundled Mach-O image with your own
   Developer ID. The signing identity stays in your Keychain:

   ```sh
   bash scripts/build-app.sh
   python3 scripts/sign-app.py build/development.noindex/Fenlet.app --identity 'Developer ID Application: Your Name (TEAMID)'
   python3 scripts/verify-bundle.py build/development.noindex/Fenlet.app
   bash scripts/package.sh build/development.noindex/Fenlet.app
   ```

3. Create a local notarization profile once. Use an
   [app-specific password](https://support.apple.com/en-us/102654); the command
   prompts for it and saves it in Keychain. Apple may require you to accept
   updated developer agreements in your account first.

   ```sh
   xcrun notarytool store-credentials PROFILE --apple-id YOUR_APPLE_ID --team-id TEAMID
   ```

   Submit the ZIP and wait for **Accepted**, staple the app, and repackage:

   ```sh
   xcrun notarytool submit build/Fenlet-macos-arm64.zip --keychain-profile PROFILE --wait
   xcrun stapler staple build/development.noindex/Fenlet.app
   xcrun stapler validate build/development.noindex/Fenlet.app
   bash scripts/package.sh build/development.noindex/Fenlet.app
   spctl --assess --type execute --verbose build/development.noindex/Fenlet.app
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

## App updates

Sparkle 2.10.1 is downloaded with a pinned SHA-256 by `scripts/prepare-updater.sh`. Development apps live under `.noindex` to keep them out of app search. The main app holds a per-user instance lock.

Builds and portable-install checks unregister their temporary app paths from
Launch Services, macOS's app lookup database. Installation registers only the
installed copy and removes Fenlet's other cached paths. To refresh an existing
install without opening it:

```sh
python3 scripts/app_registration.py --prefer /Applications/Fenlet.app
```

This changes no windows or files.

Release signing covers nested Sparkle bundles as well as the Python runtime. After notarizing, stapling, and packaging the final ZIP, run `python3 scripts/update-appcast.py build/Fenlet-macos-arm64.zip`. It signs and verifies the archive using the Fenlet Ed25519 key in Keychain and writes `docs/appcast.xml`. Never export or commit that private key. Upload the archive to a draft GitHub release, commit the appcast, then publish the release. Future releases must retain both the Developer ID and the Ed25519 public key. Check the public feed and download after publishing.
