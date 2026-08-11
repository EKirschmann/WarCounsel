"""Owned items matched to the quests that want them.

The inventory export says what you are carrying; item wiki pages say which
quests reference each item; quest pages carry a structured header with the
giver, the zone, the minimum level and the reward. Joining those three is
the whole feature -- none of it is inferred.

PROGRESS IS SHOWN ONLY WHERE THE REQUIREMENT IS STATED. The vendored race
-unlock table gives exact totals (800 Phosphorous Powder, 1200 Gnoll Fang),
and the inventory export gives an exact stack size, so those rows carry a
real bar. Wiki quests do not: their counts live in walkthrough PROSE
("Bring me two tufts of bat fur and two fire beetle legs"), and a number
scraped out of a sentence would be wrong often enough to send someone
farming the wrong amount. Those rows show what you HOLD and link the quest
so the requirement can be read at its source.

The distinction is the point. A bar that appears on some rows and not
others is honest about which numbers are known.

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

# Which wiki eras EQL actually implements. It is a reimagined PRE-KUNARK
# game and Kunark shipped in April 2000, so the cut is by date, taken from
# the era templates' own documentation rather than guessed:
#
#   Classic  1999-2000            in     Kunark   2000          out
#   Temple   October 1999         in     Epics    last sub-era  out
#   Paineel  February 2000        in     Velious  Dec 2000+     out
#
# An era we do not recognise counts as IN. A quest wrongly shown is a
# moment's reading; a quest wrongly hidden is invisible, and the player is
# already carrying items for it.
_IN_ERA = {"classic era", "temple era", "paineel era"}

_CLASSES = {"warrior", "cleric", "paladin", "ranger", "shadow knight", "druid",
            "monk", "bard", "rogue", "shaman", "necromancer", "wizard",
            "magician", "enchanter", "beastlord", "berserker"}

# Sections, in the order a player would work through them. Derived from the
# wiki's OWN categories rather than invented: "Paladin Quests", "Warrior
# Equipment", "Repeatable Turn-in Quests" are its labels, not ours.
KINDS = ("race", "class", "equipment", "faction", "spell", "other")
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
    m = re.match(r"\s*\{\{\s*([^}|]{0,40}?Era)\s*\}\}", wikitext)
    if m:
        out["era"] = m.group(1).strip()
    cats = [c.strip() for c in re.findall(r"\[\[Category:([^\]|]+)", wikitext)]
    if cats:
        out["categories"] = cats
    if re.search(r"^\s*Disambiguation", wikitext, re.M):
        out["disambiguation"] = True
    return out


def _have(held: dict, item_names: list, only: Optional[str] = None) -> int:
    """How many of the counted item you are carrying, across every stack.

    `only` names the ONE item a requirement refers to. Gnoll Bounty also
    references a Water Flask and a Ration, and summing all three read
    190/1200 against a total that is 1200 GNOLL FANGS -- a progress bar
    inflated by unrelated things sharing a page.

    The export's stack column was being discarded too, so 27 fangs and 42
    powder both counted as one. Both halves had to be right before a bar
    could mean anything.
    """
    names = [only] if only else item_names
    return sum(held.get(n, {}).get("count", 0) for n in names)


def _unlocks(kind: str, page: dict) -> Optional[str]:
    """What the quest is FOR, when that is knowable.

    A "Race unlocks" heading with no race under it makes the reader open
    every row to find out which. The class categories say it outright.
    """
    if kind != "class":
        return None
    names = [c[:-7].strip().title()
             for c in (page.get("categories") or [])
             if c.lower().endswith(" quests") and c[:-7].strip().lower() in _CLASSES]
    uniq = list(dict.fromkeys(names))
    if len(uniq) > 4:
        return f"most classes ({len(uniq)})"
    return ", ".join(uniq) or None


def _kind(quest: str, page: dict, item_names: list) -> str:
    """Which section a quest belongs in.

    Category-first, because those are the wiki's own labels. Rewards only
    break a tie: a page with no categories still usually says what it gives
    you, and "Spell: Cure Poison" is unambiguous where a bare item name is
    not.
    """
    # NOT keyed on "an item in this quest appears in the race table":
    # Gnoll Fang is a Barbarian turn-in AND an ingredient in Moonstones and
    # Gnoll Bounty, so that test made every quest touching it a race
    # unlock. Only rows seeded FROM the table are race rows; they set their
    # kind directly and never reach here.
    cats = [c.lower() for c in (page.get("categories") or [])]
    blob = " ".join(cats)
    if any(c.endswith(" quests") and c[:-7].strip() in _CLASSES for c in cats):
        return "class"
    if "equipment" in blob or "fashion" in blob:
        return "equipment"
    if "repeatable turn-in" in blob:
        return "faction"
    rewards = " ".join(page.get("rewards") or []).lower()
    if rewards.startswith("spell:") or "spell:" in rewards:
        return "spell"
    if "faction" in rewards and "item" not in rewards:
        return "faction"
    if rewards:
        return "equipment"
    return "other"


async def _quest_page(name: str) -> dict:
    cached = wiki_page_cache.get("quest2", name.lower())
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
    wiki_page_cache.set(data, _QUEST_TTL, "quest2", name.lower())
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
    merged: dict = {}   # wiki quest name -> race-table record for the same turn-in
    for name, qs in zip(held, pairs):
        if isinstance(qs, Exception):
            continue
        for q in qs:
            by_quest.setdefault(q, []).append(name)

    # The item page is not the only source, and relying on it alone lost
    # real matches: Phosphorous Powder is a Froglok unlock turn-in in the
    # table this app already ships, and its wiki page carries only a
    # "Drops From" section, so the quest never appeared. Seed from the
    # table too -- it names the race, the NPC, the zone and the count,
    # which is more than most item pages give.
    from backend import race_unlocks
    seeded: dict = {}
    for name in held:
        rec = race_unlocks.match(name)
        if not rec:
            continue
        label = f"{rec['race']} unlock — {rec['npc']}"
        seeded.setdefault(label, rec)
        by_quest.setdefault(label, []).append(name)
    # The wiki usually has a page for the same turn-in under its real name
    # -- Gnoll Bounty IS the Barbarian unlock at Lysbith McNaff -- and
    # listing both is the same quest twice. Pages are fetched first so the
    # giver can be compared; a shared giver AND a shared item is the same
    # thing by any reading.
    _pre = await asyncio.gather(*(_quest_page(q) for q in by_quest
                                  if q not in seeded), return_exceptions=True)
    _pre = dict(zip((q for q in by_quest if q not in seeded), _pre))
    for label, rec in list(seeded.items()):
        npc = (rec.get("npc") or "").strip().lower()
        mine = set(by_quest.get(label) or [])
        for quest, page in _pre.items():
            if not isinstance(page, dict):
                continue
            if (page.get("giver") or "").strip().lower() != npc or not npc:
                continue
            if not mine & set(by_quest.get(quest) or []):
                continue
            merged[quest] = rec           # the wiki name wins, our data rides along
            by_quest.pop(label, None)
            seeded.pop(label, None)
            break

    pages = await asyncio.gather(*(_quest_page(q) for q in by_quest
                                   if q not in seeded),
                                 return_exceptions=True)
    pages = dict(zip((q for q in by_quest if q not in seeded), pages))
    out = []
    for quest, item_names in by_quest.items():
        rec = seeded.get(quest)
        if rec:
            out.append({
                "quest": quest,
                "url": race_unlocks.guide_url(),
                "items": [{"name": n, "count": held[n]["count"],
                           "where": sorted(held[n]["where"])}
                          for n in item_names],
                "giver": rec.get("npc"), "zone": rec.get("zone"),
                "min_level": None, "classes": None, "races": None,
                "rewards": [f"{rec['race']} unlock"],
                "kind": "race", "unlocks": rec.get("race"),
                "needed": rec.get("total"),
                "have": _have(held, item_names, (extra or {}).get("item")),
                "per_turnin": rec.get("per_turnin"),
                "note": rec.get("note"),
                "era": None, "out_of_era": False,
                "disambiguation": False, "below_level": False,
            })
            continue
        page = pages.get(quest)
        page = page if isinstance(page, dict) else {}
        extra = merged.get(quest)
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
            "kind": "race" if extra else (k := _kind(quest, page, item_names)),
            "unlocks": (extra["race"] if extra
                        else _unlocks(_kind(quest, page, item_names), page)),
            "needed": (extra or {}).get("total"),
            "have": _have(held, item_names,
                          (extra or {}).get("item")),
            "per_turnin": (extra or {}).get("per_turnin"),
            "note": (extra or {}).get("note"),
            "era": page.get("era"),
            # unknown era counts as in-era: see _IN_ERA
            "out_of_era": bool(page.get("era")
                               and page["era"].strip().lower() not in _IN_ERA),
            "disambiguation": bool(page.get("disambiguation")),
            # reported, never used to hide a row -- see the module docstring
            "below_level": bool(lvl and level and level < lvl),
        })
    # most items held first: that is the closest honest proxy for "nearly done"
    # in-era first, then by how much of it you are already carrying
    out.sort(key=lambda q: (q["out_of_era"],
                            -sum(i["count"] for i in q["items"]),
                            -len(q["items"]), q["quest"]))
    return out
