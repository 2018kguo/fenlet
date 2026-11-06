---
name: fenlet
description: Organize macOS windows into non-overlapping panes across connected displays and Spaces, minimize useful background windows, close idle clutter. Uses the same engine as the Fenlet CLI and menu-bar widget.
---

# Fenlet

Use `scripts/fenlet` relative to this skill. The installed app includes its runtime and native window helper. Run `doctor`; `setup` or the widget guides Accessibility permission and a provider key into Keychain. No agent-desktop, browser automation, Homebrew, or Python installation is needed for the built app.

Accept natural intent. Inspect live state, preserve the focused window, and honor explicit placements. Do not introduce a background loop or task lifecycle.

```sh
scripts/fenlet doctor
scripts/fenlet scan
scripts/fenlet plan "Tile coding on the big screen; chat and references on my laptop. Minimize useful background windows and close idle clutter." --model jev
```

Read the plan's `actions` and `coverage.errors`. The model classifies purpose; code owns geometry, screen bounds, minimum sizes, and all effects. Display choices are generated from the connected screens. The widget and CLI accept per-purpose display UUID preferences; missing screens fall back automatically. One display shares panes, and three or more can receive separate work, chat and references. When reliable physical display dimensions are available, the planner favors 6–8 inch reading widths and uses portrait height; unknown dimensions fall back to logical points. Jev is the fast default. `hybrid` escalates uncertain assignments to Nemotron; `nemotron` and `beam` are also available. Jev/hybrid use Gateway. No screenshot or document content is uploaded, but app names and window titles are sent to the provider. Never search unrelated projects for credentials.

An existing instruction to organize windows authorizes ordinary moves, minimizations, and closing clearly idle clutter. Use `scripts/fenlet arrange --yes` to classify and apply in one run, or inspect the separate plan when helpful. Do not ask again unnecessarily. For an exploratory request, show the concrete result before requesting permission to apply. Unsaved work and dialogs stay open. Normal closes are real closes and cannot always be undone; do not claim otherwise.

```sh
scripts/fenlet apply PLAN_PATH --yes
scripts/fenlet check
scripts/fenlet undo JOURNAL_PATH
```

Use the final OS overlap check as evidence. Report remaining overlaps and inaccessible windows; never infer success from the number of delivered actions. Default scope is visible windows on current Spaces, excluding Fenlet and Google Chrome for Testing. When intent includes other Spaces/fullscreen apps, use `--all-spaces`; `--display laptop` gathers onto the built-in display, or pass a connected display UUID. Read `coverage.errors`: unresolved windows are left alone. Fullscreen exits only during apply; macOS may animate or briefly change focus. The widget automatically includes other Desktops and adapts display roles to the connected screens. It has one Arrange → review → confirm flow; explicit scope and destination overrides remain available through the CLI.

For deterministic operations without a model:

```sh
scripts/fenlet snap left
scripts/fenlet tile
scripts/fenlet tile --yes
scripts/fenlet tile --all-spaces --display laptop
```

Snap supports left/right/top/bottom/full for the focused window. Tile previews/applies size-aware panes on each current display, minimizing windows that cannot fit. Ordinary layout requests use the model to choose which windows belong on each display.

Each plan applies once and expires after 15 minutes. Windows changed since preview are preserved. Never blindly rerun an uncertain mutation. Observe the live state and journal; a confirmed minimum-size clamp or fixed obstacle permits a newly computed partition. Undo restores moves/minimizes, original regular Space membership, and fullscreen state that have not subsequently changed. Restoring fullscreen creates a new Space; its original order is not guaranteed. Do not force an Undo across a later manual Space change. Classification can be reused for 60 seconds for identical inputs; inventory, geometry and actuation guards are always fresh. Fenlet only controls windows; it never scans Desktop files. Keep private plans, titles, credentials, and journals out of public commits.

The widget always shows a draft before applying. Drag edits and CLI `edit PLAN_PATH --swap WINDOW OTHER` / `--move WINDOW DISPLAY` create a new plan locally, with no model call or OS mutation. The agent may use the explicitly authorized one-shot CLI above.
