"""What each WEB panel shows -- chosen in Settings.

Separate from overlay_prefs.py on purpose, and the separation is the whole
design decision. A 42px overlay strip and a 340px column answer different
questions: you genuinely want a damage meter and nothing else while
fighting, and the full session ledger while planning. One shared set of
toggles would mean hiding deaths in the overlay also hides them in the web
view, which sounds tidy and is wrong.

Same SHAPE as the overlay's, deliberately -- per section and per field,
defaults all on, saves merged onto current -- so there is one pattern to
learn rather than two.

Lives in data/, which is gitignored and which the updater preserves, so a
choice made here survives both a restart and an upgrade.
"""
import json
import logging

from backend.paths import data_path

logger = logging.getLogger(__name__)

_PATH = data_path("panel_prefs.json")

# Allow-list AND the source of truth the Settings UI renders from, so the
# switchboard cannot drift from what the panels actually draw. Field keys
# map 1:1 onto blocks the components already build.
SECTIONS = {
    "vitals": {
        "label": "Vitals & Session",
        "hint": "the left column",
        "fields": {
            "level": {"label": "Level and XP", "hint": "with time-to-ding"},
            "maxes": {"label": "Max HP and mana", "hint": "typed, or read from screen"},
            "dps": {"label": "DPS meter", "hint": "rolling 60 seconds"},
            "damage": {"label": "Damage dealt and taken", "hint": ""},
            "healing": {"label": "Healing", "hint": "received and done"},
            "kills": {"label": "Kills and deaths", "hint": ""},
            "aa": {"label": "AA points", "hint": ""},
            "accuracy": {"label": "Hit rate and skill-ups", "hint": ""},
            "coin": {"label": "Coin and crits", "hint": ""},
            "loot": {"label": "Recent loot", "hint": ""},
            "unlocks": {"label": "Race unlock turn-ins", "hint": "progress on what you loot"},
            "hunting": {"label": "Session hunting", "hint": "per-mob kills, XP, drops"},
            "trio": {"label": "Trio comparison", "hint": "DPS by class combination"},
            "sessions": {"label": "Past sessions", "hint": ""},
        },
    },
    "encounter": {
        "label": "Encounter",
        "hint": "the per-fight breakdown",
        "fields": {
            "abilities": {"label": "Ability table", "hint": "hits, average, DPS"},
            "defense": {"label": "Defence line", "hint": "blocks, dodges, parries"},
            "heals": {"label": "Healing rows", "hint": "attributed to the healer"},
            "pet": {"label": "Pet section", "hint": "when a mapped pet contributes"},
            "group": {"label": "Group damage", "hint": "per-member totals"},
            "filtered": {"label": "Not counted", "hint": "contributors you have not confirmed"},
            "timeline": {"label": "Damage sparkline", "hint": ""},
        },
    },
    "quests": {
        "label": "Quests",
        "hint": "what your bags are partway through",
        "fields": {
            "race": {"label": "Race unlocks", "hint": ""},
            "class": {"label": "Class quests", "hint": ""},
            "equipment": {"label": "Equipment", "hint": ""},
            "spell": {"label": "Spells", "hint": ""},
            "faction": {"label": "Faction and repeatables", "hint": ""},
            "other": {"label": "Other", "hint": "the wiki did not say enough to place these"},
            "out_of_era": {"label": "Out of era", "hint": "Kunark and later"},
        },
    },
    "ledger": {
        "label": "War Ledger",
        "hint": "the live log",
        "fields": {
            "damage": {"label": "Damage", "hint": "yours and incoming"},
            "heals": {"label": "Heals", "hint": ""},
            "casts": {"label": "Casts and fizzles", "hint": ""},
            "loot": {"label": "Loot and coin", "hint": ""},
            "misc": {"label": "Everything else", "hint": "zones, factions, skill-ups"},
        },
    },
}

# Named starting points, so nobody has to click through forty switches.
PRESETS = {
    "everything": {
        "label": "Everything",
        "hint": "every section, every field",
        "sections": list(SECTIONS),
    },
    "combat": {
        "label": "Combat focus",
        "hint": "what is happening now — no session history",
        "sections": ["vitals", "encounter", "ledger"],
        "off_fields": {"vitals": ["sessions", "trio", "hunting", "unlocks", "loot"]},
    },
    "planning": {
        "label": "Planning",
        "hint": "quests, loot and session history — no live combat",
        "sections": ["vitals", "quests"],
        "off_fields": {"vitals": ["dps", "damage", "healing"]},
    },
}


def defaults() -> dict:
    return {
        "sections": {k: True for k in SECTIONS},
        "fields": {k: {f: True for f in v["fields"]}
                   for k, v in SECTIONS.items()},
    }


def _coerce(raw, base: dict | None = None) -> dict:
    """Fill a partial or malformed payload out to the full shape.

    `base` is what an OMITTED key falls back to. Reading a file uses the
    defaults, so a section a newer version added arrives switched on.
    Saving passes the CURRENT prefs, so a partial POST leaves untouched
    what it did not mention instead of springing it back on.
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
    try:
        return _coerce(json.loads(_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return defaults()


def save(patch: dict) -> dict:
    """Merge a partial payload onto what is stored and write it back."""
    merged = _coerce(patch, base=load())
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("could not save panel prefs: %s", exc)
    return merged


def apply_preset(name: str) -> dict:
    """Switch to a named starting point, then save it."""
    p = PRESETS.get(name)
    if not p:
        return load()
    on = set(p.get("sections") or [])
    prefs = {
        "sections": {k: (k in on) for k in SECTIONS},
        "fields": {k: {f: True for f in v["fields"]} for k, v in SECTIONS.items()},
    }
    for sec, offs in (p.get("off_fields") or {}).items():
        for f in offs:
            if sec in prefs["fields"] and f in prefs["fields"][sec]:
                prefs["fields"][sec][f] = False
    return save(prefs)


def schema() -> dict:
    """Everything the Settings UI needs to render itself."""
    return {"sections": SECTIONS, "presets": PRESETS, "prefs": load()}
