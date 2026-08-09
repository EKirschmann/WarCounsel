"""User-tracked alert rules (tracked_rules.json) — EQBuddy-style watches.

Rules are deliberately SUBSTRING matches, not regex (per EQBuddy: users
should never need to escape anything). data/tracked_rules.json holds a
list of {"kind": k, "pattern": "text", "enabled": true, "sound": true}
where k is loot|kill|death|zone|tell|fade — pattern "*" matches
everything — plus the special kind "bighit" whose pattern is a NUMBER
(alert when a single hit taken meets it). The file is created with
disabled examples on first load and re-read automatically when edited
(mtime). Built-in alerts (summon, name mentioned in group/guild/raid
chat) fire without rules. Matches surface as overlay banners (+ chime
when sound is true) with a 5s per-rule cooldown; the seed replay never
fires alerts (live only).
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

from backend.paths import data_path

RULES_FILE = data_path("tracked_rules.json")
KINDS = ("loot", "kill", "death", "zone", "tell", "fade", "bighit",
         # These five were PARSED all along and simply had nothing to fire:
         # the events existed, no rule kind reached them. "Can I trigger on a
         # spell interrupt like GINA does" was a fair question with a silly
         # answer -- the line was already in ev.CastInterrupted, complete with
         # the spell name.
         "interrupt", "fizzle", "cast", "mechanic", "mez")

# What each kind matches its pattern AGAINST. Shown in the settings panel,
# because "pattern" means nothing without knowing what it is compared to --
# and a rule that never fires looks identical to a quiet night.
KIND_HELP = {
    "loot": "item name",
    "kill": "what you killed",
    "death": "'slain by <killer>'",
    "zone": "zone name",
    "tell": "'<sender>: <message>'",
    "fade": "'<spell> (<target>)' as a buff drops -- mez and charm breaks",
    "bighit": "a NUMBER: alert when one hit on you meets it",
    "interrupt": "the spell your cast was interrupted on",
    "fizzle": "the spell that fizzled",
    "cast": "'<caster>: <spell>' when someone else starts casting",
    "mechanic": "the raid mechanic's name",
    "mez": "the mob that just got mesmerized",
}

_EXAMPLE = [
    {"kind": "loot", "pattern": "Kitchen Toolbelt",
     "enabled": False, "sound": True},
    {"kind": "tell", "pattern": "*", "enabled": False, "sound": True},
    {"kind": "fade", "pattern": "Mesmerize", "enabled": False, "sound": True},
    {"kind": "fade", "pattern": "Charm", "enabled": False, "sound": True},
    {"kind": "interrupt", "pattern": "*", "enabled": False, "sound": True},
    {"kind": "bighit", "pattern": "800", "enabled": False, "sound": True},
]

_cache = {"mtime": None, "rules": [], "all": []}


def _clean(raw) -> list:
    """Well-formed rules, enabled or not, in file order."""
    out = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict) or r.get("kind") not in KINDS:
            continue
        pattern = str(r.get("pattern", "")).strip()
        if not pattern:
            continue
        out.append({"kind": r["kind"], "pattern": pattern,
                    "enabled": bool(r.get("enabled", True)),
                    "sound": bool(r.get("sound", True))})
    return out


def all_rules() -> list:
    """Every rule INCLUDING disabled ones — what an editor has to show.

    load_rules() drops the disabled ones because matching should never see
    them, which meant /api/tracked-rules reported an empty list on a fresh
    install: the seeded examples all ship disabled, so the one surface that
    was supposed to explain the feature showed nothing at all.
    """
    load_rules()
    return list(_cache["all"])


def load_rules() -> list:
    try:
        if not RULES_FILE.is_file():
            RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
            RULES_FILE.write_text(json.dumps(_EXAMPLE, indent=2),
                                  encoding="utf-8")
        mtime = os.path.getmtime(RULES_FILE)
        if _cache["mtime"] != mtime:
            raw = json.loads(RULES_FILE.read_text(encoding="utf-8"))
            _cache["all"] = _clean(raw)
            _cache["rules"] = [r for r in _cache["all"] if r["enabled"]]
            _cache["mtime"] = mtime
    except Exception:
        logger.exception("tracked_rules.json load failed")
    return _cache["rules"]


def save(rules) -> list:
    """Replace the rule set. Returns what was actually stored.

    Written whole rather than merged: unlike the settings panel's API keys,
    a rules LIST has no per-field identity to merge on -- the editor owns the
    whole table, and a merge would make deleting a rule impossible.
    """
    clean = _clean(rules)
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RULES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    tmp.replace(RULES_FILE)          # atomic: the overlay re-reads on mtime
    _cache["mtime"] = None           # force a reload on the next match
    load_rules()
    logger.info("tracked_rules.json saved (%d rules)", len(clean))
    return clean


def match(kind: str, text: str) -> list:
    """Enabled rules of `kind` whose pattern appears in `text`
    ("*" matches everything)."""
    low = (text or "").lower()
    return [r for r in load_rules()
            if r["kind"] == kind
            and (r["pattern"] == "*" or r["pattern"].lower() in low)]


def bighit_threshold():
    """Smallest enabled bighit rule value, or None."""
    best = None
    for r in load_rules():
        if r["kind"] != "bighit":
            continue
        try:
            v = int(str(r["pattern"]).strip())
        except ValueError:
            continue
        best = v if best is None else min(best, v)
    return best