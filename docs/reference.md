# Reference
## CLI

```sh
fenlet setup
fenlet doctor
fenlet scan
fenlet arrange --yes       # classify and arrange in one run
fenlet plan "Work on my big screen; chat on my laptop" --model jev
fenlet apply PLAN_PATH --yes
fenlet edit PLAN_PATH --swap WINDOW_ID OTHER_WINDOW_ID
fenlet edit PLAN_PATH --move WINDOW_ID DISPLAY_UUID
# Also: edit PLAN_PATH --minimize WINDOW_ID / --close WINDOW_ID
fenlet check
# Optional: plan --work-display DISPLAY_UUID --chat-display DISPLAY_UUID

fenlet snap left        # focused window: left/right/top/bottom/full
fenlet tile             # offline pane preview
fenlet tile --yes       # apply offline panes on each current display

fenlet undo JOURNAL_PATH
```

Commands return JSON, also accepted explicitly with `--json`. `arrange --yes` authorizes ordinary moves, minimizes and normal closes; omit `--yes` for an interactive confirmation. An authorized agent can also review a separate plan and apply it. Environment keys (`AI_GATEWAY_API_KEY`, `OPENROUTER_API_KEY`) and an explicit `--env-file PATH` are supported. No automatic credential discovery.

Plans expire after 15 minutes and apply once. Changes made after a preview are preserved. Operations use process-start identity plus window ID, a write-ahead journal, native batched app control, and observed results. Only reads retry automatically; uncertain mutations are inspected before any further action. Undo preserves subsequent manual changes and never overwrites files.


## Layout decisions

Models select a connected display, minimize, close, or leave unchanged. The widget lists actual display names and scrolls when more displays are connected. Automatic uses the largest display for work, another display for chat when available, and a third for references when available. All groups share panes when only one display is connected. Saved display UUIDs fall back to Automatic when unplugged. Code partitions usable screen rectangles, reserves menu-bar/Dock space, applies 6-point gaps, favors tall columns, and respects exposed minimum sizes. OS-reported physical dimensions favor 6–8 inch text panes (7 inches ideal), including portrait layouts that use vertical space. Missing or estimated dimensions use point-based sizing; native minimum sizes and available space take priority. When panes cannot fit, lower-priority windows minimize. The focused window stays open. Arrangement never activates or raises apps. Video-app and video-title hints favor wider panes; these hints do not establish playback state.

Related work browsers and terminals stay adjacent within their chosen display. Explicitly unchanged windows are fixed obstacles. Some apps omit their minimum size. A confirmed resize clamp triggers one new partition using the measured dimensions. Failed closes and newly opened windows become fixed obstacles in a bounded geometric repair. Actual OS rectangles are checked afterward. `fenlet check` reports the exact overlap count and up to 32 examples; a partial run does not mean the desktop is clean.

Opening a draft keeps windows in their current slots when they already fit the chosen layout, including a manually reordered layout. A new display assignment, overlapping windows, or changed screen geometry still triggers a new partition. Grab handles use reserved header space so entering edit mode does not squeeze or shift tile captions.

Repeat previews reuse placements from the last confirmed arrangement while window identities, positions, and instructions still match. This keeps a cached model classification from minimizing a window you chose to keep visible. New windows are classified normally; moved or replaced windows and changed instructions are evaluated afresh. The shared engine records the confirmed journal pointer for both CLI and widget runs.

The engine operates on visible windows in the current Spaces. It leaves fullscreen/other-Space windows, protected dialogs, unsaved work, and unrelated browser-test windows alone. It never force-quits an app or clicks Discard. A normal close cannot always be undone; “Undo” restores moves/minimizes and keeps later manual changes intact.
