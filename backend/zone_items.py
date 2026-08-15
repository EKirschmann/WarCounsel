"""What is worth picking up in the zone you are standing in.

Reverses the lookup the Quests tab already does. That one asks "which quests
want this item I hold"; this asks "which of the things I want drop HERE", so
a zone line becomes a short list of things not to vendor.

Two hard limits, both measured rather than assumed (2026-08-14):

- **Class-unlock items cannot be placed this way.** 0 of 20 sampled Plane of
  Sky criteria have a "Drops From" section on their wiki page at all — those
  items come off named island bosses and the wiki records that elsewhere, if
  at all. The eqlposky/EQProgression tables do carry it ("Island 5: The
  Spiroc Lord") but state no licence, so nothing is vendored from them. Sky
  is therefore absent here on purpose, not by oversight.
- **We can only want what we can already see.** Quest rows come from items
  you HOLD, so a quest needing something you have none of is invisible. Race
  unlocks are the exception: that table is curated, so all seven turn-ins
  count whether you hold any or not.

36 of 41 candidates resolved to a zone on a real character, which is the
coverage to expect.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def _drop_zones(name: str) -> list:
    """Zones named in an item page's "Drops From" section.

    Those lines interleave zones and mob names with nothing marking which is
    which — "Blackburrow, a burly gnoll, a gnoll brewer". A name that
    resolves through the zone table IS a zone; everything else is a mob.
    Same bridge `zem_entry_for` uses, and the reason it has to exist: the
    two namespaces are not comparable as strings.
    """
    from backend.game_data import item_acquisition
    from backend.map_system import _canonical
    try:
        acq = await item_acquisition(name)
    except Exception:
        return []
    for sec in (acq.get("sections") or []):
        if "drop" in (sec.get("label") or "").lower():
            out = []
            for line in (sec.get("lines") or []):
                t = (line.get("text") or "").strip()
                z = _canonical(t) if t else None
                if z:
                    out.append(z)
            return list(dict.fromkeys(out))
    return []


async def worth_collecting(zone: Optional[str], quest_rows: list,
                           held: Optional[dict] = None) -> dict:
    """Wanted items that drop in `zone`, with why each one is wanted."""
    from backend.map_system import _canonical
    from backend import race_unlocks
    if not zone:
        return {"zone": None, "items": []}
    here = _canonical(zone) or zone

    why: dict = {}
    for row in quest_rows or []:
        for it in row.get("items") or []:
            why.setdefault(it["name"], []).append(row["quest"])
    for rec in race_unlocks.all_items():
        why.setdefault(rec["item"], []).append(
            f"{rec['race']} unlock — {rec['npc']}")

    names = sorted(why)
    zones = await asyncio.gather(*(_drop_zones(n) for n in names),
                                 return_exceptions=True)
    items = []
    for name, zs in zip(names, zones):
        if isinstance(zs, Exception) or here not in zs:
            continue
        rec = race_unlocks.match(name)
        items.append({
            "name": name,
            "for": sorted(set(why[name]))[:3],
            "held": (held or {}).get(name, 0),
            # A turn-in with a stated total is the one case where "keep
            # farming" has a number behind it.
            "needed": rec.get("total") if rec else None,
            "also_drops": [z for z in zs if z != here][:4],
        })
    items.sort(key=lambda i: (i["needed"] is None, i["name"]))
    return {"zone": zone, "resolved": here, "items": items}
