"""OCR region calibrator — an always-on-top translucent gold box.

Run:  python -m backend.ocr_overlay   (the web UI's Calibrate button does this)

Drag the box over the in-game map's location text (X:/Y:/Z:/zone), drag the
bottom-right grip to resize, then DOUBLE-CLICK (or press Enter) to save the
region to data/ocr_config.json and close. Esc cancels.

Note: the game must be in Windowed or Borderless mode — exclusive
fullscreen draws over every overlay.
"""
import ctypes
import json
import sys
import tkinter as tk

from backend.paths import data_path

CONFIG_PATH = data_path("ocr_config.json")
GRIP = 18  # px corner zone that resizes instead of moves


def load() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"left": 100, "top": 100, "width": 240, "height": 130, "enabled": False}


def main() -> None:
    # Physical-pixel coordinates so the region matches what mss captures
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    cfg = load()
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.45)
    root.configure(bg="#c8aa6e")  # gold border via 2px padding
    root.geometry(f"{cfg['width']}x{cfg['height']}+{cfg['left']}+{cfg['top']}")

    inner = tk.Frame(root, bg="#12151a")
    inner.place(x=2, y=2, relwidth=1, relheight=1, width=-4, height=-4)
    label = tk.Label(
        inner,
        text="OCR region\ndrag = move · corner = resize\ndouble-click = save · Esc = cancel",
        bg="#12151a", fg="#e7cd92", font=("Segoe UI", 9), justify="left",
    )
    label.place(x=6, y=4)

    # ANCHORED, not incremental: every motion is measured from the geometry
    # captured at press time. `root.geometry()` only *requests* a move, and
    # winfo_x/width keep reporting the old values until the ConfigureNotify
    # comes back, so a handler that reads them mid-drag computes from stale
    # numbers. Anchoring also makes a repeated event idempotent instead of
    # destructive (see the single-bind note below).
    drag = {"x": 0, "y": 0, "ox": 0, "oy": 0, "ow": 0, "oh": 0, "resizing": False}

    def press(e):
        root.update_idletasks()  # settle geometry before we anchor to it
        drag.update(x=e.x_root, y=e.y_root,
                    ox=root.winfo_x(), oy=root.winfo_y(),
                    ow=root.winfo_width(), oh=root.winfo_height())
        # e.x/e.y are relative to whichever widget got the event (the label
        # sits at 6,4 inside a frame at 2,2), so the grip test works in
        # screen space instead — it is the only coordinate all three share.
        drag["resizing"] = (e.x_root - drag["ox"] > drag["ow"] - GRIP
                            and e.y_root - drag["oy"] > drag["oh"] - GRIP)

    def motion(e):
        dx, dy = e.x_root - drag["x"], e.y_root - drag["y"]
        if drag["resizing"]:
            w = max(drag["ow"] + dx, 120)
            h = max(drag["oh"] + dy, 60)
            root.geometry(f"{w}x{h}")
        else:
            root.geometry(f"+{drag['ox'] + dx}+{drag['oy'] + dy}")

    def save(_e=None):
        cfg.update(left=root.winfo_x(), top=root.winfo_y(),
                   width=root.winfo_width(), height=root.winfo_height())
        CONFIG_PATH.parent.mkdir(exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"saved: {cfg}")
        root.destroy()

    # Bind ONCE, on root only. A widget's bindtags are (widget, class,
    # toplevel, all), so events on inner/label already reach root's handler —
    # binding all three ran every handler TWICE per event. That also
    # double-fired save(), whose second call touched a destroyed window.
    root.bind("<ButtonPress-1>", press)
    root.bind("<B1-Motion>", motion)
    root.bind("<Double-Button-1>", save)
    root.bind("<Return>", save)
    root.bind("<Escape>", lambda e: (print("cancelled"), root.destroy()))
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
