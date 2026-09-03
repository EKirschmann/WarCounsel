#!/usr/bin/env python3
"""Single-process launcher for the packaged WarCounsel.

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
WINDOW_TITLE = "WarCounsel"


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
    """Is an WarCounsel already serving here? (Re-launching should focus
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
        window = webview.create_window(WINDOW_TITLE, url, width=1500, height=950)
        _register_quit_hook(window)
        webview.start()  # blocks until the user closes the window
        return True
    except Exception:
        logging.info("No native window available - using the browser",
                     exc_info=True)
        webbrowser.open(url)
        return False


def _register_quit_hook(window) -> None:
    """Let the backend close this window.

    A self-update has to exit through the SAME path the user takes, not
    os._exit: closing the window sets server.should_exit below, which runs
    the lifespan handler, which is what snapshots the session. An update
    that cost you the evening's session state would be worse than no
    update at all.
    """
    try:
        from backend import updater
        updater.QUIT_HOOK = window.destroy
    except Exception:
        logging.info("no quit hook available for updates", exc_info=True)


def _sweep_update_leftovers() -> None:
    """Clear the previous version's binary, which the installer could not
    delete while it was still mapped. Certainly free by now."""
    if not _is_frozen():
        return
    try:
        from backend import updater
        updater.sweep_leftovers(updater.target_exe())
    except Exception:
        logging.info("could not sweep update leftovers", exc_info=True)


def _apply_update(args) -> int:
    """The installer half of a self-update, running inside the NEW build.

    Its own streams are dead (windowed), and it is deliberately given the
    log path rather than deriving one — see the note at the call site.
    """
    from pathlib import Path
    log_path = Path(args.log) if args.log else Path("update.log")
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO, force=True,
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.stdout is None or sys.stderr is None:
        stream = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    if not args.target or not args.wait_pid:
        logging.error("--apply-update needs --target and --wait-pid")
        return 2
    from backend.updater import apply_update
    try:
        return apply_update(Path(args.target), args.wait_pid)
    except Exception:
        logging.exception("the installer itself failed")
        return 1


def _serve() -> None:
    import uvicorn
    _setup_logging()
    _sweep_update_leftovers()
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
    parser = argparse.ArgumentParser(prog="WarCounsel", add_help=True)
    parser.add_argument("--overlay", action="store_true",
                        help="run the combat overlay window only")
    parser.add_argument("--ocr-overlay", action="store_true",
                        help="run the OCR region calibrator only")
    parser.add_argument("--overlay-check", action="store_true",
                        help="verify the overlay's imports, then exit "
                             "(0 = usable) — used by the release build")
    parser.add_argument("--ocr-check", action="store_true",
                        help="verify screen OCR really works, then exit "
                             "(0 = usable) — used by the OCR release build")
    parser.add_argument("--apply-update", action="store_true",
                        help="install this build over an existing one, then "
                             "relaunch it (spawned by the running app; not "
                             "meant to be typed)")
    parser.add_argument("--target", help="the executable to replace")
    parser.add_argument("--wait-pid", type=int,
                        help="wait for this pid to exit before replacing it")
    parser.add_argument("--log", help="where the installer writes its log")
    args, _unknown = parser.parse_known_args()
    if args.apply_update:
        # Handled before anything else, and before _adopt_dead_streams():
        # this process is the DOWNLOADED build running out of a staging
        # folder, so data_path() would resolve beside the staged copy
        # rather than beside the install. The log path is passed in for
        # exactly that reason.
        raise SystemExit(_apply_update(args))
    _adopt_dead_streams()
    try:
        if args.ocr_check:
            # IMPORTING rapidocr is not proof. Its models and config are
            # package DATA, which PyInstaller does not collect unless told
            # to, and a half-present install raises FileNotFoundError from
            # deep inside the engine rather than at import — so the only
            # honest check is to run the thing on an image with known text
            # in it. v2.6.0's first OCR build shipped-in-CI with the code
            # bundled and default_models.yaml missing.
            from backend import ocr_system
            if not ocr_system.HAS_DEPS:
                print(f"OCR deps unusable: {ocr_system._IMPORT_ERROR}")
                raise SystemExit(1)
            from PIL import Image, ImageDraw
            import numpy as np
            img = Image.new("RGB", (240, 64), "black")
            ImageDraw.Draw(img).text((8, 20), "X: 1234", fill="yellow")
            engine = ocr_system._get_engine()
            result = engine(np.array(img))
            text = " ".join(str(x) for x in (result or []))
            print(f"OCR engine ran, read: {text[:120]!r}")
            # "1234" is the assertion, not the whole string: the engine's
            # confidence on a 64px synthetic render is not the point, and
            # demanding an exact match would make this brittle rather than
            # meaningful.
            raise SystemExit(0 if "1234" in text else 1)
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
        _fatal("WarCounsel failed to start.")
        raise


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # PyInstaller: keep child procs sane
    main()
