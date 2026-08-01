"""Item facts LEARNED from the game's own exports, not the wiki.

eqlwiki does not document every item -- launch added a whole block of them
(ids around 69xxx) and several are gear a player is already WEARING. Without
a wiki page there is no Slot line, and every recommend path needs one to
place an item, so a perfectly good piece sat in a bag with the matching slot
empty and nothing said so.

The export already answers the part that matters. For a worn row the
Location column IS the slot, and the game only let the item go there if the
character could use it. So:

    slot          <- learned, free, exact
    trio-usable   <- implied (the game accepted it)
    stats         <- still wiki-only, and still refused when missing

Keyed on the item ID, not the name: an id is stable across +N merges (a base
item and its +2 share one), so "Boots of the Long Road" and its +2 teach the
same fact once. Names also get decorated and collide; ids do not.

Deliberately NOT inferred: stats, and the slot of an item never yet worn. A
guess about where a piece goes would be the same class of error as a fuzzy
zone match -- it reads as knowledge and is wrong invisibly.
"""
import json
import logging
import threading
from datetime import datetime
from typing import Optional

from backend.paths import data_path

logger = logging.getLogger(__name__)

FACTS_PATH = data_path("item_facts.json")
_lock = threading.Lock()
_cache: Optional[dict] = None

# "Any Slot" is deliberately excluded: it accepts anything equippable, so
# seeing an item there proves nothing about where the item belongs.
_IGNORED_SLOTS = {"Any Slot"}


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        raw = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
        _cache = raw if isinstance(raw, dict) else {}
    except Exception:
        _cache = {}
    return _cache


def _save(facts: dict) -> None:
    try:
        FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = FACTS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(facts, indent=1, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(FACTS_PATH)
    except Exception:
        logger.debug("item_facts save failed", exc_info=True)


def _base(name: str) -> str:
    n = (name or "").strip()
    if " +" in n:
        head, _, tail = n.rpartition(" +")
        if tail.isdigit():
            return head
    return n


def learn(items: list) -> int:
    """Record slot facts from an inventory export's WORN rows.

    Returns how many NEW facts were added, and only writes when something
    was actually learned so the common case touches no disk.
    """
    facts = _load()
    added = 0
    with _lock:
        for it in items or []:
            iid = it.get("id") or 0
            if not iid or it.get("where") != "worn":
                continue
            slot = (it.get("loc") or "").strip()
            if not slot or slot in _IGNORED_SLOTS:
                continue
            key = str(iid)
            rec = facts.get(key)
            if rec and rec.get("slot") == slot:
                continue
            facts[key] = {"slot": slot,
                          "name": _base(it.get("name") or ""),
                          "learned": datetime.now().isoformat(
                              timespec="seconds")}
            added += 1
        if added:
            _save(facts)
    return added


# Marker on a stats line meaning "these numbers are ALREADY at +N".
# scale_item_line() refuses to touch a line carrying it, so a supplied
# figure can never be scaled a second time -- the wiki slider expects BASE
# values and a player reads their stats off the item at its CURRENT rank.
PRESCALED = "PRE-SCALED"


def set_stats(item_id, stats: str, rank: int, slot: Optional[str] = None,
              name: Optional[str] = None, override: bool = False) -> None:
    """Record stats a PLAYER supplied for a wiki-less item.

    `override` marks the reading as beating the wiki rather than merely
    filling a gap. Normally a supplied stat is a LAST resort, because the
    wiki carries base (+0) values that scale to any rank while a hand-read
    figure is pinned to the rank it was read at. That is right when the
    wiki is SILENT and wrong when it is MISTAKEN: eqlwiki carries some
    classic-era item pages verbatim (a Leatherfoot Raider Skullcap listed
    at AC 7 with three stats and a Ring of Commons click reads AC 4 and
    nothing else in game), and no amount of correct scaling rescues a
    number describing a different game. A player holding the item outranks
    that page.

    `stats` is a compact wiki-shaped line ("Slot: CHEST; AC: 8; ...") so
    every existing consumer -- _fits_slot, item_stat_vector, weapon_indices,
    the prompt builder -- works on it unchanged. `rank` is the +N those
    numbers were read at, kept because it is the only way to know they must
    not be scaled again.
    """
    facts = _load()
    with _lock:
        key = _key_for(item_id, name)
        rec = facts.setdefault(key, {})
        rec["stats"] = stats.strip()
        rec["stats_rank"] = int(rank)
        rec["stats_source"] = "user"
        rec["stats_override"] = bool(override)
        if slot:
            rec["slot"] = slot
        if name:
            rec["name"] = _base(name)
        rec["learned"] = datetime.now().isoformat(timespec="seconds")
        _save(facts)
    reset_cache()


def override_for(item_id, name: str = "") -> Optional[tuple]:
    """(line, rank) only when the player marked the reading authoritative."""
    rec = _record(item_id, name)
    if not rec or not rec.get("stats") or not rec.get("stats_override"):
        return None
    return rec["stats"], int(rec.get("stats_rank") or 0)


def _record(item_id, name: str = "") -> Optional[dict]:
    facts = _load()
    rec = None
    try:
        n = int(item_id or 0)
    except (TypeError, ValueError):
        n = 0
    if n:
        rec = facts.get(str(n))
    if not rec and name:
        rec = facts.get("name:" + _base(name).lower())
    if not rec and name:
        b = _base(name).lower()
        rec = next((r for r in _load().values()
                    if (r.get("name") or "").lower() == b and r.get("stats")),
                   None)
    return rec


def _key_for(item_id, name: Optional[str]) -> str:
    """Storage key: the item ID when we have one, else the item NAME.

    An id is stable across +N merges and is the right key whenever the
    export supplies one. But a correction can be made for an item we have
    no id for, and `str(int(item_id or 0))` turned every such record into
    the key "0" -- one shared slot that the next lookup with no id would
    return for ANY item. Caught immediately: correcting a Leatherfoot
    Raider Skullcap made a Ringmail Coif report the skullcap's stats.
    """
    try:
        n = int(item_id or 0)
    except (TypeError, ValueError):
        n = 0
    return str(n) if n else "name:" + _base(name or "").lower()


def stats_for(item_id, name: str = "") -> Optional[tuple]:
    """(line, rank) for a supplied stats record, else None."""
    rec = None
    try:
        rec = _load().get(str(int(item_id or 0)))
    except (TypeError, ValueError):
        rec = None
    if not rec and name:
        b = _base(name).lower()
        rec = next((r for r in _load().values()
                    if (r.get("name") or "").lower() == b and r.get("stats")),
                   None)
    if not rec or not rec.get("stats"):
        return None
    return rec["stats"], int(rec.get("stats_rank") or 0)


def slot_for_id(item_id) -> Optional[str]:
    """The slot this item was seen worn in, or None if never observed."""
    try:
        rec = _load().get(str(int(item_id or 0)))
    except (TypeError, ValueError):
        return None
    return (rec or {}).get("slot")


def slot_for_name(name: str) -> Optional[str]:
    """Fallback lookup by base name, for callers without the id."""
    b = _base(name).lower()
    if not b:
        return None
    for rec in _load().values():
        if (rec.get("name") or "").lower() == b:
            return rec.get("slot")
    return None


def known() -> dict:
    """id -> record, for diagnostics and the settings panel."""
    return dict(_load())


def reset_cache() -> None:
    global _cache
    _cache = None
