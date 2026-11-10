---
name: fenlet
description: Organize macOS windows into non-overlapping panes across connected displays and Spaces, minimize useful background windows, close idle clutter. Uses the same engine as the Fenlet CLI and menu-bar widget.
---

# Fenlet

Use `scripts/fenlet` relative to this skill. The installed app includes its runtime and native window helper. Run `doctor`; the widget guides window-control and preview permissions. A provider key in Keychain is optional: local layouts and drag edits need no AI. No agent-desktop, browser automation, Homebrew, or Python installation is needed for the built app.

Accept natural intent. Inspect live state, preserve the focused window, and honor explicit placements. Do not introduce a background loop or task lifecycle.

```sh
scripts/fenlet doctor
scripts/fenlet scan
scripts/fenlet plan "Tile coding on the big screen; chat and references on my laptop. Minimize useful background windows and close idle clutter."
```

Read the plan's `actions`, `model.notice`, and `coverage.errors`. Code owns geometry, screen bounds, minimum sizes, and all effects. Display choices follow the connected screens automatically; explicit display overrides belong to the CLI. One display shares panes, and three or more can receive separate work, chat and references. Reported physical dimensions favor 6–8 inch reading widths and portrait height; unknown dimensions fall back to logical points. `--model auto` uses configured AI with a four-second request timeout and falls back to safe local choices. Local planning never closes windows or interprets written instructions: explain the fallback and use local draft edits for explicit placements. `--model local` never reads provider credentials. Jev is the preferred AI model; `hybrid` escalates uncertainty to Nemotron. Explicit `jev`, `hybrid`, `nemotron`, and `beam` require credentials. Jev/hybrid use Gateway. Images stay local; AI requests send app names, titles, and instructions. Never search unrelated projects for credentials.

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

Snap supports left/right/top/bottom/full for the focused window. Tile previews/applies size-aware panes on each current display, minimizing windows that cannot fit.

Each plan applies once and expires after 15 minutes. Windows changed since preview are preserved. Never blindly rerun an uncertain mutation. Observe the live state and journal; a confirmed minimum-size clamp or fixed obstacle permits a newly computed partition. Undo restores moves/minimizes, original regular Space membership, and fullscreen state that have not subsequently changed. Restoring fullscreen creates a new Space; its original order is not guaranteed. Do not force an Undo across a later manual Space change. Classification can be reused for 60 seconds for identical inputs; inventory, geometry and actuation guards are always fresh. Fenlet only controls windows; it never scans Desktop files. Keep private plans, titles, credentials, and journals out of public commits.

The widget always shows a draft before applying. Drag edits and CLI `edit PLAN_PATH --swap WINDOW OTHER` / `--move WINDOW DISPLAY` create a new plan locally, with no model call or OS mutation. `rebase PLAN_PATH --all-spaces` preserves valid choices while refreshing the desktop; manually moved and newly opened windows stay in place. Review a changed draft before applying it. `serve` keeps the same engine warm over a serial JSON pipe; observation never invokes a provider. The agent may use the explicitly authorized one-shot CLI above.
