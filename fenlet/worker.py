"""A private, serial pipe to the same operations the CLI invokes."""
import json
import os
import contextlib
import io
from .__main__ import arguments, execute


def serve(source, destination):
    last_id = 0
    while True:
        line = source.readline(5 * 1024 * 1024 + 1)
        if not line:
            return
        request_id = None
        environment = os.environ.copy()
        try:
            if not line.endswith("\n"):
                raise ValueError("Incomplete engine request. No operation was started.")
            request = json.loads(line)
            if not isinstance(request, dict) or set(request) - {"id", "args", "input", "focus"}:
                raise ValueError("Invalid engine request.")
            request_id = request.get("id")
            argv = request.get("args")
            text = request.get("input")
            focus = request.get("focus")
            if type(request_id) is not int or not last_id < request_id <= 2**53:
                raise ValueError("Invalid or previously handled request. Inspect before retrying.")
            last_id = request_id
            if not isinstance(argv, list) or len(argv) > 100 or not all(isinstance(a, str) for a in argv):
                raise ValueError("Invalid command arguments.")
            if text is not None and (not isinstance(text, str) or len(text) > 16384):
                raise ValueError("Invalid input text.")
            if focus is not None and (not isinstance(focus, dict) or set(focus) != {"pid", "window_id"}
                or type(focus["pid"]) is not int or focus["pid"] <= 0 or not isinstance(focus["window_id"], str)):
                raise ValueError("Invalid work-window identity.")
            for key, value in (("FENLET_FRONTMOST_PID", str(focus["pid"]) if focus else None),
                               ("FENLET_FRONTMOST_WINDOW_ID", focus["window_id"] if focus else None)):
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
            with contextlib.redirect_stdout(io.StringIO()):
                args = arguments(argv)
            if args.command == "serve" or args.command in ("arrange", "apply") and not args.yes:
                raise ValueError("An explicit confirmation is required before applying a layout.")
            if args.command == "setup" and args.key_stdin and text is None:
                raise ValueError("Include input when saving a provider key.")
            result = {"id": request_id, "ok": True, "data": execute(args, input_text=text)}
        except (Exception, SystemExit) as error:
            result = {"id": request_id, "ok": False, "error": str(error)}
        finally:
            os.environ.clear()
            os.environ.update(environment)
        destination.write(json.dumps(result, ensure_ascii=False) + "\n")
        destination.flush()
        if not line.endswith("\n"):
            return
