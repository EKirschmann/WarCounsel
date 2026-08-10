"""Loot that feeds a race-unlock faction grind.

Some drops are worth keeping for a reason nothing in the game tells you at
the moment you loot them: they are turn-ins on a race-unlock path. A Gnoll
Fang looks like vendor trash and is 1/1200th of a Barbarian.

Deliberately LOOTABLE turn-ins only. The guide's other routes are vendor
purchases or quest hand-outs and never appear in a loot line, so they could
not fire this alert and are not in the table.

Data hand-curated from eqlwiki's Race Unlock Guide (CC BY-SA 4.0) — see
race_unlocks.json for the source link and why it is not generated.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from backend.paths import bundle_path

logger = logging.getLogger(__name__)

_BY_NAME: Optional[dict] = None


def _load() -> dict:
    global _BY_NAME
    if _BY_NAME is not None:
        return _BY_NAME
    _BY_NAME = {}
    try:
        raw = json.loads(
            (bundle_path() / "backend" / "race_unlocks.json").read_text(encoding="utf-8")
        )
        for rec in raw.get("items", []):
            if rec.get("item"):
                _BY_NAME[rec["item"].strip().lower()] = rec
    except (OSError, ValueError) as exc:
        # Fails SOFT and loud-in-the-log: a missing data file must never
        # stop the loot pipeline, but it should not vanish silently either.
        logger.warning("race unlock table unavailable: %s", exc)
    return _BY_NAME


def match(item: str) -> Optional[dict]:
    """The turn-in record for a looted item, or None.

    EXACT (case-folded) match on the base name. No fuzzy matching, for the
    same reason the zone table has none: the names most likely to be
    confused are the near-identical ones, and telling someone to hoard the
    wrong drop for 400 kills is worse than saying nothing.
    """
    if not item:
        return None
    name = item.strip().lower()
    # loot lines carry the odd article
    for prefix in ("a ", "an ", "the "):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return _load().get(name)


def all_items() -> list:
    return sorted(_load().values(), key=lambda r: (r["race"], r["item"]))


def reset_cache() -> None:
    global _BY_NAME
    _BY_NAME = None


def guide_url() -> str:
    """Where the table came from, so a row can link its source."""
    try:
        raw = json.loads(
            (bundle_path() / "backend" / "race_unlocks.json").read_text(encoding="utf-8")
        )
        return raw.get("_url") or ""
    except (OSError, ValueError):
        return ""
