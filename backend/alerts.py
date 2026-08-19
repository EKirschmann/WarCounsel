"""User-tracked alert rules (tracked_rules.json) — EQBuddy-style watches.

Rules are deliberately SUBSTRING matches, not regex (per EQBuddy: users
should never need to escape anything). data/tracked_rules.json holds a
list of {"kind": k, "pattern": "text", "enabled": true, "sound": true}
where k is loot|kill|death|zone|tell|fade — pattern "*" matches
everything — plus the special kind "bighit" whose pattern is a NUMBER
(alert when a single hit taken meets it). The file is created with
a few disabled STARTER rules on first load (the rest are offered in
the panel, never written unasked) and re-read automatically when edited
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

# ------------------------------------------------------------- starter set
# A catalogue of rules worth having, NOT a second copy of the user's file.
# It is offered in the Triggers panel and copied in one row at a time on
# request, because the seed below only ever writes on a FRESH install: a
# bigger seed would reach nobody who already has the app, and merging into
# an existing file would resurrect rules somebody deleted on purpose.
#
# Every `fade` pattern here was checked against the client spell table
# (spells_us.txt, 73,971 names) rather than written from memory, because a
# pattern that matches nothing looks exactly like a quiet night. Two of
# them are why this matters: "Mesmerize" matches 3 spell names and misses
# all 60 "Mesmerization" spells, and "Levitate" misses "Levitation"
# entirely. The truncated stems match both families.
STARTER = [
    # kind, pattern, group, label, why
    ("bighit", "800", "Survival", "One hit takes 800+",
     "The number is the threshold; lower it as your health pool grows."),
    ("death", "*", "Survival", "You die",
     "Marks the moment in the log for the post-mortem."),
    ("fade", "Invis", "Survival", "Invisibility drops",
     "Matches all 40 invis spells. The one that gets people killed in "
     "Kithicor."),
    ("fade", "Levitat", "Survival", "Levitation drops",
     "Matches Levitate and Levitation both -- the stem is deliberate."),
    ("fade", "Mesmeriz", "Group", "A mez breaks",
     "Covers Mesmerize and Mesmerization. Breaking a mez is the classic "
     "group mistake."),
    ("fade", "Charm", "Group", "A charm breaks",
     "Your pet is about to be someone else's problem."),
    ("mez", "*", "Group", "Something gets mezzed",
     "The apply half: know what not to hit."),
    ("mechanic", "*", "Group", "A raid mechanic fires",
     "Any of the 13 vendored boss triggers -- breaths, roars, death "
     "touches."),
    ("interrupt", "*", "Casting", "Your cast is interrupted",
     "Names the spell you lost."),
    ("fizzle", "*", "Casting", "Your cast fizzles",
     "Noisy at low skill, which is exactly when it is worth watching."),
    ("tell", "*", "Attention", "Anyone sends you a tell",
     "Pattern a name instead of * to watch for one person."),
    ("zone", "*", "Attention", "You change zone",
     "Pattern a zone name to be told when you reach it."),
    ("loot", "*", "Attention", "You loot anything",
     "Narrow the pattern to an item name once you know what you are "
     "hunting."),
]


def starter_set() -> list:
    """The catalogue, as rows the panel can render and add."""
    return [{"kind": k, "pattern": p, "group": g, "label": lbl, "why": why,
             "enabled": False, "sound": True}
            for k, p, g, lbl, why in STARTER]


# Seeded on a fresh install: a handful of the above, so the two cannot
# drift apart. Everything else is one click away in the panel.
_SEEDED = ("bighit:800", "tell:*", "fade:Mesmeriz", "fade:Charm",
           "interrupt:*", "death:*")
_EXAMPLE = [{k: r[k] for k in ("kind", "pattern", "enabled", "sound")}
            for r in starter_set()
            if r["kind"] + ":" + r["pattern"] in _SEEDED]

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