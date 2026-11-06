# Setup and privacy

## First launch

Download the ZIP from [Releases](https://github.com/2018kguo/fenlet/releases),
unzip it, and move **Fenlet.app** into Applications. The app includes Python
and its native helper; you do not need Homebrew, Python, or browser tools.

Release downloads are Developer ID signed and notarized by Apple. macOS may
ask you to confirm opening an app downloaded from the internet.
[Apple describes the security check here](https://support.apple.com/en-us/102445).
Checksums are published with every archive.

Open Fenlet's menu-bar icon. Setup guides you through:

1. **Accessibility** for window control. Enable the app in System Settings,
   then return to Fenlet. Setup detects the permission automatically while open.
2. **Screen Recording** for real window thumbnails on macOS 14+. Enable Fenlet
   in Screen & System Audio Recording. If macOS asks, choose Quit & Reopen.
   Fenlet shows a restart button when a grant needs a fresh process. You can
   explicitly skip previews and arrange using app names instead.
3. **A provider key**, saved in your Keychain. Vercel AI Gateway supports all
   model choices; OpenRouter supports Nemotron and Beam.

If Accessibility already shows Fenlet enabled but setup still reports it
blocked, remove that Fenlet entry and add the installed copy again. A grant
from an earlier development build can refer to its old code signature.
macOS may ask you to authenticate this change. Release builds use a stable
Developer ID identity so subsequent signed updates retain that identity.

In Settings, **Install CLI & skill** adds `~/.local/bin/fenlet` to your zsh
PATH and links the included skill into `~/.codex/skills/fenlet`. Open a new
terminal after installing. Agents with another skill directory can install
from the public repository instead.

## Gather windows from other Spaces

Choose **All Spaces** in the widget, then **Laptop** in the destination menu
(or any connected display). **Arrange windows** prepares an editable draft;
**Confirm arrangement** brings the selected windows onto that display's regular
Desktop and tiles them. Fullscreen apps leave fullscreen on confirmation.
A live overview shows separate thumbnails for windows from different Spaces.

For an offline preview of the same operation:

```sh
fenlet tile --all-spaces --display laptop
fenlet apply PLAN_PATH --yes
```

Add `--all-spaces --display laptop` to `plan` or `arrange` to also classify
background windows and clutter. Omit `--display` to use the usual display roles.
**Current Space** remains the default. Previewing never switches Spaces or
leaves fullscreen. Confirmation may briefly animate a fullscreen transition;
Fenlet never activates or raises another app to arrange it.

All Spaces uses optional, undocumented macOS window-management APIs; no root
helper, SIP changes, or extra installation is required. Availability can change
with macOS. Discovery is bounded, and windows that cannot be resolved are
reported rather than moved speculatively. Hidden/minimized apps and windows
pinned to multiple Spaces are excluded. The destination must have an existing
regular Desktop. Fenlet does not create, delete, or reorder regular Desktops.

## Windows that cannot change

Dialogs, inaccessible windows and unsaved documents stay open. The final report
says what could not be changed. Fenlet never force-quits an app or clicks Discard.

**Undo** restores moves and minimizes that have not been changed since the
run. Closing a window cannot always be undone. A fresh preview preserves
subsequent manual moves and changes to connected displays. Undo also restores
original Space membership and fullscreen state. macOS creates a new fullscreen
Space when restoring it, so its numeric ID and position may differ. A Space
that was deleted after the run cannot be restored.

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

Short screens keep text panes at least 600 logical points tall when space allows.
Extra work windows go to the visible minimize tray in the draft, rather than
forcing a short 2×2 grid. Tall displays can stack readable panes. The focused
work window and its browser/terminal companion take priority over setup tools.
