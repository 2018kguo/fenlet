# Fenlet

Keep the menu-bar app and agent skill on the same engine. Pure layout decisions live in `fenlet/core.py`; exact overlap counting lives in `fenlet/overlap.py`; model wording and spending thresholds live in `fenlet/questions.py`; OS and model IO live in `runtime.py` and `operations.py`. Discovery and actuation use `native/Helper.swift`; the view is `native/MenuBar.swift`.

Optional window captures live in `native/WindowPreviews.swift`. Keep them asynchronous, bounded, and in memory. Never send image data to the planner/provider or write thumbnail caches to disk. Match window ID and owner PID, and key cached images by process start identity. Preview images must not activate, raise, resize, or close windows.

Visible preview updates use the shared CLI's `scan`; stop them when the popover closes. Never add model calls or Desktop file enumeration to that loop. Keep the planned layout separate from live observations and invalidate it when geometry changes. Keep the OS/Keychain identifier stable across the product rename so existing permission and credentials remain valid. The shared brand path in `native/Brand.swift` generates the widget mark, status icon, app icon and SVG.

Use synthetic data in public tests, benchmarks, and screenshots. Keep window titles, real Desktop files, plans, journals, local config, and API keys outside the repository.

Never repeat an uncertain desktop mutation. Observe its actual effect, journal the result, and verify Undo. Preserve the user's subsequent window changes and unrelated browser automation.

Run `python3 -m unittest discover -v` and `bash scripts/build-app.sh` after changing the engine or widget. For native window changes run `python3 scripts/verify-native.py`, which owns disposable windows and never mutates other apps. For performance changes run `scripts/benchmark-cpu.py`; separate CPU, provider, native operations, and full CLI wall time. For a model change, rerun `scripts/benchmark.py` with explicit credentials and keep observed latency, provider-reported cost, and assignment quality separate. Verify the native popover before claiming the widget works.

The widget always prepares an editable draft before confirmation. Keep drag edits local and immutable via `fenlet edit`; no model or OS calls during editing. Only the display gallery scrolls on the main page, and instructions and confirmation stay visible for any display count. Use reported physical dimensions for readable pane widths and fall back to logical points when they are unknown or estimated.
