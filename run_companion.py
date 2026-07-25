#!/usr/bin/env python3
"""Single-process launcher for the packaged EQL Companion.

Starts the FastAPI server (which serves BOTH the API and the static UI) and
opens the dashboard in a native window. Also runnable straight from source
for a production-mode single-window experience.

This file is the executable's ONLY entrypoint, so it doubles as the
dispatcher for the helper windows. A frozen build has no interpreter to
re-invoke, and handing the bootloader `-m backend.overlay` would just start
a second server, so the overlay and the OCR calibrator are reached through
flags instead (see backend/paths.child_command).

Packaged builds are windowed — there is no console to print to — so
everything goes to a log file in the writable state dir, and a failure to
start raises a message box rather than vanishing silently.
"""
import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
WINDOW_TITLE = "EQL Companion"


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _log_file():
    from backend.paths import data_path
    return data_path("companion.log")


def _adopt_dead_streams() -> None:
    """A windowed build has NO console: sys.stdout and sys.stderr are None.
    Anything that touches them dies — uvicorn's colour formatter calls
    sys.stdout.isatty() while configuring logging, which is fatal before a
    single request is served. Point them at the log file so stray writes
    land somewhere readable instead of crashing the app.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    stream = open(_log_file(), "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _fatal(message: str) -> None:
    """Surface a startup failure. Windowed builds have no stderr to read."""
    logging.exception(message)
    if _is_frozen() and os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, f"{message}\n\nDetails are in the log file beside the "
                      f"executable (data\\companion.log).",
                WINDOW_TITLE, 0x10)
        except Exception:
            pass


def _setup_logging() -> None:
    handlers: list = [logging.FileHandler(_log_file(), encoding="utf-8")]
    if not _is_frozen():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO, handlers=handlers, force=True,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _port_is_ours(port: int) -> bool:
    """Is an EQL Companion already serving here? (Re-launching should focus
    the running instance rather than race it for the log file.)"""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://{HOST}:{port}/health", timeout=1.5) as r:
            return "version" in json.loads(r.read())
    except Exception:
        return False


def _free_port(preferred: int) -> int:
    """Preferred port, else whatever the OS hands out. The UI resolves the
    API against its own origin, so any port works."""
    with socket.socket() as s:
        try:
            s.bind((HOST, preferred))
            return preferred
        except OSError:
            pass
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _open_window(url: str, wait_for_server: bool = True) -> bool:
    """Show the dashboard. MUST be called on the main thread — pywebview
    refuses to start anywhere else.

    Returns True if a native window ran (and has now been closed), False if
    we could only hand the URL to a browser. The caller needs to know: a
    closed window means quit, a browser means keep serving.
    """
    if wait_for_server:
        import urllib.request
        for _ in range(120):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
    try:
        import webview  # pywebview
        webview.create_window(WINDOW_TITLE, url, width=1500, height=950)
        webview.start()  # blocks until the user closes the window
        return True
    except Exception:
        logging.info("No native window available - using the browser",
                     exc_info=True)
        webbrowser.open(url)
        return False


def _serve() -> None:
    import uvicorn
    _setup_logging()
    from backend.main import app  # the object, not an import string:
    #                               a frozen build has no module search path
    if _port_is_ours(DEFAULT_PORT):
        logging.info("Companion already running on %s — opening its window",
                     DEFAULT_PORT)
        _open_window(f"http://{HOST}:{DEFAULT_PORT}/", wait_for_server=False)
        return
    port = _free_port(DEFAULT_PORT)
    url = f"http://{HOST}:{port}/"
    logging.info("Serving %s", url)
    # The SERVER goes to the worker thread, not the window: pywebview has to
    # own the main thread. log_config=None keeps the handlers set above --
    # uvicorn's default config installs a formatter that inspects
    # sys.stdout, which a windowed build does not have.
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning",
                            log_config=None)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    if _open_window(url):
        # the window is how the user quits; ask uvicorn to run its shutdown
        # (the lifespan handler snapshots the session) before we go
        logging.info("Window closed - shutting down")
        server.should_exit = True
        thread.join(timeout=10)
    else:
        thread.join()  # browser fallback: nothing to close, keep serving


def main() -> None:
    parser = argparse.ArgumentParser(prog="EQLCompanion", add_help=True)
    parser.add_argument("--overlay", action="store_true",
                        help="run the combat overlay window only")
    parser.add_argument("--ocr-overlay", action="store_true",
                        help="run the OCR region calibrator only")
    parser.add_argument("--overlay-check", action="store_true",
                        help="verify the overlay's imports, then exit "
                             "(0 = usable) — used by the release build")
    args, _unknown = parser.parse_known_args()
    _adopt_dead_streams()
    try:
        if args.overlay_check:
            # No window: just prove the pieces are present. The overlay is a
            # child process, so nothing else in the build exercises them.
            from backend import overlay          # noqa: F401
            from backend import overlay_tray
            raise SystemExit(0 if overlay_tray.available() else 1)
        if args.overlay:
            from backend.overlay import main as overlay_main
            overlay_main()
        elif args.ocr_overlay:
            from backend.ocr_overlay import main as ocr_main
            ocr_main()
        else:
            _serve()
    except Exception:
        _fatal("EQL Companion failed to start.")
        raise


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # PyInstaller: keep child procs sane
    main()
