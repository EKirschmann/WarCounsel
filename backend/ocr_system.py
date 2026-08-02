"""Live position via screen OCR.

Reads the small on-screen region where the in-game map shows:
    X: -76
    Y: -3
    Z: 4
    Befallen

Loop: every ~1s, if eqgame.exe is running and OCR is enabled, grab the
configured screen rectangle (mss), upscale 3x (PIL), OCR it with RapidOCR
(ONNX PaddleOCR — the Windows built-in engine drops short lines like
"Z: 4"), parse X/Y/Z, and push the position into the tracker + WebSocket.
Passive screen reading only — never touches the game process.

Region + enabled flag live in data/ocr_config.json; the tkinter calibrator
(backend/ocr_overlay.py) writes the same file.
"""
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from backend.paths import data_path

CONFIG_PATH = data_path("ocr_config.json")
DEFAULT_CONFIG = {
    "left": 100, "top": 100, "width": 240, "height": 130, "enabled": False,
    # SECOND region: the Inventory window's stat panel (HP/mana/AC/resists).
    # Deliberately its own region, cadence and gate rather than a mode of the
    # position feed -- that one reads a small always-visible box several
    # times a second, and this reads a large panel that is usually not on
    # screen at all. Sharing either setting would make one of them wrong.
    "stats_enabled": False,
    "stats_left": 100, "stats_top": 300, "stats_width": 320, "stats_height": 260,
    # Stats do not move on their own. They change when you equip something,
    # level, or buff -- so this reads on the order of a quarter-minute, not
    # a second, and costs almost nothing next to the position feed.
    "stats_interval": 15,
    # Fraction of pixels that must be EQ's yellow label text before we spend
    # an OCR pass. This is the "is the Equipment tab actually focused" test:
    # the panel is only legible then, and an unfocused or closed window
    # would otherwise be read as a screenful of zeroes.
    "stats_yellow_min": 0.004,
}
GAME_PROCESS = "eqgame.exe"

try:
    import mss  # noqa: F401
    import numpy as np
    import psutil
    from PIL import Image
    try:
        from rapidocr_onnxruntime import RapidOCR   # Python <= 3.12
        _OCR_V2 = False
    except Exception:
        from rapidocr import RapidOCR               # successor pkg, 3.13+
        _OCR_V2 = True
    HAS_DEPS = True
    _IMPORT_ERROR = None
except Exception as e:
    # Deliberately broad. OCR is OPTIONAL, so nothing it does may stop the
    # app from booting -- and a half-present install does not fail cleanly:
    # rapidocr raises FileNotFoundError when its model manifest is missing
    # (e.g. a packaged build with no onnxruntime), which an ImportError
    # guard would let through to kill startup for everyone.
    HAS_DEPS = False
    _IMPORT_ERROR = f"{type(e).__name__}: {e}"

_engine = None


def _get_engine():
    """RapidOCR loads its ONNX models on first use (~1s) — do it lazily."""
    global _engine
    if _engine is None:
        try:
            _engine = RapidOCR()
        except Exception as e:
            raise RuntimeError(
                "OCR engine failed to start "
                f"({str(e)[:80]}) — run update_companion.bat to refresh "
                "dependencies (needs the onnxruntime package)") from e
    return _engine

RE_X = re.compile(r"X\s*[:;.,]?\s*(-?\d+)", re.IGNORECASE)
RE_Y = re.compile(r"Y\s*[:;.,]?\s*(-?\d+)", re.IGNORECASE)
RE_Z = re.compile(r"Z\s*[:;.,]?\s*(-?\d+)", re.IGNORECASE)


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {**DEFAULT_CONFIG, **cfg}
    except (OSError, ValueError):
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


_DIGIT_FIXES = str.maketrans("OolISsB", "0011558")


def _fix_digit_confusions(text: str) -> str:
    """Classic OCR letter/digit confusions (O->0, l/I->1, S->5, B->8)
    fixed inside NUMBER-LIKE tokens only — a token must contain at least
    one real digit and not sit inside a word, so zone names are never
    mangled. Rescues partially-misread coordinates ("-1O2", "3S") that
    previously dropped the whole frame."""
    text = re.sub(
        r"(?<![A-Za-z])[-+]?[0-9OolISsB.,]*[0-9][0-9OolISsB.,]*",
        lambda m: m.group(0).translate(_DIGIT_FIXES), text)
    # a token straight after a coordinate label is DEFINITELY a number —
    # fix it even when every glyph was misread ("Z: -SO" -> "Z: -50")
    return re.sub(
        r"(?i)((?:^|[^A-Za-z])[XYZ]\s*[:;.,]\s*)([-+]?[0-9OolISsB.,]+)",
        lambda m: m.group(1) + m.group(2).translate(_DIGIT_FIXES), text)


def parse_loc_text(text: str) -> Optional[dict]:
    """Extract x/y/z (+ trailing zone words) from OCR output."""
    text = _fix_digit_confusions(text)
    mx, my, mz = RE_X.search(text), RE_Y.search(text), RE_Z.search(text)
    if not (mx and my and mz):
        return None
    remainder = RE_Z.sub("", RE_Y.sub("", RE_X.sub("", text)))
    zone_words = [w for w in re.findall(r"[A-Za-z'][A-Za-z']+", remainder)
                  if w.lower() not in ("x", "y", "z")]
    return {
        "x": float(mx.group(1)),
        "y": float(my.group(1)),
        "z": float(mz.group(1)),
        "zone_text": " ".join(zone_words) or None,
    }


def _capture_and_ocr(region: dict, prev_hash: Optional[str] = None):
    """Capture the region and OCR it (worker thread — blocking CPU).
    Returns (text|None, frame_hash). When the captured pixels are identical
    to prev_hash the ONNX inference is skipped entirely — standing still or
    sitting in menus costs (almost) nothing."""
    import hashlib
    import mss as _mss
    with _mss.mss() as sct:
        shot = sct.grab({"left": region["left"], "top": region["top"],
                         "width": region["width"], "height": region["height"]})
    frame_hash = hashlib.md5(shot.bgra).hexdigest()
    if prev_hash is not None and frame_hash == prev_hash:
        return None, frame_hash
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    # contrast stretch markedly improves recognition of EQ's small
    # semi-transparent UI text (technique from DavisChappins/eql-tooltip)
    from PIL import ImageEnhance
    img = ImageEnhance.Contrast(img).enhance(1.7)
    if _OCR_V2:
        out = _get_engine()(np.array(img))
        return "\n".join(list(getattr(out, "txts", None) or [])), frame_hash
    result, _elapsed = _get_engine()(np.array(img))
    return "\n".join(r[1] for r in (result or [])), frame_hash


async def ocr_region(region: dict) -> str:
    text, _h = await asyncio.to_thread(_capture_and_ocr, region)
    return text or ""



# EQ draws the stat labels in a saturated yellow. Requiring some of it is
# how we tell "Inventory open with Equipment focused" from "window closed"
# or "a different tab" -- OCR on either of those yields confident nonsense
# rather than nothing, which is the worse failure.
def yellow_ratio(img) -> float:
    """Fraction of pixels that look like EQ's yellow label text."""
    import numpy as np
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    hit = (r > 120) & (g > 110) & (b < 110) & (abs(r - g) < 70) & ((r - b) > 60)
    return float(hit.mean())


_STAT_DIGITS = "0123456789OoLlIiSsBb"
_STAT_DIGIT_FIXES = str.maketrans("OoLlIiSsBb", "0011115588")

_STAT_KEYS = ("STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA")
_RESIST_KEYS = ("MAGIC", "FIRE", "COLD", "DISEASE", "POISON", "VOID")


def parse_stats_text(text: str) -> dict:
    """Pull character numbers out of the Inventory panel's OCR text.

    Tolerant about layout -- OCR drops colons, splits columns unpredictably
    and reflows lines -- but STRICT about what it will believe: a number
    only counts when its own label sits beside it, so a misread never lands
    silently in the wrong field. Anything unrecognised is left out.

    Digit repair is applied to the CAPTURED NUMBER only, never to the whole
    text: _fix_digit_confusions maps S->5, which turns STR into 5TR and SV
    into 5V and made every label past HP unmatchable.
    """
    if not text:
        return {}
    t = re.sub(r"[^A-Za-z0-9/ ]+", " ", text.upper())
    out: dict = {}

    def num(raw: str) -> Optional[int]:
        d = raw.translate(_STAT_DIGIT_FIXES)
        return int(d) if d.isdigit() else None

    # "HP 1948 / 1948" -- a pair is current/max; a lone number is the max
    for key, dest in (("HP", "hp"), ("MANA", "mana"), ("END", "endurance")):
        m = re.search(rf"\b{key}[^0-9OoLlIiSsBb]{{0,4}}([0-9OoLlIiSsBb]+)\s*/\s*([0-9OoLlIiSsBb]+)", t)
        if m:
            cur, mx = num(m.group(1)), num(m.group(2))
            if cur is not None and mx is not None and mx >= cur:
                out[dest], out[f"max_{dest}"] = cur, mx
                continue
        m = re.search(rf"\b{key}[^0-9OoLlIiSsBb]{{0,4}}([0-9OoLlIiSsBb]+)", t)
        if m and (v := num(m.group(1))) is not None:
            out[f"max_{dest}"] = v

    simple = (("AC", "ac"), ("ATK", "atk")) + tuple(
        (k, k.lower()) for k in _STAT_KEYS)
    for key, dest in simple:
        m = re.search(rf"\b{key}[^0-9OoLlIiSsBb]{{0,4}}([0-9OoLlIiSsBb]+)", t)
        if m and (v := num(m.group(1))) is not None:
            out[dest] = v

    for key in _RESIST_KEYS:
        m = re.search(rf"\b(?:SV\s*)?{key}[^0-9OoLlIiSsBb]{{0,4}}([0-9OoLlIiSsBb]+)", t)
        if m and (v := num(m.group(1))) is not None:
            out[f"sv_{key.lower()}"] = v
    return out



def _stats_region(cfg: dict) -> dict:
    return {"left": cfg["stats_left"], "top": cfg["stats_top"],
            "width": cfg["stats_width"], "height": cfg["stats_height"]}


def _capture_stats(cfg: dict):
    """Grab the stats region; OCR it only if the panel is actually up.

    Returns (text, yellow_ratio). text is None when the yellow gate says
    the Inventory window is closed or the Equipment tab is not focused --
    OCR on either produces confident nonsense rather than nothing, and that
    is the failure that would quietly overwrite good numbers with bad ones.

    The gate grabs its own frame and then hands off to _capture_and_ocr
    rather than doing the inference here: that function carries the tuning
    this text needs (3x upscale, contrast stretch) and the rapidocr version
    branch, and a second copy of it would drift from the first.
    """
    import mss as _mss
    region = _stats_region(cfg)
    with _mss.mss() as sct:
        shot = sct.grab(region)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    ratio = yellow_ratio(img)
    if ratio < float(cfg.get("stats_yellow_min", 0.004)):
        return None, ratio
    text, _hash = _capture_and_ocr(region)
    return (text or ""), ratio


class OcrWatcher:
    def __init__(self, tracker, ws_manager):
        self.tracker = tracker
        self.ws_manager = ws_manager
        self._running = False
        self._game_running = False
        self._game_checked = 0.0
        self.last_text: Optional[str] = None
        self._stats_at = 0.0
        self.stats: dict = {}
        self.stats_seen: Optional[str] = None
        self.stats_yellow: Optional[float] = None
        self.last_ok: Optional[str] = None
        self.error: Optional[str] = None

    def game_running(self) -> bool:
        """Is eqgame.exe alive? (cached 5s — process scans aren't free)"""
        if not HAS_DEPS:
            return False
        now = time.monotonic()
        if now - self._game_checked > 5.0:
            self._game_checked = now
            self._game_running = any(
                p.info["name"] and p.info["name"].lower() == GAME_PROCESS
                for p in psutil.process_iter(["name"]))
        return self._game_running

    def status(self) -> dict:
        cfg = load_config()
        return {
            "deps_ok": HAS_DEPS,
            "deps_error": _IMPORT_ERROR,
            "enabled": cfg["enabled"],
            "region": {k: cfg[k] for k in ("left", "top", "width", "height")},
            "game_running": self.game_running(),
            "last_text": self.last_text,
            "last_ok": self.last_ok,
            "position": self.tracker.position,
            "stats_enabled": cfg["stats_enabled"],
            "stats_region": {k: cfg["stats_" + k]
                             for k in ("left", "top", "width", "height")},
            "stats_interval": cfg["stats_interval"],
            # the gate's own reading, so calibrating is not guesswork: point
            # the box at the panel and watch this rise above the threshold
            "stats_yellow": self.stats_yellow,
            "stats_yellow_min": cfg["stats_yellow_min"],
            "stats": self.stats,
            "stats_seen": self.stats_seen,
            "error": self.error,
        }

    async def _maybe_stats(self, cfg: dict) -> None:
        """Read the Inventory stat panel on its own slow cadence.

        Separate from the position pass in every respect: a much longer
        interval (stats change when you equip, level or buff -- not while
        you walk), its own region, and a gate that skips the OCR entirely
        unless the panel is on screen. Failures are swallowed: this is a
        bonus feed and must never take the position feed down with it.
        """
        now = time.monotonic()
        if now - self._stats_at < max(2, int(cfg["stats_interval"])):
            return
        self._stats_at = now
        try:
            text, ratio = await asyncio.to_thread(_capture_stats, cfg)
        except Exception as exc:
            self.error = f"stats OCR: {exc}"
            return
        self.stats_yellow = round(ratio, 4)
        if text is None:
            return  # panel not up -- keep the last good numbers
        parsed = parse_stats_text(text)
        if not parsed:
            return
        self.stats = parsed
        self.stats_seen = time.strftime("%H:%M:%S")
        self.tracker.apply_ocr_stats(parsed)

    async def run(self) -> None:
        if not HAS_DEPS:
            logger.warning(f"OCR disabled — missing deps: {_IMPORT_ERROR}")
            return
        self._running = True
        logger.info("OCR watcher started")
        while self._running:
            cfg = load_config()
            if not cfg["enabled"] or not self.game_running():
                await asyncio.sleep(2.0)
                continue
            if cfg["stats_enabled"]:
                await self._maybe_stats(cfg)
            try:
                text, self._frame_hash = await asyncio.to_thread(
                    _capture_and_ocr, cfg, getattr(self, "_frame_hash", None))
                if text is None:
                    # frame identical to the last one: position unchanged,
                    # inference skipped — still a healthy read
                    self.last_ok = time.strftime("%H:%M:%S")
                    await asyncio.sleep(1.0)
                    continue
                self.last_text = text.strip() or None
                parsed = parse_loc_text(text) if text else None
                if parsed:
                    self.error = None
                    self.last_ok = time.strftime("%H:%M:%S")
                    # The in-game map window labels the /loc NORTH-SOUTH value
                    # as "X:" and EAST-WEST as "Y:" (classic EQ axis confusion),
                    # so swap: window-X is our y, window-Y is our x. Verified
                    # against "The Broken Stair" landmark in Befallen.
                    self.tracker.position = {
                        "x": parsed["y"], "y": parsed["x"], "z": parsed["z"],
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                    self.tracker._dirty = True
                    await self.ws_manager.broadcast(
                        {"type": "state", "data": self.tracker.snapshot()})
            except Exception as e:
                self.error = str(e)[:200]
                logger.warning(f"OCR tick failed: {self.error}")
            await asyncio.sleep(1.0)

    def stop(self) -> None:
        self._running = False
