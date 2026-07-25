"""What the overlay shows -- chosen in the web Settings panel.

The overlay is a glance surface, not a dashboard. The webapp already covers
session analytics in depth, so a player who wants nothing but a damage meter
and their timers should be able to cut the rest; what is left then gets the
whole of a 300px column instead of sharing it.

Choices live per SECTION and per FIELD within a section, because "I want the
session line but not the coin" is a real preference and a section-level
switch cannot express it.

Read straight off disk by backend/overlay.py -- mtime-cached, the same shape
as alerts.load_rules() -- rather than fetched over HTTP. The overlay is a
separate process on the same machine that repaints twice a second, so a
round-trip per frame would be pure waste.

Defaults are ALL ON: an absent or unreadable file behaves exactly like the
overlay did before this file existed.
"""
import json
import logging
import os

from backend.paths import data_path

logger = logging.getLogger(__name__)

_PATH = data_path("overlay_prefs.json")

# Allow-list, and the single source of truth for the Settings UI -- it renders
# from this over the API rather than hardcoding a parallel list that could
# drift. Field keys map 1:1 onto rows the overlay already builds.
SECTIONS = {
    "combat": {
        "label": "Combat",
        "hint": "who is doing the damage",
        "fields": {
            "hero": {"label": "Headline numbers",
                     "hint": "fight / session / best DPS"},
            "bars": {"label": "Contributor bars",
                     "hint": "ranked, colored by class"},
            "share": {"label": "Damage share",
                      "hint": "each row's % of the fight"},
        },
    },
    "timers": {
        "label": "Timers",
        "hint": "what is about to run out",
        "fields": {
            "spell": {"label": "Spell durations", "hint": "your own casts"},
            "cooldown": {"label": "Ability cooldowns",
                         "hint": "Lay on Hands, Harm Touch, Quick Buff"},
            "raid": {"label": "Raid mechanics", "hint": "boss shout timers"},
        },
    },
    "session": {
        "label": "Session",
        "hint": "how the night is going",
        "fields": {
            "kills": {"label": "Kills and deaths", "hint": "with per-hour rate"},
            "xp": {"label": "Experience", "hint": "percent gained and %/hr"},
            "coin": {"label": "Coin", "hint": "taken and per hour"},
            "crits": {"label": "Crits, hit rate, rune", "hint": ""},
            "motes": {"label": "Motes", "hint": "counted by tier"},
        },
    },
    "loot": {
        "label": "Loot",
        "hint": "what dropped",
        "fields": {
            "recent": {"label": "Recent drops", "hint": "last four items"},
            "rates": {"label": "Drop rates", "hint": "best mobs seen so far"},
        },
    },
    "progress": {
        "label": "Progress",
        "hint": "how far to the next level",
        "fields": {
            "ding": {"label": "Level and ding estimate", "hint": ""},
            "clocks": {"label": "Session clocks", "hint": "elapsed and active"},
        },
    },
}

# Named starting points. Most players want one of these, not twenty clicks --
# "Custom" is what the UI shows once someone edits away from a preset.
PRESETS = {
    "everything": {
        "label": "Everything",
        "hint": "every section, every field",
        "sections": list(SECTIONS),
    },
    "combat": {
        "label": "Combat focus",
        "hint": "the meter and your timers, nothing else",
        "sections": ["combat", "timers"],
    },
    "meter": {
        "label": "Meter only",
        "hint": "damage bars alone, no headline numbers",
        "sections": ["combat"],
        "off_fields": {"combat": ["hero"]},
    },
}

_cache = {"mtime": None, "prefs": None}


def defaults() -> dict:
    return {
        "sections": {k: True for k in SECTIONS},
        "fields": {k: {f: True for f in v["fields"]}
                   for k, v in SECTIONS.items()},
    }


def _coerce(raw, base: dict | None = None) -> dict:
    """Fill a partial/garbage payload out to the full shape.

    `base` is what an OMITTED key falls back to. Reading a file uses the
    defaults (a missing section is one this version added). Saving passes
    the CURRENT prefs instead, so a partial POST leaves everything it did
    not mention alone rather than quietly switching it back on -- the same
    rule the settings panel follows for API keys.
    """
    out = json.loads(json.dumps(base)) if base else defaults()
    if not isinstance(raw, dict):
        return out
    for key, on in (raw.get("sections") or {}).items():
        if key in out["sections"]:
            out["sections"][key] = bool(on)
    for key, fields in (raw.get("fields") or {}).items():
        if key not in out["fields"] or not isinstance(fields, dict):
            continue
        for field, on in fields.items():
            if field in out["fields"][key]:
                out["fields"][key][field] = bool(on)
    return out


def load() -> dict:
    """Current prefs, fully populated. Cheap enough for a render loop."""
    try:
        if not _PATH.is_file():
            return defaults()
        mtime = os.path.getmtime(_PATH)
        if _cache["mtime"] != mtime or _cache["prefs"] is None:
            _cache["prefs"] = _coerce(
                json.loads(_PATH.read_text(encoding="utf-8")))
            _cache["mtime"] = mtime
    except Exception:
        logger.exception("overlay_prefs.json load failed")
        return _cache["prefs"] or defaults()
    return _cache["prefs"]


def save(raw: dict) -> dict:
    """Merge `raw` over the current prefs and persist."""
    prefs = _coerce(raw, base=load())
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    _cache["mtime"] = None          # force the next load() to re-read
    return prefs


def apply_preset(name: str) -> dict:
    """Expand a preset name to a full prefs dict (does not save)."""
    preset = PRESETS.get(name)
    if not preset:
        return defaults()
    prefs = defaults()
    keep = set(preset["sections"])
    for key in prefs["sections"]:
        prefs["sections"][key] = key in keep
    for key, offs in (preset.get("off_fields") or {}).items():
        for field in offs:
            if field in prefs["fields"].get(key, {}):
                prefs["fields"][key][field] = False
    return prefs


def matches_preset(prefs: dict) -> str | None:
    """Which preset this equals, or None when the user has customized."""
    for name in PRESETS:
        if apply_preset(name) == prefs:
            return name
    return None


def on(prefs: dict, section: str, field: str | None = None) -> bool:
    """Guard used throughout the overlay's paint path."""
    if not (prefs.get("sections") or {}).get(section, True):
        return False
    if field is None:
        return True
    return bool((prefs.get("fields") or {}).get(section, {}).get(field, True))
