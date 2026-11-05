# Desk Tidy

A native macOS menu-bar widget, CLI, and agent skill for any connected display setup.

Assign Work, Chat, and References to a connected display, or leave each on Automatic. Click **Tidy windows**, or use Preview to review changes first. Useful foreground windows become non-overlapping panes. Useful background windows minimize; idle clutter closes through the normal macOS Close button. Old Desktop screenshots have a separate Trash preview.

## Install

Requires Apple Silicon and macOS 13+. The built app includes Python and its native window helper. End users need no Homebrew, Python installation, browser automation, or developer tools.

For a prebuilt ZIP, unzip it, move Desk Tidy.app into Applications, and open it. Setup handles permission and key entry; “Install CLI & skill” enables Terminal and Codex.

For a source build:

```sh
bash scripts/install.sh
open "$HOME/Applications/Desk Tidy.app"
```

The source installer opens Apple's Command Line Tools installer when needed and downloads a standalone Python runtime through [uv](https://docs.astral.sh/uv/). Run it again after Apple's installer finishes. The installed app and CLI work independently of this checkout.

Open the menu-bar icon. Setup guides you through macOS Accessibility permission and a provider API key, saved in Keychain. Vercel AI Gateway supports all model options; OpenRouter supports Nemotron and Beam. The widget can install the CLI into `~/.local/bin` and the included agent skill into `~/.codex/skills`. The source installer also links the skill into `~/.codex/skills/desk-tidy`; other agents can use the included skill directory.

Build a distributable ZIP with `bash scripts/package.sh`. Local builds are ad-hoc signed. A public release still needs Developer ID signing and notarization; no public release is published by this repository's build scripts.

## Panes, not guessed coordinates

Models select a connected display, minimize, close, or leave unchanged. The widget lists actual display names and scrolls when more displays are connected. Automatic uses the largest display for work, another display for chat when available, and a third for references when available. All groups share panes when only one display is connected. Saved display UUIDs fall back to Automatic when unplugged. Code partitions usable screen rectangles, reserves menu-bar/Dock space, applies 6-point gaps, favors tall columns, and respects exposed minimum sizes. When panes cannot fit, lower-priority windows minimize. The focused window stays open. Arrangement never activates or raises apps. Video-app and video-title hints favor wider panes; these hints do not establish playback state.

Related work browsers and terminals stay adjacent within their chosen display. Explicitly unchanged windows are fixed obstacles. Some apps omit their minimum size. A confirmed resize clamp triggers one new partition using the measured dimensions. Failed closes and newly opened windows become fixed obstacles in a bounded geometric repair. Actual OS rectangles are checked afterward. `desk-tidy check` reports the exact overlap count and up to 32 examples; a partial run does not mean the desktop is clean.

The engine operates on visible windows in the current Spaces. It leaves fullscreen/other-Space windows, protected dialogs, unsaved work, and unrelated browser-test windows alone. It never force-quits an app or clicks Discard. A normal close cannot always be undone; “Undo layout” restores moves/minimizes, and screenshot Undo restores unchanged files from Trash.

## CLI

```sh
desk-tidy setup
desk-tidy doctor
desk-tidy scan
desk-tidy tidy --yes       # classify and arrange in one run
desk-tidy plan "Work on my big screen; chat on my laptop" --model jev
desk-tidy apply PLAN_PATH --scope windows --yes
desk-tidy check
# Optional: plan --work-display DISPLAY_UUID --chat-display DISPLAY_UUID

desk-tidy snap left        # focused window: left/right/top/bottom/full
desk-tidy tile             # offline pane preview
desk-tidy tile --yes       # apply offline panes on each current display

desk-tidy cleanup --days 30
desk-tidy apply PLAN_PATH --scope screenshots --yes
desk-tidy undo JOURNAL_PATH
```

Commands return JSON, also accepted explicitly with `--json`. `tidy --yes` authorizes ordinary moves, minimizes and normal closes; omit `--yes` for an interactive confirmation. An authorized agent can also review a separate plan and apply it. Environment keys (`AI_GATEWAY_API_KEY`, `OPENROUTER_API_KEY`) and an explicit `--env-file PATH` are supported. No automatic credential discovery.

Plans expire after 15 minutes and each section applies once. Changes made after a preview are preserved. Operations use process-start identity plus window ID, a write-ahead journal, native batched app control, and observed results. Only reads retry automatically; uncertain mutations are inspected before any further action. Undo preserves subsequent manual changes and never overwrites files.

Cleanup only considers default-named screenshot files directly on Desktop, using the newer of creation/modification time. No recursion, symlink following, or emptying Trash. Other files stay where they are.

## Models and privacy

Jev 1.14 is the default: one batch of short, concrete per-window questions. **Jev + Nemotron** spends a second request on uncertain classifications; its threshold controls spending. Nemotron and Beam are available directly. Geometry and permission to act never come from model confidence.

The [synthetic benchmark](benchmarks/2026-11-05-synthetic.json) is a small repeatable smoke benchmark, not a general accuracy claim. Reproduce it with your provider:

```sh
export AI_GATEWAY_API_KEY='…'
python3 scripts/benchmark.py --repeats 2
```

Layout requests send app names, window titles, and your instructions to the chosen provider. Screenshots, file names, and document contents stay local. There are no background model calls or recurring cleanup jobs. Private plans/journals live in `~/.local/state/desk-tidy`; settings live in `~/.config/desk-tidy`.

Identical classification inputs reuse a private result for up to 60 seconds. Changes to titles, focus, process identities, instructions, display preferences or model invalidate it. Geometry and permission to act are checked fresh every time. Window arrangement does not enumerate or stat Desktop screenshots.

[agent-browser](https://github.com/vercel-labs/agent-browser) operates inside browser pages. Desk Tidy uses native Accessibility and CoreGraphics APIs for desktop arrangement, avoiding a screenshot-driven browser-agent loop.

## Develop

```sh
python3 -m unittest discover -v
python3 scripts/benchmark-cpu.py
python3 scripts/verify-native.py
bash scripts/build-app.sh
```

SwiftUI/AppKit widget; Python standard-library planner; Swift discovery and OS control. No Electron, web server, or Python packages. One short-lived native connection serves each CLI invocation; app window indexes are read once per batch, and already correct panes skip AX enumeration and setters. Undo batches restores and waits for Dock restore animation to finish before verifying.

Overlap checking uses an O(N log N) sweep with O(N) memory and capped examples, including dense stacks. Pane search is bounded by the screen's physical capacity and window minimums, rather than trying every subset of N windows. The [CPU benchmark](benchmarks/2026-11-05-cpu.json) measures planning and exact overlap counting separately from OS and provider latency. `verify-native.py` creates disposable windows, checks moves, minimize/Undo, real Close, unsaved-state and stale-identity guards, then removes only its own fixture. It never arranges other apps.

`--show` opens the normal menu-bar popover once; `--preview-window` is a development view.

MIT licensed.
