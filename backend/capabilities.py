"""Trio capability facts, vendored from eqltools.com's picker data.

The advisor reasons spell by spell and has no concept of a CAPABILITY. It
cannot currently know that a PAL/ENC/MNK has no snare and no SoW -- which
rules out kiting and makes travel slow -- nor that slow arrives at level 9
and is worth planning around. One compact line replaces inference the model
does badly, and gives the deterministic gates something real to check.

Refreshed by scripts/refresh_picker.py, which is where the trimming rules
and their reasoning live. Data from eqltools.com; their robots.txt asks that
anyone building on it cite eqltools.com, so the attribution ships in the
snapshot and in every line this module emits.

TWO RULES, both learned the hard way elsewhere in this app:

1. Membership in `byClass` IS the capability. `level` is optional detail --
   `track` carries none for any of BRD/DRU/RNG. Reading a missing level as
   "does not have it" would tell a Ranger they cannot track.
2. No snapshot means UNKNOWN, never "lacks everything". Absence of evidence
   is not evidence of absence -- the same rule that governs gear counsel
   (see the stranded-stone gate) applies to a table that failed to load.
"""
import json
import logging
from typing import Optional

from backend.log_system.parser import CLASS_ABBREV
from backend.paths import bundle_path

logger = logging.getLogger(__name__)

SNAPSHOT = bundle_path("backend", "picker_capabilities.json")
ATTRIBUTION = "capabilities: eqltools.com"

# "Paladin" -> "PAL", reusing the map /who lines are already parsed with
# rather than writing a second one that can disagree with it.
_CODE = {full.lower(): code for code, full in CLASS_ABBREV.items()}

_cache: dict = {"mtime": None, "data": None}


def load() -> Optional[dict]:
    """The snapshot, or None when it is absent or unreadable."""
    try:
        mtime = SNAPSHOT.stat().st_mtime
    except OSError:
        return None
    if _cache["mtime"] != mtime:
        try:
            _cache["data"] = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
            _cache["mtime"] = mtime
        except Exception:
            logger.exception("picker_capabilities.json load failed")
            return None
    return _cache["data"]


def class_code(name: str) -> Optional[str]:
    """'Shadow Knight' -> 'SHD'. Already-abbreviated input passes through."""
    if not name:
        return None
    s = str(name).strip()
    if s.upper() in CLASS_ABBREV:
        return s.upper()
    return _CODE.get(s.lower())


def trio_capabilities(classes: list) -> Optional[dict]:
    """What this trio HAS and LACKS. None when nothing can be said.

    has:   [{name, level, classes, best, target, note}] -- level/best may be
           None where the source records none; `level` None means "has it,
           level unrecorded", never "does not have it".
    lacks: capability names no class in the trio appears under.
    """
    snap = load()
    if not snap:
        return None
    codes = [c for c in (class_code(x) for x in (classes or [])) if c]
    if not codes:
        return None

    has, lacks = [], []
    for name, cap in sorted((snap.get("capabilities") or {}).items()):
        by = cap.get("byClass") or {}
        mine = {c: by[c] for c in codes if c in by}
        if not mine:
            lacks.append(name)
            continue
        levels = [e["level"] for e in mine.values() if e.get("level") is not None]
        best_lv = min(levels) if levels else None
        # who gets it first; everyone who has it when no level is recorded
        owners = sorted(c for c, e in mine.items()
                        if best_lv is None or e.get("level") == best_lv)
        magnitudes = [e["best"] for e in mine.values() if e.get("best") is not None]
        has.append({"name": name, "level": best_lv, "classes": owners,
                    "best": max(magnitudes) if magnitudes else None,
                    "target": next((e["target"] for e in mine.values()
                                    if e.get("target")), None),
                    "note": cap.get("note"), "seal": cap.get("seal")})
    return {"has": has, "lacks": lacks,
            "attribution": ATTRIBUTION,
            "spell_patch": (snap.get("meta") or {}).get("spellPatch")}


def trio_capability_line(classes: list) -> Optional[str]:
    """One prompt-sized line. None when the snapshot is unavailable.

    Levels are what the advisor plans around, so they lead; a capability
    with no recorded level still appears, without an invented one.
    """
    caps = trio_capabilities(classes)
    if not caps:
        return None
    def fmt(c):
        return c["name"] + (f" L{c['level']}" if c["level"] is not None else "")
    has = " · ".join(fmt(c) for c in sorted(
        caps["has"], key=lambda c: (c["level"] is None, c["level"] or 0)))
    out = "HAS %s" % (has or "nothing recorded")
    if caps["lacks"]:
        out += "\nLACKS %s" % " · ".join(caps["lacks"])
    return out + "\n(%s)" % ATTRIBUTION
