# Desktop demo

The public loop shows a fictional desktop becoming an organized workspace.
The widget images are captured from the production SwiftUI components, using
synthetic window data. The final rectangles come from `fenlet.core.build_actions`.
The desktop and app documents are illustrations. No model calls, user window
operations, private desktop captures, or provider keys are involved.

The 12-second story shows overlapping windows, **Arrange windows**, the editable
review, **Confirm arrangement**, and the result. The transitions demonstrate
the workflow; they are not a latency benchmark.

```sh
python3 scripts/demo.py --prepare-only
cd build/fenlet-demo
npx hyperframes preview --background
```

Edit the HTML in this directory and prepare again to regenerate the project.
To preserve edits made in the generated HyperFrames project, use
`python3 scripts/demo.py --render-only`. The complete command is
`python3 scripts/demo.py`; it checks the composition and exports the README GIF,
poster, and MP4 to `docs`. Development tools need Node 22+, FFmpeg, and Peekaboo
with its desktop permissions. None are dependencies of the installed app.

The pointer uses the geometry of HyperFrames' `oversized-cursor` example.
