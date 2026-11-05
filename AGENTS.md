# Desk Tidy

Keep the menu-bar app and agent skill on the same engine. Pure layout decisions live in `desk_tidy/core.py`; exact overlap counting lives in `desk_tidy/overlap.py`; model wording and spending thresholds live in `desk_tidy/questions.py`; OS and model IO live in `runtime.py` and `operations.py`. Discovery and actuation use `native/Helper.swift`; the view is `native/MenuBar.swift`.

Use synthetic data in public tests, benchmarks, and screenshots. Keep window titles, real Desktop files, plans, journals, local config, and API keys outside the repository.

Never repeat an uncertain desktop mutation. Observe its actual effect, journal the result, and verify Undo. Never empty Trash or overwrite a restore destination. Preserve the user's subsequent window changes and unrelated browser automation.

Run `python3 -m unittest discover -v` and `bash scripts/build-app.sh` after changing the engine or widget. For native window changes run `python3 scripts/verify-native.py`, which owns disposable windows and never mutates other apps. For performance changes run `scripts/benchmark-cpu.py`; separate CPU, provider, native operations, and full CLI wall time. For a model change, rerun `scripts/benchmark.py` with explicit credentials and keep observed latency, provider-reported cost, and assignment quality separate. Verify the native popover before claiming the widget works.
