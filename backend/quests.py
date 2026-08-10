"""Owned items matched to the quests that want them.

The inventory export says what you are carrying; item wiki pages say which
quests reference each item; quest pages carry a structured header with the
giver, the zone, the minimum level and the reward. Joining those three is
the whole feature -- none of it is inferred.

WHAT THIS DELIBERATELY DOES NOT DO is compute a progress bar. Required
quantities live in walkthrough PROSE ("Bring me two tufts of bat fur and
two fire beetle legs"), not in any structured field, and a number scraped
out of a sentence would be wrong often enough to send someone farming the
wrong count. The panel shows how many you HOLD, which is exact, and links
the quest so the requirement can be read from the source.

Class restrictions are reported, never used to filter: players change
their trio and intend to keep changing it, so "your current classes cannot
do this" is not a reason to hide a quest you are already carrying items
for.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from backend.game_data import item_acquisition, wiki_page_cache

logger = logging.getLogger(__name__)

WIKI_BASE = "https://eqlwiki.com/"
_QUEST_TTL = 24 * 3600

# Rows of the questTopTable worth keeping, mapped to the key we expose.
_HEADER_FIELDS = {
    "start zone": "zone",
    "quest giver": "giver",
    "minimum level": "min_level",
    "classes": "classes",
    "races": "races",
    "related zones": "related_zones",
    "related npcs": "related_npcs",
}


def _delink(text: str) -> str:
    """[[A|B]] -> B, [[A]] -> A. Function replacement, not a backreference
    string: a mis-escaped one silently substitutes a control character."""
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", lambda m: m.group(2), text)
    text = re.sub(r"\[\[([^\]]+)\]\]", lambda m: m.group(1), text)
    # {{:Runescale Cloak}} is a transclusion of the item page, not a reward
    # name -- it rendered literally in the first run.
    text = re.sub(r"\{\{:?\s*([^}|]+?)\s*(\|[^}]*)?\}\}",
                  lambda m: m.group(1), text)
    return re.sub(r"'{2,}", "", text).strip()


def _parse_quest(wikitext: str) -> dict:
    """Header fields and rewards from a quest page. {} when it is not one."""
    out: dict = {}
    # questTopTable: alternating "! field" / "| value" rows
    m = re.search(r"\{\|[^\n]*questTopTable(.*?)\n\|\}", wikitext, re.S)
    if m:
        rows = re.findall(r"!\s*(.+?)\s*\n\|\s*(.+?)\s*(?=\n[!|])", m.group(1), re.S)
        for label, value in rows:
            key = _HEADER_FIELDS.get(_delink(label).strip(": ").lower())
            if key:
                out[key] = _delink(value.replace("\n", " "))
    rw = re.search(r"==\s*Reward\s*==(.*?)(?=\n==|\Z)", wikitext, re.S | re.I)
    if rw:
        items = re.findall(r"<li>(.*?)</li>", rw.group(1), re.S)
        if not items:
            items = re.findall(r"^\*\s*(.+)$", rw.group(1), re.M)
        rewards = [_delink(i) for i in items if _delink(i)]
        if rewards:
            out["rewards"] = rewards[:12]
    if re.search(r"^\s*Disambiguation", wikitext, re.M):
        out["disambiguation"] = True
    return out


async def _quest_page(name: str) -> dict:
    cached = wiki_page_cache.get("quest1", name.lower())
    if cached is not None:
        return cached or {}
    from backend import wiki_http
    try:
        txt = await wiki_http.fetch_page_wikitext(name)
    except Exception:
        return {}
    data = _parse_quest(txt) if txt else {}
    # Cached even when empty: a quest page we cannot parse is still a page
    # we should not re-fetch on every consult.
    wiki_page_cache.set(data, _QUEST_TTL, "quest1", name.lower())
    return data


async def quests_for_items(items: list, level=None) -> list:
    """Quests referenced by items the player is carrying.

    `items` are export rows ({name, where, ...}); several rows of the same
    item are counted, since "you hold 7 Bone Chips" is the number that
    matters and it is the one thing here that is exact.
    """
    held: dict = {}
    for it in items or []:
        n = (it.get("name") or "").strip()
        if not n:
            continue
        r = held.setdefault(n, {"count": 0, "where": set()})
        r["count"] += int(it.get("count") or 1)
        if it.get("where"):
            r["where"].add(it["where"])

    # item -> quest names, from the pages we already mine for hover cards
    async def quests_of(name: str) -> list:
        try:
            acq = await item_acquisition(name)
        except Exception:
            return []
        out = []
        for sec in (acq.get("sections") or []):
            if "quest" not in (sec.get("label") or "").lower():
                continue
            out += [l.get("text", "").strip()
                    for l in (sec.get("lines") or []) if l.get("text")]
        return [q for q in out if q]

    pairs = await asyncio.gather(*(quests_of(n) for n in held),
                                 return_exceptions=True)
    by_quest: dict = {}
    for name, qs in zip(held, pairs):
        if isinstance(qs, Exception):
            continue
        for q in qs:
            by_quest.setdefault(q, []).append(name)

    pages = await asyncio.gather(*(_quest_page(q) for q in by_quest),
                                 return_exceptions=True)
    out = []
    for (quest, item_names), page in zip(by_quest.items(), pages):
        page = page if isinstance(page, dict) else {}
        lvl = None
        if page.get("min_level"):
            m = re.search(r"\d+", str(page["min_level"]))
            lvl = int(m.group()) if m else None
        out.append({
            "quest": quest,
            "url": WIKI_BASE + quest.replace(" ", "_"),
            "items": sorted(
                ({"name": n, "count": held[n]["count"],
                  "where": sorted(held[n]["where"])} for n in item_names),
                key=lambda x: -x["count"]),
            "giver": page.get("giver"),
            "zone": page.get("zone"),
            "min_level": lvl,
            "classes": page.get("classes"),
            "races": page.get("races"),
            "rewards": page.get("rewards"),
            "disambiguation": bool(page.get("disambiguation")),
            # reported, never used to hide a row -- see the module docstring
            "below_level": bool(lvl and level and level < lvl),
        })
    # most items held first: that is the closest honest proxy for "nearly done"
    out.sort(key=lambda q: (-sum(i["count"] for i in q["items"]),
                            -len(q["items"]), q["quest"]))
    return out
