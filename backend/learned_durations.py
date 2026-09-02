"""Buff and debuff durations measured on THIS character.

The vendored timer table (`alert_data.SPELL_TIMERS`) is a raid trigger pack
plus the eqlbuilds durationTicks for three classes: thin below the high end,
timed at an unknown tier, and blind to focus effects and AAs. Its timers
deliberately under-promise. But the log carries both ends of every cycle --
"You begin casting X." and, later, "Your X spell has worn off[ of T]." --
so the real length on this character, at this tier, with these AAs, is
sitting there to be read. EQBuddy leads with exactly this feature.

The rule for USING a measurement is EQBuddy's: three cycles agreeing within
15%, and only then. One clean gap is never enough -- the same spell cast on
two mobs measures the second target's fade against the first's cast, a
refresh mid-cycle shortens the gap, a death drops every buff at once. None
of those agree with each other or with the true length, so demanding
agreement is what keeps them out. A single sample is stored and reported as
"measuring", never acted on.

Keyed per character AND per exact cast name (tier included): the tier
changes the length, and extended-duration AAs belong to one character.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import threading
from typing import Optional

from backend.paths import data_path

log = logging.getLogger(__name__)

FILE = data_path("learned_durations.json")
MAX_SAMPLES = 8          # newest kept; older cycles reflect older gear/AAs
MIN_AGREE = 3            # cycles that must agree before a value is used
AGREE_WITHIN = 0.15      # ...within this fraction of their median
# Outside this band a gap is not a cycle at all: under it is a spell that
# was resisted/cured/overwritten, over it is a fade matched to a cast from
# a previous session.
MIN_SECONDS = 6
MAX_SECONDS = 3 * 3600

_LOCK = threading.Lock()
_DATA: Optional[dict] = None


def _load() -> dict:
    global _DATA
    if _DATA is not None:
        return _DATA
    try:
        with open(FILE, encoding="utf-8") as fh:
            raw = json.load(fh)
        _DATA = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        _DATA = {}
    return _DATA


def _save(data: dict) -> None:
    tmp = FILE.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, FILE)
    except OSError:
        log.info("could not save learned durations", exc_info=True)


def char_key(name: Optional[str], server: Optional[str]) -> str:
    return f"{(name or '?').lower()}@{(server or '?').lower()}"


def observe(char: str, spell: str, seconds: float) -> Optional[dict]:
    """Record one cast-to-fade cycle. Returns the entry's current verdict
    (see `estimate`) so the caller can log when a spell just became known."""
    secs = int(seconds)
    if not (MIN_SECONDS <= secs <= MAX_SECONDS):
        return None
    key = spell.lower().strip()
    with _LOCK:
        data = _load()
        entry = data.setdefault(char, {}).setdefault(key, {"samples": [], "seen": 0})
        entry["samples"] = (entry["samples"] + [secs])[-MAX_SAMPLES:]
        entry["seen"] = entry.get("seen", 0) + 1
        _save(data)
        return _verdict(entry)


def _verdict(entry: dict) -> dict:
    samples = [int(s) for s in entry.get("samples", []) if isinstance(s, (int, float))]
    if not samples:
        return {"seconds": None, "n": 0, "agree": 0, "usable": False}
    med = statistics.median(samples)
    agreeing = [s for s in samples if abs(s - med) <= AGREE_WITHIN * med]
    usable = len(agreeing) >= MIN_AGREE
    # Rounded DOWN, for the same reason the tier scaling is: every
    # remaining error should point at under-promising.
    est = int(statistics.median(agreeing)) if usable else None
    return {"seconds": est, "n": len(samples), "agree": len(agreeing),
            "usable": usable}


def estimate(char: str, spell: str) -> Optional[dict]:
    """The measured length, or None until enough cycles agree.

    Callers get a dict with `seconds` only when `usable`; a spell still
    being measured returns None here and shows up in `progress` instead,
    so nothing downstream can mistake a first reading for a fact.
    """
    with _LOCK:
        entry = _load().get(char, {}).get(spell.lower().strip())
    if not entry:
        return None
    v = _verdict(entry)
    return v if v["usable"] else None


def progress(char: str, spell: str) -> Optional[dict]:
    """How far along a spell's measurement is, usable or not."""
    with _LOCK:
        entry = _load().get(char, {}).get(spell.lower().strip())
    return _verdict(entry) if entry else None


def known(char: str) -> dict:
    """Every measured spell for a character, for the settings/vitals view."""
    with _LOCK:
        spells = dict(_load().get(char, {}))
    return {name: _verdict(e) for name, e in spells.items()}


def _reset_for_tests() -> None:
    global _DATA
    with _LOCK:
        _DATA = None
