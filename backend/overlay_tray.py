"""System-tray icon for the combat overlay.

The overlay is click-through most of the time and has no title bar, so once
it is hidden — or once someone has dragged it off-screen — there is nothing
left to click. The tray is the way back in, and the only always-available
place to say "quit" without hunting for the window.

Fail-soft on purpose: a missing pystray must cost the tray icon, never the
overlay. The tray runs on its own thread with its own Win32 message pump
(pystray's `run_detached`), so it never contends with tkinter's mainloop —
callbacks are marshalled back with `root.after` because every Tk call has to
happen on the thread that owns the window.
"""
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

ICON_NAME = "EQLCompanionOverlay"
TITLE = "EQL Companion — overlay"


def available() -> bool:
    """Is a tray icon possible in this build? (Packaged builds need
    pystray._win32 as a hidden import — it is imported lazily by pystray,
    so PyInstaller cannot see it by static analysis.)"""
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
        return True
    except Exception:
        return False


def _icon_image(size: int = 64):
    """The overlay's mark: gold bars on dark glass, drawn rather than
    shipped so there is no image file to lose in the bundle."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (18, 21, 26, 235))
    d = ImageDraw.Draw(img)
    d.rectangle([1, 1, size - 2, size - 2], outline=(200, 170, 110, 210), width=2)
    bars = ((14, 0.62, (200, 170, 110, 255)),   # gold — damage out
            (26, 0.42, (212, 87, 74, 255)),     # red  — damage in
            (38, 0.52, (31, 179, 140, 255)),    # green— healing
            (50, 0.30, (176, 124, 198, 255)))   # violet— casts
    for y, frac, colour in bars:
        d.rectangle([12, y, 12 + int((size - 26) * frac), y + 7], fill=colour)
    return img


class OverlayTray:
    """Tray icon wired to an overlay's actions.

    `actions` maps a label to a callable; they are invoked on the Tk thread.
    `is_hidden` lets the menu label itself correctly each time it opens.
    """

    def __init__(self, root, actions: dict,
                 is_hidden: Optional[Callable[[], bool]] = None) -> None:
        self._root = root
        self._actions = actions
        self._is_hidden = is_hidden or (lambda: False)
        self._icon = None

    def _call(self, name: str) -> Callable:
        def run(_icon=None, _item=None) -> None:
            fn = self._actions.get(name)
            if not fn:
                return
            try:
                # Tk is not thread-safe: hop back to the thread that owns it
                self._root.after(0, fn)
            except Exception:
                logger.debug("Tray action %s failed", name, exc_info=True)
        return run

    def start(self) -> bool:
        """Returns True when the icon is running."""
        if not available():
            logger.info("Tray icon unavailable (pystray/Pillow missing) — "
                        "the overlay works without it")
            return False
        try:
            import pystray
            from pystray import Menu, MenuItem

            menu = Menu(
                MenuItem("Show overlay", self._call("show"),
                         visible=lambda _i: self._is_hidden()),
                MenuItem("Hide overlay", self._call("hide"),
                         visible=lambda _i: not self._is_hidden()),
                Menu.SEPARATOR,
                MenuItem("Compact mode", self._call("compact")),
                MenuItem("More opaque", self._call("opacity_up")),
                MenuItem("More transparent", self._call("opacity_down")),
                Menu.SEPARATOR,
                MenuItem("Reset position", self._call("reset_position")),
                Menu.SEPARATOR,
                MenuItem("Quit overlay", self._call("quit")),
            )
            self._icon = pystray.Icon(ICON_NAME, _icon_image(), TITLE, menu)
            # detached: pystray owns a thread and its own message pump, so
            # tkinter keeps the main thread
            self._icon.run_detached()
            logger.info("Tray icon started")
            return True
        except Exception:
            logger.warning("Tray icon failed to start — continuing without it",
                           exc_info=True)
            self._icon = None
            return False

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
