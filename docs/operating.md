# Setup and privacy

## First launch

Download the ZIP from [Releases](https://github.com/2018kguo/fenlet/releases),
unzip it, and move **Fenlet.app** into Applications. The app includes Python
and its native helper; you do not need Homebrew, Python, or browser tools.

The first public preview is Developer ID signed but not notarized. If macOS
blocks it, use **System Settings → Privacy & Security → Open Anyway** only
if you trust this download. [Apple describes the security check here](https://support.apple.com/en-us/102445).
Checksums are published with every archive. No system security setting needs
to be disabled.

Open Fenlet's menu-bar icon. Setup guides you through:

1. **Accessibility** for window control. Enable the app in System Settings,
   then return and check setup again.
2. **A provider key**, saved in your Keychain. Vercel AI Gateway supports all
   model choices; OpenRouter supports Nemotron and Beam.
3. **Screen Recording**, optional, for real window thumbnails on macOS 14+.
   Arrangement works without thumbnails.

In Settings, **Install CLI & skill** adds `~/.local/bin/fenlet` to your zsh
PATH and links the included skill into `~/.codex/skills/fenlet`. Open a new
terminal after installing. Agents with another skill directory can install
from the public repository instead.

## Windows that cannot change

Fenlet works on visible windows in the current Spaces. Fullscreen windows,
other Spaces, dialogs, inaccessible apps, and unsaved documents may need to
be handled in their own app. The final report says what could not be changed.
Fenlet never force-quits an app or clicks Discard.

**Undo** restores moves and minimizes that have not been changed since the
run. Closing a window cannot always be undone. A fresh preview preserves
subsequent manual moves and changes to connected displays.

## Models, data, and cost

Jev 1.14 is the default: one batch of short, concrete per-window questions. **Jev + Nemotron** spends a second request on uncertain classifications; its threshold controls spending. Nemotron and Beam are available directly. Geometry and permission to act never come from model confidence.

The [synthetic benchmark](../benchmarks/2026-11-05-synthetic.json) is a small repeatable smoke benchmark, not a general accuracy claim. Reproduce it with your provider:

```sh
export AI_GATEWAY_API_KEY='…'
python3 scripts/benchmark.py --repeats 2
```

Layout requests send app names, window titles, and your instructions to the chosen provider. Window images stay local. Fenlet only organizes windows; it does not scan or modify Desktop files. There are no background model calls. Private plans/journals live in `~/.local/state/fenlet`; settings live in `~/.config/fenlet`.

Window thumbnails use ScreenCaptureKit on macOS 14+ and optional Screen Recording permission. Use “Allow…” below the preview if permission is missing. Arrangement still works without it. Captures stay in widget memory, never go to the provider, and are never saved to disk. While the widget is open, window positions and images refresh about once a second. Closing it stops refreshes. These updates make no model calls and never scan Desktop files. A budget of 24 small images limits memory; inspecting a window prioritizes it. A desktop geometry change invalidates an old proposed layout. Captures never block the CLI or arrangement.

Identical classification inputs reuse a private result for up to 60 seconds. Changes to titles, focus, process identities, instructions, display preferences or model invalidate it. Geometry and permission to act are checked fresh every time. Fenlet never enumerates Desktop files.

[agent-browser](https://github.com/vercel-labs/agent-browser) operates inside browser pages. Fenlet uses native Accessibility and CoreGraphics APIs for desktop arrangement, avoiding a screenshot-driven browser-agent loop.


## Local files

Settings are `~/.config/fenlet/config.json`. Private plans, verified journals,
geometry constraints, and short-lived classifications live under
`~/.local/state/fenlet`. Plan files and journals can contain window titles;
keep them private when reporting a problem. API keys are stored in Keychain,
not in these files. `--env-file PATH` is an explicit alternative for CLI use.

`fenlet doctor` checks the runtime, provider key, and Accessibility permission
without arranging anything. `fenlet scan` reads windows; `fenlet check`
measures actual overlap. All three return JSON. See the [reference](reference.md).
