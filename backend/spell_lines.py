"""Curated spell lines: which buffs share a slot, and which supersede which.

EverQuest buffs occupy effect SLOTS. Two buffs in the same slot do not add —
the later cast overwrites the earlier one. A loadout that recommends both
Center and Bravery (both `ac-slot-1`) is therefore recommending one wasted
gem, and nothing in the spell data we already had says so: our supersession
check reasons from SPA effect ids and magnitudes, which cannot see slot
occupancy at all.

Data is rari/eqlfinest's hand-curated `paths` table (CC0), vendored as
backend/spell_lines.json — 112 lines over 431 spells. A line is ordered
weakest to strongest, so it answers two questions at once:

    same line          -> they conflict, keep one
    later in the line  -> that one is the upgrade

Coverage is partial by design (431 of ~66k spell records), so every helper
returns a "don't know" answer rather than a guess, and callers must treat
absence as "no opinion" — never as "no conflict".
"""
import json
import logging
from typing import Optional

from backend.log_system.parser import strip_tier
from backend.paths import bundle_path

logger = logging.getLogger(__name__)

_DATA: Optional[dict] = None


def _norm(name: str) -> str:
    """Match the log's tier suffixes against the table's base names."""
    return strip_tier((name or "").strip()).lower()


def _load() -> dict:
    """{normalised spell name: {slot: index}} plus the raw lines."""
    global _DATA
    if _DATA is not None:
        return _DATA
    index: dict = {}
    lines: dict = {}
    try:
        raw = json.loads(bundle_path("backend", "spell_lines.json")
                         .read_text(encoding="utf-8"))
        lines = raw.get("paths") or {}
        for slot, names in lines.items():
            for position, name in enumerate(names):
                index.setdefault(_norm(name), {})[slot] = position
    except (OSError, ValueError) as e:
        logger.warning("spell_lines.json unavailable (%s) — stacking checks "
                       "will be skipped", e)
    _DATA = {"index": index, "lines": lines}
    return _DATA


def slots_for(name: str) -> dict:
    """{slot: position} for a spell — empty when it is not in the table.
    A spell can occupy several slots (56 of them do), so this is a dict."""
    return dict(_load()["index"].get(_norm(name), {}))


def known(name: str) -> bool:
    return bool(slots_for(name))


def conflict(a: str, b: str) -> Optional[dict]:
    """Do these two overwrite each other?

    Returns {slot, keep, drop, same} when they share a slot, None when they
    do not — or when either spell is outside the table, because "not in the
    data" is not evidence of compatibility.
    """
    if _norm(a) == _norm(b):
        return None
    sa, sb = slots_for(a), slots_for(b)
    if not sa or not sb:
        return None
    shared = set(sa) & set(sb)
    if not shared:
        return None
    slot = sorted(shared)[0]
    pa, pb = sa[slot], sb[slot]
    if pa == pb:
        return {"slot": slot, "keep": a, "drop": b, "same": True}
    keep, drop = (a, b) if pa > pb else (b, a)
    return {"slot": slot, "keep": keep, "drop": drop, "same": False}


def supersedes(upgrade: str, using: str) -> bool:
    """True when `upgrade` sits later in a line the two share."""
    c = conflict(upgrade, using)
    return bool(c and not c["same"] and _norm(c["keep"]) == _norm(upgrade))


def find_conflicts(names: list) -> list:
    """Every overwriting pair in a proposed loadout, each reported once."""
    out, seen = [], set()
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            c = conflict(a, b)
            if not c:
                continue
            key = (c["slot"], _norm(c["keep"]), _norm(c["drop"]))
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
    return out


def line_for(name: str, slot: str) -> list:
    return list(_load()["lines"].get(slot) or [])


def stats() -> dict:
    d = _load()
    return {"lines": len(d["lines"]), "spells": len(d["index"])}
