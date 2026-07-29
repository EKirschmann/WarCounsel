"""Sectioned session overlay (always-on-top, click-through).

EQBuddy-style widget on our StoneGlass meter base: collapsible sections
- COMBAT   ranked class-colored damage bars (Damage|DPS, fight|last-5)
- SESSION  kills/deaths, XP + XP/hr, coin + coin/hr, crits/hit rate
- LOOT     recent drops + best observed drop-rate mobs
- PROGRESS level, hours-to-ding estimate, session/active clock
plus a COMPACT mode (header strip only) and adjustable opacity.

While Scroll Lock is OFF the window is CLICK-THROUGH — every click lands
in the game. Scroll Lock ON makes it interactive: drag to move, click
the title to switch Damage|DPS, the right header side to switch
fight|last-5, a section header to collapse/expand it, keys c=compact
+/-=opacity, double-click to close. Layout/position/opacity persist to
data/overlay_ui.json. Passive: reads the HTTP API only.

The overlay is a singleton (a second launch exits immediately) and
closes itself when the game exits.

Run: python -m backend.overlay   (or the Overlay button in the web header)
"""
import colorsys
import ctypes
import json
import logging
import threading
import time
import tkinter as tk
from typing import Optional
import urllib.request
from pathlib import Path

API_CHAR = "http://localhost:8000/api/character"
API_ENCS = "http://localhost:8000/api/encounters?limit=5"
from backend import overlay_prefs
from backend.paths import data_path

logger = logging.getLogger(__name__)

STATE_FILE = data_path("overlay_ui.json")

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
LWA_ALPHA = 0x00000002
VK_SCROLL = 0x91

BG = "#12151a"
HEADER_BG = "#1b1f26"
SEC_BG = "#171b21"
GOLD = "#c8aa6e"
BRIGHT = "#e7cd92"
INK = "#e6dEca"
MUTED = "#8b8577"
HEAL = "#1fb38c"
RED = "#d4574a"
CAST = "#b07cc6"      # the frontend semantic cast color
TRACK = "#1e2228"     # unfilled remainder of a timer track

W = 300
HEADER_H = 22
HERO_H = 30
SEC_H = 15
ROW_H = 17
TROW_H = 14
HINT_H = 13
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_X = 0x58
VK_C = 0x43
VK_O = 0x4F
VK_UP = 0x26
VK_DOWN = 0x28

SECTIONS = ("combat", "timers", "session", "loot", "progress")
ALERT_BANNER_SECS = 6.0

# EQ class colors (first abbrev of the trio decides the bar color)
CLASS_COLORS = {
    "WAR": "#b5654a", "CLR": "#e8e0c0", "PAL": "#d8a8c8", "RNG": "#5fb55f",
    "SHD": "#7a5fb5", "DRU": "#c89a3e", "MNK": "#5fc4b0", "BRD": "#c45fb0",
    "ROG": "#c8c05f", "SHM": "#5f9fc4", "NEC": "#8fd45f", "WIZ": "#5f7fd4",
    "MAG": "#d47f5f", "ENC": "#b0a0e0", "BST": "#a08060", "BER": "#d45f5f",
}


def _class_color(classes, name):
    # Synthetic rows are parenthesised -- "(filtered - N sources)" is meta,
    # not a participant, so it must not be handed a class colour that makes
    # it read like one more person in the fight.
    if name and name.startswith("("):
        return MUTED
    ab = (classes or "").split("/")[0].strip().upper()
    if ab in CLASS_COLORS:
        return CLASS_COLORS[ab]
    hue = (hash(name or "?") % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.40, 0.72)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _fmt(v):
    v = v or 0
    return f"{v / 1000:.1f}k" if v >= 10000 else f"{v:,.0f}"


def _fmt_coin(copper):
    """3267 copper -> '3p2g' (two largest denominations)."""
    c = int(copper or 0)
    parts = [(c // 1000, "p"), ((c % 1000) // 100, "g"),
             ((c % 100) // 10, "s"), (c % 10, "c")]
    out = [f"{n}{u}" for n, u in parts if n > 0][:2]
    return "".join(out) or "0c"


def _fight_rows(enc):
    """Contributor list for one encounter view; solo fights synthesize You."""
    allies = list(enc.get("allies") or [])
    if not allies and enc.get("total_damage"):
        allies = [{"name": "You", "damage": enc.get("total_damage", 0),
                   "dps": enc.get("dps", 0), "classes": None}]
    return allies


def compute_rows(snap, history, segment):
    """[(name, classes, damage, dps)] ranked by damage, plus fight label."""
    if segment == "current":
        enc = (snap or {}).get("encounter")
        if not enc:
            return [], "no encounter"
        rows = [(a.get("name") or "?", a.get("classes"),
                 a.get("damage", 0), a.get("dps", 0))
                for a in _fight_rows(enc)]
        # Damage the group filter excluded, as ONE row. Shown rather than
        # dropped: a silently missing contributor is indistinguishable from
        # a quiet fight, and the filter can be wrong -- an unmapped
        # groupmate's pet has a generated name that proves nothing.
        ua = enc.get("unattributed")
        if ua and ua.get("damage"):
            n = ua.get("sources") or 0
            rows.append((f"(filtered · {n} source{'' if n == 1 else 's'})",
                         None, ua["damage"], 0))
        foes = enc.get("foes") or []
        label = (f"{len(foes)} foes" if len(foes) > 1
                 else (enc.get("target") or "fight"))
        label = f"{label} · {enc.get('duration', 0):g}s"
    else:
        dmg, secs, cls = {}, {}, {}
        for enc in history or []:
            dur = enc.get("duration") or 0
            for a in _fight_rows(enc):
                n = a.get("name") or "?"
                dmg[n] = dmg.get(n, 0) + (a.get("damage") or 0)
                secs[n] = secs.get(n, 0) + dur
                cls.setdefault(n, a.get("classes"))
        rows = [(n, cls.get(n), d, round(d / secs[n], 1) if secs.get(n) else 0)
                for n, d in dmg.items()]
        label = f"last {len(history or [])} fights"
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows[:8], label


def timer_rows(snap, prefs=None):
    """TIMERS: (name, clock, color, fraction remaining, urgent).

    `kind` doubles as the visibility switch -- "cooldowns yes, every buff
    I refreshed no" is the distinction that actually matters here, so the
    toggles are the kinds rather than columns of a row.
    """
    rows = []
    for t in ((snap or {}).get("timers") or []):
        kind = t.get("kind")
        field = ("raid" if kind == "raid" else
                 "cooldown" if kind == "cooldown" else "spell")
        if prefs is not None and not overlay_prefs.on(prefs, "timers", field):
            continue
        rem = t.get("remaining", 0)
        mins, secs = divmod(max(0, int(rem)), 60)
        clock = f"{mins}:{secs:02d}" if mins else f"{secs}s"
        total = t.get("seconds") or 0
        frac = max(0.0, min(1.0, rem / total)) if total > 0 else 0.0
        color = (GOLD if kind == "raid" else
                 HEAL if kind == "cooldown" else CAST)
        rows.append((t.get("name", "?")[:30], clock, color, frac, rem <= 5))
        if len(rows) >= 6:
            break
    return rows

def session_rows(snap, prefs=None):
    """SESSION section: [(left, right, color)]."""
    s = (snap or {}).get("session") or {}
    r = (snap or {}).get("rates") or {}

    def act(key):
        return (r.get(key) or {}).get("active_hr", 0)

    def want(field):
        return prefs is None or overlay_prefs.on(prefs, "session", field)

    rows = []
    if want("kills"):
        rows.append((f"kills {s.get('kills', 0)} · deaths {s.get('deaths', 0)}",
                     f"{act('kills'):g}/hr", INK))
    if want("xp"):
        rows.append((f"xp +{s.get('xp_percent', 0):g}%",
                     f"{act('xp'):g}%/hr", INK))
    if want("coin"):
        rows.append((f"coin {_fmt_coin(s.get('coin_copper', 0))}",
                     f"{_fmt_coin(act('coin'))}/hr", INK))
    if want("crits"):
        rows.append((f"crits {s.get('crits', 0)} · hit {s.get('hit_rate', 0):g}%",
                     f"rune {_fmt(s.get('rune_absorbed', 0))}", MUTED))
    if want("motes") and s.get("motes"):
        rows.append((f"motes {sum((s.get('motes') or {}).values())} · "
                     + " ".join(f"{k[:5]} {v}" for k, v in
                                sorted((s.get('motes') or {}).items())[:3]),
                     "", MUTED))
    return rows

def loot_rows(snap, prefs=None):
    """LOOT section: recent drops + best observed drop-rate mobs."""
    s = (snap or {}).get("session") or {}

    def want(field):
        return prefs is None or overlay_prefs.on(prefs, "loot", field)

    rows = []
    if want("recent"):
        rows += [((" " + item)[:42], "", INK)
                 for item in (s.get("loots") or [])[:4]]
    if want("rates"):
        best = []
        for m in (snap or {}).get("mob_stats") or []:
            kills, drops = m.get("kills") or 0, m.get("loot_drops") or 0
            if kills > 0 and drops > 0:
                best.append((m.get("name") or "?", round(100 * drops / kills)))
        best.sort(key=lambda x: -x[1])
        for name, pct in best[:2]:
            rows.append((name[:28], f"{pct}% drops", MUTED))
    return rows or [("no loot yet", "", MUTED)]

def progress_rows(snap, prefs=None):
    """PROGRESS section: level, ding estimate, session clocks."""
    r = (snap or {}).get("rates") or {}
    lvl = (snap or {}).get("level")
    htl = r.get("hours_to_level")
    right = ""
    if htl:
        right = f"ding in ~{htl:g}h"
        if not r.get("hours_to_level_exact"):
            right += " (max)"
    rows = []
    if prefs is None or overlay_prefs.on(prefs, "progress", "ding"):
        rows.append((f"level {lvl if lvl is not None else '?'}", right, INK))
    if prefs is None or overlay_prefs.on(prefs, "progress", "clocks"):
        rows.append((f"session {r.get('elapsed_hours', 0):g}h · "
                     f"active {r.get('active_hours', 0):g}h", "", MUTED))
    return rows

def section_summary(key, snap, history, segment):
    """One-liner shown on a COLLAPSED section header."""
    if key == "combat":
        return f"{(snap or {}).get('dps', 0):g} dps"
    if key == "session":
        s = (snap or {}).get("session") or {}
        r = (snap or {}).get("rates") or {}
        return (f"{s.get('kills', 0)}k · "
                f"{(r.get('xp') or {}).get('active_hr', 0):g}%/hr")
    if key == "timers":
        timers = (snap or {}).get("timers") or []
        if not timers:
            return "—"
        t = timers[0]
        return f"{t.get('name', '?')[:16]} {t.get('remaining', 0)}s"
    if key == "loot":
        loots = ((snap or {}).get("session") or {}).get("loots") or []
        return (loots[0][:22] if loots else "—")
    if key == "progress":
        r = (snap or {}).get("rates") or {}
        htl = r.get("hours_to_level")
        return f"~{htl:g}h to ding" if htl else "—"
    return ""

class OverlayMeter:
    def __init__(self) -> None:
        self.snap = None
        self.history = []
        self.prefs = overlay_prefs.load()
        st = self._load_state()
        self.mode = st.get("mode", "damage")          # damage | dps
        self.segment = st.get("segment", "current")   # current | last5
        self.compact = bool(st.get("compact", False))
        self.alpha = min(1.0, max(0.35, float(st.get("alpha", 0.90))))
        self.collapsed = {k: bool(st.get("collapsed", {}).get(k, False))
                          for k in SECTIONS}
        self.pinned = {k: bool(st.get("pinned", {}).get(k, False))
                       for k in SECTIONS}
        self.force_interactive = False  # Ctrl+Alt+X toggle (not persisted)
        self._hot_prev: dict = {}
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.alpha)
        self.root.configure(bg=BG)
        x, y = int(st.get("x", 60)), int(st.get("y", 140))
        self.root.geometry(f"{W}x{HEADER_H + ROW_H + HINT_H}+{x}+{y}")
        self._drag = None
        self._moved = False
        self._transparent = None
        self._sec_zones = []  # [(y0, y1, key)] rebuilt every render
        self._last_alert_id = 0
        self._alert_until = 0.0
        self._alert_text = ""

        self.canvas = tk.Canvas(self.root, width=W, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", lambda _e: self.root.destroy())
        self.root.bind("<KeyPress>", self._key)

        threading.Thread(target=self._poll_char, daemon=True).start()
        threading.Thread(target=self._poll_encounters, daemon=True).start()
        threading.Thread(target=self._watch_game, daemon=True).start()
        self.root.after(300, self._render)

    # ---- persisted layout state -------------------------------------------
    def _load_state(self) -> dict:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps({
                "x": self.root.winfo_x(), "y": self.root.winfo_y(),
                "alpha": round(self.alpha, 2), "compact": self.compact,
                "collapsed": self.collapsed, "pinned": self.pinned,
                "mode": self.mode, "segment": self.segment,
            }), encoding="utf-8")
        except Exception:
            pass

    # ---- interaction (only reachable while Scroll Lock is ON) -------------
    def _press(self, e) -> None:
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())
        self._moved = False
        try:
            self.root.focus_force()  # so c / +/- keys land here
        except Exception:
            pass

    def _motion(self, e) -> None:
        if self._drag:
            self._moved = True
            self.root.geometry(
                f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _release(self, e) -> None:
        if not self._moved:
            if e.y <= HEADER_H:
                if e.x < W // 2:
                    self.mode = "dps" if self.mode == "damage" else "damage"
                else:
                    self.segment = ("last5" if self.segment == "current"
                                    else "current")
            else:
                for y0, y1, key in self._sec_zones:
                    if y0 <= e.y <= y1:
                        if e.x >= W - 18:   # star zone: pin to compact strip
                            self.pinned[key] = not self.pinned[key]
                        else:
                            self.collapsed[key] = not self.collapsed[key]
                        break
        self._drag = None
        self._save_state()

    # ---- named actions ---------------------------------------------------
    # Keyboard, global hotkeys and the tray menu all route through these, so
    # the three never drift apart.

    def act_compact(self) -> None:
        self.compact = not self.compact
        self._save_state()

    def act_opacity_up(self) -> None:
        self.alpha = min(1.0, self.alpha + 0.05)
        self.root.attributes("-alpha", self.alpha)
        self._save_state()

    def act_opacity_down(self) -> None:
        self.alpha = max(0.35, self.alpha - 0.05)
        self.root.attributes("-alpha", self.alpha)
        self._save_state()

    def act_hide(self) -> None:
        self.root.withdraw()

    def act_show(self) -> None:
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def act_toggle_visible(self) -> None:
        if self.is_hidden():
            self.act_show()
        else:
            self.act_hide()

    def is_hidden(self) -> bool:
        try:
            return self.root.state() == "withdrawn"
        except Exception:
            return False

    def act_reset_position(self) -> None:
        """Rescue for an overlay dragged off-screen — with no title bar and
        click-through on, there is otherwise no way to grab it back."""
        self.x, self.y = 120, 120
        self.root.geometry(f"+{self.x}+{self.y}")
        self.act_show()
        self._save_state()

    def act_quit(self) -> None:
        self.root.destroy()

    def _key(self, e) -> None:
        ch = (e.char or "").lower()
        if ch == "c":
            self.act_compact()
        elif ch in ("+", "="):
            self.act_opacity_up()
        elif ch in ("-", "_"):
            self.act_opacity_down()

    def _set_click_through(self, enable: bool) -> None:
        if enable == self._transparent:
            return
        self._transparent = enable
        try:
            hwnd = (ctypes.windll.user32.GetParent(self.root.winfo_id())
                    or self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED
            if enable:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            # Tk already made this window layered when it applied -alpha.
            # Rewriting the ex-style touches the layering style bit, and a
            # layered window whose attributes have been dropped paints BLACK
            # -- the whole widget, with the render loop running normally, so
            # nothing in the logs. Re-assert the alpha every time the style
            # changes; it is one call and it costs nothing when unnecessary.
            ctypes.windll.user32.SetLayeredWindowAttributes(
                hwnd, 0, int(max(0.0, min(1.0, self.alpha)) * 255), LWA_ALPHA)
        except Exception:
            pass

    # ---- data --------------------------------------------------------------
    def _poll_char(self) -> None:
        while True:
            try:
                with urllib.request.urlopen(API_CHAR, timeout=2) as r:
                    self.snap = json.loads(r.read().decode("utf-8"))
            except Exception:
                self.snap = None
            time.sleep(1.0)

    def _poll_encounters(self) -> None:
        while True:
            try:
                with urllib.request.urlopen(API_ENCS, timeout=3) as r:
                    d = json.loads(r.read().decode("utf-8"))
                self.history = d.get("encounters", d) if isinstance(d, dict) else d
            except Exception:
                pass
            time.sleep(5.0)

    def _watch_game(self) -> None:
        """Close the overlay when eqgame.exe exits (after it has been seen
        running at least once — launching the overlay first is fine)."""
        try:
            import psutil
        except ImportError:
            return
        seen = False
        while True:
            try:
                running = any((p.info.get("name") or "").lower() == "eqgame.exe"
                              for p in psutil.process_iter(["name"]))
            except Exception:
                running = seen  # scan hiccup: don't close on bad data
            if running:
                seen = True
            elif seen:
                self.root.after(0, self.root.destroy)
                return
            time.sleep(5)

    # ---- paint ---------------------------------------------------------
    def _sec_header(self, c, y, key, title, extra="") -> int:
        arrow = "v" if not self.collapsed[key] else ">"
        c.create_rectangle(0, y, W, y + SEC_H, fill=SEC_BG, width=0)
        c.create_text(6, y + SEC_H // 2, anchor="w", fill=GOLD,
                      font=("Consolas", 7, "bold"),
                      text=f"{arrow} {title}")
        summary = extra if not self.collapsed[key] else section_summary(
            key, self.snap, self.history, self.segment)
        if summary:
            c.create_text(W - 18, y + SEC_H // 2, anchor="e", fill=MUTED,
                          font=("Consolas", 7), text=summary[:32])
        c.create_text(W - 6, y + SEC_H // 2, anchor="e",
                      fill=GOLD if self.pinned[key] else "#3a3f47",
                      font=("Consolas", 8), text="*")
        self._sec_zones.append((y, y + SEC_H, key))
        return y + SEC_H

    def _hero_band(self, c, y) -> int:
        """Three big numbers: FIGHT dps | SESSION dps | BEST dps."""
        s = (self.snap or {}).get("session") or {}
        r = (self.snap or {}).get("rates") or {}
        active_h = r.get("active_hours") or 0
        sess_dps = (s.get("damage_dealt", 0) / (active_h * 3600)
                    if active_h > 0 else 0)
        vals = ((f"{(self.snap or {}).get('dps', 0):g}", "FIGHT"),
                (f"{sess_dps:,.0f}", "SESSION"),
                (f"{(self.snap or {}).get('session_max_dps', 0):g}", "BEST"))
        c.create_rectangle(0, y, W, y + HERO_H, fill=BG, width=0)
        col_w = W // 3
        for i, (val, label) in enumerate(vals):
            cx = i * col_w + col_w // 2
            c.create_text(cx, y + 11, anchor="center",
                          fill=BRIGHT if i == 0 else INK,
                          font=("Consolas", 12, "bold"), text=val)
            c.create_text(cx, y + 24, anchor="center", fill=MUTED,
                          font=("Consolas", 6), text=label)
        return y + HERO_H

    def _text_rows(self, c, y, rows) -> int:
        for left, right, color in rows:
            c.create_text(8, y + TROW_H // 2, anchor="w", fill=color,
                          font=("Consolas", 8), text=left)
            if right:
                c.create_text(W - 6, y + TROW_H // 2, anchor="e", fill=color,
                              font=("Consolas", 8), text=right)
            y += TROW_H
        return y

    def _timer_tracks(self, c, y, rows) -> int:
        """Timers as depleting tracks rather than a list of numbers.

        This is the one place in the overlay where a sub-second read
        changes what you do next, so it is the one place that gets a bar
        outside the damage meter. The fill drains on its own as the clock
        runs, which means the motion carries the information -- a timer
        about to expire looks different across the room, and nothing has
        to animate for decoration.
        """
        if not rows:
            c.create_text(8, y + TROW_H // 2, anchor="w", fill=MUTED,
                          font=("Consolas", 8), text="no active timers")
            return y + TROW_H
        for name, clock, color, frac, urgent in rows:
            # An expiring timer has almost no fill left, so it cannot rely
            # on the bar to carry the warning -- the whole row washes red
            # instead, and the text stays bright enough to read on it.
            base = RED if urgent else TRACK
            c.create_rectangle(0, y + 1, W, y + TROW_H - 1, fill=base,
                               width=0, stipple="gray25" if urgent else "")
            if frac > 0:
                c.create_rectangle(0, y + 1, max(2, int(W * frac)),
                                   y + TROW_H - 1,
                                   fill=RED if urgent else color, width=0,
                                   stipple="" if urgent else "gray50")
            fg = BRIGHT if urgent else INK
            c.create_text(8, y + TROW_H // 2, anchor="w", fill=fg,
                          font=("Consolas", 8, "bold" if urgent else "normal"),
                          text=name)
            c.create_text(W - 6, y + TROW_H // 2, anchor="e", fill=fg,
                          font=("Consolas", 8, "bold" if urgent else "normal"),
                          text=clock)
            y += TROW_H
        return y
    # Ctrl+Alt+<key>, polled rather than RegisterHotKey'd: the overlay is
    # click-through and usually unfocused, so it receives no key events, and
    # polling is what already worked for Ctrl+Alt+X. Ctrl+Alt is used because
    # EQ binds bare and shifted keys but leaves that combination alone.
    HOTKEYS = (
        (VK_X, "interactive"),
        (VK_O, "toggle_visible"),
        (VK_C, "compact"),
        (VK_UP, "opacity_up"),
        (VK_DOWN, "opacity_down"),
    )

    def _poll_hotkeys(self) -> None:
        down = ctypes.windll.user32.GetAsyncKeyState
        mods = bool(down(VK_CONTROL) & 0x8000 and down(VK_MENU) & 0x8000)
        for vk, action in self.HOTKEYS:
            pressed = mods and bool(down(vk) & 0x8000)
            if pressed and not self._hot_prev.get(vk):
                if action == "interactive":
                    self.force_interactive = not self.force_interactive
                elif action == "toggle_visible":
                    self.act_toggle_visible()
                elif action == "compact":
                    self.act_compact()
                elif action == "opacity_up":
                    self.act_opacity_up()
                elif action == "opacity_down":
                    self.act_opacity_down()
            self._hot_prev[vk] = pressed

    def _log_warning(self) -> Optional[str]:
        """Why the numbers are not moving, when they should be.

        Silence is normal while idling, so this only speaks up once the gap
        is long enough to be odd, and it names the likeliest cause: a newer
        log belonging to a different character, which is what happens the
        moment someone rolls a new one.
        """
        snap = self.snap or {}
        other = snap.get("newer_log")
        if other:
            return f"! newer log for {other} — switch character"
        if snap.get("log_seen_growth") is False:
            return "! no log activity yet — is /log on?"
        stale = snap.get("log_stale_s")
        if isinstance(stale, (int, float)) and stale > 600:
            return f"! log quiet {int(stale // 60)}m — is /log on?"
        return None

    def _render(self) -> None:
        self._poll_hotkeys()
        self.prefs = overlay_prefs.load()
        interactive = (bool(ctypes.windll.user32.GetKeyState(VK_SCROLL) & 1)
                       or self.force_interactive)
        self._set_click_through(not interactive)
        c = self.canvas
        c.delete("all")
        self._sec_zones = []

        rows, label = compute_rows(self.snap, self.history, self.segment)
        s = (self.snap or {}).get("session") or {}
        r = (self.snap or {}).get("rates") or {}
        my_dps = (self.snap or {}).get("dps", 0)
        live = self.snap and self.snap.get("in_combat")

        # ---- header (always visible) ----
        y = HEADER_H
        c.create_rectangle(0, 0, W, HEADER_H, fill=HEADER_BG, width=0)
        if self.compact:
            pinned = [k for k in SECTIONS if self.pinned.get(k)
                      and overlay_prefs.on(self.prefs, k)]
            if pinned:
                header = " | ".join(
                    section_summary(k, self.snap, self.history, self.segment)
                    for k in pinned)
            else:
                # Built from what is switched on, so the one-line strip
                # never advertises a number the player chose to hide.
                bits = []
                if overlay_prefs.on(self.prefs, "combat"):
                    bits.append(f"{my_dps:g}dps")
                if overlay_prefs.on(self.prefs, "session", "kills"):
                    bits.append(f"{s.get('kills', 0)}k")
                if overlay_prefs.on(self.prefs, "session", "xp"):
                    xp_act = (r.get("xp") or {}).get("active_hr", 0)
                    bits.append(f"{xp_act:g}%/hr")
                if overlay_prefs.on(self.prefs, "session", "coin"):
                    coin_act = (r.get("coin") or {}).get("active_hr", 0)
                    bits.append(f"{_fmt_coin(coin_act)}/hr")
                header = " · ".join(bits) or "WarCounsel"
            c.create_text(6, HEADER_H // 2, anchor="w", fill=GOLD,
                          font=("Consolas", 9, "bold"),
                          text=header[:46])
        else:
            mode_label = "Damage" if self.mode == "damage" else "DPS"
            c.create_text(8, HEADER_H // 2, anchor="w", fill=GOLD,
                          font=("Consolas", 9, "bold"),
                          text=f"{mode_label} · {label}"[:34])
            c.create_text(W - 8, HEADER_H // 2, anchor="e",
                          fill=HEAL if live else MUTED,
                          font=("Consolas", 9, "bold"), text=f"{my_dps:g}")

        # tracked-rule alert banner (+ chime once per alert)
        alerts = (self.snap or {}).get("alerts") or []
        if alerts:
            latest = alerts[-1]
            if latest.get("id", 0) > self._last_alert_id:
                self._last_alert_id = latest.get("id", 0)
                self._alert_until = time.time() + ALERT_BANNER_SECS
                self._alert_text = f"{latest.get('kind', '')}: {latest.get('text', '')}"
                if latest.get("sound"):
                    try:
                        import winsound
                        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    except Exception:
                        pass
        if time.time() < self._alert_until:
            c.create_rectangle(0, y, W, y + TROW_H, fill=GOLD, width=0)
            c.create_text(6, y + TROW_H // 2, anchor="w", fill=BG,
                          font=("Consolas", 8, "bold"),
                          text=self._alert_text[:44])
            y += TROW_H

        if not self.snap:
            c.create_text(8, y + TROW_H // 2, anchor="w", fill=RED,
                          font=("Consolas", 9),
                          text="companion offline (:8000)")
            y += TROW_H
        elif self._log_warning():
            # A stalled tailer looks exactly like a quiet night: the numbers
            # simply stop moving, with nothing on screen to say why. This is
            # the difference between "nothing is happening" and "nothing is
            # being READ" -- most often a new character writing to a new log
            # while we still watch the old one.
            c.create_rectangle(0, y, W, y + TROW_H, fill=RED, width=0,
                               stipple="gray25")
            c.create_text(6, y + TROW_H // 2, anchor="w", fill=BRIGHT,
                          font=("Consolas", 8, "bold"),
                          text=self._log_warning()[:46])
            y += TROW_H
        elif not self.compact:
            prefs = self.prefs
            shown = [k for k in SECTIONS if overlay_prefs.on(prefs, k)]
            # A lone section needs no header: there is nothing to tell it
            # apart from, and the 15px it costs buys another row of the one
            # thing the player actually kept.
            solo = len(shown) == 1

            if not shown:
                c.create_text(8, y + TROW_H // 2, anchor="w", fill=MUTED,
                              font=("Consolas", 8),
                              text="nothing to show — pick sections in Settings")
                y += TROW_H

            if "combat" in shown:
                if overlay_prefs.on(prefs, "combat", "hero"):
                    y = self._hero_band(c, y)
                if not solo:
                    y = self._sec_header(c, y, "combat", "COMBAT")
                open_bars = ((solo or not self.collapsed["combat"])
                             and overlay_prefs.on(prefs, "combat", "bars"))
                if open_bars:
                    if not rows:
                        c.create_text(8, y + TROW_H // 2, anchor="w",
                                      fill=MUTED, font=("Consolas", 9),
                                      text="waiting for combat…")
                        y += TROW_H
                    total = sum(x[2] for x in rows) or 1
                    top = rows[0][2] if rows else 1
                    want_share = overlay_prefs.on(prefs, "combat", "share")
                    for i, (name, classes, dmg, dps) in enumerate(rows):
                        y0 = y + i * ROW_H
                        frac = (dmg / top) if top else 0
                        color = _class_color(classes, name)
                        c.create_rectangle(0, y0 + 1, max(2, int(W * frac)),
                                           y0 + ROW_H - 1, fill=color,
                                           width=0, stipple="gray50")
                        val = _fmt(dmg) if self.mode == "damage" else f"{dps:g}"
                        if want_share:
                            val = f"{val} ({100 * dmg / total:.0f}%)"
                        fg = BRIGHT if name == "You" else INK
                        c.create_text(6, y0 + ROW_H // 2, anchor="w", fill=fg,
                                      font=("Consolas", 9),
                                      text=f"{i + 1}. {name[:15]}")
                        c.create_text(W - 6, y0 + ROW_H // 2, anchor="e",
                                      fill=fg, font=("Consolas", 9), text=val)
                    y += len(rows) * ROW_H

            for key, title in (("timers", "TIMERS"), ("session", "SESSION"),
                               ("loot", "LOOT"), ("progress", "PROGRESS")):
                if key not in shown:
                    continue
                if not solo:
                    y = self._sec_header(c, y, key, title)
                if not solo and self.collapsed[key]:
                    continue
                if key == "timers":
                    y = self._timer_tracks(c, y, timer_rows(self.snap, prefs))
                elif key == "session":
                    y = self._text_rows(c, y, session_rows(self.snap, prefs))
                elif key == "loot":
                    y = self._text_rows(c, y, loot_rows(self.snap, prefs))
                else:
                    y = self._text_rows(c, y, progress_rows(self.snap, prefs))
        hint_y = y + HINT_H // 2
        if interactive:
            c.create_text(6, hint_y, anchor="w", fill=GOLD,
                          font=("Consolas", 7),
                          text="MOVABLE · section=fold · *=pin · c=compact "
                               "· ±=opacity · Ctrl+Alt+X=lock · dbl-click closes")
        else:
            c.create_text(6, hint_y, anchor="w", fill=MUTED,
                          font=("Consolas", 7),
                          text="click-through · Scroll Lock ON to interact")
        height = y + HINT_H
        self.root.geometry(f"{W}x{height}")
        c.configure(height=height)
        self.root.after(500, self._render)


def _already_running() -> bool:
    """Named-mutex singleton: survives backend restarts losing the process
    handle (which used to allow a second overlay on the next toggle)."""
    ctypes.windll.kernel32.CreateMutexW(None, False, "WarCounselOverlayMutex")
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def main() -> None:
    """Entrypoint for both `python -m backend.overlay` and the packaged
    executable's --overlay flag. The named mutex keeps it a singleton
    either way."""
    if _already_running():
        raise SystemExit(0)
    meter = OverlayMeter()
    tray = None
    try:
        from backend.overlay_tray import OverlayTray
        tray = OverlayTray(meter.root, {
            "show": meter.act_show,
            "hide": meter.act_hide,
            "compact": meter.act_compact,
            "opacity_up": meter.act_opacity_up,
            "opacity_down": meter.act_opacity_down,
            "reset_position": meter.act_reset_position,
            "quit": meter.act_quit,
        }, is_hidden=meter.is_hidden)
        tray.start()
    except Exception:
        logger.warning("Tray unavailable", exc_info=True)
    try:
        meter.root.mainloop()
    finally:
        if tray is not None:
            tray.stop()


if __name__ == "__main__":
    main()